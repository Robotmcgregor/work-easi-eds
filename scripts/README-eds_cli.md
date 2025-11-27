# README — eds_cli.py

Utilities to list, filter, download, and upload Landsat inputs on S3, plus run the EDS pipeline for a single tile.

Works well on Windows PowerShell and preserves your S3 folder structure (e.g., `089_078/2023/202307/...`).

## Prerequisites

- Python 3.12 (or 3.11)
- Install minimal dependencies:
  - `py -3 -m pip install boto3 requests python-dotenv`
  - Or: `py -3 -m pip install -r requirements-py312.txt`
- Configure credentials via environment or an AWS profile/role (preferred).
- Optional: set `.env` in the repo root; it is auto-loaded.

## S3 naming support

The CLI automatically tries both tile folder styles:
- `PPPRRR/` (e.g., `089078/`)
- `PPP_RRR/` (e.g., `089_078/`) — this matches your current bucket layout

## Quick start (Windows PowerShell)

List a tile’s keys (auto-tries underscore variant):
```
py -3 scripts\eds_cli.py list-s3 089078 --limit 10 --bucket "eia-satellite" --region "ap-southeast-2"
```

Download filtered files to local destination (preserves S3 structure under `--dest`):
```
# fc3ms (ls_fc) for 2023
py -3 scripts\eds_cli.py download-s3 089078 --bucket "eia-satellite" --region "ap-southeast-2" \
  --year 2023 --sensor ls_fc --type fc3ms --limit 5 --dest "D:\data\lsat"

# fmask (ls9c) for 2023
py -3 scripts\eds_cli.py download-s3 089078 --bucket "eia-satellite" --region "ap-southeast-2" \
  --year 2023 --sensor ls9c --type fmask --limit 5 --dest "D:\data\lsat"
```

Upload filtered local files back to S3 (preserves relative structure under `--source`):
```
# Dry-run first (no changes):
py -3 scripts\eds_cli.py upload-s3 089078 --source "D:\data\lsat" --bucket "eia-satellite" --region "ap-southeast-2" \
  --year 2023 --sensor ls_fc --type fc3ms --dry-run

# Upload for real (omit --dry-run)
py -3 scripts\eds_cli.py upload-s3 089078 --source "D:\data\lsat" --bucket "eia-satellite" --region "ap-southeast-2" \
  --year 2023 --sensor ls_fc --type fc3ms
```

Fetch inputs by date window (S3 first, then USGS fallback if configured):
```
py -3 scripts\eds_cli.py fetch-inputs 089078 --start 2023-07-01 --end 2023-07-31 --limit 5 \
  --bucket "eia-satellite" --region "ap-southeast-2"
```

Run EDS for a tile (ensures inputs exist):
```
py -3 scripts\eds_cli.py run-tile 089078 --days-back 7 --confidence 0.7
# or
py -3 scripts\eds_cli.py run-tile 089078 --start 2023-07-01 --end 2023-07-31 --confidence 0.7
```

## Command reference

### list-s3
- Purpose: List S3 keys for a tile prefix.
- Examples:
```
py -3 scripts\eds_cli.py list-s3 089078 --limit 10 --bucket "eia-satellite" --region "ap-southeast-2"
py -3 scripts\eds_cli.py list-s3 089078 --bucket "eia-satellite" --region "ap-southeast-2" --prefix "089_078/2023/202307/"
```
- Options: `--bucket --region --profile --endpoint --role-arn --base-prefix --prefix --shallow --limit`

### download-s3
- Purpose: Download S3 files to a local destination using filters, preserving the S3 structure under `--dest`.
- Filters:
  - `--year 2023`
  - `--sensor ls_fc|ls9c|ls8c` (parsed from filename, e.g., `ga_ls_fc_*`)
  - `--type fc3ms|fmask|srb7|...` (last token before `.tif`)
- Example:
```
py -3 scripts\eds_cli.py download-s3 089078 --bucket "eia-satellite" --region "ap-southeast-2" \
  --year 2023 --sensor ls_fc --type fc3ms --limit 5 --dest "D:\data\lsat"
```
- Options: `--bucket --region --profile --endpoint --role-arn --base-prefix --prefix --year --sensor --type --limit --dest --overwrite`

### upload-s3
- Purpose: Upload local files to S3 while preserving relative structure under `--source`.
- Filters: Same as download-s3 (year inferred from folder or filename, sensor/type from filename).
- Example:
```
py -3 scripts\eds_cli.py upload-s3 089078 --source "D:\data\lsat" --bucket "eia-satellite" --region "ap-southeast-2" \
  --year 2023 --sensor ls_fc --type fc3ms --dry-run
```
- Options: `--source --bucket --region --profile --endpoint --role-arn --base-prefix --year --sensor --type --limit --overwrite --dry-run`

### fetch-inputs
- Purpose: Ensure inputs exist locally by date range (S3 first, if empty then USGS M2M if configured).
- Example:
```
py -3 scripts\eds_cli.py fetch-inputs 089078 --start 2023-07-01 --end 2023-07-31 --limit 5 \
  --bucket "eia-satellite" --region "ap-southeast-2"
```

### run-tile
- Purpose: Run pipeline for a tile using a recent window or explicit dates.

## Behavior on existing files
- Downloads: skip existing local files by default; use `--overwrite` to replace.
- Uploads: skip existing S3 objects by default; use `--overwrite` to replace.
- No deletes are performed by these commands (local or S3).

## Environment variables (optional)
- S3: `S3_BUCKET`, `S3_BASE_PREFIX`, `AWS_REGION`, `AWS_PROFILE`, `S3_ENDPOINT_URL`, `S3_ROLE_ARN`
- USGS: `USGS_USERNAME`, `USGS_PASSWORD`, `USGS_M2M_ENDPOINT`, `USGS_DATASET`, `USGS_NODE`

## Troubleshooting
- AccessDenied on list: ensure your IAM or assumed role has `s3:ListBucket` and the bucket policy allows it.
- Cross-account: use `--role-arn` or an AWS profile that assumes a role with access.
- USGS 404 on login: ensure endpoint is `https://m2m.cr.usgs.gov/api/api/json/stable/`, account active, dataset/node correct.
