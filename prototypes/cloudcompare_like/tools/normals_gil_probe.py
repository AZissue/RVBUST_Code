# -*- coding: utf-8 -*-
"""探针：open3d estimate_normals 在 QThread 中是否释放 GIL（主线程 QTimer 存活判据）。"""
import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
import numpy as np
import open3d as o3d
from PySide6.QtCore import QTimer, QThread
from PySide6.QtWidgets import QApplication

N = 500_000
rng = np.random.default_rng(7)
pts = rng.normal(size=(N, 3)) * 100.0
pts[rng.choice(N, size=N // 100, replace=False)] = np.inf
pcd = o3d.geometry.PointCloud()
pcd.points = o3d.utility.Vector3dVector(pts)


class W(QThread):
    def __init__(self, payload):
        super().__init__()
        self._payload = payload
        self.elapsed = None

    def run(self):
        t0 = time.perf_counter()
        self._payload()
        self.elapsed = time.perf_counter() - t0


def main():
    app = QApplication([])
    ticks = {"n": 0, "t0": time.perf_counter()}
    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(lambda: ticks.__setitem__("n", ticks["n"] + 1))
    timer.start()

    def payload_open3d():
        mask = np.isfinite(np.asarray(pcd.points)).all(axis=1)
        clean = pcd.select_by_index(np.where(mask)[0])
        clean.estimate_normals(
            o3d.geometry.KDTreeSearchParamHybrid(radius=0.3, max_nn=30))

    def payload_numpy():
        # 对照：纯 numpy 重负载（numpy 释放 GIL）
        a = np.random.rand(3000, 3000)
        for _ in range(30):
            a = a @ a
            a /= a.max()

    for name, payload in [("open3d", payload_open3d), ("numpy-mm", payload_numpy)]:
        ticks["n"] = 0
        w = W(payload)
        t0 = time.perf_counter()
        w.start()
        while w.isRunning():
            app.processEvents()
            time.sleep(0.001)
        wall = time.perf_counter() - t0
        print(f"{name}: worker={w.elapsed:.2f}s wall={wall:.2f}s "
              f"ticks={ticks['n']} (期望 ~{int(wall/0.05)})")


if __name__ == "__main__":
    main()
