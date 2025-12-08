# python
import argparse
import os
import re
import subprocess
import sys


def find_inputs(path, recursive):
    if os.path.isfile(path):
        return [path] if re.search(r"_fcm3s\.tif$", path, re.IGNORECASE) else []
    matches = []
    if recursive:
        for root, _, files in os.walk(path):
            for fn in files:
                if fn.lower().endswith("_fcm3s.tif"):
                    matches.append(os.path.join(root, fn))
    else:
        for fn in os.listdir(path):
            if fn.lower().endswith("_fcm3s.tif"):
                matches.append(os.path.join(path, fn))
    return matches


def make_output_path(input_path):
    return re.sub(r"_fcm3s\.tif$", "_fpc3s.tif", input_path, flags=re.IGNORECASE)


def run_one(python_exe, script, inp, out, dry_run=False):
    cmd = [python_exe, script, "-f", inp, "-o", out]
    print("Running:", " ".join(['"{}"'.format(x) for x in cmd]))
    if dry_run:
        return 0
    proc = subprocess.run(cmd)
    return proc.returncode


# python
def main():
    p = argparse.ArgumentParser(
        description="Batch run `fpc_from_pv_fc.py` on all `*_fcm3s.tif` files"
    )
    p.add_argument(
        "--path", required=True, help="file or directory to scan for `*_fcm3s.tif`"
    )
    p.add_argument(
        "--script",
        default=os.path.join("fc_to_fpc", "fpc_from_pv_fc.py"),
        help="path to `fpc_from_pv_fc.py` (default `fc_to_fpc/fpc_from_pv_fc.py`)",
    )
    p.add_argument(
        "--no-recursive",
        dest="recursive",
        action="store_false",
        help="do not recurse into subdirectories",
    )
    p.add_argument(
        "--overwrite", action="store_true", help="overwrite existing outputs"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="only print commands, do not run"
    )
    args = p.parse_args()

    if not os.path.exists(args.path):
        print(f"Path does not exist: `{args.path}`")
        return

    if os.path.isfile(args.path):
        if not re.search(r"_fcm3s\.tif$", args.path, re.IGNORECASE):
            print(f"File does not match pattern `*_fcm3s.tif`: `{args.path}`")
            return
    print(args.path)
    inputs = find_inputs(args.path, args.recursive)
    print(
        f"Scanning `{args.path}` (recursive={args.recursive}) -> found {len(inputs)} file(s)"
    )
    if not inputs:
        print("No `*_fcm3s.tif` files found.")
        return

    python_exe = sys.executable
    script = args.script

    for inp in inputs:
        out = make_output_path(inp)
        if os.path.exists(out) and not args.overwrite:
            print("Skipping existing output:", out)
            continue
        rc = run_one(python_exe, script, inp, out, dry_run=args.dry_run)
        if rc != 0:
            print("Command failed for:", inp, "return code", rc)


if __name__ == "__main__":
    main()
