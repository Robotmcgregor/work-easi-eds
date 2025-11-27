# style_dll_dlj.py

Apply a legacy-like palette to DLL and set DLJ band names for easy viewing in QGIS.

- DLL band 1 (classes):
  - 0 = transparent (nodata)
  - 10 = no clearing (light grey)
  - 3 = FPC-only (cyan)
  - 34..39 = increasing clearing (yellow → orange → red → purple)
- DLJ bands: spectralIndex, sTest, combinedIndex, clearingProb

Usage:
```
python scripts/style_dll_dlj.py --dll path\to\*_dllmz.img --dlj path\to\*_dljmz.img
```
