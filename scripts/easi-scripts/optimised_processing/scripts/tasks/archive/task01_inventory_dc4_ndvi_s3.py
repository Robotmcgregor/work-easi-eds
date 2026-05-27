"""
task01_inventory_dc4_ndvi_s3.py: Inventory Existing NDVI Outputs in S3
-----------------------------------------------------------------------

This module provides a utility function to list all existing NDVI (Normalized Difference Vegetation Index)
output files for a given tile in an S3 bucket. It is used to quickly determine which NDVI products have
already been generated, so the pipeline can skip reprocessing and resume efficiently.

Where and how it is called:
        - This function is typically called by the EDS master pipeline script:
            `eds_master_pipeline_optimised.py` (step 3: ensure required NDVI scenes exist in S3).
        - It may also be used by other orchestration or diagnostic scripts that need to check for existing NDVI outputs.

Place in the EDS pipeline:
        - This script is part of the early pipeline steps, before any new NDVI scenes are generated.
        - It helps the pipeline avoid redundant work by identifying which NDVI files are already present in S3.
        - The output (a set of S3 keys) is used to decide which scenes need to be built or skipped.
"""
from __future__ import annotations

from typing import Dict, Set

from lib.s3_io import list_s3_keys

# ------------------------------------------------------------------------------
# MIT License

# Copyright (c) 2026 Robert McGregor

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# ------------------------------------------------------------------------------


def inventory_existing_ndvi(
    bucket: str,
    prefix: str,
    tile: str,
) -> Set[str]:
    """
    Return a set of S3 keys for NDVI files that already exist.

    This is mainly so we can skip stuff we already did and resume faster.

        Expected layout (month-bucketed):
            {prefix}/tiles/{tile}/ndvi/{platform}/{YYYY}/{YYYYMM}/..._ndvi_*.tif

    We return keys only (not full s3:// URIs) because its easier to compare.
    """
    # normalise tile name
    tile = tile.lower().strip()

    # build the base prefix where ndvi outputs should live
    base = f"{prefix.rstrip('/')}/tiles/{tile}/ndvi/"

    # list everything under that prefix
    keys = list_s3_keys(bucket=bucket, prefix=base)

    # only keep tif files that look like ndvi outputs
    return {
        k for k in keys
        if k.lower().endswith(".tif") and "_ndvi_" in k
    }