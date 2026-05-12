# Troubleshooting

This is a quick list of common issues and where to look.

## “My outputs overwrote each other”

Cause:
- You ran multiple times with the same `--run-tag`.

Fix:
- Always set `--run-tag run1`, then `--run-tag run2`, etc.

## “The pipeline chose different dates than I asked for”

Cause:
- The pipeline picks the closest usable SR scenes (usually low cloud) around your requested start/end.

What to do:
- Check the console output for the effective start/end dates.
- If you need exact dates, the resolver logic would need to be changed (not recommended for routine runs).

## “Missing NDVI in S3” warnings

Cause:
- A required NDVI scene wasn’t found at the expected S3 key.

What to do:
- Re-run with the pipeline (it can build missing NDVI if configured to do so).
- Confirm your S3 `bucket` and `prefix` are correct.

## “Autoscale failed” / missing temp file during GA0 build

Cause:
- Usually indicates a temporary file was not created as expected.

What to do:
- Re-run once (sometimes transient filesystem issues happen).
- If it persists, check the `ga0_work/` folder inside the run directory.

## “Extreme values / nonsense stats in diagnostics”

Often caused by one of:
- SR scaling mismatch (reflectance 0..1 vs 0..10000)
- nodata being included in NDVI baseline statistics

What to do:
- Compare runs using the SR scaling A/B flags (see [ab_testing_flags.md](ab_testing_flags.md)).
- Use `--legacy-baseline-include-nodata` only when you specifically want the old behaviour.

## “Shapefiles are empty but I expected detections”

Common reasons:
- The clear/strong thresholds are too high for this tile/date
- The chosen DLJ band is not the one you expect

What to do:
- Check the printed stats for the DLJ band in the logs.
- Try lowering `--strong-threshold`/`--clear-threshold` if those flags are exposed in your run.
