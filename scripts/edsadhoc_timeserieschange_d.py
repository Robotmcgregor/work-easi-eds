#!/usr/bin/env python
"""
A re-write of the main timeseries change detection script. Uses the same
underlying methods as in qv_timeserieschange.py, but with fewer obsolete options.
The main functional differences are that this is designed to work with the "d" stage
processing stream, i.e. the scene names are the standard path/row names, copes
with the need to mask the FPC inputs on-the-fly, and deals with nominal date
start/end images.

Internally, all traces of PyModeller have been removed, and all is done with RIOS,
which makes it considerably easier to modify.

Note also that this program has been written for compatability with Python 3, using
the "from __future__" import at the start, so watch your print statements.

"""
from __future__ import print_function, division

import os
import sys
import argparse
import datetime
import tempfile

import numpy

numpy.seterr(all="ignore")
from osgeo import ogr, osr

from rios import applier

import qv
import qvf
from rsc.utils import metadb
from rsc.utils import history
from rsc.utils import masks
from rsc.utils import gdalcommon

maskTypes_cloud = [masks.MT_CLOUD, masks.MT_CLOUDSHADOW]
maskTypes_other = [
    masks.MT_WATERNDX,
    masks.MT_TOPOINCIDENCE,
    masks.MT_TOPOCASTSHADOW,
    masks.MT_SNOW,
]
maskTypes = maskTypes_other + maskTypes_cloud


def getCmdargs():
    """
    Get commandline arguments
    """
    p = argparse.ArgumentParser(
        description=(
            "Run the top-of-atmosphere-based clearing detection  model. "
            + "Incorporates prior timeseries of FPC, and simple topo-correction."
        )
    )
    p.add_argument("--scene", help="Name of scene to process")
    p.add_argument(
        "--era",
        help=(
            "Change era to process. If given as a year pair (e.g. e1213, meaning 2012-2013) "
            + "this results in files named as e1213, based on formal SLATS era definition. "
            + "If given as a date range "
            + "(e.g. d2012092120130903) the output files are named with that date range. "
        ),
    )
    p.add_argument(
        "--startdateimage",
        help="File name for start date image (db8 stage). If using this, do not use --era or --scene. ",
    )
    p.add_argument(
        "--enddateimage",
        help="File name for end date image (db8 stage). If using this, do not use --era or --scene. ",
    )
    p.add_argument(
        "--reportinputs",
        help=(
            "Give the name of a file in which to list the input "
            + "files which would be required for this run. Does not actually execute anything, and exits "
            + "after creating this list file. "
        ),
    )
    p.add_argument(
        "--omitcloudmasks",
        default=False,
        action="store_true",
        help="Omit the cloud masks from the start/end date image masking",
    )
    p.add_argument(
        "--writeindexes",
        default=False,
        action="store_true",
        help=(
            "Write secondary output file of component indexes (default does not write this). "
            + "Layers are (combinedIndex, spectralIndex, fpcDiff, sTest, tTest). File name is "
            + "same as output, with _zindex"
        ),
    )
    p.add_argument(
        "--timeseriesdates",
        help=(
            "Comma-separated list of specific dates to use for timeseries stats. No spaces. "
            + "For when we need to over-ride the automatically selected list of dates for "
            + "the FPC timeseries, and should not normally be necessary"
        ),
    )
    p.add_argument("--cloudthresh", default=40, help="Cloud threshold")
    p.add_argument(
        "--clipqldstate",
        default=False,
        action="store_true",
        help="Clip to QLD state boundary",
    )

    cmdargs = p.parse_args()
    return cmdargs


def mainRoutine():
    """
    Main routine
    """
    cmdargs = getCmdargs()
    DBcon = metadb.connect(api=metadb.DB_API)
    DBcursor = DBcon.cursor()

    stages = AllStages(cmdargs)

    (refPair, fpcPair) = getImagePairs(cmdargs, DBcursor, stages)
    print("Change pair: %s" % " ".join(refPair))

    fpcTimeseries = getFpcTimeseries(fpcPair, DBcursor, cmdargs)
    print("FPC time series with %d images" % len(fpcTimeseries))

    allMaskFiles = getAllMaskfiles(refPair, fpcTimeseries)
    footprintFile = metadb.stdProjFilename("lztmna_%s_eall_dw1mz.img" % cmdargs.scene)

    # A single list of all the required inputs (without duplicates)
    allFpc = list(set(fpcPair + fpcTimeseries))
    allInputs = refPair + allFpc + allMaskFiles + [footprintFile]
    if cmdargs.reportinputs is not None:
        reportInputs(cmdargs.reportinputs, allInputs)
        sys.exit()

    # Recall the inputs we don't have already
    toRecall = [fn for fn in allInputs if not os.path.exists(fn)]
    if len(toRecall) > 0:
        print("Recalling %s files" % len(toRecall))
        qv.recallToHere(toRecall)

    # Mask and normalise the FPC timeseries
    normedFpcTimeseries = normaliseFpc(fpcTimeseries)
    normedFpcPair = normaliseFpc(fpcPair, omitcloud=cmdargs.omitcloudmasks)

    # Generate timeseries stats
    timeseriesStatsImg = doTimeseriesStats(normedFpcTimeseries)

    (changeClass, changeInterp) = runChangeModel(
        refPair,
        normedFpcPair,
        fpcPair[0],
        timeseriesStatsImg,
        footprintFile,
        cmdargs,
        stages,
        DBcursor,
    )

    addClrTbl(changeClass, cmdargs.era)
    addHistory(changeClass, changeInterp, refPair, fpcPair, fpcTimeseries)


def getImagePairs(cmdargs, DBcursor, stages):
    """
    Work out the filenames required for the image pairs for start date and end date.
    """
    if cmdargs.startdateimage is not None and cmdargs.enddateimage is not None:
        startFilename = qvf.changestage(cmdargs.startdateimage, stages.ref)
        endFilename = qvf.changestage(cmdargs.enddateimage, stages.ref)
        cmdargs.scene = qvf.locationid(cmdargs.startdateimage)
        cmdargs.era = "d{}{}".format(
            qvf.when(cmdargs.startdateimage), qvf.when(cmdargs.enddateimage)
        )
    elif cmdargs.era is not None:
        era = cmdargs.era
        if era.startswith("d"):
            if era[1] == "n":
                startDate = era[1:10]
            else:
                startDate = era[1:9]
            if era[-9] == "n":
                endDate = era[-9:]
            else:
                endDate = era[-8:]
        else:
            # Assume it is an era specification. Allow either with or without the leading 'e'
            if era.startswith("e"):
                era = era[1:]
            startYear = year2digitTo4(era[:2])
            endYear = year2digitTo4(era[2:])
            startDate = getSLATSdate(cmdargs.scene, startYear, DBcursor)
            endDate = getSLATSdate(cmdargs.scene, endYear, DBcursor)

        startFilename = getRefFilename(cmdargs.scene, startDate, DBcursor, stages)
        endFilename = getRefFilename(cmdargs.scene, endDate, DBcursor, stages)

    refPair = [startFilename, endFilename]
    fpcPair = [qvf.changestage(fn, stages.fpc) for fn in refPair]

    return (refPair, fpcPair)


def getSLATSdate(scene, year, DBcursor):
    """
    Return a date string (yyyymmdd) for the image date corresponding to the
    requested SLATS year, for the given scene
    """
    sql = "select date from slats_dates where scene = %(scene)s and year = %(year)s"
    sqlVars = {"scene": scene, "year": year}

    DBcursor.execute(sql, sqlVars)
    results = DBcursor.fetchall()

    if len(results) != 1:
        msg = "Unable to deduce SLATS date for scene='%s', year='%s'. " % (scene, year)
        if len(results) > 1:
            msg += "Found %d possibilities" % len(results)
        elif len(results) == 0:
            msg += "No entry in slats_dates table"
        raise InputSpecificationError(msg)

    date = results[0][0]

    return date


def getRefFilename(scene, date, DBcursor, stages):
    """
    Get the name of the TOA reflectance image for the given scene/date
    """
    dateObj = qvf.when_dateobj(date)
    dateStr = dateObj.strftime("%Y%m%d")

    sql = """
        select satellite, instrument 
        from landsat_list 
        where scene = %(scene)s and date = %(date)s and product = 're'
    """
    sqlVars = {"scene": scene, "date": dateStr}
    DBcursor.execute(sql, sqlVars)
    results = DBcursor.fetchall()

    (sat, instr) = tuple(results[0])

    filename = "%s%sre_%s_%s_%smz.img" % (sat, instr, scene, date, stages.ref)
    filename = metadb.stdProjFilename(filename)

    return filename


def year2digitTo4(year2):
    """
    Convert a 2-digit year string into a 4-digit year string
    """
    year = 1900 + int(year2)
    if int(year2) < 50:
        year += 100
    return str(year)


def getFpcTimeseries(fpcPair, DBcursor, cmdargs):
    """
    Generate a list of FPC filenames for the timeseries for the
    requested start/end pair

    """
    fpcTimeseries = []
    scene = qvf.locationid(fpcPair[0])
    startDate = qvf.when_dateobj(fpcPair[0]).strftime("%Y%m%d")
    endDate = qvf.when_dateobj(fpcPair[1]).strftime("%Y%m%d")
    stage = qvf.stage(fpcPair[0])

    if cmdargs.timeseriesdates is None:
        dateList = findSimilarSeasonDates(scene, endDate, DBcursor, cmdargs.cloudthresh)
    else:
        dateList = useRequestedDates(scene, cmdargs.timeseriesdates, DBcursor)

    # Restrict to dates up to the start of the era.
    dateList = [
        (sat, instr, date) for (sat, instr, date) in dateList if date <= startDate
    ]

    print("Using these dates for FPC timeseries:", ",".join([d[2] for d in dateList]))

    # Construct the filenames from the list of (satellite, date) tuples
    for satellite, instrument, date in dateList:
        fpcImg = (
            qvf.assemble([satellite + instrument + "re", scene, date, stage + "mz"])
            + ".img"
        )
        fpcImg = metadb.stdProjFilename(fpcImg)
        fpcTimeseries.append(fpcImg)

    return fpcTimeseries


def findSimilarSeasonDates(scene, targetdate, DBcursor, cloudthresh):
    """
    Finds a set of all dates which are in the same season as the
    target date, for which we have a landsat image. The date chosen is
    the one with the least cloud, as given by the cloudamount table

    Being in the "same season" means within 2 months of the target date in
    any given year.

    Limit to 10 years prior to target date

    Returns a list of tuples (satellite, instrument, date), one per year.

    """
    # Tolerance on what constitutes "same season". Date +/- this many months
    seasonTol = 2

    targetMMDD = targetdate[4:]
    targetMonth = int(targetMMDD[:2])

    # The list of month numbers which are within 2 months of the target month
    months = [
        (m - 1) % 12 + 1
        for m in range(targetMonth - seasonTol, targetMonth + seasonTol + 1)
    ]
    monthSet = ",".join(["'%2.2d'" % m for m in months])

    # The list of years witch are within the past 10 years of the target date
    yearTol = 10
    targetYear = int(targetdate[:4])
    years = [y for y in range(targetYear - yearTol + 1, targetYear + 1)]
    yearSet = ",".join(["'%d'" % y for y in years])

    # Select scenes which are close, limiting to ones with < 40% cloud, and excluding
    # the Landsat-7 SLC-off dates (SLC failure was 20030531).
    sql = """
        select landsat_list.satellite, landsat_list.instrument, 
            landsat_list.date, cloudamount.pcntcloud
        from landsat_list 
        join cloudamount on landsat_list.scene = cloudamount.scene and 
            landsat_list.date = cloudamount.date
        where 
            substring(landsat_list.date, 5, 2) in (%s) and
            substring(landsat_list.date, 1, 4) in (%s) and
            product = 're' and
            landsat_list.scene = '%s' and 
            landsat_list.satellite in ('l8', 'l9') and
            pcntcloud < %s
        order by date
    """ % (
        monthSet,
        yearSet,
        scene,
        cloudthresh,
    )

    DBcursor.execute(sql)
    results = DBcursor.fetchall()

    datelist = sorted([r[2] for r in results])
    startYear = int(datelist[0][:4])
    endYear = int(datelist[-1][:4])

    bestDates = []
    for year in range(startYear, endYear + 1):
        datesThisYear = [
            (sat, instr, date, cld)
            for (sat, instr, date, cld) in results
            if date[:4] == "%4.4d" % year
        ]
        if len(datesThisYear) > 0:
            minCloudVal = min(datesThisYear, key=lambda x: x[-1])[-1]
            minCloudDates = sorted(
                [
                    (date, sat, instr)
                    for (sat, instr, date, cld) in datesThisYear
                    if cld == minCloudVal
                ]
            )
            numDates = len(minCloudDates)
            if numDates > 0:
                # Probably should pick the one closest to targetMMDD, but that was too hard, so
                # picking the middle one.
                (middleDate, sat, instr) = minCloudDates[numDates // 2]
                bestDates.append((sat, instr, middleDate))

    return bestDates


def useRequestedDates(scene, timeseriesdates, DBcursor):
    """
    If we have been given a list of dates to use, then create the same sort of list
    as is otherwise returned by findSimilarSeasonDates(). This is a list of
        [(sat, instr, date), ...]
    used for constructing the list of filenames

    """
    datelist = timeseriesdates.split(",")

    outDatelist = []
    for date in datelist:
        sql = """
            select satellite, instrument 
            from landsat_list 
            where product = 're' and scene = '%s' and date = '%s'
        """ % (
            scene,
            date,
        )
        DBcursor.execute(sql)
        results = DBcursor.fetchall()

        if len(results) > 0:
            (sat, instr) = results[0]
            outDatelist.append((sat, instr, date))

    return outDatelist


def getAllMaskfiles(refPair, fpcTimeseries):
    """
    Generate a list of all the relevant mask files for the given inputs
    """
    allFiles = refPair + fpcTimeseries
    allMaskFiles = []
    msgList = []
    for filename in allFiles:
        masklist = [masks.getAvailableMaskname(filename, mt) for mt in maskTypes]
        if None in masklist:
            msg = "Missing masks for image '%s'. Mask list is %s" % (filename, masklist)
            msgList.append(msg)
        allMaskFiles.extend(masklist)

    if len(msgList) > 0:
        msg = "\n" + "\n".join(msgList)
        raise MissingInputError(msg)

    return allMaskFiles


def reportInputs(reportfile, allInputs):
    """
    Write the list of inputs to the given outfile, and exit
    """
    f = open(reportfile, "w")
    for filename in allInputs:
        f.write(filename + "\n")
    f.close()
    sys.exit()


def normaliseFpc(fpcTimeseries, omitcloud=False):
    """
    Apply all masks and then normalise each FPC file
    """
    normalisedFpcList = []

    infiles = applier.FilenameAssociations()
    outfiles = applier.FilenameAssociations()

    for fpc in fpcTimeseries:
        maskedFpc = qvf.changeoptionfield(fpc, "z", "masked")
        normedFpc = qvf.changeoptionfield(maskedFpc, "z", "normed")

        if not os.path.exists(normedFpc):
            print("Mask and normalise", fpc)
            cmd = "qv_applystdmasks.py --infile %s --outfile %s" % (fpc, maskedFpc)

            if omitcloud:
                cmd += " --omitmask cloud --omitmask cloudshadow"
            os.system(cmd)

            infiles.fpc = maskedFpc
            outfiles.normed = normedFpc
            applier.apply(doNormFpc, infiles, outfiles)

            os.remove(maskedFpc)
        else:
            print("Normalised fpc exists for", fpc)

        normalisedFpcList.append(normedFpc)

    return normalisedFpcList


def doNormFpc(info, inputs, outputs):
    """
    Called from RIOS

    Normalise the FPC. This is done so as to match the way Peter's original
    model did it, so there is no accounting for scaling, etc., it just works
    on the DN values.
    """
    mean = info.global_mean(inputs.fpc)
    stddev = info.global_stddev(inputs.fpc)

    fpcnorm = 125 + numpy.round(15 * (inputs.fpc.astype(numpy.float32) - mean) / stddev)
    outputs.normed = fpcnorm.clip(1, 255).astype(numpy.uint8)
    nullmask = inputs.fpc == 0
    outputs.normed[nullmask] = 0


def doTimeseriesStats(normedFpcTimeseries):
    """
    Use gdaltimeseries to calculate some timeseries statistics
    for the given timeseries of normalised FPC images
    """
    yearList = [qvf.when_dateobj(fn).year for fn in normedFpcTimeseries]
    earliestYear = min(yearList)
    latestYear = max(yearList)
    era = "e%s%s" % (str(earliestYear)[2:], str(latestYear)[2:])
    scene = qvf.locationid(normedFpcTimeseries[0])
    stage = qvf.stage(normedFpcTimeseries[0])
    proj = qvf.zonecode(normedFpcTimeseries[0])
    statsImg = "lztmre_%s_%s_%s%s_ztsstats.img" % (scene, era, stage, proj)

    if not os.path.exists(statsImg):
        print("Running gdaltimeseries")
        cmdlist = ["gdaltimeseries", statsImg]
        for normedFpc in normedFpcTimeseries:
            cmdlist.append(normedFpc)
            decimalYear = makeDecimalYear(normedFpc)
            cmdlist.append(str(decimalYear))

        cmdStr = " ".join(cmdlist)
        os.system(cmdStr)
    else:
        print("Using existing stats image:", statsImg)

    return statsImg


def makeDecimalYear(filename):
    """
    Return a decimal year value for the date of the given filename
    Note that the decimal part starts at zero, e.g. 1998.0 is 1 Jan 1998.
    """
    dateObj = qvf.when_dateobj(filename)
    dateJan1 = datetime.date(dateObj.year, 1, 1)
    dateDec31 = datetime.date(dateObj.year, 12, 31)

    daysInYear = (dateDec31 - dateJan1).days + 1
    dayNum = (dateObj - dateJan1).days
    fraction = dayNum / float(daysInYear)

    decimalYear = dateObj.year + fraction

    return decimalYear


def runChangeModel(
    refPair, normedFpcPair, fpcStart, statsImg, footprintFile, cmdargs, stages, DBcursor
):
    """
    Run Peter's TOA-based change detection model.
    """
    infiles = applier.FilenameAssociations()
    outfiles = applier.FilenameAssociations()
    otherargs = applier.OtherInputs()
    controls = applier.ApplierControls()

    infiles.refPair = refPair
    infiles.normedFpcPair = normedFpcPair
    infiles.fpcStart = fpcStart
    infiles.stats = statsImg
    maskTypesForChange = maskTypes_other + maskTypes_cloud

    if cmdargs.omitcloudmasks:
        maskTypesForChange = maskTypes_other

    infiles.masklist = [
        masks.getAvailableMaskname(refPair[i], mt)
        for i in range(2)
        for mt in maskTypesForChange
    ]
    infiles.footprint = footprintFile

    stateBoundary = None
    if cmdargs.clipqldstate:
        stateBoundary = getStateBoundary(refPair[0], DBcursor)

    if stateBoundary is not None:
        infiles.stateboundary = stateBoundary

    changeclassFile = makeOutfileName(refPair, cmdargs, stages.changeclass)
    outfiles.changeclass = changeclassFile
    (fd, tmpfile) = tempfile.mkstemp(prefix="tmp", suffix=".img", dir=".")
    os.close(fd)
    outfiles.indexes = tmpfile
    otherargs.writeindexfile = False
    otherargs.indexNullVal = -10000.0

    if cmdargs.writeindexes:
        outfiles.allindexes = qvf.changeoptionfield(
            outfiles.changeclass, "z", "indexes"
        )
        otherargs.writeindexfile = True
        controls.setStatsIgnore(otherargs.indexNullVal, imagename="allindexes")
    controls.setStatsIgnore(0, imagename="changeclass")
    controls.setThematic(True, imagename="changeclass")

    otherargs.predictionDate = makeDecimalYear(refPair[1])

    # This list must correspond exactly to the order given by infiles.masklist
    otherargs.maskRecodeVals = [
        108,
        107,
        107,
        109,
        103,
        105,
        108,
        107,
        107,
        109,
        104,
        106,
    ]

    if cmdargs.omitcloudmasks:
        otherargs.maskRecodeVals = [108, 107, 107, 109, 108, 107, 107, 109]
    otherargs.maskerList = [masks.Masker(fn) for fn in infiles.masklist]

    applier.apply(doChangeModel, infiles, outfiles, otherargs, controls=controls)

    # Now re-stretch the index layers for the final interpretation image
    infiles = applier.FilenameAssociations()
    outfiles = applier.FilenameAssociations()

    infiles.indexes = tmpfile
    outfiles.interp = qvf.changestage(changeclassFile, stages.interp)

    applier.apply(stretchInterp, infiles, outfiles)

    os.remove(tmpfile)
    if stateBoundary is not None:
        ds = ogr.Open(stateBoundary)
        drvr = ds.GetDriver()
        del ds
        drvr.DeleteDataSource(stateBoundary)

    changeFiles = (changeclassFile, outfiles.interp)

    return changeFiles


def doChangeModel(info, inputs, outputs, otherargs):
    """
    Called from RIOS

    Apply Peter's TOA-based change detection model
    """
    NO_CLEARING = 10
    NULL_CLEARING = 0

    tsMean = inputs.stats[0]
    tsStdDev = inputs.stats[1]
    tsStdErr = inputs.stats[2]
    tsSlope = inputs.stats[3]
    tsIntercept = inputs.stats[4]

    normedFpcStart = inputs.normedFpcPair[0][0]
    normedFpcEnd = inputs.normedFpcPair[1][0]
    fpcStart = inputs.fpcStart[0]

    refStart = inputs.refPair[0].astype(numpy.float32)
    refEnd = inputs.refPair[1].astype(numpy.float32)

    fpcDiff = normedFpcEnd.astype(numpy.float32) - normedFpcStart

    fpcDiffStdErr = -fpcDiff * tsStdErr

    predictedNormedFpc = tsIntercept + tsSlope * otherargs.predictionDate
    observedNormedFpc = normedFpcEnd

    sTest = (observedNormedFpc - predictedNormedFpc) / tsStdErr
    sTest[tsStdErr < 0.2] = 0

    tTest = (observedNormedFpc - tsMean) / tsStdDev
    tTest[tsStdDev < 0.2] = 0

    spectralIndex = (
        (0.77801094 * numpy.log1p(refStart[1]))
        + (1.7713253 * numpy.log1p(refStart[2]))
        + (2.0714311 * numpy.log1p(refStart[4]))
        + (2.5403550 * numpy.log1p(refStart[5]))
        + (-0.2996241 * numpy.log1p(refEnd[1]))
        + (-0.5447928 * numpy.log1p(refEnd[2]))
        + (-2.2842536 * numpy.log1p(refEnd[4]))
        + (-4.0177752 * numpy.log1p(refEnd[5]))
    )

    combinedIndex = (
        -11.972499 * spectralIndex
        - 0.40357223 * fpcDiff
        - 5.2609715 * tTest
        - 4.3794265 * sTest
    )

    imgShape = inputs.stats[0].shape
    changeclass = numpy.zeros(imgShape, dtype=numpy.uint8)
    changeclass.fill(NO_CLEARING)

    # Code the various change classes
    changeclass[combinedIndex > 21.80] = 34
    changeclass[(combinedIndex > 27.71) & (sTest < -0.27) & (spectralIndex < -0.86)] = (
        35
    )
    changeclass[(combinedIndex > 33.40) & (sTest < -0.60) & (spectralIndex < -1.19)] = (
        36
    )
    changeclass[(combinedIndex > 39.54) & (sTest < -1.01) & (spectralIndex < -1.50)] = (
        37
    )
    changeclass[(combinedIndex > 47.05) & (sTest < -1.55) & (spectralIndex < -1.84)] = (
        38
    )
    changeclass[(combinedIndex > 58.10) & (sTest < -2.34) & (spectralIndex < -2.27)] = (
        39
    )
    changeclass[(tTest > -1.70) & (fpcDiffStdErr > 740)] = 3
    changeclass[fpcStart < 108] = NO_CLEARING

    # Apply masks to change class raster
    numMasks = len(inputs.masklist)
    for i in range(numMasks):
        masker = otherargs.maskerList[i]
        maskArr = inputs.masklist[i][0]
        mask = masker.mask(maskArr) & ~masker.isNull(maskArr)
        recodeVal = otherargs.maskRecodeVals[i]
        changeclass[mask] = recodeVal

    refDNnull = 0
    nullMask = (refStart == refDNnull).any(axis=0) | (refEnd == refDNnull).any(axis=0)
    changeclass[nullMask] = NULL_CLEARING
    footprintNullMask = inputs.footprint[0] == 0

    if hasattr(inputs, "stateboundary"):
        footprintNullMask = footprintNullMask | (inputs.stateboundary[0] == 0)
    changeclass[footprintNullMask] = NULL_CLEARING
    outputs.changeclass = numpy.array([changeclass])

    # This is the unstretched interpretation image. The stretch has to be done
    # after the whole image is written, so it can use global stats
    outputs.indexes = numpy.array([spectralIndex, sTest, combinedIndex])
    for i in range(len(outputs.indexes)):
        outputs.indexes[i][footprintNullMask] = 0

    # Used for debugging purposes, etc.
    if otherargs.writeindexfile:
        outlist = [combinedIndex, spectralIndex, fpcDiff, sTest, tTest]
        outputs.allindexes = numpy.array(outlist, dtype=numpy.float32)

        # Mask out the areas which are masked in the classes
        fullMask = (outputs.changeclass[0] > 100) | (
            outputs.changeclass[0] == NULL_CLEARING
        )
        for i in range(len(outlist)):
            outputs.allindexes[i][fullMask] = otherargs.indexNullVal


def stretchInterp(info, inputs, outputs):
    """
    Called from RIOS.

    Apply a stretch to the layers of the various indexes, and write the final
    interpretation image
    """
    spectralIndex = inputs.indexes[0]
    sTest = inputs.indexes[1]
    combinedIndex = inputs.indexes[2]

    spectralMean = info.global_mean(inputs.indexes, band=1)
    spectralStddev = info.global_stddev(inputs.indexes, band=1)
    sTestMean = info.global_mean(inputs.indexes, band=2)
    sTestStddev = info.global_stddev(inputs.indexes, band=2)
    combinedMean = info.global_mean(inputs.indexes, band=3)
    combinedStddev = info.global_stddev(inputs.indexes, band=3)

    # There is a trap in the next three lines, so pay attention.
    # In the previous version of this script, the unstretched interpretation image
    # had been clipped to the minimal footprint only for the spectral index, but the sTest
    # included all the surrounding rubbish, with all sorts of edge effects. This then flowed
    # into the combined index. This meant that the global statistics for those two layers
    # included much larger standard deviations than would otherwise be the case.
    # In this version, we clip all these layers to the minimal footprint, and instead use
    # a larger number of standard deviations to reproduce the equivalent behaviour.
    # So, the three lines following have wildly different values for numStdDev. We played
    # around a bit to find values which seemed to give a good amount of discrimination.
    spectralStretched = stretch(
        spectralIndex, spectralMean, spectralStddev, 2, 1, 255, 0
    )
    sTestStretched = stretch(sTest, sTestMean, sTestStddev, 10, 1, 255, 0)
    combinedStretched = stretch(
        combinedIndex, combinedMean, combinedStddev, 10, 1, 255, 0
    )

    clearingProb = 200 * (1 - numpy.exp(-((0.01227 * combinedIndex) ** 3.18975)))
    clearingProb = numpy.round(clearingProb).astype(numpy.uint8)
    clearingProb[combinedIndex <= 0] = 0

    outStack = numpy.array(
        [spectralStretched, sTestStretched, combinedStretched, clearingProb],
        dtype=numpy.uint8,
    )
    nullMask = spectralIndex == 0
    for i in range(len(outStack)):
        outStack[i][nullMask] = 0

    outputs.interp = outStack


def stretch(img, mean, stddev, numStdDev, minVal, maxVal, ignoreVal):
    """
    Sort of in mimicry of Imagine's STRETCH function. Applies a linear
    stretch to the img, by the given number of std deviations.
    """
    stretched = minVal + (img - mean + stddev * numStdDev) * (maxVal - minVal) / (
        stddev * 2 * numStdDev
    )
    stretched = stretched.clip(minVal, maxVal)
    stretched[img == ignoreVal] = 0
    return stretched


def makeOutfileName(refPair, cmdargs, outstage):
    """
    Create the output filename
    """
    sat = qvf.satellite(refPair[0])
    if sat != qvf.satellite(refPair[1]):
        sat = "lz"
    instr = qvf.instrument(refPair[0])
    scene = qvf.locationid(refPair[0])
    era = cmdargs.era
    if not era.startswith("e") and len(era) == 4:
        era = "e" + era
    filename = "%s%sre_%s_%s_%smz.img" % (sat, instr, scene, era, outstage)
    filename = metadb.stdProjFilename(filename)
    return filename


def addClrTbl(changeClass, era):
    """
    Add a standard colour table to the change classification raster
    """
    eraStr = era
    if era.startswith("e"):
        eraStr = eraStr[1:]

    clrTblFile = os.path.expandvars(
        "$QV_IMGTEMPLATEDIR/clearing_colours_%s.txt" % eraStr
    )
    if not os.path.exists(clrTblFile):
        clrTblFile = os.path.expandvars(
            "$QV_IMGTEMPLATEDIR/clearing_colours_fallback.txt"
        )

    ratFile = os.path.expandvars(
        "$QV_IMGTEMPLATEDIR/clearing_class_names_%s.dat" % eraStr
    )

    if os.path.exists(clrTblFile):
        clrTbl = gdalcommon.readColourTableFromFile(clrTblFile)
        gdalcommon.setColourTable(clrTbl, filename=changeClass, layernum=1)

    if os.path.exists(ratFile):
        cmd = "gdaladdRATfromfile.py --imgfile %s --ratfile %s" % (changeClass, ratFile)
        os.system(cmd)


def addHistory(changeClass, changeInterp, refPair, fpcPair, fpcTimeseries):
    """
    Add processing history to output files
    """
    parents = refPair + [fpcPair[1]] + fpcTimeseries
    opt = {}
    opt[
        "DESCRIPTION"
    ] = """
        Part of woody change detection. 
        Classification with values of 34, 35, 36, 37, 38 and 39 representing change at 
        1%, 2%, 4%, 5%, 10% and 20% probability levels and 
        values of 3 representing probable cropping change. 
        Masks have been applied. 
    """
    history.insertMetadataFilename(changeClass, parents, opt)

    opt[
        "DESCRIPTION"
    ] = """
        Vegetation change interpretation raster. Bands are: spectral index; 
        FPC relative change index; combined index; clearing probability estimates. 
        First three bands have been re-stretched for easy viewing. 
    """
    history.insertMetadataFilename(changeInterp, parents, opt)


def getStateBoundary(imgfile, DBcursor):
    """
    Work out whether we should clip to the state boundary. If not, return None.
    If we should clip, extract a GeoJSON outline of the boundary for this scene,
    and save as a text file. Return the name of this file.

    """
    stateBoundary = None
    scene = qvf.locationid(imgfile)
    row = int(scene[5:])
    path = int(scene[1:4])

    if (
        (row == 80)
        or (path == 100)
        or (
            scene
            in [
                "p097r079",
                "p097r078",
                "p098r078",
                "p099r078",
                "p099r077",
                "p099r076",
                "p101r071",
                "p101r072",
                "p099r066",
            ]
        )
    ):

        zone = int(qvf.utmzone(imgfile))
        epsg = 32700 + zone
        sql = """
            select ST_AsText(st_transform(st_intersection(scene.geom, qld.geom), %d)), scene.pr 
                from 
                    (SELECT geom as geom, path||'/'||row as pr 
                        from landsat_wrs2 where path=%d and row = %d
                    ) as scene, 
                    (select geom, state from state_boundaries where state = 'QLD') as qld
        """ % (
            epsg,
            path,
            row,
        )
        DBcursor.execute(sql)
        results = DBcursor.fetchall()
        geoJSON = results[0][0]

        (fd, stateBoundary) = tempfile.mkstemp(prefix="tmp", suffix=".shp", dir=".")
        os.close(fd)
        os.remove(stateBoundary)

        sr = osr.SpatialReference()
        sr.ImportFromEPSG(epsg)

        drvr = ogr.GetDriverByName("ESRI Shapefile")
        ds = drvr.CreateDataSource(stateBoundary)
        lyr = ds.CreateLayer("layer", srs=sr, geom_type=ogr.wkbPolygon)
        featDefn = lyr.GetLayerDefn()
        for geomWKT, pr in results:
            if geomWKT != "GEOMETRYCOLLECTION EMPTY":
                feat = ogr.Feature(featDefn)
                geom = ogr.Geometry(wkt=geomWKT)
                feat.SetGeometry(geom)
                lyr.CreateFeature(feat)
        del lyr
        del ds

    return stateBoundary


class InputSpecificationError(Exception):
    pass


class MissingInputError(Exception):
    pass


class AllStages(object):
    """
    Define fields for all the stage codes we need, which can be dependant on the inputs
    """

    def __init__(self, cmdargs):
        self.fpc = "dc4"
        self.ref = "db8"
        self.interp = "dlj"
        self.changeclass = "dll"


if __name__ == "__main__":
    mainRoutine()
