# vector_postprocess.py

Dissolve and/or skinny-core filter the merged polygons to clean and simplify outputs.

- Dissolve merges adjacent/overlapping polygons.
- Skinny-core filter removes polygons whose maximum core width is < N pixels (approx. via negative buffer).

Key options:
- --input-dir or --input-file
- --out-dir
- --dissolve
- --skinny-pixels N and either --pixel-size or --from-raster to infer pixel size

Notes:
- If input layer is geographic, area computations are done in EPSG:3577.
- Preserves 'thr' or 'class' attribute if present and recomputes area fields.
