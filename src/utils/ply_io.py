import numpy as np
import struct


def save_binary_ply(filepath: str, points: np.ndarray, colors: np.ndarray = None):
    """保存二进制 PLY 文件（比 ASCII 快 10~50 倍）。

    Args:
        filepath: 输出路径
        points: Nx3 float64/float32
        colors: Nx3 uint8 (BGR)，可选
    """
    n = len(points)
    has_color = colors is not None and len(colors) == n

    header_lines = [
        "ply",
        "format binary_little_endian 1.0",
        "comment Created by CodedCircleRegistration_v2",
        f"element vertex {n}",
        "property float x",
        "property float y",
        "property float z",
    ]
    if has_color:
        header_lines.extend([
            "property uchar red",
            "property uchar green",
            "property uchar blue",
        ])
    header_lines.append("end_header")
    header = "\n".join(header_lines) + "\n"

    points = np.asarray(points, dtype=np.float32)
    if has_color:
        colors = np.asarray(colors, dtype=np.uint8)
        # BGR -> RGB
        colors = colors[:, [2, 1, 0]]
        data = np.hstack([points, colors]).view(np.uint8)
        # float32 * 3 = 12 bytes, uchar * 3 = 3 bytes => 15 bytes / vertex
        dtype = np.dtype([
            ('x', np.float32, 3),
            ('c', np.uint8, 3)
        ])
        structured = np.zeros(n, dtype=dtype)
        structured['x'] = points
        structured['c'] = colors
    else:
        structured = points.astype(np.float32)

    with open(filepath, 'wb') as f:
        f.write(header.encode('ascii'))
        f.write(structured.tobytes())
