# clip_vectors.py

Clip polygons by a clip layer (e.g., FC coverage masks).

- Unions all polygons in the clip layer for faster clipping.
- Preserves original attributes and (re)computes area_m2/area_ha.

Key options:
- --input-dir <dir of .shp>
- --clip <shapefile>
- --out-dir

Notes:
- Reprojects the clip geometry to match input layer CRS when required.
- If clip is polygonized from a raster, the union collapses many parts into a MultiPolygon.
