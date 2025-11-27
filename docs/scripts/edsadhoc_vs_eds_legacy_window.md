# edsadhoc_timeserieschange_d vs legacy seasonal-window tools

This note compares the original legacy script (`edsadhoc_timeserieschange_d.py`) with the modern seasonal-window pathway: `eds_legacy_method_window.py` (re-implementation) and `eds_legacy_window_runner.py` (runner for the original).

In short: `edsadhoc_timeserieschange_d.py` is the reference implementation that depends on a DB, RIOS, mask infrastructure, and `gdaltimeseries`. The new tools aim to replicate outputs where feasible on machines without those dependencies by using the compat filesystem and Python/GDAL only.

## Summary of differences

- Discovery & dependencies:
  - edsadhoc: requires DB (landsat_list, cloudamount, slats_dates), RIOS, masks module, `gdaltimeseries`, and qv/qvf utilities.
  - eds_legacy_method_window: no DB/RIOS; uses file globbing of compat `db8/dc4` files; computes stats in NumPy.
  - eds_legacy_window_runner: still calls the original edsadhoc, but prepares inputs (db8) and passes an explicit seasonal date list, avoiding DB date selection logic.

- Start/End selection:
  - edsadhoc: uses `--era` (SLATS year pair or date range) or explicit db8s; DB resolves the dates for a scene and SLATS year.
  - method_window: takes explicit `--start-date/--end-date` (YYYYMMDD) and will pick nearest dc4 start/end within the window if exact matches aren’t present.
  - window_runner: for a given year and window (MMDD..MMDD), picks earliest and latest dc4 dates within that window for that year, then builds db8 for those dates.

- Seasonal baseline (FPC timeseries):
  - edsadhoc: within ±2 months of target month; last 10 years; L8/L9 only; cloud-filtered (`pcntcloud < cloudthresh`); chooses minimum-cloud date per year (ties -> middle).
  - method_window: within a provided window (MMDD..MMDD); last N years; chooses date per year closest in MMDD to the end target; no cloud criteria (assumes FC CLR masking and availability drive quality).
  - window_runner: similar to method_window selection but only assembles the list to pass into edsadhoc via `--timeseriesdates`.

- FPC normalization:
  - edsadhoc: mask first (qv_applystdmasks) then normalize via RIOS using `125 + 15*(DN-mean)/std`, with rounding and clip to [1..255], zeros set to 0.
  - method_window: treats FPC>0 as valid; compute mean/std over valid; same 125±15 scaling (float then cast) with clip [1..255], nodata=0; no external mask files.

- Timeseries stats:
  - edsadhoc: computed by `gdaltimeseries` (mean, std, stderr, slope, intercept) over normalized FPC stack.
  - method_window: computes the same arrays directly in NumPy, using decimal-year regression.

- Masks during change classification:
  - edsadhoc: applies mask rasters (cloud/shadow/water/topo/snow) and recodes masked pixels to special class values (103..109); respects footprint and optional QLD boundary.
  - method_window: no mask rasters; uses reflectance zeros as nodata; optional FPC start <108 rule preserved; footprint is typically the compat footprint image.

- Indices, thresholds, and outputs:
  - All: same spectralIndex formula, sTest/tTest definitions, combinedIndex weights, and class thresholds for 3 and 34..39. Same DLJ stretching rules and clearingProb formula.
  - Styling:
    - edsadhoc: adds palette and optional RAT directly via template files.
    - method_window: use `style_dll_dlj.py` to set palette and band names.

- State boundary clipping:
  - edsadhoc: optional `--clipqldstate` using DB geometries.
  - method_window: not included. If needed, clip downstream using `clip_vectors.py`.

## Practical impacts

- No DB/masks environment: method_window produces comparable DLL/DLJ where FC CLR and SR inputs are good; masked-class recodes (103..109) do not appear because masks aren’t applied.
- Cloud selection vs nearest-in-window: where edsadhoc would avoid cloudy years, method_window may include the nearest-in-window day irrespective of cloud; the expectation is that FC CLR timeseries mitigates cloud-related bias.
- Numeric small differences: edsadhoc rounds the normalized FPC values during scaling; method_window computes float then clips/casts. In practice the difference is ≤1 DN and rarely changes class outcomes.
- `gdaltimeseries` vs NumPy: for stable stacks these should match numerically; any divergence should be small. If a discrepancy is observed, check the chosen baseline date set.

## Recommendation

- If you can run the legacy stack (DB + masks + RIOS + tools), and you want exact provenance parity, use edsadhoc (optionally via `eds_legacy_window_runner.py` to assemble the seasonal dates from compat files).
- If you need a portable, DB-free workflow operating directly on local compat files, use `eds_legacy_method_window.py`.

## Feature matrix

- Discovery: DB (edsadhoc) vs file-system (method_window, window_runner)
- Baseline: cloud-min per year (edsadhoc) vs nearest-in-window per year (method_window/window_runner)
- Masks: explicit multi-mask recodes (edsadhoc) vs none (method_window)
- Stats: gdaltimeseries (edsadhoc) vs NumPy (method_window)
- Outputs: same DLL/DLJ names and classes
- Styling: in-script via templates (edsadhoc) vs separate `style_dll_dlj.py`
- Clipping: optional QLD (edsadhoc) vs downstream clip if needed

## References
- `scripts/edsadhoc_timeserieschange_d.py` – legacy script
- `scripts/eds_legacy_method_window.py` – portable re-implementation
- `scripts/eds_legacy_window_runner.py` – runner that adapts inputs but executes the legacy script