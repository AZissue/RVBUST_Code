#!/usr/bin/env python3
"""把 live_shot.png 的 2D 视窗区域按 1:1 裁出来，供 A 读像素坐标。
用法：python reports/T-012/_crop.py [x1,y1,x2,y2]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

OUT = Path(__file__).resolve().parent
SRC = OUT / "live_shot.png"


def main() -> int:
    box = (25, 183, 751, 804)
    if len(sys.argv) > 1:
        box = tuple(int(float(v)) for v in sys.argv[1].split(","))
    img = Image.open(SRC)
    crop = img.crop(box)
    dst = OUT / "crop_2dview.png"
    crop.save(dst)
    print(f"{dst}  box={box}  size={crop.size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
