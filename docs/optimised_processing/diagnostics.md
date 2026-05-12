# Diagnostics and comparing runs

The pipeline can write small “one row per run” diagnostics files (CSV/JSON) so you can concatenate them across many tiles.

These are intended to answer questions like:
- “Did this run use SR scaling?”
- “How many pixels were classified as clearing?”
- “Did the DLJ clearing probability look sane?”

## Where diagnostics live

Diagnostics are stored in the local run folder under:

- `<work-dir>/<tile>/<run-tag>/diagnostics/`

The legacy method also uploads run outputs to S3, but the diagnostics files are primarily intended for local batch comparison (you can copy them elsewhere if needed).

## Typical diagnostics artefacts

Depending on how you run the pipeline, you may see:

- Run metadata JSON (one file):
  - “what inputs were used?”
  - “what flags were enabled?”
  - “what outputs were written?”

- Summary CSV (one row):
  - key counts and summary stats designed for concatenation

- SR scaling verification CSV (one row):
  - percentiles/ranges that help confirm scaling and sanity

Filenames include a suffix encoding the legacy-mode flags so different A/B runs do not overwrite each other in the same diagnostics folder.

## How to compare runs (practical)

Start with a simple folder compare:

- Compare S3 run outputs:
  - `.../outputs/run1/` vs `.../outputs/run2/`

Then use the diagnostics:

1) Concatenate many per-run CSVs into one table
2) Sort/group by tile and run_tag
3) Compare high-level counts (e.g. number of “clearing” pixels)

## What to compare first

- DLL class counts (overall and by class code)
- DLJ clearing probability band percentiles
- Strong/Clear mask pixel counts
- Shapefile polygon counts and total area

If you want, I can add a small helper script to walk a folder tree and concatenate the one-row CSVs automatically.
