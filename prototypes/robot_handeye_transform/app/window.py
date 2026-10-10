# -*- coding: utf-8 -*-
"""
主窗口（批 3：A3 验证门禁 + A6 会话接线）—— 左控制面板 + 右 3D 点云查看器 + 底部日志。

闭环（无相机、无机器人可跑）：
  手眼矩阵（JSON / 手动） + 机器人位姿（手动 / Mock 序列 / CSV）
  → 合成相机系点云（固定随机种子，可复现）
  → T_cam2base = compute_cam2base(...)（core，A1 真值测试锁死）
  → 变换到基座系 → ViewerPanel 显示（相机系 / 基座系 / 叠加）
  → A3 戳点门禁（TipTouchValidator，唯一可用性判据）→ VERIFIED 才允许保存会话（A6）

状态机（A3）：IDLE → UNVERIFIED（矩阵已加载）→ VERIFIED（戳点 PASS，导出解锁）
/ FAILED（戳点 FAIL，红字）。重合度快检是 warning 级，不改变状态（R2 轴向盲区）。

批 4.5（合入预适配）：本文件只提供 **QWidget 工作区** `RobotWorkspace`，接口对齐
合入形态（`set_devices` / `set_state` / `set_background_runner` + `log_message` /
`dirty_changed` 信号，照 src/ui_v2/workspaces/turntable_workspace.py:86）。
QMainWindow 壳移到 app/host.py —— 合入后由 MainWindowShell 提供（工具栏/状态栏/
QStackedWidget 已在那边，工作区若自带 QMainWindow 就是第二层嵌套）。

复用主项目组件的形态：
  - 3D 查看器 → src/ui_v2/widgets/viewer_panel.ViewerPanel（ui_v2 公共面板，
    其内部再包装 ui.viewer_3d）→ 本文件对旧 `ui.*` 的直接依赖为零，
    Phase 2 搬 viewer_3d 时它跟着 ui_v2 走，打不到这里
  - 后台任务 → 宿主注入 runner（与 BackendBridge._run_background 同签名），
    不再 import src/ui/worker_thread，本类不自建线程池（1.0.10）

M2a-3（设计语言复刻，docs/原型UI一次性复刻方案与截图验收标准_20260923.md §5）：
  - 色值全部走 `ui_v2.theme` token（本文件**禁硬编码色值**，U2/S5）；
  - 左控制面板外包 `QScrollArea`（U9/S6：GLOBAL_QSS 生效后内容超窗高必裁）；
  - 3D 区标签走 QSS `mutedLabel`，外边距/间距对齐 10 / 8px 基准。

R6：位姿读取失败（首帧未 move_to）一律报错，**不静默跳过**。
A9：判别下限声明写在控制面板与 README，禁止把"显示正常"当精度保证。

直接跑（无相机也可）：
  python app/main.py                 # 手点交互（宿主壳 = app/host.py）
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

import handeye_file as hf_mod            # noqa: E402  core/（批 6A：A10 矩阵落文件）
import handeye_result as he_mod          # noqa: E402  core/
import pose_source as ps_mod             # noqa: E402  core/
import session as session_mod            # noqa: E402  core/（A6 会话落盘/恢复）
import transform_chain                   # noqa: E402  core/
import validation                        # noqa: E402  core/（A3 戳点门禁 + 重合度快检）

from PySide6.QtCore import Qt, Signal                    # noqa: E402
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel,  # noqa: E402
                               QScrollArea, QSplitter, QVBoxLayout,
                               QWidget)

# 批 4.5：查看器改走 ui_v2 公共面板。原型对旧 `ui.*` 的直接依赖清零；
# ui_v2/widgets/viewer_panel.py 自己包装 ui.viewer_3d，Phase 2 搬库时只改它一处。
try:
    from ui_v2.widgets.viewer_panel import ViewerPanel
    HAS_VIEWER = True
except Exception as _e:      # 缺依赖 / 无 GL：**显形失败**，不再静默降级
    print(f"[ERROR] 3D 查看器引入失败（HAS_VIEWER=False）: {_e}")
    print("[ERROR] 合入形态下该降级非法：--smoke 一律判失败（批 4.5 ⑤）")
    ViewerPanel = None
    HAS_VIEWER = False

try:
    from core.pcd_utils import merge_pointclouds     # 保色合并（K 规：禁止裸 +=）
except Exception as _e:      # src/core 缺失 → 合并导出 fail-closed（见 merged_pcd）
    print(f"[WARN] src/core 不可用（merge_pointclouds 缺失，合并导出将拒绝）: {_e}")
    merge_pointclouds = None

# M2a-3：设计语言 token（唯一来源 ui_v2.theme）。缺 src 时**显形失败**：
# 没有 token 就无法对齐主程序设计语言（禁止静默降级，同 3D 查看器口径）。
try:
    from ui_v2.theme import (SPACE, STATUS_ERR, STATUS_OK,  # noqa: E402
                             STATUS_WARN, TEXT_MUTED)
except Exception as _e:      # noqa: BLE001
    print(f"[ERROR] ui_v2.theme 设计 token 引入失败（UI 无法对齐主程序）: {_e}")
    raise

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


class RobotWorkspace(QWidget):
    """手眼矩阵 + 机器人位姿 → 点云转基座系（工作区本体，批 4.5）。

    合入形态接口（照 src/ui_v2/workspaces/turntable_workspace.py）：
        信号 log_message(message, level) / dirty_changed(bool)
        方法 set_devices(devices) / set_state(state) / set_background_runner(runner)
    工具栏 / 状态栏 / 日志面板不在本类里：原型阶段由 app/host.py 提供，
    合入后由 MainWindowShell 提供。
    """

    STATES = ("idle", "matrix_loaded", "verified")

    log_message = Signal(str, str)
    """工作区日志（message, level）——宿主/主窗口统一汇入日志面板。"""

    dirty_changed = Signal(bool)
    """数据脏标记变化（采集到新帧 / 会话已保存 / 已清空）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = "idle"
        self._devices: list = []

        self.handeye: Optional[he_mod.HandEyeResult] = None
        self.validator: Optional[validation.TipTouchValidator] = None
        self.tip_report: Optional[dict] = None       # 最近一次戳点门禁报告（A6 落盘）
        self.pose_src: ps_mod.PoseSource = ps_mod.ManualPoseSource()
        self.pose_kind = "manual"
        self.frame_index = 0
        self._mock_started = False
        self.last_base_pcd = None
        self.last_pose_used = None
        self.captured_frames: list = []   # [(xyz N×3, colors N×3|None), ...]（A6）
        self.captured_poses: list = []    # [T_base2tool, ...]（A6）
        self._background_runner = None   # 宿主注入（见 set_background_runner）

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(SPACE)

        split = QSplitter(Qt.Horizontal)

        # ---- 左侧控制面板（可滚动，U9/S6）----
        # 照 src/ui_v2/workspaces/turntable_workspace.py:146-163 范式：GLOBAL_QSS 生效后
        # 面板内容高度 692→1083px，不做滚动区在 850 高的窗口里必裁 4 组业务区。
        self._left_panel = QScrollArea()
        self._left_panel.setWidgetResizable(True)
        self._left_panel.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._left_panel.setFrameShape(QFrame.NoFrame)
        self._left_panel.setMinimumWidth(330)
        self._left_panel.setMaximumWidth(440)
        self.panel = ControlPanel()
        self._left_panel.setWidget(self.panel)
        split.addWidget(self._left_panel)
        split.addWidget(self._build_viewer_area())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        outer.addWidget(split, 1)

        self._wire()

        self._log("手眼变换原型 批 4.5 工作区启动（合入形态：QWidget + 注入 runner）")
        self._log(f"仓库根 = {REPO_ROOT or '未找到（3D 显示与 src 复用降级）'}")
        if not HAS_VIEWER:
            self._log("[ERROR] 3D 查看器不可用：--smoke 将判失败（禁止静默降级）")
        self._log("无相机：点云用合成帧；无机器人：位姿用手动录入 / Mock 序列。")
        self._log("提示：单位、安装方式、位姿类型、欧拉顺序均无默认，必须显式选。")
        self._log("判别下限 ≈ 1.0 mm（A9）：显示正常不等于精度保证。")
        # 启动即刷一次四态（@verify 2026-09-23 S4 实测命中）：否则面板停在构造默认
        # 「状态：IDLE」+ STATUS_WARN 黄，与状态机 idle（应为 TEXT_MUTED 灰）不一致。
        self._refresh_state()

    def _build_viewer_area(self) -> QWidget:
        holder = QWidget()
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(SPACE)
        bar = QHBoxLayout()
        bar.setContentsMargins(SPACE, 0, SPACE, 0)     # 8px 基准：对齐 3D 区内边距
        self.lbl_scene = QLabel("未采集。相机系与基座系点云会同时叠加上屏（白色=相机系）。")
        self.lbl_scene.setObjectName("mutedLabel")     # 色值/字号由 GLOBAL_QSS 提供
        bar.addWidget(self.lbl_scene, 1)
        v.addLayout(bar)
        if HAS_VIEWER:
            self.viewer = ViewerPanel("3D 手眼变换预览")
            self.viewer.viewer_message.connect(self._log)
            self.viewer.set_reference(CAM_ID)
            v.addWidget(self.viewer, 1)
        else:
            self.viewer = None
            lbl = QLabel("3D 查看器不可用（ui_v2 ViewerPanel 引入失败）—— 其余流程仍可跑，"
                         "但 --smoke 一律判失败（批 4.5：禁止静默降级）。")
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
        p.sig_tip_record.connect(self.on_tip_record)
        p.sig_tip_check.connect(self.on_tip_check)
        p.sig_overlap.connect(self.on_overlap_check)
        p.sig_save_session.connect(self.on_save_session)
        p.sig_save_ply.connect(self.on_save_merged_ply)
        p.sig_export_handeye_file.connect(self.on_export_handeye_file)
        p.sig_import_handeye_file.connect(self.on_import_handeye_file)

    # ------------------------------------------------------------------
    # 日志 / 状态
    # ------------------------------------------------------------------
    def _log(self, text: str, level: str = "info"):
        print(text)
        self.log_message.emit(str(text), level)

    # ------------------------------------------------------------------
    # 合入形态接口（宿主 / 主窗口侧调用；照 ui_v2 转台工作区）
    # ------------------------------------------------------------------
    def set_devices(self, devices):
        """传入设备列表（合入形态接口）。本原型无相机：只记录并打印。"""
        self._devices = list(devices or [])
        self._log(f"[设备] 收到 {len(self._devices)} 台设备（本原型无相机，仅记录）")

    def set_state(self, state: str):
        """设置工作区状态（与面板上的 A3 状态机并行，宿主/主窗口侧用）。"""
        if state not in self.STATES:
            raise ValueError(f"未知状态: {state}")
        self._state = state

    def current_state(self) -> str:
        return self._state

    def set_background_runner(self, runner):
        """注入统一后台 runner（与 BackendBridge._run_background 同签名）。

        签名 `(work, on_done, must_finish=False, name=None)`，
        回调 `on_done(result, error)`（backend_bridge.py:1966）。
        注入后后台任务全部走它；未注入（独立自测）时同步执行——
        本类**不自建线程池**（1.0.10「全工程只留一个后台池」）。
        """
        self._background_runner = runner

    def _refresh_state(self):
        """状态机（A3）：IDLE → UNVERIFIED（矩阵已加载）→ VERIFIED / FAILED。"""
        p = self.panel
        if self.handeye is None:
            p.set_state("IDLE（未加载手眼矩阵）", TEXT_MUTED)
            p.set_tip_enabled(False)
            p.btn_export.setEnabled(False)
            p.set_save_ply_enabled(False)
            p.set_export_file_enabled(False)
            p.set_export_gate(False, False)
            p.set_he_meta("")
            return
        p.set_export_file_enabled(True)     # 批 6A：矩阵落文件不卡 A3 门禁（文件 stamp validated）
        # 批 6A 屏上显形（@lead v2 §10.4-①）：门禁状态 + rms/n_samples（未知显示"未知"）
        p.set_export_gate(True, bool(self.handeye.validated))
        p.set_he_meta(self.handeye_meta_text())
        p.set_tip_enabled(True)
        if self.handeye.validated:
            p.set_state("VERIFIED（戳点门禁通过，允许导出）", STATUS_OK)
            p.btn_export.setEnabled(True)
        elif self.tip_report is not None \
                and self.tip_report.get("verdict") == "FAIL":
            p.set_state("FAILED（戳点门禁未通过，矩阵不可用）", STATUS_ERR)
            p.btn_export.setEnabled(False)
        else:
            p.set_state("矩阵已加载 · UNVERIFIED（须通过戳点门禁才可导出）", STATUS_WARN)
            p.btn_export.setEnabled(False)
        p.set_overlap_enabled(len(self.captured_frames) >= 2)
        # A4：合并 PLY 同属导出，同样吃 A3 门禁（VERIFIED 且 ≥1 帧）
        p.set_save_ply_enabled(self.handeye.validated
                               and len(self.captured_frames) >= 1)

    # ------------------------------------------------------------------
    # 手眼矩阵
    # ------------------------------------------------------------------
    def on_load_handeye(self, path: str, unit: Optional[str], eye_in_hand):
        if not path:
            self._log("[拒绝] 请填写 handeye.json 路径")
            return
        if unit is None:
            self._log("[拒绝] 单位必须显式选择 mm 或 m（无默认，D4）")
            return
        # 安装方式未选 = None：**原样传下去**，由 JSON 自己的 eye_in_hand 决定并在日志明说。
        # 旧版把 None 转成 False 再传，对 eye_in_hand=true 的 JSON 会报
        # "安装方式不一致"（其实是"没选"）——@lead v2 §10.4-③。
        if eye_in_hand is None:
            self._log("[提示] 未选安装方式 → 以 JSON 内 eye_in_hand 为准"
                      "（与 JSON 声明冲突时会拒绝）")
        ok, msg, res = he_mod.HandEyeResult.load(path, unit, eye_in_hand)
        self._on_handeye_result(ok, msg, res)

    def on_manual_handeye(self, text: str, unit: Optional[str], eye_in_hand):
        vals = ControlPanel.parse_floats(text)
        if vals is None:
            self._log("[拒绝] 手动录入需 16 个数（行优先，逗号/空格分隔）")
            return
        if unit is None:
            self._log("[拒绝] 单位必须显式选择 mm 或 m（无默认，D4）")
            return
        if eye_in_hand is None:
            # 手动录入没有文件可推断安装方式 → 必须显式选（D4：安装方式不预选）
            self._log("[拒绝] 安装方式必须显式选择（眼在手上 / 眼在手外）："
                      "手动录入无文件可推断，静默默认会写出反装矩阵（K6）")
            return
        ok, msg, res = he_mod.HandEyeResult.from_matrix(vals, unit, eye_in_hand)
        self._on_handeye_result(ok, msg, res)

    def _on_handeye_result(self, ok: bool, msg: str, res):
        if not ok:
            self.handeye = None
            self.validator = None
            self.tip_report = None
            self._refresh_state()
            self._log(f"[拒绝] 手眼矩阵未加载：{msg}")
            return
        self.handeye = res
        # A3：换矩阵 = 验证状态重置（validated 由加载器置 False），戳点样本清零
        self.validator = validation.TipTouchValidator(
            res.eye_in_hand, res.T_handeye_mm)
        self.tip_report = None
        self.captured_frames.clear()
        self.captured_poses.clear()
        self._refresh_state()
        self._log(f"[OK] 手眼矩阵已加载（{res.key()}, ‖t‖="
                  f"{np.linalg.norm(res.T_handeye_mm[:3, 3]):.3f} mm, "
                  f"source={res.source}）")
        self._log(f"     {msg}")
        self._log("     矩阵状态 UNVERIFIED：请做 ≥3 个离面姿态的戳点验证（A3）。")

    # ------------------------------------------------------------------
    # 批 6A：矩阵落文件（A10）
    # ------------------------------------------------------------------
    def handeye_meta_text(self) -> str:
        """矩阵元数据回显文本（`未知` 不许显示成 0，@lead v2 §10.4-②）。"""
        h = self.handeye
        if h is None:
            return ""
        unknown = bool(getattr(h, "rms_unknown", False)) or h.n_samples == 0
        rms_txt = ("rms=未知 · n_samples=未知（文件里是 null，不是 0）" if unknown
                   else f"rms_t={h.rms_t_mm:g} mm · rms_r={h.rms_r_deg:g}° · "
                        f"n_samples={h.n_samples}")
        ver = getattr(h, "verification", None)
        ver_txt = f"verification={ver['state']}" if ver else "无 verification 块"
        return (f"来源 {os.path.basename(h.source)} · {rms_txt} · {ver_txt} · "
                f"‖t‖={np.linalg.norm(h.T_handeye_mm[:3, 3]):.3f} mm")

    def export_handeye_file(self, path: str) -> bool:
        """把当前矩阵写成 v1 矩阵文件（无对话框版本，`--smoke` 也走它，A10）。

        - 单位：面板选了就用面板的；未选 → 取内部毫米口径（日志显式说明，不静默）。
        - `euler.order`：面板「欧拉顺序」若已选则写入（批 6B 起改为判定结果，
          见补充方案 §4）；未选 → 写 null（= 未判定），不编一个顺序出来。
        - 不卡 A3 门禁：现场要把矩阵带走用；门禁状态写进文件 `validated` 字段，
          接手方据此判断要不要复核。
        """
        if self.handeye is None:
            self._log("[拒绝] 尚未加载手眼矩阵，无可导出内容")
            return False
        unit_sel = self.panel.combo_he_unit.currentData()
        unit = unit_sel or "mm"
        note = "" if unit_sel else "（面板未选单位 → 取内部毫米口径）"
        order = self.panel.combo_pose_order.currentData()
        euler = {"order": order,
                 "intrinsic": (order.isupper() if order else None),
                 "output_format": hf_mod.EULER_OUTPUT_FORMAT,
                 "angle_unit": hf_mod.EULER_ANGLE_UNIT}
        src = (hf_mod.SOURCE_TOOL if self.handeye.source == "manual"
               else f"{hf_mod.SOURCE_TOOL}; loaded_from="
                    f"{os.path.basename(self.handeye.source)}")
        # 未知的 rms/n_samples 写 null，不写 0.0（@lead v2 §10.4-②）
        unknown = (bool(getattr(self.handeye, "rms_unknown", False))
                   or self.handeye.n_samples == 0)
        rms = (None, None) if unknown else (self.handeye.rms_t_mm,
                                            self.handeye.rms_r_deg)
        n_samples = None if unknown else self.handeye.n_samples
        # A3 门禁留痕块（@lead v2 §10.4-①）：屏上黄条与文件里同一份事实
        tip = self.tip_report or {}
        verification = {
            "state": ("VERIFIED" if self.handeye.validated
                      else ("FAILED" if tip.get("verdict") == "FAIL"
                            else "UNVERIFIED")),
            "validated": bool(self.handeye.validated),
            "tip_verdict": tip.get("verdict"),
            "err_mean_mm": (float(tip["err_mean_mm"])
                            if tip.get("err_mean_mm") is not None else None),
        }
        ok, msg = hf_mod.write_matrix_file(
            path, self.handeye.T_handeye_mm,
            eye_in_hand=self.handeye.eye_in_hand, unit=unit, source=src,
            rms=rms, n_samples=n_samples, euler=euler,
            validated=self.handeye.validated, verification=verification)
        self._log(("[OK] " if ok else "[拒绝] ") + msg + note)
        if ok and unknown:
            self._log("     注意：文件里 rms_t_mm / rms_r_deg / n_samples = null 的"
                      "含义是**未知**（源数据没有这几个量），不是 0 误差。")
        return ok

    def on_export_handeye_file(self):
        """面板按钮 → 选路径 → `export_handeye_file`。"""
        import datetime
        from PySide6.QtWidgets import QFileDialog
        default = ("handeye_matrix_"
                   + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".json")
        path, _ = QFileDialog.getSaveFileName(
            self, "导出矩阵文件（A10）", default, "矩阵文件 (*.json)")
        if not path:
            return
        self.export_handeye_file(path)

    def import_handeye_file(self, path: str) -> bool:
        """读矩阵文件（v1 或 MCC 旧 JSON）并走正常加载路径（无对话框版本，A10）。

        单位/安装方式都按面板当前选择传入；未选（None）则交回文件规则：
        v1 以文件 unit 为准，旧 JSON 无 unit → 拒（提示显式选单位）。
        """
        unit, mount = self.panel.handeye_meta()
        ok, msg, res = hf_mod.read_matrix_file(
            path, unit_override=unit, eye_in_hand=mount)
        self._on_handeye_result(ok, msg, res)
        return ok

    def on_import_handeye_file(self):
        """面板按钮 → 选文件 → `import_handeye_file`。"""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "导入矩阵文件（A10）", "", "矩阵文件 (*.json)")
        if not path:
            return
        self.import_handeye_file(path)

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
        self.last_pose_used = T_bt
        colors = None
        try:
            if pcd_base.has_colors():
                colors = np.asarray(pcd_base.colors)
        except Exception:
            colors = None
        self.captured_frames.append((np.asarray(pcd_base.points).copy(), colors))
        self.captured_poses.append(T_bt.copy())
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
        """采集一帧（变换放后台，30 万点级别不卡 UI）。

        批 4.5：后台任务一律走宿主注入的 runner；未注入时同步执行。
        本类不再自建 `_workers` 池、不再 import src/ui/worker_thread。
        """
        if self._background_runner is not None:
            self._show_loading()
            self._background_runner(self.capture_job, self._on_capture_done)
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
        if ok:
            self.dirty_changed.emit(True)
        self._refresh_state()

    def on_clear(self):
        self.frame_index = 0
        self._mock_started = False
        self.last_base_pcd = None
        self.captured_frames.clear()
        self.captured_poses.clear()
        if self.viewer is not None:
            self.viewer.clear_all()
        self.lbl_scene.setText("已清空。")
        self._log("[清空] 3D 视图、帧计数与已采集帧列表已重置（戳点样本保留）")
        self.dirty_changed.emit(False)
        self._refresh_state()

    # ------------------------------------------------------------------
    # 验证（A3 戳点门禁 + R2 重合度快检）与会话保存（A6）
    # ------------------------------------------------------------------
    def on_tip_record(self, tip_text: str):
        """记录一个戳点样本：当前位姿源位姿 + 相机系针尖单点。"""
        if self.validator is None:
            self._log("[拒绝] 尚未加载手眼矩阵，无验证对象")
            return
        tip = ControlPanel.parse_floats(tip_text)
        if tip is None or len(tip) != 3:
            self._log("[拒绝] 针尖坐标需 3 个数（相机系，毫米，每姿态单点）")
            return
        ok, msg, T = self.pose_src.get_pose()
        if not ok or T is None:
            self._log(f"[拒绝] 无法读取当前位姿（{msg}）：请先录入/加载位姿")
            return
        ok2, msg2 = self.validator.add_sample(T, tip)
        self._log(("[OK] " if ok2 else "[拒绝] ") + msg2)

    def on_tip_check(self):
        """运行戳点门禁（唯一可用性判据，A3）；PASS 才允许导出。"""
        if self.validator is None:
            self._log("[拒绝] 尚未加载手眼矩阵")
            return
        rep = self.validator.check()
        self.tip_report = rep
        if rep["verdict"] == "PASS":
            self.handeye.validated = True
        else:
            self.handeye.validated = False
        self._refresh_state()
        self._log(f"[戳点门禁] verdict={rep['verdict']}  n={rep['n']}  "
                  f"err_mean={rep['err_mean_mm']:.3f} mm（门禁 ≤ "
                  f"{rep['mean_gate_mm']:.1f}）  err_max={rep['err_max_mm']:.3f} mm")
        self._log(f"     姿态离面：{rep['spread_message']}")
        for w in rep["warnings"]:
            self._log(f"     [warning] {w}")
        for r in rep["reasons"]:
            self._log(f"     [原因] {r}")

    def on_overlap_check(self):
        """两帧重合度快检（warning 级，**不进门禁、不改变状态**，R2）。"""
        if len(self.captured_frames) < 2:
            self._log("[拒绝] 重合度快检需要 ≥2 帧已采集点云")
            return
        (xyz_a, _), (xyz_b, _) = self.captured_frames[-2:]
        Ta, Tb = self.captured_poses[-2], self.captured_poses[-1]
        rep = validation.TwoFrameOverlapChecker.check(xyz_a, xyz_b, Ta, Tb)
        self._log(f"[重合度快检] median={rep['median_mm']:.3f} mm  "
                  f"p95={rep['p95_mm']:.3f} mm（两位姿旋转差 "
                  f"{rep['rotation_deg']:.1f}°，前提 ≥30°）")
        self._log(f"     {rep['hint']}")
        if rep["verdict"] == "PRECONDITION_FAILED":
            self._log("     [warning] 旋转差 <30°，本报告数值仅供参考（前提不满足）")

    def on_save_session(self):
        """保存会话（A6）。fail-closed：未 VERIFIED 时按钮置灰，到不了这里。"""
        if self.handeye is None or not self.handeye.validated:
            self._log("[拒绝] 会话保存被 A3 门禁拦住：未 VERIFIED")
            return
        from PySide6.QtWidgets import QFileDialog
        target = QFileDialog.getExistingDirectory(
            self, "选择会话保存目录（将新建 session_ 子目录）")
        if not target:
            return
        import datetime
        sub = os.path.join(
            target, "session_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        ok, msg = session_mod.save_session(
            sub, self.handeye, self.captured_poses, self.captured_frames,
            error_report=self.tip_report)
        self._log(("[OK] " if ok else "[拒绝] ") + msg)
        if ok:
            self.dirty_changed.emit(False)

    def merged_pcd(self):
        """已采集帧的保色合并点云（open3d）。走 merge_pointclouds 逐帧折叠，禁止裸 +=。"""
        if not self.captured_frames:
            return None
        clouds = []
        for xyz, colors in self.captured_frames:
            pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(xyz))
            if colors is not None:
                pc.colors = o3d.utility.Vector3dVector(colors)
            clouds.append(pc)
        if merge_pointclouds is None:
            raise RuntimeError("src/core 不可用（merge_pointclouds 缺失）："
                               "合并导出已 fail-closed 禁用")
        # merge_pointclouds(merged, pcd) 原地折叠 accumulator → 先 copy 首帧（K3）
        merged = o3d.geometry.PointCloud(clouds[0])
        for c in clouds[1:]:
            merged = merge_pointclouds(merged, c)
        return merged

    def on_save_merged_ply(self):
        """保存合并 PLY（A4）。fail-closed：未 VERIFIED 或无帧时按钮置灰，到不了这里。"""
        if self.handeye is None or not self.handeye.validated:
            self._log("[拒绝] 合并 PLY 保存被 A3 门禁拦住：未 VERIFIED")
            return
        if not self.captured_frames:
            self._log("[拒绝] 尚未采集任何帧，无内容可保存")
            return
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "保存合并点云", "merged_base.ply", "PLY (*.ply)")
        if not path:
            return
        try:
            merged = self.merged_pcd()
            ok = o3d.io.write_point_cloud(path, merged)
            self._log(("[OK] " if ok else "[拒绝] ") +
                      f"合并点云已保存：{path}（{len(merged.points)} 点）")
        except Exception as e:
            self._log(f"[拒绝] 合并 PLY 保存失败：{e}")

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
            self._log(("[OK] " if ok else "[拒绝] ") + msg)
            if not ok:
                bad += 1
                continue
            if pcd is not None:
                # A4 加严（@feas/@arch v4.3）：**每帧**都跑解析真值比对，不只第 1 帧。
                # 真值 = 内联矩阵乘（不调被测函数），与 A1 §[1] 同口径 → core 层 + app
                # 接线层两级同口径证据。
                pc_truth = np.asarray(make_camera_frame(seed=i + 1).points)
                truth = (self.last_pose_used @ self.handeye.T_handeye_mm @ np.concatenate(
                    [pc_truth, np.ones((len(pc_truth), 1))], axis=1).T).T[:, :3]
                err = float(np.max(np.abs(np.asarray(pcd.points) - truth)))
                tag = "OK" if err < 1e-9 else "FAIL"
                print(f"[{tag}] 第 {i + 1} 帧基座系点云 vs 解析真值：逐点最大偏差 "
                      f"{err:.3e} mm（门槛 1e-9）")
                self._log(f"    第 {i + 1} 帧 vs 解析真值 err={err:.3e} mm")
                if err >= 1e-9:
                    bad += 1
        # 反例：米制当毫米必须被拦（否则说明守卫丢了）
        ok2, msg2 = self.pose_src.append_pose(
            ps_mod.euler_to_matrix([0.4, 0.1, 0.2], [0, 0, 0], "ZYX"),
            "mm", "absolute")
        self._log(f"反例（米制当毫米）：{'未被拦住(严重)' if ok2 else '已拦住 -> ' + msg2[:60]}")
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
        # RG-11 fail-closed：UI 槽位传 delta 也必须被拒（core 收口，不是靠下拉置灰）
        self.pose_src = ps_mod.ManualPoseSource()
        self.on_manual_pose("400,100,420", "0,0,15", "ZYX", "mm", "delta")
        if self.pose_src.get_pose()[0]:
            print("[FAIL] delta 位姿经 UI 槽位竟然录入成功（RG-11 未收口）")
            bad += 1
        else:
            print("[OK] UI 槽位：delta 位姿 → 已拒绝（fail-closed，R11）")
        # ---- 批 3：A3 戳点门禁（UI 槽位，正/反例）+ A6 会话往返 ----
        self._log("--- smoke：A3 戳点门禁 + A6 会话保存/恢复 ---")
        P_TIP = np.array([400.0, 100.0, 420.0])

        def _tip_cam_of(T_handeye, T_bt):
            T_cb = transform_chain.compute_cam2base(True, T_handeye, T_bt)
            return (np.linalg.inv(T_cb) @ np.append(P_TIP, 1.0))[:3]

        # 1) 真值一致的 3 个离面姿态 → 门禁 PASS → VERIFIED → 导出解锁
        demo = [ps_mod.euler_to_matrix([x, y, z], [rx, ry, rz], "ZYX")
                for x, y, z, rx, ry, rz in
                [(400, 100, 420, 0, 0, 0),
                 (420, 110, 430, 0, 20, 25),
                 (410, 120, 425, 25, 0, -20)]]
        self.pose_src = ps_mod.MockPoseSource(demo, "mm", "absolute")
        for _ in range(3):
            _, _, Tp = self.pose_src.get_pose()
            tip = _tip_cam_of(self.handeye.T_handeye_mm, Tp)
            self.on_tip_record(", ".join(f"{v:.3f}" for v in tip))
            self.pose_src.step_next()
        self.on_tip_check()
        if self.handeye.validated and self.panel.btn_export.isEnabled():
            print("[OK] 戳点门禁 PASS → VERIFIED，导出已解锁")
        else:
            print("[FAIL] 真值一致的戳点样本应判 PASS 并解锁导出")
            bad += 1
        # 2) A6 会话保存/恢复：帧/位姿/矩阵/validated 全部还原
        import shutil
        import tempfile
        sess_tmp = tempfile.mkdtemp(prefix="mcc_smoke_session_")
        oks, _ = session_mod.save_session(
            os.path.join(sess_tmp, "session_smoke"), self.handeye,
            self.captured_poses, self.captured_frames,
            error_report=self.tip_report)
        okl, msgl, restored = session_mod.load_session(
            os.path.join(sess_tmp, "session_smoke"))
        n_ok = (oks and okl
                and len(restored["frames"]) == len(self.captured_frames)
                and len(restored["poses"]) == len(self.captured_poses)
                and restored["handeye"]["validated"] == self.handeye.validated
                and np.array_equal(restored["handeye"]["T_handeye_mm"],
                                   self.handeye.T_handeye_mm))
        if not n_ok:
            bad += 1
        self._log(("[OK] " if n_ok else "[FAIL] ") + f"A6 会话往返：{msgl}")
        self.dirty_changed.emit(False)   # 会话已落盘（合入形态：脏标记复位）
        shutil.rmtree(sess_tmp, ignore_errors=True)
        # 3) 退化矩阵反例（平移错 110 mm，@qa/@feas 场景）：同一批针尖观测
        #    必须判 FAIL、导出回锁（A3 核心回归）
        T_good = self.handeye.T_handeye_mm.copy()
        T_bad = T_good.copy()
        T_bad[:3, 3] += np.array([110.0, 0.0, 0.0])
        okb, msgb, resb = he_mod.HandEyeResult.from_matrix(
            T_bad.reshape(-1).tolist(), "mm", True)
        if not okb:
            print(f"[FAIL] 退化矩阵加载失败（应能加载、由门禁判死）：{msgb}")
            bad += 1
        else:
            self._on_handeye_result(True, msgb, resb)   # 走正常 UI 加载路径
            for _ in range(3):
                _, _, Tp = self.pose_src.get_pose()
                tip = _tip_cam_of(T_good, Tp)   # 针尖观测由真值链产生
                self.on_tip_record(", ".join(f"{v:.3f}" for v in tip))
                self.pose_src.step_next()
            self.on_tip_check()
            if self.handeye.validated or self.panel.btn_export.isEnabled():
                print("[FAIL] 退化矩阵戳点必须判 FAIL 并回锁导出（A3）")
                bad += 1
            else:
                print("[OK] 退化矩阵（平移错 110 mm）戳点判 FAIL，导出已回锁")
        # 4) 重载正确矩阵 → 验证状态重置回 UNVERIFIED，导出仍锁
        okg, msgg, resg = he_mod.HandEyeResult.from_matrix(
            T_good.reshape(-1).tolist(), "mm", True)
        self._on_handeye_result(okg, msgg, resg)
        if self.handeye.validated or self.panel.btn_export.isEnabled():
            print("[FAIL] 重载矩阵后应回到 UNVERIFIED（导出置灰）")
            bad += 1
        else:
            print("[OK] 重载矩阵 → UNVERIFIED 重置，导出保持锁定")
        # ---- 批 4.5：合入形态自检（工作区接口 / 单一后台 runner / 查看器缺失必显形）----
        self._log("--- smoke：批 4.5 合入形态（QWidget 工作区 + 注入 runner + HAS_VIEWER）---")
        # ① HAS_VIEWER=False 必须显形（Phase 2 把 src/ui/viewer_3d 搬进 ui_v2 时，
        #    旧 import 打伤这里会表现为"全绿灯 + 3D 静默消失"；此处钉死为红）
        if HAS_VIEWER:
            print(f"[OK] 3D 查看器可用：HAS_VIEWER=True，面板 = "
                  f"{ViewerPanel.__module__}.{ViewerPanel.__name__}")
        else:
            print("[FAIL] HAS_VIEWER=False：合入形态下该降级非法（禁止静默降级，批 4.5 ⑤）")
            bad += 1
        # ② 合入形态接口齐备（QWidget 工作区 + 5 接口，照 ui_v2 转台工作区）
        missing = [n for n in ("set_devices", "set_state", "set_background_runner",
                               "log_message", "dirty_changed")
                   if not hasattr(self, n)]
        still_window = hasattr(self, "setCentralWidget")     # QMainWindow 专属 API
        if missing or still_window:
            print(f"[FAIL] 合入形态接口不齐：缺 {missing}，仍是 QMainWindow={still_window}")
            bad += 1
        else:
            print("[OK] 合入形态接口齐备：QWidget 工作区 + set_devices / set_state / "
                  "set_background_runner / log_message / dirty_changed")
        # ③ 旧 ui.* 直接依赖必须为零（Phase 2 搬 viewer_3d 打不到本模块）
        import inspect as _inspect
        import re as _re
        _src = _inspect.getsource(sys.modules[__name__]).splitlines()
        _old_ui = [ln for ln in _src
                   if _re.match(r"\s*(from|import)\s+ui\.", ln)
                   and not ln.strip().startswith("#")]
        if _old_ui:
            print(f"[FAIL] 仍直接 import 旧 ui.*：{_old_ui}")
            bad += 1
        else:
            print("[OK] 无 `from ui.` / `import ui.` 直接依赖（查看器经 ui_v2 面板）")
        # ④ 后台任务必须走注入 runner（禁自建池，1.0.10）
        calls = []
        dirty_events = []
        self.dirty_changed.connect(dirty_events.append)

        def _rec_runner(work, on_done, must_finish=False, name=None):
            """记录型 runner：**与 _run_background 同签名**（(result, error) 回调）。"""
            calls.append((getattr(work, "__name__", "?"), must_finish, name))
            try:
                on_done(work(), None)
            except Exception as e:
                on_done(None, e)

        self.set_background_runner(_rec_runner)
        self.set_devices([])
        self.set_state("matrix_loaded")
        self.pose_src = ps_mod.MockPoseSource(demo, "mm", "absolute")
        self._mock_started = False
        n_before = len(self.captured_frames)
        self.on_capture()
        runner_ok = (len(calls) == 1 and calls[0][0] == "capture_job"
                     and len(self.captured_frames) == n_before + 1
                     and self.panel.btn_capture.isEnabled())
        print(f"[{'OK' if runner_ok else 'FAIL'}] 后台任务走注入 runner：调用 {len(calls)} 次 "
              f"{calls}；帧 {n_before}→{len(self.captured_frames)}；"
              f"采集按钮已复位={self.panel.btn_capture.isEnabled()}")
        if not runner_ok:
            bad += 1
        if True in dirty_events:
            print(f"[OK] dirty_changed 已接线（本次 smoke 共 {len(dirty_events)} 次事件）")
        else:
            print("[FAIL] 采集成功未触发 dirty_changed")
            bad += 1
        if self.current_state() == "matrix_loaded":
            print("[OK] set_state / current_state 生效（matrix_loaded）")
        else:
            print(f"[FAIL] set_state 未生效：state={self.current_state()!r}")
            bad += 1
        self.set_background_runner(None)     # 还原：桩不外泄
        # ---- 批 6A：矩阵落文件（A10 导出 → 读回 → 逐元素比对 / 单位冲突必拒）----
        self._log("--- smoke：批 6A 矩阵落文件（A10）---")
        import json
        he_tmp = tempfile.mkdtemp(prefix="mcc_smoke_hefile_")
        f6a = os.path.join(he_tmp, "handeye_matrix.json")
        exp_ok = self.export_handeye_file(f6a)
        assert self.handeye is not None, "smoke 前置：矩阵已加载（否则上面早已返回 1）"
        T_before = self.handeye.T_handeye_mm
        ok_rd, msg_rd, res_rd = hf_mod.read_matrix_file(f6a)
        d16 = (float(np.max(np.abs(res_rd.T_handeye_mm - T_before)))
               if (ok_rd and res_rd is not None) else float("nan"))
        ok_rt, msg_rt, maxd_rt = hf_mod.roundtrip_check(f6a)
        n6a = exp_ok and ok_rd and ok_rt and d16 == 0.0
        print(f"[{'OK' if n6a else 'FAIL'}] 6A 矩阵文件写→读：16 元素逐元素 max|Δ|="
              f"{d16:.3e}（门槛 {hf_mod.RT_TOL:g}；roundtrip {maxd_rt:.3e}）")
        if not n6a:
            bad += 1
        fu = (res_rd.file_meta.get("unit") if (ok_rd and res_rd is not None) else "mm")
        conflict = "m" if fu == "mm" else "mm"
        ok_c, msg_c, _ = hf_mod.read_matrix_file(f6a, unit_override=conflict)
        print(f"[{'OK' if not ok_c else 'FAIL'}] 6A 单位冲突必拒：文件 unit={fu} + 界面 "
              f"{conflict} → {'已拒绝' if not ok_c else '竟然放行'}")
        if ok_c:
            bad += 1
        with open(f6a, "r", encoding="utf-8") as fh6:
            d6 = json.load(fh6)
        stamp_ok = (d6.get("validated") is False
                    and self.handeye.validated is False
                    and (d6.get("verification") or {}).get("state") == "UNVERIFIED"
                    and self.panel.btn_export_he_file.isEnabled()
                    and self.panel.lbl_export_gate.isVisible())
        print(f"[{'OK' if stamp_ok else 'FAIL'}] 6A 门禁留痕+屏上显形：UNVERIFIED 也可导出，"
              f"文件 validated={d6.get('validated')}／verification.state="
              f"{(d6.get('verification') or {}).get('state')}，导出按钮可用="
              f"{self.panel.btn_export_he_file.isEnabled()}，屏上黄条可见="
              f"{self.panel.lbl_export_gate.isVisible()}")
        if not stamp_ok:
            bad += 1
        # 未知值必须写 null（不是 0.0），读回必须标记为未知（@lead v2 §10.4-②）
        null_ok = (d6.get("rms_t_mm") is None and d6.get("rms_r_deg") is None
                   and d6.get("n_samples") is None
                   and bool(getattr(res_rd, "rms_unknown", False))
                   and "未知" in self.handeye_meta_text())
        print(f"[{'OK' if null_ok else 'FAIL'}] 6A 未知值写 null：文件 rms_t_mm="
              f"{d6.get('rms_t_mm')!r} / rms_r_deg={d6.get('rms_r_deg')!r} / "
              f"n_samples={d6.get('n_samples')!r}；读回 rms_unknown="
              f"{getattr(res_rd, 'rms_unknown', None)}；屏上元数据行含'未知'="
              f"{'未知' in self.handeye_meta_text()}")
        if not null_ok:
            bad += 1
        # 安装方式未选：手动录入必须报"未选"，不许伪装成 False 再报"不一致"（§10.4-③）
        self.panel.combo_he_mount.setCurrentIndex(0)      # 回到「请选择」
        self.panel.combo_he_unit.setCurrentIndex(1)       # 毫米
        n_frames_before = len(self.captured_frames)
        self.on_manual_handeye("1,0,0,20, 0,1,0,-10, 0,0,1,120, 0,0,0,1", "mm", None)
        mount_ok = (self.handeye is not None
                    and np.array_equal(self.handeye.T_handeye_mm, T_before)
                    and len(self.captured_frames) == n_frames_before)
        print(f"[{'OK' if mount_ok else 'FAIL'}] 6A 安装方式未选 → 手动录入已拒："
              f"矩阵未被替换={mount_ok}（旧版会静默当'眼在手外'录进去）")
        if not mount_ok:
            bad += 1
        # 面板导入槽位（不经鼠标，直接调窗口槽；与 RG-14 ④ 同手法）
        imp_ok = self.import_handeye_file(f6a)
        imp_same = bool(imp_ok and self.handeye is not None
                        and np.array_equal(self.handeye.T_handeye_mm, T_before))
        print(f"[{'OK' if imp_same else 'FAIL'}] 6A 面板导入路径：读回矩阵与导出前"
              f"逐元素一致={imp_same}；导入后状态 validated="
              f"{None if self.handeye is None else self.handeye.validated}（应 False）")
        if not imp_same:
            bad += 1
        print(f"       6A 落盘文件 = {f6a}")
        shutil.rmtree(he_tmp, ignore_errors=True)
        print(f"=== smoke 结束：{frames} 帧，失败 {bad} 项 ===")
        return 0 if bad == 0 else 1
