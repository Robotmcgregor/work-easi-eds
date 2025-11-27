# slats_compat_builder.py

Build SLATS-compatible products from GA SR and FC: db8 reflectance stacks (start/end) and dc4 time series (FPC).

- Input sources: directories or files pointing to SR composites and FC rasters
- Outputs:
	- `lztmre_<scene>_<date>_db8mz.img` (ENVI) for each SR date (B2..B7 or composite)
	- `lztmre_<scene>_<date>_dc4mz.img` (ENVI) for each FC date; can optionally convert FC→FPC
	- `lztmna_<scene>_eall_dw1mz.img` footprint (binary mask)

## Key options
- `--tile pXXXrYYY` – scene code
- SR (two dates expected):
	- `--sr-date YYYYMMDD --sr-dir <folder|composite>` (repeat twice)
	- Directory may contain per-band `*_B2.tif` etc or a composite `*_srb6/_srb7.tif`
- FC inputs (time series):
	- `--fc <glob>` (repeatable) and/or `--fc-list <txt file>`
	- `--fc-only-clr` (keep only `*_fc3ms_clr.tif`)
	- `--fc-prefer-clr` (prefer clr when both present; default behavior)
- FC→FPC conversion (optional):
	- `--fc-convert-to-fpc` – apply FPC = 100*(1-exp(-k*FC^n)) before writing dc4
	- `--fc-k` (default 0.000435) and `--fc-n` (default 1.909)
	- `--fc-nodata` – override nodata for FC input (else band nodata used)

Notes:
- Without `--fc-convert-to-fpc`, dc4 will contain FC green as provided (e.g., 0–100); downstream normalization in legacy methods treats 0 as nodata and rescales valid pixels, so this still works.
- With `--fc-convert-to-fpc`, dc4 contains FPC (0–100, uint8). This is the preferred feed for the legacy FPC time series.
- The script de-duplicates FC inputs by date and prefers masked CLR variants.

## Example
```powershell
python scripts\slats_compat_builder.py `
	--tile p094r076 `
	--sr-date 20230724 --sr-dir D:\data\lsat\094_076\2023\202307\ga_ls9c_ard_094076_20230724_srb7.tif `
	--sr-date 20240831 --sr-dir D:\data\lsat\094_076\2024\202408\ga_ls8c_ard_094076_20240831_srb7.tif `
	--fc "D:\data\lsat\094_076\**\*_fc3ms*.tif" `
	--fc-prefer-clr `
	--fc-convert-to-fpc --fc-k 0.000435 --fc-n 1.909
```

## Implementation details
- SR stacking copies per-band files (or the composite bands) to an ENVI stack with nodata=0.
- FC→FPC conversion respects the input band’s nodata (or `--fc-nodata`) and writes nodata as 0 for downstream handling.
- The footprint is created from the first product encountered (db8 or dc4) with value 1 and nodata 0.
