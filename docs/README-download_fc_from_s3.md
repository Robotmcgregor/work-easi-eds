# download_fc_from_s3

Download GA Fractional Cover (FC) stacks from your S3 bucket for a tile.

Two modes:
- Explicit dates: `--dates 20160106,20170124` (YYYYMMDD)
- Seasonal window across years: `--start-yyyymm 202507 --end-yyyymm 202510 --span-years 10`
  - Collects all FC whose year-month falls within the [07..10] window for years 2016..2025 (inclusive of end year).

What it matches in S3:
- `*_fc3ms.tif`
- `*_fc3ms_clr.tif`

Output folder structure (Windows-friendly):
- `D:\data\lsat\<PPP_RRR>\<YYYY>\<YYYYMM>\<filename>.tif`
  - Example: `D:\data\lsat\089_080\2016\201601\ga_ls_fc_089080_20160106_fc3ms.tif`

Env/flags for S3:
- Uses `S3_BUCKET`, `AWS_REGION` / `AWS_DEFAULT_REGION`, optional `S3_BASE_PREFIX`, `AWS_PROFILE`, `S3_ENDPOINT_URL`, `S3_ROLE_ARN`.
- Pass `--no-base-prefix` to ignore `S3_BASE_PREFIX` and scan from bucket root (useful if your keys start at `<PPP_RRR>/`).

## Examples (PowerShell)

Dry-run explicit dates (no downloads, just prints hits):

```powershell
python scripts\download_fc_from_s3.py --tile 089_080 --dates 20160106,20170124 --dry-run --no-base-prefix
```

Seasonal window across last 10 years (inclusive of end year):

```powershell
python scripts\download_fc_from_s3.py --tile 089_080 --start-yyyymm 202507 --end-yyyymm 202510 --span-years 10 --dry-run --no-base-prefix
```

Actually download and write CSV report:

```powershell
python scripts\download_fc_from_s3.py --tile 089_080 --start-yyyymm 202507 --end-yyyymm 202510 --span-years 10 --dest D:\data\lsat --no-base-prefix --csv data\fc_089_080_season.csv
```

Include expected but missing months in the CSV (for seasonal mode):

```powershell
python scripts\download_fc_from_s3.py --tile 089_080 --start-yyyymm 202507 --end-yyyymm 202510 --span-years 10 --dry-run --no-base-prefix --csv data\fc_089_080_season.csv --csv-include-expected
```

## CSV columns

- `mode`          : `dates` or `seasonal`
- `tile`          : `PPP_RRR`
- `year`          : `YYYY`
- `yearmonth`     : `YYYYMM`
- `date`          : `YYYYMMDD` if parsed
- `key`           : S3 key found (blank for MISS/EXPECTED-NOT-FOUND)
- `filename`      : basename
- `dest`          : target local path
- `action`        : `HIT (dry-run)` | `DOWNLOADED` | `MISS` | `ERROR: ...` | `EXPECTED-NOT-FOUND`

## Existing files handling

- Use `--on-exists skip` (default) to leave existing local files untouched (records `SKIP-EXISTS` in CSV).
- Use `--on-exists overwrite` to re-download and replace existing files.

## Notes

- The script does not modify your S3 bucket.
- If both `_fc3ms.tif` and `_fc3ms_clr.tif` exist for a date, it will list whichever it finds; re-run if you want both.
- Combine with `external/ga_data_pull/mask_lsat.py` to apply `_clr` masks using FMASK files.
