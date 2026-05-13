# Optimised NDVI pipeline docs

This folder documents the **optimised NDVI** pipeline in `scripts/easi-scripts/optimised_ndvi/scripts/`.

## What this pipeline does

- Builds (or loads) a **scene manifest** (Parquet) for a WRS tile and date window.
- For each scene, loads DEA ARD measurements via **ODC Datacube**.
- Computes **NDVI** and a **land-clear mask** (from `oa_fmask`).
- Writes outputs as **COGs** and uploads them to **S3**.

## Where to start

- `pipeline.md` – step-by-step explanation of how the code flows.
- `cli.md` – how to run the entrypoint + argument reference.
- `outputs.md` – all outputs and the exact paths/patterns the code writes.
