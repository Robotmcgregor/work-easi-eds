!/usr/bin/env python3

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

from __future__ import annotations

from typing import List
from lib.s3_io import list_s3_keys


def inventory_existing_outputs(bucket: str, prefix: str, tile: str) -> List[str]:
    """
    Just lists NDVI outputs that already exist in S3 so we dont redo work.
    """
    # build the base path where ndvi files should be
    base = f"{prefix}/tiles/{tile}/ndvi/"

    # list all keys under that prefix
    keys = list_s3_keys(bucket=bucket, prefix=base)

    # only keep files that look like ndvi tifs
    # this is a bit loose but good enough for now
    return [k for k in keys if "_ndvi_" in k and k.endswith(".tif")]