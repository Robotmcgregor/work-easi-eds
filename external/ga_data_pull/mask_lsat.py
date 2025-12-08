#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
mask_apply_rios.py — Find SR/FC + FMASK pairs and apply pixel masks with RIOS.

Pairs files by (pathrow, date) extracted from filenames.

Inputs (standard names it will match)
-------------------------------------
FC : ga_ls_fc_<PATHROW>_<YYYYMMDD>_fc3ms.tif
SR : <sensor>_<PATHROW>_<YYYYMMDD>_sr6b.tif  OR  ..._sr7b.tif   (e.g., ga_ls9c_089080_20231024_sr7b.tif)
FM : <sensor>_<PATHROW>_<YYYYMMDD>_fmask.tif (e.g., ga_ls9c_089080_20231024_fmask.tif)

Outputs
-------
FC masked → ..._fc3ms_<suffix>.tif
SR masked → ..._sr6b_<suffix>.tif  /  ..._sr7b_<suffix>.tif

Mask presets & suffix
---------------------
no mask : ignore FMASK                  → (no suffix; script will NO-OP for safety)
clr     : keep [1] (clear)              → _clr
cw      : keep [1,5] (clear, water)     → _cw
cws     : keep [1,5,3] (+cloud_shadow)  → _cws
cld     : keep [2] (cloud)              → _cld
shd     : keep [3] (cloud_shadow)       → _shd
snow    : keep [4] (snow)               → _snow
water   : keep [5] (water)              → _water
custom  : use --mask-keep codes         → _m<codes>  e.g. _m135

Notes
-----
- Masking sets pixels outside 'keep' to 0 in all bands (RGBA not used).
- We DO NOT overwrite originals by default; you must choose a suffix preset.
- Use --dry-run to preview, --do-write to actually write outputs.
- Searches leaf directories by default (fewer false positives). Use --include-nonleaf to scan everything.

Requires: rios, numpy
"""

import os
import re
import argparse
from pathlib import Path
from collections import defaultdict
import numpy as np
from rios import applier

# -----------------------
# Preset → codes + suffix
# -----------------------
PRESETS = {
    "no": {"keep": None, "suffix": ""},  # no-op
    "clr": {"keep": [1], "suffix": "_clr"},
    "cw": {"keep": [1, 5], "suffix": "_cw"},
    "cws": {"keep": [1, 5, 3], "suffix": "_cws"},
    "cld": {"keep": [2], "suffix": "_cld"},
    "shd": {"keep": [3], "suffix": "_shd"},
    "snow": {"keep": [4], "suffix": "_snow"},
    "water": {"keep": [5], "suffix": "_water"},
    "custom": {"keep": None, "suffix": None},  # set from --mask-keep
}

# -----------------------
# Patterns & pairing key
# -----------------------
# Key = (pathrow, yyyymmdd)
# ---- Key = (pathrow, yyyymmdd); accept YYYYMMDD or YYYY-MM-DD, followed by "_" or "." or end
RE_KEY = re.compile(
    r"_(?P<pathrow>\d{6})_(?P<date>(?:\d{8}|\d{4}-\d{2}-\d{2}))(?=_|\.|$)",
    re.IGNORECASE,
)

RE_SR = re.compile(
    r"^(?P<sens>ga_ls\d+c)(?:_ard)?_(?P<pr>\d{6})_(?P<ymd>\d{8})_(?:final_)?(?:sr6b|srb6|sr7b|srb7)\.tif$",
    re.IGNORECASE,
)

RE_FM = re.compile(
    r"^(?P<sens>ga_ls\d+c)(?:_ard)?_(?P<pr>\d{6})_(?P<ymd>\d{8})_(?:final_)?fmask\.tif$",
    re.IGNORECASE,
)

# ---- File recognisers (names only; folder is arbitrary)

# FC: ga_ls_fc_089080_20220615_fc3ms.tif  (your renamed FC product)
RE_FC = re.compile(r"^ga_ls_fc_(?P<pr>\d{6})_(?P<ymd>\d{8})_fc3ms\.tif$", re.IGNORECASE)


def parse_args():
    p = argparse.ArgumentParser(
        description="Apply FMASK to SR/FC products with RIOS (batch)."
    )
    p.add_argument("--dir", required=True, help="Root directory to scan")
    p.add_argument(
        "--mode",
        choices=["fc", "sr", "both"],
        default="both",
        help="Which products to process (default: both)",
    )
    p.add_argument(
        "--include-nonleaf",
        action="store_true",
        help="Scan ALL directories (default: leaf/bottom-only).",
    )

    # Masking
    p.add_argument(
        "--preset",
        choices=list(PRESETS.keys()),
        default="clr",
        help="Mask preset (default: clr). 'no' = no-op.",
    )
    p.add_argument(
        "--mask-keep",
        nargs="*",
        type=int,
        default=None,
        help="Codes to keep for preset=custom (e.g. --mask-keep 1 3 5).",
    )

    # Safety & behaviour
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only (default if --do-write not set).",
    )
    p.add_argument(
        "--do-write", action="store_true", help="Actually write masked outputs."
    )
    p.add_argument(
        "--on-exists",
        choices=["skip", "overwrite", "suffix"],
        default="skip",
        help="If output exists: skip (default), overwrite, or add '__new' suffix.",
    )
    p.add_argument("--debug", action="store_true", help="Verbose scan/match logging.")

    return p.parse_args()


def rio_controls():
    """Standard RIOS writer options: tiled + LZW."""
    c = applier.ApplierControls()
    c.setOutputDriverName("GTiff")
    c.setWindowXsize(256)
    c.setWindowYsize(256)
    c.setCreationOptions(
        [
            "COMPRESS=LZW",
            "TILED=YES",
            "BLOCKXSIZE=256",
            "BLOCKYSIZE=256",
            "BIGTIFF=IF_SAFER",
        ]
    )
    return c


def key_from_name(name: str):
    m = RE_KEY.search(name)
    if not m:
        return None
    pr = m.group("pathrow")
    d = m.group("date").replace("-", "")
    return (pr, d)


def collect_pairs(
    root: Path, include_nonleaf: bool, want_fc: bool, want_sr: bool, debug: bool = True
):
    """
    Return:
      fc_pairs : list[(fc_path, fmask_path, (pr, yyyymmdd))]
      sr_pairs : list[(sr_path, fmask_path, (pr, yyyymmdd))]
      orphans  : dict
    """
    buckets = defaultdict(dict)

    for dirpath, dirnames, filenames in os.walk(root):
        if debug:
            print(f"\n[SCAN] dir={dirpath}")
            if dirnames and not include_nonleaf:
                print("  └─ has subdirs and leaf-only is True → skip this level")
        if not include_nonleaf and dirnames:
            continue

        if debug:
            print("  files:", filenames if filenames else "– (none)")

        for fn in filenames:
            p = Path(dirpath) / fn
            key = key_from_name(fn)
            if debug:
                print(f"   • {fn}")

            if not key:
                if debug:
                    print("     ↳ no (pathrow,date) key found → skip")
                continue

            is_fc = bool(RE_FC.match(fn)) if want_fc else False
            # *** changed: single SR recogniser ***
            is_sr = bool(RE_SR.match(fn)) if want_sr else False
            is_fm = bool(RE_FM.match(fn))

            if debug:
                print(f"     key={key} | FC={is_fc} SR={is_sr} FMASK={is_fm}")

            if is_fc:
                if "fc" not in buckets[key] or len(str(p)) > len(
                    str(buckets[key]["fc"])
                ):
                    if debug and "fc" in buckets[key]:
                        print(
                            f"     ↳ replace FC: {buckets[key]['fc'].name} → {p.name}"
                        )
                    buckets[key]["fc"] = p

            if is_sr:
                if "sr" not in buckets[key] or len(str(p)) > len(
                    str(buckets[key]["sr"])
                ):
                    if debug and "sr" in buckets[key]:
                        print(
                            f"     ↳ replace SR: {buckets[key]['sr'].name} → {p.name}"
                        )
                    buckets[key]["sr"] = p

            if is_fm:
                if "fm" not in buckets[key] or len(str(p)) > len(
                    str(buckets[key]["fm"])
                ):
                    if debug and "fm" in buckets[key]:
                        print(
                            f"     ↳ replace FM: {buckets[key]['fm'].name} → {p.name}"
                        )
                    buckets[key]["fm"] = p

    fc_pairs, sr_pairs = [], []
    orphans = {"fc": {}, "sr": {}, "fm": {}}

    if debug:
        print("\n[BUCKET SUMMARY]")
        for k, d in sorted(buckets.items()):
            print(
                f"  key={k} → {{ {', '.join(f'{t}: {Path(v).name}' for t, v in d.items())} }}"
            )

    for key, d in buckets.items():
        if "fc" in d and "fm" in d:
            fc_pairs.append((d["fc"], d["fm"], key))
        elif "fc" in d:
            orphans["fc"][key] = d["fc"]

        if "sr" in d and "fm" in d:
            sr_pairs.append((d["sr"], d["fm"], key))
        elif "sr" in d:
            orphans["sr"][key] = d["sr"]

        if "fm" in d and "fc" not in d and "sr" not in d:
            orphans["fm"][key] = d["fm"]

    if debug:
        print(
            f"\n[RESULT] fc_pairs={len(fc_pairs)} sr_pairs={len(sr_pairs)} "
            f"orphans: fc={len(orphans['fc'])} sr={len(orphans['sr'])} fm={len(orphans['fm'])}"
        )

    return fc_pairs, sr_pairs, orphans


def out_name_with_suffix(in_path: Path, suffix: str) -> Path:
    """Append suffix before extension (no double underscores)."""
    if not suffix:
        # no-suffix choice → to avoid overwriting, we treat this as a no-op
        return in_path
    return in_path.with_name(f"{in_path.stem}{suffix}{in_path.suffix}")


def apply_mask_rios(in_img: Path, in_fm: Path, out_img: Path, keep_vals):
    """
    Use RIOS to apply the mask. Keep dtype & band count, write masked (0 outside keep).
    """
    infiles = applier.FilenameAssociations()
    outfiles = applier.FilenameAssociations()
    controls = rio_controls()

    infiles.img = str(in_img)
    infiles.fmsk = str(in_fm)
    outfiles.out = str(out_img)

    def do_mask(info, inputs, outputs):
        arr = inputs.img  # (bands, rows, cols)
        fm = inputs.fmsk[0]
        # valid where FMASK in keep set
        keep = np.isin(fm, np.array(keep_vals, dtype=fm.dtype))
        out = arr.copy()
        out[:, ~keep] = 0
        outputs.out = out

    applier.apply(do_mask, infiles, outfiles, controls=controls)


def resolve_preset_and_suffix(preset: str, mask_keep: list | None):
    """
    Return (keep_vals, suffix). For 'custom', suffix becomes _m<codes>.
    For 'no', returns (None, '').
    """
    if preset == "custom":
        if not mask_keep:
            raise SystemExit(
                "[ERR] --preset custom requires --mask-keep codes (e.g. 1 3 5)."
            )
        keep_vals = sorted(set(int(x) for x in mask_keep))
        suffix = f"_m{''.join(str(x) for x in keep_vals)}"
        return keep_vals, suffix
    info = PRESETS[preset]
    return info["keep"], info["suffix"]


def main():
    args = parse_args()
    root = Path(args.dir)
    if not root.is_dir():
        raise SystemExit(f"[ERR] Not a directory: {root}")

    want_fc = args.mode in ("fc", "both")
    want_sr = args.mode in ("sr", "both")

    keep_vals, suffix = resolve_preset_and_suffix(args.preset, args.mask_keep)
    writing = args.do_write and not args.dry_run

    print(f"[INFO] root={root}")
    print(f"[INFO] mode={args.mode} | leaf_only={not args.include_nonleaf}")
    print(
        f"[INFO] preset={args.preset} keep={keep_vals} suffix='{suffix or '(no suffix)'}'"
    )
    print(f"[INFO] dry_run={args.dry_run and not args.do_write} | do_write={writing}")
    print("")

    fc_pairs, sr_pairs, orphans = collect_pairs(
        root, args.include_nonleaf, want_fc, want_sr, debug=args.debug
    )

    # fc_pairs, sr_pairs, orphans = collect_pairs(root, args.include_nonleaf, want_fc, want_sr)

    if want_fc:
        print(f"[FC] pairs: {len(fc_pairs)}")
        for fc, fm, (pr, ymd) in sorted(fc_pairs, key=lambda x: x[2]):
            out_fc = out_name_with_suffix(Path(fc), suffix)
            print(f"  {pr} {ymd}:")
            print(f"     FC : {fc}")
            print(f"     FM : {fm}")
            if suffix == "":
                print("     → preset 'no' → no-op (no new file written).")
                continue

            target = out_fc
            if target.exists():
                if args.on_exists == "skip":
                    print("     [SKIP] output exists.")
                    continue
                elif args.on_exists == "suffix":
                    target = target.with_name(f"{target.stem}__new{target.suffix}")
                    print(f"     [WARN] output exists → writing as {target.name}")
                else:
                    print("     [WARN] will overwrite.")

            if writing:
                try:
                    apply_mask_rios(fc, fm, target, keep_vals)
                    print(f"     [OK] wrote {target}")
                except Exception as e:
                    print(f"     [ERR] mask failed: {e}")
            else:
                print(f"     [DRY-RUN] would write: {target}")

    if want_sr:
        print(f"\n[SR] pairs: {len(sr_pairs)}")
        for sr, fm, (pr, ymd) in sorted(sr_pairs, key=lambda x: x[2]):
            out_sr = out_name_with_suffix(Path(sr), suffix)
            print(f"  {pr} {ymd}:")
            print(f"     SR : {sr}")
            print(f"     FM : {fm}")
            if suffix == "":
                print("     → preset 'no' → no-op (no new file written).")
                continue

            target = out_sr
            if target.exists():
                if args.on_exists == "skip":
                    print("     [SKIP] output exists.")
                    continue
                elif args.on_exists == "suffix":
                    target = target.with_name(f"{target.stem}__new{target.suffix}")
                    print(f"     [WARN] output exists → writing as {target.name}")
                else:
                    print("     [WARN] will overwrite.")

            if writing:
                try:
                    apply_mask_rios(sr, fm, target, keep_vals)
                    print(f"     [OK] wrote {target}")
                except Exception as e:
                    print(f"     [ERR] mask failed: {e}")
            else:
                print(f"     [DRY-RUN] would write: {target}")

    # Orphan summaries
    if orphans["fc"]:
        print(f"\n[WARN] FC with NO FMASK: {len(orphans['fc'])}")
        for (pr, ymd), p in sorted(orphans["fc"].items()):
            print(f"  {pr} {ymd}: {p}")
    if orphans["sr"]:
        print(f"\n[WARN] SR with NO FMASK: {len(orphans['sr'])}")
        for (pr, ymd), p in sorted(orphans["sr"].items()):
            print(f"  {pr} {ymd}: {p}")
    if orphans["fm"]:
        print(f"\n[WARN] FMASK with NO SR/FC: {len(orphans['fm'])}")
        for (pr, ymd), p in sorted(orphans["fm"].items()):
            print(f"  {pr} {ymd}: {p}")


if __name__ == "__main__":
    main()
