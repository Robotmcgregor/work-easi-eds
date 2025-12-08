import os
import glob
from fc_lsat_dea_data import main as fc_main
from sr_lsat_dea_data import main as sr_main
from fmask import mask_composite


def process_scene(path, row, output_dir, cloud_threshold=10):
    # Step 1: Download SR + Fmask
    sr_main(path, row, output_dir, cloud_threshold)

    # Step 2: Download FC
    fc_main(path, row, output_dir, cloud_threshold)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Pipeline: SR + FC + Fmask Masking by Date"
    )
    parser.add_argument(
        "--path", type=str, required=True, help="Landsat path (e.g. 091)"
    )
    parser.add_argument("--row", type=str, required=True, help="Landsat row (e.g. 078)")
    parser.add_argument(
        "--output_dir",
        type=str,
        default=r"D:\projects\working\lsat",
        help="Output directory",
    )
    parser.add_argument(
        "--cloud_threshold", type=float, default=10, help="Max cloud cover allowed"
    )

    args = parser.parse_args()

    process_scene(args.path, args.row, args.output_dir, args.cloud_threshold)
