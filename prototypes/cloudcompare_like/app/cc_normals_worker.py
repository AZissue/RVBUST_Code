# -*- coding: utf-8 -*-
"""
法线估计工作线程（NormalsEstimationWorker）。

设计口径（方案 A，GIL 修正版）：
  - open3d 的 estimate_normals 全程持有 GIL（实测探针 tools/normals_gil_probe.py：
    QThread 内 1.3 s 运算期间主线程 50 ms 定时器仅触发 2 次），单纯 QThread 救不了
    事件循环。因此重活放到独立子进程（app/normals_subprocess.py）执行，本线程只做
    清洗（numpy，释放 GIL）+ 子进程管理（Popen.communicate 在 C 层等待，释放 GIL），
    UI 全程存活，且整云一次估计、与子进程外同步路径结果逐点一致（无分块边界效应）。
  - 节点写回与撤销历史由主线程在 CloudCompareWorkflow.commit_estimate_normals
    完成；本线程持有的是主线程深拷贝的 before 副本，不接触 workflow 状态。
  - 运算期间 UI 禁用入口按钮并显示「处理中」，重复点击被忽略。
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
import tempfile
import time
from typing import Any, Optional

import numpy as np
from PySide6.QtCore import QThread, Signal

from ..core.cc_workflow import sanitize_cloud

_SUBPROCESS_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "normals_subprocess.py")


class NormalsEstimationWorker(QThread):
    """后台法线估计（子进程承载 open3d）；finished_normals(ok, msg, info, result_pcd)。"""

    finished_normals = Signal(bool, str, dict, object)

    def __init__(self, node_id: str, before_pcd: Any,
                 radius: Optional[float] = None, max_nn: int = 30,
                 parent=None):
        super().__init__(parent)
        self.node_id = node_id
        self.before_pcd = before_pcd
        self._radius = radius
        self._max_nn = max_nn
        self._proc: Optional[subprocess.Popen] = None

    # 子进程挂死（如 open3d 内部死循环）时的兜底：默认 10 分钟
    SUBPROCESS_TIMEOUT_S = 600

    def abort(self):
        """终止估算子进程（应用退出/用户取消路径）；run() 会随之报错收尾。"""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.kill()

    def run(self):
        try:
            info, result = self._estimate_in_subprocess()
        except Exception as e:
            self.finished_normals.emit(False, f"法线估计失败: {e}", {}, None)
            return
        msg = (f"法线估计完成: {info['points_out']} 点"
               + (f"（剔除非有限点 {info['dropped']} 行）" if info["dropped"] else "")
               + f"，耗时 {info['elapsed']:.2f} s"
               + f"，半径={info['radius']:.4g}，max_nn={info['max_nn']}")
        self.finished_normals.emit(True, msg, info, result)

    def _estimate_in_subprocess(self):
        import json

        import open3d as o3d
        t0 = time.perf_counter()
        n_in = len(self.before_pcd.points)
        # 清洗（numpy 释放 GIL，50 万点 ~10 ms）；残余非有限点在此兜底剔除
        clean, dropped = sanitize_cloud(self.before_pcd)
        if len(clean.points) == 0:
            raise ValueError("点云全部为非有限点（NaN/Inf），无法估计法线")

        # 子进程继承 PYTHONPATH 可能指向坏 numpy 环境（Hermes 桌面端即如此），剥掉
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as d:
            np.save(os.path.join(d, "pts.npy"),
                    np.asarray(clean.points, dtype=np.float64))
            self._proc = subprocess.Popen(
                [sys.executable, _SUBPROCESS_SCRIPT, d,
                 f"{self._radius if self._radius else 0.0}", str(self._max_nn)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=env)
            proc = self._proc
            try:
                _, err = proc.communicate(timeout=self.SUBPROCESS_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                raise RuntimeError(
                    f"估计子进程超时（>{self.SUBPROCESS_TIMEOUT_S} s），已终止")
            finally:
                self._proc = None
            if proc.returncode != 0:
                raise RuntimeError(f"估计子进程退出码 {proc.returncode}: "
                                   f"{(err or '').strip()[-400:]}")
            normals = np.load(os.path.join(d, "normals.npy"))
            with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
                meta = json.load(f)

        if normals.shape[0] != len(clean.points):
            raise RuntimeError(f"子进程返回法线行数 {normals.shape[0]} 与点数 "
                               f"{len(clean.points)} 不一致")
        # clean 可能是 before_pcd 原对象（无剔除时），必须副本再写属性，保撤销底账
        result = copy.deepcopy(clean)
        result.normals = o3d.utility.Vector3dVector(normals)
        info = {
            "points_in": n_in,
            "dropped": dropped,
            "points_out": len(result.points),
            "radius": float(meta["radius"]),
            "max_nn": int(self._max_nn),
            "elapsed": time.perf_counter() - t0,
            "elapsed_compute": float(meta["elapsed_compute"]),
        }
        return info, result
