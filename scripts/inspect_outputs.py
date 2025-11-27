#!/usr/bin/env python
import argparse
from osgeo import gdal
import numpy as np
from pathlib import Path
import glob

def inspect(cls_path: str, int_path: str):
    ds = gdal.Open(cls_path)
    if ds is None:
        print(f"Cannot open {cls_path}")
        return
    band = ds.GetRasterBand(1)
    a = band.ReadAsArray()
    print(f"dllmz shape: {a.shape} dtype: {a.dtype}")
    vals, counts = np.unique(a, return_counts=True)
    pairs = sorted(zip(vals.tolist(), counts.tolist()), key=lambda x: x[0])
    print("class counts (first 10):", pairs[:10])

    ids = gdal.Open(int_path)
    if ids is None:
        print(f"Cannot open {int_path}")
        return
    print(f"dljmz bands: {ids.RasterCount}")
    for i in range(1, ids.RasterCount+1):
        b = ids.GetRasterBand(i)
        arr = b.ReadAsArray()
        print(f" band {i} -> dtype {arr.dtype}, min {np.nanmin(arr)}, max {np.nanmax(arr)}")

def main():
    ap = argparse.ArgumentParser(description="Inspect change outputs (dll/dlj)")
    ap.add_argument('--cls', help='Path to dllmz.img')
    ap.add_argument('--dlj', help='Path to dljmz.img')
    ap.add_argument('--scene', help='Scene code to autodetect latest files, e.g., p089r080')
    ap.add_argument('--pattern', help='Glob pattern to locate files if --scene not given')
    args = ap.parse_args()

    if not args.cls or not args.dlj:
        if args.scene:
            base = Path('data/compat/files') / args.scene
            # Prefer latest date-range era outputs dYYYY.. files; fallback to eYYYY
            cand = sorted(glob.glob(str(base / f"lztmre_{args.scene}_d*_dllmz.img")))
            if not cand:
                cand = sorted(glob.glob(str(base / f"lztmre_{args.scene}_e*_dllmz.img")))
            if not cand:
                raise SystemExit("No outputs found to inspect")
            cls_path = cand[-1]
            dlj_path = cls_path.replace('_dllmz.img', '_dljmz.img')
        elif args.pattern:
            cand = sorted(glob.glob(args.pattern))
            if not cand:
                raise SystemExit("Pattern matched no files")
            cls_path = cand[-1]
            dlj_path = cls_path.replace('_dllmz.img', '_dljmz.img')
        else:
            # Default to the known example
            base = Path('data/compat/files/p089r080')
            cls_path = str(base / 'lztmre_p089r080_e1625_dllmz.img')
            dlj_path = str(base / 'lztmre_p089r080_e1625_dljmz.img')
    else:
        cls_path = args.cls
        dlj_path = args.dlj

    print(f"Inspecting: {cls_path}")
    print(f"           {dlj_path}")
    inspect(cls_path, dlj_path)

if __name__ == "__main__":
    main()
