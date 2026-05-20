from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

import rasterio
from rasterio.enums import ColorInterp


RGBA = Tuple[int, int, int, int]


def dll_colormap() -> Dict[int, RGBA]:
    """Return the standard DLL change-class colormap (uint8 -> RGBA).

    Values are based on the legacy SLATS-style palette.
    """

    # Default all values to transparent.
    cmap: Dict[int, RGBA] = {i: (0, 0, 0, 0) for i in range(256)}

    # Keep 0 transparent (nodata)
    # 10 no clearing: light grey
    cmap[10] = (200, 200, 200, 255)
    # 3 FPC-only: cyan
    cmap[3] = (0, 200, 200, 255)
    # 34..39 gradient
    cmap.update(
        {
            34: (255, 255, 0, 255),  # yellow
            35: (255, 200, 0, 255),  # yellow-orange
            36: (255, 150, 0, 255),  # orange
            37: (255, 100, 0, 255),  # red-orange
            38: (255, 0, 0, 255),  # red
            39: (200, 0, 200, 255),  # purple
        }
    )

    return cmap


def write_arcgis_clr(path: Path) -> None:
    """Write an ArcGIS-style .clr file for importing a raster colormap.

    ArcGIS Pro supports importing a colormap from a .clr file for integer rasters.
    """

    rows = [
        (0, 0, 0, 0, "NoData"),
        (10, 200, 200, 200, "No clearing"),
        (3, 0, 200, 200, "FPC-only"),
        (34, 255, 255, 0, "Clearing 34"),
        (35, 255, 200, 0, "Clearing 35"),
        (36, 255, 150, 0, "Clearing 36"),
        (37, 255, 100, 0, "Clearing 37"),
        (38, 255, 0, 0, "Clearing 38"),
        (39, 200, 0, 200, "Clearing 39"),
    ]

    # Common .clr format is: VALUE R G B [LABEL]
    # Labels may be ignored by some tools, but they don't hurt.
    lines = ["# DLL (change class) colormap", "# VALUE R G B LABEL"]
    for v, r, g, b, label in rows:
        lines.append(f"{v} {r} {g} {b} {label}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def apply_dll_style_to_cog_tif(tif_path: Path) -> None:
    """Embed a palette/colormap into a 1-band uint8 DLL GeoTIFF.

    This makes the raster immediately display as a classified raster in many GIS tools
    (including ArcGIS) without needing a separate layer file.
    """

    tif_path = Path(tif_path)
    cmap = dll_colormap()

    with rasterio.open(tif_path, "r+") as dst:
        if int(dst.count) != 1:
            raise ValueError(f"Expected 1-band DLL raster, found {dst.count}: {tif_path}")

        # Ensure nodata is consistently set.
        try:
            if dst.nodata is None:
                dst.nodata = 0
        except Exception:
            pass

        # Write palette + set band interpretation.
        dst.write_colormap(1, cmap)
        try:
            dst.colorinterp = (ColorInterp.palette,)
        except Exception:
            pass
