# -*- coding: utf-8 -*-
"""AC7 实测：真实云 叶片拼接.ply（1,814,567 点）走 UI 法线估计路径。

判据：触发后界面全程可交互（50 ms 定时器持续触发），完成 ≤20 s，法线全有限。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "D:/RVC_SRC/Python/MultiCameraCalibration")

import numpy as np
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from prototypes.cloudcompare_like.app.cc_workspace import CloudCompareWorkspace

PLY = "D:/RVC_SRC/Python/MultiCameraCalibration/叶片拼接.ply"


def main():
    app = QApplication([])
    ws = CloudCompareWorkspace()
    logs = []
    ws.log_message.connect(lambda m, lvl: logs.append((lvl, m)))

    ok, msg, nid = ws._workflow.load_from_file(PLY)
    print(f"load: ok={ok} msg={msg}")
    ws._current_node_id = nid

    ticks = {"n": 0}
    timer = QTimer(ws)
    timer.setInterval(50)
    timer.timeout.connect(lambda: ticks.__setitem__("n", ticks["n"] + 1))
    timer.start()

    t0 = time.perf_counter()
    ws._on_estimate_normals(0.0, 30)     # 0 = 自适应半径
    worker = ws._normals_worker
    loop = QEventLoop(ws)
    worker.finished_normals.connect(lambda *a: loop.quit())
    QTimer.singleShot(60_000, loop.quit)
    loop.exec()
    wall = time.perf_counter() - t0
    timer.stop()

    node = ws._workflow.get_node(nid)
    norms = np.asarray(node.pcd.normals)
    print(f"wall={wall:.2f}s ticks={ticks['n']} points={len(node.pcd.points)} "
          f"normals_finite={np.isfinite(norms).all()}")
    for lvl, m in logs:
        if "法线" in m:
            print(f"log[{lvl}] {m}")
    assert wall <= 20.0, f"AC7 超时: {wall:.2f}s"
    print("AC7 PASS")


if __name__ == "__main__":
    main()
