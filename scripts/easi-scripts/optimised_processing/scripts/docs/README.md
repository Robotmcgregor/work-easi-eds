# Optimised EDS processing (NDVI seasonal-window) — docs

These docs describe the pipeline under `scripts/easi-scripts/optimised_processing/scripts/` and (in particular) how the **DLL** and **DLJ** rasters are produced, what they represent, and how downstream masks/vectors are derived.

## Where to start

- `eds_master_pipeline_optimised.py` is the main entrypoint.
- The change detection logic that creates DLL/DLJ is in `methods/legacy_window_ndvi_envi.py` (invoked by `tasks/task05_run_legacy_method.py`).

## Documents

- [Pipeline overview](pipeline.md)
- [DLL/DLJ outputs (formats, naming, derivation)](outputs_dll_dlj.md)
- [DLJ bands reference (what each band means)](dlj_bands.md)
- [Clearing probability thresholds (strong/clear)](clearing_probability_thresholds.md)
- [Output locations (normal vs --diagnostics)](output_locations.md)
- [Troubleshooting & diagnostics](troubleshooting.md)

## Note on “legacy” flags

Even though the pipeline exposes `--legacy-*` flags, the default behavior (no legacy flags) enables SR auto-scaling and nodata-aware baseline stats, which often produces the best results. See [Troubleshooting & diagnostics](troubleshooting.md) for details.

## Glossary (quick)

- **GA0**: 6‑band Surface Reflectance composite (Blue/Green/Red/NIR/SWIR1/SWIR2). Produced for start and end dates.
- **GA1**: NDVI scene (cloud-masked) produced per date (float32 NDVI) and stored in S3, then staged locally.
- **Seasonal window**: MMDD range expanded around requested dates to reduce seasonal effects.
- **DLL**: 1‑band classification raster (uint8) describing the “clearing class”.
- **DLJ**: 4‑band interpretation raster (uint8) containing stretched indices plus `clearingProb` (used for masks/vectors).
