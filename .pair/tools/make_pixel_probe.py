#!/usr/bin/env python3
"""为「像素→3D」的界面验收造一份**已知真值**的数据。

产物（默认写到 .pair/reports/ui-probe-001/）：

* ``probe.ply``  —— 64×48 的对齐点云，点 i = (i+0.125, 2i+0.25, 3i+0.375)，
  所以界面上读到 (453.125, 906.250, 1359.375) 就等价于"像素 (5,7) 取到了
  索引 7*64+5 = 453 的那个点"，对错一眼可判。
* ``probe.png``  —— 同尺寸（64×48）的真 PNG，工具页只需要它的宽高。

用法：python .pair/tools/make_pixel_probe.py [输出目录]
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

WIDTH = 64
HEIGHT = 48


def point(index: int) -> tuple[float, float, float]:
    return (index + 0.125, 2 * index + 0.25, 3 * index + 0.375)


def write_ply(path: Path) -> None:
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {WIDTH * HEIGHT}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "end_header\n"
    )
    with path.open("wb") as handle:
        handle.write(header.encode("ascii"))
        for i in range(WIDTH * HEIGHT):
            handle.write(struct.pack("<fff", *point(i)))


def write_png(path: Path) -> None:
    from PIL import Image

    image = Image.new("RGB", (WIDTH, HEIGHT), (32, 32, 32))
    for x in range(WIDTH):
        image.putpixel((x, (x * HEIGHT) // WIDTH), (200, 200, 200))
    image.save(path)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".pair/reports/ui-probe-001")
    out.mkdir(parents=True, exist_ok=True)
    write_ply(out / "probe.ply")
    write_png(out / "probe.png")
    for pixel in ((5, 7), (0, 0), (63, 47)):
        index = pixel[1] * WIDTH + pixel[0]
        expected = point(index)
        print(f"pixel {pixel} -> index {index} -> "
              f"{expected[0]:.3f}, {expected[1]:.3f}, {expected[2]:.3f}")
    print(f"written to {out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
