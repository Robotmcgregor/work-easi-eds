#!/usr/bin/env python3
"""
Check the actual geospatial bounds of FC files to verify they match expected tile locations
"""

from osgeo import gdal
import os


def check_file_bounds(filepath):
    """Check geospatial bounds of a raster file"""
    if not os.path.exists(filepath):
        return f"File not found: {os.path.basename(filepath)}"

    ds = gdal.Open(filepath)
    if not ds:
        return f"Could not open: {os.path.basename(filepath)}"

    gt = ds.GetGeoTransform()
    xsize, ysize = ds.RasterXSize, ds.RasterYSize

    # Calculate bounds
    xmin = gt[0]
    xmax = gt[0] + gt[1] * xsize
    ymax = gt[3]
    ymin = gt[3] + gt[5] * ysize

    filename = os.path.basename(filepath)
    result = f"{filename}:\n"
    result += f"  Bounds: {xmin:.2f}, {ymin:.2f}, {xmax:.2f}, {ymax:.2f}\n"
    result += f"  Size: {xsize}x{ysize}\n"
    result += f"  Center: {(xmin+xmax)/2:.2f}, {(ymin+ymax)/2:.2f}\n"

    # Estimate which Landsat path/row this might be based on center coordinates
    center_x = (xmin + xmax) / 2
    center_y = (ymin + ymax) / 2

    # Very rough estimation for Australian tiles
    # Path 089, Row 078 should be around:
    # Center approximately: longitude ~151-152, latitude ~-27 to -28
    result += f"  Estimated center coords: Lon {center_x:.3f}, Lat {center_y:.3f}\n"

    return result


def main():
    print("Checking FC file bounds to verify tile identity...")
    print("=" * 60)

    # Check a sample of FC files
    files_to_check = [
        r"D:\data\lsat\089_078\2013\201307\ga_ls_fc_089078_20130716_fc3ms.tif",
        r"D:\data\lsat\089_078\2013\201307\ga_ls_fc_089078_20130724_fc3ms.tif",
        r"D:\data\lsat\089_078\2013\201308\ga_ls_fc_089078_20130801_fc3ms.tif",
        r"D:\data\lsat\089_078\2020\202007\ga_ls_fc_089078_20200703_fc3ms.tif",
        r"D:\data\lsat\089_078\2024\202408\ga_ls_fc_089078_20240831_fc3ms.tif",
    ]

    for filepath in files_to_check:
        print(check_file_bounds(filepath))
        print()

    # Also check what should be the expected bounds for tile 089078
    print("Expected bounds for Landsat Path 089, Row 078 (approximate):")
    print("  Should be in Queensland/NSW border region")
    print("  Longitude: approximately 151-152°E")
    print("  Latitude: approximately -27 to -28°S")
    print("  In projected coordinates (likely Albers): different values")


if __name__ == "__main__":
    main()
