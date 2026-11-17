# -*- coding: utf-8 -*-
"""法线估计子进程入口（由 NormalsEstimationWorker 拉起，不面向用户）。

原因（实测，见 tools/normals_gil_probe.py）：open3d 的 estimate_normals 是 pybind
C++ 调用，全程持有 GIL——放进 QThread 主线程事件循环仍被饿死（1.3 s 内 50 ms 定时器
仅触发 2 次）。独立子进程没有 GIL 之争，UI 完全存活，且整云一次性估计、结果与子进程外
的同步路径逐点一致（无分块边界效应）。

协议（argv + 同目录文件）：
    argv[1] = 工作目录（pts.npy 已就位；结果写回同目录）
    argv[2] = 搜索半径（<=0 时按最近邻点距中位数×3 自适应，口径同 core.cc_workflow）
    argv[3] = max_nn
产出：
    normals.npy  (float64, N×3，行序与输入一致)
    meta.json    {"radius": float, "elapsed_compute": float}
"""

import json
import os
import sys
import time

import numpy as np


def main() -> int:
    workdir = sys.argv[1]
    radius = float(sys.argv[2])
    max_nn = int(sys.argv[3])

    # 复用 core 的点距口径：项目根与 src/ 上 path（本文件在 prototypes/cloudcompare_like/app/）
    _root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    for _p in (_root, os.path.join(_root, "src")):
        if _p not in sys.path:
            sys.path.insert(0, _p)

    import open3d as o3d
    from prototypes.cloudcompare_like.core.cc_workflow import _median_point_spacing

    pts = np.load(os.path.join(workdir, "pts.npy"))
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(pts)

    if radius <= 0:
        radius = max(_median_point_spacing(pcd) * 3.0, 1e-9)

    t0 = time.perf_counter()
    pcd.estimate_normals(
        o3d.geometry.KDTreeSearchParamHybrid(radius=radius, max_nn=max_nn))
    elapsed = time.perf_counter() - t0

    normals = np.asarray(pcd.normals, dtype=np.float64)
    np.save(os.path.join(workdir, "normals.npy"), normals)
    with open(os.path.join(workdir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"radius": float(radius), "elapsed_compute": elapsed}, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
