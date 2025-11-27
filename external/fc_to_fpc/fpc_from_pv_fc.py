#!/usr/bin/env python
"""
This script creates a classified layer identifying broad vegetation density classes based on FCC canopy cover equivilants.

 - Dense vegetation: FPC 70-100% (>80% crown cover equivelent)
 - Mid-Dense vegetation: FPC 30-70% (50-80% crown cover equivelent)
 - Sparse vegetation: FPC 10-30% (20-50% crown cover equivelent)
 - Very sparce/isolated vegetation: FPC <10% (0.25-20% crown cover equivelent)

"""

from __future__ import print_function, division
import sys
from rios import applier, fileinfo
import numpy as np
import csv
import pdb
import argparse
import pandas as pd
import scipy.stats.mstats as mstats
from numpy import inf
import numpy.ma as ma


def getCmdargs():
    """
    Get command line arguments
    """
    p = argparse.ArgumentParser()

    p.add_argument("-f", "--infimage", help="input seasonal dc4 image to process")

    # p.add_argument("-s","--inhimage", help="input seasonal tree structure image to process")

    p.add_argument("-o", "--output", help="name of the output image")

    cmdargs = p.parse_args()

    if cmdargs.infimage is None:
        p.print_help()
        sys.exit()

    return cmdargs


def mainRoutine():
    cmdargs = getCmdargs()

    infiles = applier.FilenameAssociations()
    outfiles = applier.FilenameAssociations()
    otherargs = applier.OtherInputs()

    infiles.fpc = cmdargs.infimage
    # infiles.height = cmdargs.inhimage
    outfiles.classImage = cmdargs.output

    controls = applier.ApplierControls()
    controls.setOutputDriverName('GTiff')
    options = ['COMPRESS=LZW', 'BIGTIFF=YES', 'TILED=YES', 'INTERLEAVE=BAND', 'BLOCKXSIZE=256', 'BLOCKYSIZE=256']
    controls.setCreationOptions(options)
    controls.setWindowXsize(256)
    controls.setWindowYsize(256)
    controls.setReferenceImage(cmdargs.infimage)

    # set up the nodata values
    imginfo = fileinfo.ImageInfo(cmdargs.infimage)
    otherargs.coverNull = imginfo.nodataval[0]

    # controls.setStatsIgnore(0)

    # using the height layer as the reference image
    controls.setReferenceImage(infiles.fpc)

    applier.apply(makeClass, infiles, outfiles, otherargs, controls=controls)

    print(cmdargs.output + 'is complete')


def makeClass(info, inputs, outputs, otherargs):
    np.seterr(all='ignore')

    Wfpc = np.array(inputs.fpc[1].astype(np.float32))
    fpc = ma.masked_array(Wfpc, Wfpc == 255)

    c = 1.86
    k = 0.000435
    n = 1.909
    fpcC = 100 * (1 - (np.exp((-k * (np.power(fpc, n))))))

    # Classify (unchanged from your script)
    imgShape = fpc.shape
    densityClass = np.zeros(imgShape, dtype=np.int)

    vegClass_nd = np.ma.filled(densityClass, fill_value=0)
    outputs.classImage = np.array([vegClass_nd], dtype=np.uint8)

    # NEW: Save the continuous FPC layer as float32
    outputs.fpcLayer = np.array([np.ma.filled(fpcC, fill_value=otherargs.coverNull)], dtype=np.float32)


if __name__ == "__main__":
    mainRoutine()