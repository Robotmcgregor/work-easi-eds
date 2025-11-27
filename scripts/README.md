# EDS CLI (scripts/eds_cli.py)

Utilities to browse and transfer Landsat inputs between S3 and your local cache, and to run a tile through the EDS pipeline.

## Install (Python 3.12-friendly)

- Minimal deps for S3/HTTP and dotenv:
  - `py -3 -m pip install boto3 requests python-dotenv`
- Or use the curated set: `py -3 -m pip install -r requirements-py312.txt`

## Commands

### list-s3
List keys for a tile. Automatically tries both PPPRRR and PPP_RRR folder styles (e.g., `089078/` and `089_078/`).

```
py -3 scripts\eds_cli.py list-s3 089078 --limit 10 --bucket "eia-satellite" --region "ap-southeast-2"
# Or target an exact folder
py -3 scripts\eds_cli.py list-s3 089078 --bucket "eia-satellite" --region "ap-southeast-2" --prefix "089_078/2023/202307/"
```

Options: `--bucket --region --profile --endpoint --role-arn --base-prefix --prefix --shallow`

### fetch-inputs
Fetch inputs for a tile and date window. Tries S3 first, then USGS M2M fallback (if configured). Downloads to `data/cache/<tile>`.

```
py -3 scripts\eds_cli.py fetch-inputs 089078 --start 2023-07-01 --end 2023-07-31 --limit 5 --bucket "eia-satellite" --region "ap-southeast-2"
```

Options: `--bucket --region --profile --endpoint --role-arn --base-prefix --prefix --limit`

### download-s3
Download S3 files for a tile with filters, preserving the S3 folder structure under `--dest`.

- Filters: `--year 2023`, `--sensor ls_fc|ls9c|ls8c`, `--type fc3ms|fmask|srb7|...`
- Destination example: `D:\data\lsat\089_078\2023\202307\ga_ls_fc_089078_20230720_fc3ms.tif`

```
py -3 scripts\eds_cli.py download-s3 089078 --bucket "eia-satellite" --region "ap-southeast-2" --year 2023 --sensor ls_fc --type fc3ms --limit 5 --dest "D:\data\lsat"
py -3 scripts\eds_cli.py download-s3 089078 --bucket "eia-satellite" --region "ap-southeast-2" --year 2023 --sensor ls9c --type fmask --limit 5 --dest "D:\data\lsat"
```

Options: `--bucket --region --profile --endpoint --role-arn --base-prefix --prefix --year --sensor --type --limit --dest --overwrite`

### upload-s3
Upload local files to S3 preserving their relative structure under `--source`. Same filters as download-s3, applied to filenames and inferred year.

```
# Dry run (no changes):
py -3 scripts\eds_cli.py upload-s3 089078 --source "D:\data\lsat" --bucket "eia-satellite" --region "ap-southeast-2" --year 2023 --sensor ls_fc --type fc3ms --dry-run

# Upload for real:
py -3 scripts\eds_cli.py upload-s3 089078 --source "D:\data\lsat" --bucket "eia-satellite" --region "ap-southeast-2" --year 2023 --sensor ls_fc --type fc3ms
```

- Keys are created as `<base-prefix>/<relative-path-under-source>`, where the relative path typically starts with `PPP_RRR/YYYY/YYYYMM/filename.tif`.
- If the relative path does not begin with the tile, files are skipped unless the tile appears later in the path.

Options: `--source --bucket --region --profile --endpoint --role-arn --base-prefix --year --sensor --type --limit --overwrite --dry-run`

### run-tile
Run EDS pipeline for a tile (mock pipeline unless you’ve wired a real one). Ensures inputs exist via `fetch-inputs` behavior.
```
py -3 scripts\eds_cli.py run-tile 089078 --days-back 7 --confidence 0.7
py -3 scripts\eds_cli.py run-tile 089078 --start 2023-07-01 --end 2023-07-31 --confidence 0.7
```

## Environment
- `.env` is loaded automatically. You can also pass overrides via flags.
- Prefer AWS profiles/roles over raw keys in `.env` for security.

Env vars commonly used:
- S3: `S3_BUCKET`, `S3_BASE_PREFIX`, `AWS_REGION`, `AWS_PROFILE`, `S3_ENDPOINT_URL`, `S3_ROLE_ARN`
- USGS: `USGS_USERNAME`, `USGS_PASSWORD`, `USGS_M2M_ENDPOINT`, `USGS_DATASET`, `USGS_NODE`

## FAQ
- Q: Does download-s3/fetch-inputs remove originals from S3?
  - A: No. They copy objects from S3 to local; originals remain in S3.
- Q: Does upload-s3 delete local files after upload?
  - A: No. It uploads and leaves your local files in place.
- Q: What if the file already exists?
  - A: By default, downloads and uploads skip existing targets. Add `--overwrite` to force replacement.
- Q: My tile folders are `PPP_RRR/`—is that supported?
  - A: Yes. The CLI auto-tries both `PPPRRR/` and `PPP_RRR/`.
