from __future__ import annotations

import re
from typing import Optional


def parse_scene_from_name(name: str) -> Optional[str]:
    m = re.search(r"_(p\d{3}r\d{3})_", name.lower())
    return m.group(1) if m else None
