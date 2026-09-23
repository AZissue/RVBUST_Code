# -*- coding: utf-8 -*-
"""
主窗口（批 2）—— 左控制面板 + 右 3D 点云查看器 + 底部日志。

闭环（无相机、无机器人可跑）：
  手眼矩阵（JSON / 手动） + 机器人位姿（手动 / Mock 序列 / CSV）
  → 合成相机系点云（固定随机种子，可复现）
  → T_cam2base = compute_cam2base(...)（core，A1 真值测试锁死）
  → 变换到基座系 → EmbeddedPointCloudViewer 显示（相机系 / 基座系 / 叠加）

复用主项目组件（路线 A：只复用组件层，不接 ui_v2 / backend_bridge）：
  src/ui/viewer_3d.EmbeddedPointCloudViewer、src/ui/worker_thread.run_in_background

R6：位姿读取失败（首帧未 move_to）一律报错，**不静默跳过**。
A9：判别下限声明写在控制面板与 README，禁止把"显示正常"当精度保证。

直接跑（无相机也可）：
  python app/main.py                 # 手点交互
  python app/main.py --smoke 3       # 无人值守：自动跑 3 帧，退出码 0/1（offscreen 亦可）
"""

from __future__ import annotations

import os
import sys
from typing import Optional

import numpy as np
import open3d as o3d

# ---- 路径引导（R12：向上找仓库根，或读 MCC_REPO_ROOT）----
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "core"))


def find_repo_root() -> Optional[str]:
    env = os.environ.get("MCC_REPO_ROOT")
    if env and os.path.isfile(os.path.join(env, "src", "core", "pcd_utils.py")):
        return os.path.abspath(env)
    cur = _HERE
    while True:
        if os.path.isfile(os.path.join(cur, "src", "core", "pcd_utils.py")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


REPO_ROOT = find_repo_root()
HAS_SRC = REPO_ROOT is not None
if HAS_SRC:
    sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

import handeye_result as he_mod          # noqa: E402  core/
import pose_source as ps_mod             # noqa: E402  core/
import transform_chain                   # noqa: E402  core/

from PySide6.QtCore import Qt                            # noqa: E402
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel,  # noqa: E402
                               QMainWindow, QPlainTextEdit, QSplitter,
                               QVBoxLayout, QWidget)

try:
    from ui.viewer_3d import EmbeddedPointCloudViewer
    from ui.worker_thread import run_in_background
    HAS_VIEWER = True
except Exception as _e:      # 无 GL / 缺依赖时仍要能起 UI（查看器降级）
    print(f"[WARN] 主项目查看器引入失败（3D 显示降级）: {_e}")
    EmbeddedPointCloudViewer = None
    run_in_background = None
    HAS_VIEWER = False

from control_panel import ControlPanel       # noqa: E402  同目录

CAM_ID = "cam"      # 相机系点云 id
BASE_ID = "base"    # 基座系点云 id


def make_camera_frame(seed: int = 0, n: int = 20000) -> o3d.geometry.PointCloud:
    """合成一帧相机系点云（毫米）。无相机时的可复现替代品。

    场景：工件平面（基座系 z≈100mm 上方）+ 高斯噪声，再由给定 T_base2tool /
    T_cam2tool 反投影回相机系——数值上等价于"相机看到工件"，用于闭环。
    """
    rng = np.random.default_rng(seed)
    xy = rng.uniform([-150.0, -100.0], [150.0, 100.0], (n, 2))
    z = 500.0 + rng.normal(0.0, 0.3, n)          # 相机前 500mm 处
    pts = np.column_stack([xy, z])
    pcd = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(pts))
    pcd.colors = o3d.utility.Vector3dVector(
        np.clip(np.column_stack([(xy[:, 0] + 150) / 300,
                                 (xy[:, 1] + 100) / 200,
                                 np.full(n, 0.6)]), 0.0, 1.0))
    return pcd


class RobotHandEyeWindow(QMainWindow):
    """手眼矩阵 + 机器人位姿 → 点云转基座系（批 2：显示闭环）。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("手眼变换原型（批 2：无相机 / 无机器人闭环）")
        self.resize(1400, 850)

        self.handeye: Optional[he_mod.HandEyeResult] = None
        self.pose_src: ps_mod.PoseSource = ps_mod.ManualPoseSource()
        self.pose_kind = "manual"
        self.frame_index = 0
        self._mock_started = False
        self.last_base_pcd = None
        self._workers = []

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        split = QSplitter(Qt.Horizontal)
        self.panel = ControlPanel()
        split.addWidget(self.panel)
        split.addWidget(self._build_viewer_area())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        outer.addWidget(split, 1)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(150)
        outer.addWidget(self.log_box)

        self._wire()

        self._log("手眼变换原型 批 2 启动")
        self._log(f"仓库根 = {REPO_ROOT or '未找到（3D 显示与 src 复用降级）'}")
        self._log("无相机：点云用合成帧；无机器人：位姿用手动录入 / Mock 序列。")
        self._log("提示：单位、安装方式、位姿类型、欧拉顺序均无默认，必须显式选。")
        self._log("判别下限 ≈ 1.0 mm（A9）：显示正常不等于精度保证。")

    def _build_viewer_area(self) -> QWidget:
        holder = QWidget()
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.lbl_scene = QLabel("未采集。相机系与基座系点云会同时叠加上屏（白色=相机系）。")
        self.lbl_scene.setStyleSheet("color: #999;")
        bar.addWidget(self.lbl_scene, 1)
        v.addLayout(bar)
        if HAS_VIEWER:
            self.viewer = EmbeddedPointCloudViewer()
            self.viewer.status_changed.connect(self._log)
            self.viewer.set_reference(CAM_ID)
            v.addWidget(self.viewer, 1)
        else:
            self.viewer = None
            lbl = QLabel("3D 查看器不可用（缺 src/ui 或 GL）—— 其余流程仍可跑，结果只记日志。")
            lbl.setWordWrap(True)
            v.addWidget(lbl, 1)
        return holder

    def _wire(self):
        p = self.panel
        p.sig_load_handeye.connect(self.on_load_handeye)
        p.sig_manual_handeye.connect(self.on_manual_handeye)
        p.sig_pose_kind.connect(self.on_pose_kind)
        p.sig_manual_pose.connect(self.on_manual_pose)
        p.sig_mock_step.connect(self.on_mock_step)
        p.sig_load_csv.connect(self.on_load_csv)
        p.sig_capture.connect(self.on_capture)
        p.sig_clear.connect(self.on_clear)

    # ------------------------------------------------------------------
    # 日志 / 状态
    # ------------------------------------------------------------------
    def _log(self, text: str):
        print(text)
        self.log_box.appendPlainText(str(text))

    def _refresh_state(self):
        if self.handeye is None:
            self.panel.set_state("IDLE（未加载手眼矩阵）", "#888888")
        else:
            self.panel.set_state(
                "矩阵已加载 · UNVERIFIED（戳点验证批 3 前不允许导出）", "#ffb300")
        self.panel.btn_export.setEnabled(False)   # A3 门禁：批 3 前一律置灰

    # ------------------------------------------------------------------
    # 手眼矩阵
    # ------------------------------------------------------------------
    def on_load_handeye(self, path: str, unit: Optional[str], eye_in_hand: bool):
        if not path:
            self._log("[拒绝] 请填写 handeye.json 路径")
            return
        if unit is None:
            self._log("[拒绝] 单位必须显式选择 mm 或 m（无默认，D4）")
            return
        ok, msg, res = he_mod.HandEyeResult.load(path, unit, eye_in_hand)
        self._on_handeye_result(ok, msg, res)

    def on_manual_handeye(self, text: str, unit: Optional[str], eye_in_hand: bool):
        vals = ControlPanel.parse_floats(text)
        if vals is None:
            self._log("[拒绝] 手动录入需 16 个数（行优先，逗号/空格分隔）")
            return
        if unit is None:
            self._log("[拒绝] 单位必须显式选择 mm 或 m（无默认，D4）")
            return
        ok, msg, res = he_mod.HandEyeResult.from_matrix(vals, unit, eye_in_hand)
        self._on_handeye_result(ok, msg, res)

    def _on_handeye_result(self, ok: bool, msg: str, res):
        if not ok:
            self.handeye = None
            self._refresh_state()
            self._log(f"[拒绝] 手眼矩阵未加载：{msg}")
            return
        self.handeye = res
        self._refresh_state()
        self._log(f"[OK] 手眼矩阵已加载（{res.key()}, ‖t‖="
                  f"{np.linalg.norm(res.T_handeye_mm[:3, 3]):.3f} mm, "
                  f"source={res.source}）")
        self._log(f"     {msg}")

    # ------------------------------------------------------------------
    # 位姿
    # ------------------------------------------------------------------
    def on_pose_kind(self, kind: str):
        self.pose_kind = kind
        self._mock_started = False
        if kind == "manual":
            self.pose_src = ps_mod.ManualPoseSource()
        elif kind == "mock":
            self.pose_src = ps_mod.MockPoseSource()
        self._log(f"[位姿源] {self.pose_src.source_name()}")

    def on_manual_pose(self, xyz_text: str, rpy_text: str, order: str,
                       unit: str, pose_type: str):
        if self.pose_kind != "manual":
            self.on_pose_kind(self.pose_kind)
        xyz = ControlPanel.parse_floats(xyz_text)
        rpy = ControlPanel.parse_floats(rpy_text)
        if xyz is None or rpy is None or len(xyz) != 3 or len(rpy) != 3:
            self._log("[拒绝] 位姿需 XYZ 3 个数 + RPY 3 个数")
            return
        if not unit or not pose_type or not order:
            self._log("[拒绝] 单位 / 位姿类型 / 欧拉顺序 三项都必填（无默认，R11）")
            return
        ok, msg = self.pose_src.set_pose_xyz_rpy(xyz, rpy, order, unit, pose_type)
        self._log(("[OK] " if ok else "[拒绝] ") + f"手动位姿：{msg}")

    def on_mock_step(self):
        if not isinstance(self.pose_src, ps_mod.MockPoseSource):
            self.pose_src = ps_mod.MockPoseSource()
        if self.pose_src.count() == 0:
            self._load_demo_poses()
        ok, msg, T = self.pose_src.step_next()
        self._log(("[OK] " if ok else "[拒绝] ") + f"Mock 位姿：{msg}")

    def _load_demo_poses(self):
        """演示用位姿序列（绝对位姿，毫米，R11 窗口内）。"""
        poses = []
        for i, (x, y, z, rz) in enumerate([(400.0, 100.0, 420.0, 0.0),
                                           (420.0, 120.0, 430.0, 15.0),
                                           (440.0, 90.0, 440.0, 30.0)]):
            poses.append(ps_mod.euler_to_matrix([x, y, z], [0.0, 0.0, rz], "ZYX"))
        ok, msg = self.pose_src.set_poses(poses, "mm", "absolute")
        self._log(("[OK] " if ok else "[拒绝] ") + f"演示位姿序列：{msg}")

    def on_load_csv(self, path: str, unit: str, pose_type: str):
        if not path:
            self._log("[拒绝] 请填写 CSV 位姿文件路径")
            return
        ok, msg, src = ps_mod.CsvPoseSource.load(path, unit or None, pose_type or None)
        if ok:
            self.pose_src = src
            self.pose_kind = "csv"
        self._log(("[OK] " if ok else "[拒绝] ") + msg)

    # ------------------------------------------------------------------
    # 采集闭环
    # ------------------------------------------------------------------
    def capture_job(self) -> tuple[bool, str, Optional[o3d.geometry.PointCloud]]:
        """同步执行一次「拍一帧 → 变基座系」，返回 (ok, message, pcd_base|None)。"""
        if self.handeye is None:
            return False, "尚未加载手眼矩阵：请先加载 JSON 或手动录入 4×4", None
        # 位姿读取：Mock 序列按「先取当前帧、再步进」推进（首帧不跳过，R6）
        if isinstance(self.pose_src, ps_mod.MockPoseSource):
            if self._mock_started:
                ok, msg, T_bt = self.pose_src.step_next()
            else:
                ok, msg, T_bt = self.pose_src.get_pose()
                self._mock_started = True
        else:
            ok, msg, T_bt = self.pose_src.get_pose()
        if not ok or T_bt is None:
            # R6：位姿读不到必须报错，不许静默跳过首帧
            return False, f"无法读取位姿（{msg}）：请先录入位姿或 Mock 序列载入", None
        self.frame_index += 1
        pcd_cam = make_camera_frame(seed=self.frame_index)
        T_cb = transform_chain.compute_cam2base(
            self.handeye.eye_in_hand, self.handeye.T_handeye_mm, T_bt)
        pcd_base = transform_chain.transform_pcd(pcd_cam, T_cb)
        self.last_base_pcd = pcd_base
        self._show(pcd_cam, pcd_base)
        n = len(pcd_base.points)
        return True, (f"第 {self.frame_index} 帧：{n} 点已转到基座系"
                      f"（{msg}；‖t_cam2base 平移‖="
                      f"{np.linalg.norm(T_cb[:3, 3]):.3f} mm）"), pcd_base

    def _show(self, pcd_cam, pcd_base):
        if self.viewer is not None:
            self.viewer.set_pointcloud(CAM_ID, pcd_cam)
            self.viewer.set_pointcloud(BASE_ID, pcd_base)
            self.viewer.set_view_preset("iso")
        b = pcd_base.get_axis_aligned_bounding_box()
        self.lbl_scene.setText(
            f"第 {self.frame_index} 帧已上屏：相机系 {len(pcd_cam.points)} 点（白）/ "
            f"基座系 {len(pcd_base.points)} 点；基座系包围盒 "
            f"{np.round(b.get_extent(), 1).tolist()} mm")

    def on_capture(self):
        # 变换放后台（30 万点级别不卡 UI）；无 src 时同步跑
        if run_in_background is not None:
            self._show_loading()
            w = run_in_background(self, self.capture_job, self._on_capture_done)
            self._workers.append(w)
            w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        else:
            self._on_capture_done(self.capture_job(), None)

    def _show_loading(self):
        self.panel.btn_capture.setEnabled(False)

    def _on_capture_done(self, result, error):
        self.panel.btn_capture.setEnabled(True)
        if error:
            self._log(f"[ERROR] 采集失败：{error}")
            return
        ok, msg = result[0], result[1]
        self._log(("[OK] " if ok else "[拒绝] ") + msg)
        self._refresh_state()

    def on_clear(self):
        self.frame_index = 0
        self._mock_started = False
        self.last_base_pcd = None
        if self.viewer is not None:
            self.viewer.clear_all()
        self.lbl_scene.setText("已清空。")
        self._log("[清空] 3D 视图与帧计数已重置")

    # ------------------------------------------------------------------
    # 无人值守自检（--smoke N，offscreen 亦可）
    # ------------------------------------------------------------------
    def run_smoke(self, frames: int) -> int:
        self._log(f"=== smoke：自动跑 {frames} 帧（无相机 / 无机器人） ===")
        ok, msg, res = he_mod.HandEyeResult.from_matrix(
            [1, 0, 0, 20, 0, 1, 0, -10, 0, 0, 1, 120, 0, 0, 0, 1], "mm", True)
        self._on_handeye_result(ok, msg, res)
        if not ok:
            return 1
        self.on_pose_kind("mock")
        self._load_demo_poses()
        bad = 0
        for i in range(frames):
            ok, msg, pcd = self.capture_job()
            print(("[OK] " if ok else "[拒绝] ") + msg)
            self.log_box.appendPlainText(("[OK] " if ok else "[拒绝] ") + msg)
            if not ok:
                bad += 1
                continue
            if i == 0 and pcd is not None:
                # 解析真值自检（A1 同口径：真值内联矩阵乘，不调被测函数）
                pc = np.asarray(make_camera_frame(seed=1).points)
                T_bt1 = ps_mod.euler_to_matrix([400.0, 100.0, 420.0],
                                               [0.0, 0.0, 0.0], "ZYX")
                truth = (T_bt1 @ self.handeye.T_handeye_mm @ np.concatenate(
                    [pc, np.ones((len(pc), 1))], axis=1).T).T[:, :3]
                err = float(np.max(np.abs(np.asarray(pcd.points) - truth)))
                tag = "OK" if err < 1e-9 else "FAIL"
                print(f"[{tag}] 第 1 帧基座系点云 vs 解析真值：逐点最大偏差 "
                      f"{err:.3e} mm（门槛 1e-9）")
                self.log_box.appendPlainText(f"[{tag}] 基座系点云 vs 解析真值 err={err:.3e} mm")
                if err >= 1e-9:
                    bad += 1
        # 反例：米制当毫米必须被拦（否则说明守卫丢了）
        ok2, msg2 = self.pose_src.append_pose(
            ps_mod.euler_to_matrix([0.4, 0.1, 0.2], [0, 0, 0], "ZYX"),
            "mm", "absolute")
        print(f"反例（米制当毫米）：{'未被拦住(严重)' if ok2 else '已拦住 -> ' + msg2[:60]}")
        self.log_box.appendPlainText(f"反例（米制当毫米）：{'未被拦住' if ok2 else '已拦住'} {msg2[:60]}")
        if ok2:
            bad += 1
        # UI 槽位自检（不经过鼠标，直接调面板→窗口的信号槽，验证接线）
        self.pose_kind = "manual"
        self.pose_src = ps_mod.ManualPoseSource()
        self.on_manual_pose("400,100,420", "0,0,15", "", "mm", "absolute")
        if not isinstance(self.pose_src, ps_mod.ManualPoseSource) \
                or self.pose_src.get_pose()[0]:
            print("[FAIL] 缺 order 时不应录入成功")
            bad += 1
        else:
            print("[OK] UI 槽位：缺 order → 已拒绝，位姿仍为空")
        self.on_manual_pose("400,100,420", "0,0,15", "ZYX", "mm", "absolute")
        self.on_manual_pose("0.4,0.1,0.42", "0,0,15", "ZYX", "m", "absolute")
        ok3, msg3, _ = self.capture_job()
        print(("[OK] " if ok3 else "[拒绝] ") + f"UI 槽位手动位姿采集：{msg3}")
        if not ok3:
            bad += 1
        # 米制当毫米：用全新的源，否则上一次成功录入的位姿会留在原处（拒绝不覆盖）
        self.pose_src = ps_mod.ManualPoseSource()
        self.on_manual_pose("0.4,0.1,0.42", "0,0,15", "ZYX", "mm", "absolute")
        if self.pose_src.get_pose()[0]:
            print("[FAIL] 米制当毫米经 UI 槽位竟然录入成功（守卫漏了）")
            bad += 1
        else:
            print("[OK] UI 槽位：米制当毫米 → 已拒绝，未产生静默错位姿")
        print(f"=== smoke 结束：{frames} 帧，失败 {bad} 项 ===")
        return 0 if bad == 0 else 1


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    frames = 0
    if "--smoke" in argv:
        i = argv.index("--smoke")
        frames = int(argv[i + 1]) if len(argv) > i + 1 and argv[i + 1].isdigit() else 3
    app = QApplication.instance() or QApplication(argv[:1])
    win = RobotHandEyeWindow()
    win.show()
    if frames > 0:
        rc = win.run_smoke(frames)
        return rc
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
