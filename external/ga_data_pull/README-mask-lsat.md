# mask_lsat — README (quick start)

Batch-find FC/SR rasters and matching FMASK files (by pathrow + date in filenames), then apply pixel masks using RIOS. Pixels outside the chosen keep-classes are set to 0 in all bands.

-----
## What it looks for (standard names)

 - FC: ga_ls_fc_<PATHROW>_<YYYYMMDD>_fc3ms.tif

 - SR: <sensor>[_ard]_<PATHROW>_<YYYYMMDD>_[final_](sr6b|srb6|sr7b|srb7).tif
   - e.g. ga_ls9c_ard_089080_20220615_final_srb7.tif

 - F MASK: <sensor>[_ard]_<PATHROW>_<YYYYMMDD>_[final_]fmask.tif
   - e.g. ga_ls9c_ard_089080_20220615_fmask.tif

Pairing key extracted from filename: _(\d{6})_(YYYYMMDD|YYYY-MM-DD) → (pathrow, yyyymmdd).


----
## Output naming

 - FC masked → ..._fc3ms_<suffix>.tif

 - SR masked → ..._sr6b_<suffix>.tif or ..._sr7b_<suffix>.tif

No overwrite by default—see --on-exists.

| Preset   | Keeps (FMASK codes) | Suffix                     |
| -------- | ------------------- | -------------------------- |
| `no`     | (ignore fmask)      | *(no suffix; no-op)*       |
| `clr`    | 1                   | `_clr`                     |
| `cw`     | 1,5                 | `_cw`                      |
| `cws`    | 1,5,3               | `_cws`                     |
| `cld`    | 2                   | `_cld`                     |
| `shd`    | 3                   | `_shd`                     |
| `snow`   | 4                   | `_snow`                    |
| `water`  | 5                   | `_water`                   |
| `custom` | `--mask-keep` list  | `_m<codes>` (e.g. `_m135`) |


FMASK codes: 0=nodata, 1=clear, 2=cloud, 3=cloud_shadow, 4=snow, 5=water.


```bash

# Dry run (default unless --do-write)
python mask_lsat.py --dir "D:\path\to\root" --mode both --preset clr

# Actually write outputs
python mask_lsat.py --dir "D:\path\to\root" --mode both --preset clr --do-write

# Safer when re-running: avoid overwrite by adding a suffix if the target exists
python mask_lsat.py --dir "D:\path\to\root" --mode fc --preset cw --do-write --on-exists suffix

# Process SR only, custom keep set
python mask_lsat.py --dir "D:\path\to\root" --mode sr --preset custom --mask-keep 1 3 5 --do-write

# Scan every directory level (not just leaves) and show debug logs
python mask_lsat.py --dir "D:\path\to\root" --include-nonleaf --debug
```

Key flags

 - --dir PATH : root folder to scan

 - --mode {fc|sr|both} : which products to mask

 - --do-write : actually write (otherwise it’s a dry run)

 - --on-exists {skip|overwrite|suffix} : behavior if output already exists (skip default)

 - --include-nonleaf : scan all subdirs (default scans leaf dirs only)

 - --debug : verbose pairing and matching info
-----

## Requirements

 - Python 3.8+

 - rios, numpy
    - (Install with conda: conda install -c conda-forge rios numpy)
