# edsadhoc_timeserieschange_d.py

Original SLATS/EDS timeseries change detection (TOA reflectance + FPC) driven by the historical toolchain.

This script is the legacy reference for DLL (classes) and DLJ (interpretation) generation. It uses a database for input discovery, RIOS for block processing, explicit cloud/topo/water/etc masks, and the `gdaltimeseries` utility to derive baseline statistics. Newer scripts in this repo mimic its behaviour where possible but remove DB and legacy tool dependencies.

## Purpose
- Detect woody clearing between a start and end date using: start/end TOA reflectance (db8), an FPC timeseries (dc4), and multiple masks.
- Produce:
  - DLL classification (10=no-clearing, 3=FPC-only, 34..39 increasing clearing thresholds)
  - DLJ interpretation stack: spectralIndex, sTest, combinedIndex, clearingProb (stretched to uint8)

## Dependencies
- Python (originally Py2-compatible via `from __future__`), now commonly run under Py3
- RIOS (`rios.applier`) for raster IO and block processing
- GDAL (ogr/osr bindings)
- qv/qvf utilities (naming, DB linkages, file staging)
- rsc.utils: `metadb`, `history`, `masks`, `gdalcommon`
- External tools invoked:
  - `gdaltimeseries` (compute baseline stats image)
  - `qv_applystdmasks.py` (apply masks to FPC per image)
  - `gdaladdRATfromfile.py` (optional RAT/class names)

## Inputs
- Scene/era OR explicit start/end db8:
  - `--scene pXXXrYYY` and `--era eYYZZ` or `--era dYYYYMMDDYYYYMMDD`
  - or `--startdateimage <db8>` and `--enddateimage <db8>`
- Optional:
  - `--reportinputs <file>`: list all required inputs and exit
  - `--omitcloudmasks`: exclude cloud/shadow masks in start/end masking
  - `--writeindexes`: write full index stack (_zindex)
  - `--timeseriesdates d1,d2,...`: override automatic seasonal timeseries selection
  - `--cloudthresh 40` (default): seasonal selection cloud percent threshold
  - `--clipqldstate`: clip outputs to QLD state boundary

Implicit inputs (discovered/generated):
- Start/end TOA reflectance (db8), inferred from DB if not provided
- FPC timeseries (dc4) images discovered via DB for the seasonal window
- Mask rasters per input image (cloud/shadow, water, topo incidence/cast, snow)
- Footprint image: `lztmna_<scene>_eall_dw1mz.img`

## Outputs
- DLL: `..._dllmz.img` (uint8, palette added; class recode values for mask-affected pixels)
- DLJ: `..._dljmz.img` (uint8 x4 bands; stretched for viewing)
- Optional `_zindex.img`: raw combined/spectral/fpcDiff/sTest/tTest (when `--writeindexes`)

## Processing steps (high level)
1. Resolve start/end db8 and FPC filenames from DB, based on `--era` or explicit images
2. Build seasonal FPC timeseries:
   - "Similar season" = within ±2 months of target end month
   - Limit to last 10 years, satellites L8/L9 only
   - Filter by `pcntcloud < cloudthresh`
   - For each year, pick the date with minimum cloud (if multiple, pick middle date after sorting)
   - Restrict to dates ≤ start date of era
3. Apply masks and normalize FPC per image:
   - `qv_applystdmasks.py` writes a masked temp; then RIOS normalizes: `125 + 15*(DN-mean)/std`, rounded, clipped [1..255], zeros preserved as nodata
4. Compute timeseries statistics with `gdaltimeseries` on the normalized stack:
   - Outputs a 5-band stats image: mean, std, stderr, slope, intercept, indexed later by RIOS
5. Change model (RIOS):
   - Compute indices: fpcDiff, sTest ((obs-pred)/stderr), tTest ((obs-mean)/std), spectralIndex (log1p-weighted bands), combinedIndex (linear combo)
   - Assign classes using legacy thresholds; force no-clearing where FPC start < 108
   - Apply masks: recode masked pixels to special class codes (e.g., 103–109 per mask type)
   - Set null where reflectance zeros present or outside footprint/state boundary
6. Interpretation stretch (RIOS):
   - Linear stretch to uint8 with different ±std windows: spectral=±2σ; sTest=±10σ; combined=±10σ
   - clearingProb = 200 * (1 - exp(-(0.01227*combined)^3.18975)), clipped to [0,255]
7. Styling and history:
   - Color table from `$QV_IMGTEMPLATEDIR/clearing_colours_*.txt` (fallback available)
   - Optional RAT class names, metadata history added with parents list

## Mask handling
- Mask types: cloud, cloudshadow, water NDX, topo incidence, topo cast shadow, snow
- For change classification, masked pixels are recoded to fixed values (103..109 pattern)
- `--omitcloudmasks` removes cloud/shadow from start/end masking stage and recode list is shortened

## Usage examples
- Process by era (SLATS years):
  ```powershell
  python scripts\edsadhoc_timeserieschange_d.py --scene p094r076 --era e2324
  ```
- Process by explicit db8 start/end images:
  ```powershell
  python scripts\edsadhoc_timeserieschange_d.py `
    --startdateimage data\compat\files\p094r076\lztmre_p094r076_20230724_db8mz.img `
    --enddateimage   data\compat\files\p094r076\lztmre_p094r076_20240831_db8mz.img
  ```
- Report only (no processing):
  ```powershell
  python scripts\edsadhoc_timeserieschange_d.py --scene p094r076 --era e2324 --reportinputs inputs.txt
  ```

## Assumptions and unknowns
- Database schema and availability:
  - Requires tables like `landsat_list`, `cloudamount`, `slats_dates` with specific columns
  - Connection parameters resolved inside `rsc.utils.metadb` (not documented here)
- External utilities available on PATH: `gdaltimeseries`, `qv_applystdmasks.py`, `gdaladdRATfromfile.py`
- Mask file locations and naming are handled by `rsc.utils.masks.getAvailableMaskname`
- Color tables and RAT files under `$QV_IMGTEMPLATEDIR`; fallback exists for colours but RAT presence varies
- Only L8/L9 considered in seasonal selection; older missions excluded by design
- Normalization uses DN values post-masking; scaling or radiometric calibration assumptions match legacy
- State boundary clipping: implemented only for QLD via DB geometry; other states not handled here
- Footprint file expected to exist: `lztmna_<scene>_eall_dw1mz.img`
- Error handling: missing masks raise `MissingInputError` (strict)

## Troubleshooting
- "Missing masks" errors: ensure mask generation pipeline has produced all mask layers for each input; or run with `--omitcloudmasks` cautiously
- No `gdaltimeseries`: install GDAL suite and ensure the tool is on PATH
- No DB connection: this script won’t run without `metadb`; use the modern replacements in this repo instead
- No outputs for thresholds 34–39: classification may contain only 3 and 10; that’s valid, and polygonization by thresholds will be empty

## Migration notes
- Modern replacements remove DB and legacy tool dependencies and operate on compat files directly
- If your environment lacks masks/DB, prefer `scripts/eds_legacy_method_window.py` or run legacy via `scripts/eds_legacy_window_runner.py` which adapts inputs while keeping legacy internals