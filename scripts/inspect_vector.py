#!/usr/bin/env python
import argparse
import os
from osgeo import ogr


def main():
    ap = argparse.ArgumentParser(
        description="List layers and feature counts in a vector file (e.g., GPKG)"
    )
    ap.add_argument("path", help="Path to GeoPackage/Shapefile")
    args = ap.parse_args()

    path = args.path
    if os.path.isdir(path):
        # Iterate shapefiles in directory
        files = [f for f in os.listdir(path) if f.lower().endswith(".shp")]
        if not files:
            print(f"No shapefiles found in directory {path}")
            return 0
        for f in sorted(files):
            fp = os.path.join(path, f)
            ds = ogr.Open(fp)
            if ds is None:
                print(f"Cannot open {fp}")
                continue
            lyr = ds.GetLayer(0)
            count = lyr.GetFeatureCount()
            defn = lyr.GetLayerDefn()
            has_thr = defn.GetFieldIndex("thr") != -1
            has_class = defn.GetFieldIndex("class") != -1
            print(f"{f}: features={count}")
            # compute area stats if available
            has_area = defn.GetFieldIndex("area_ha") != -1
            if has_area:
                total_area = 0.0
                for feat in lyr:
                    total_area += float(feat.GetField("area_ha") or 0)
                lyr.ResetReading()
                print(f"  total_area_ha={total_area:,.2f}")
            # sample values
            sample_field = "thr" if has_thr else ("class" if has_class else None)
            if sample_field:
                vals = {}
                n = 0
                for feat in lyr:
                    v = feat.GetField(sample_field)
                    vals[v] = vals.get(v, 0) + 1
                    n += 1
                    if n > 10000:
                        break
                lyr.ResetReading()
                items = sorted(vals.items())[:20]
                print(f"  sample {sample_field} counts (partial): {items}")
    else:
        ds = ogr.Open(path)
        if ds is None:
            print(f"Cannot open {path}")
            return 1
        for i in range(ds.GetLayerCount()):
            lyr = ds.GetLayerByIndex(i)
            name = lyr.GetName()
            count = lyr.GetFeatureCount()
            print(f"Layer {i}: {name}, features={count}")
            defn = lyr.GetLayerDefn()
            has_class = defn.GetFieldIndex("class") != -1
            n = 0
            if has_class:
                vals = {}
                for feat in lyr:
                    val = feat.GetField("class")
                    vals[val] = vals.get(val, 0) + 1
                    n += 1
                    if n > 10000:
                        break
                lyr.ResetReading()
                items = sorted(vals.items())[:20]
                print("  sample class counts (partial):", items)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
