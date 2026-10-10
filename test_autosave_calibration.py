# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
test_autosave_calibration.py —— 标定结果自动保存/恢复的 core 层行为测试。

背景（2026-10-09）：原生堆损坏崩溃复发后用户反馈"崩溃后要重新标定"。
ui_v2 已在标定成功/加载外参/加载会话后自动落盘
offline_data/autosave_calibration.json，并在连接同一组相机时自动恢复到
扫描阶段。本测试锁定该机制的 core 层前提：

  [1] 自动保存格式与「保存外参」一致：to_dict() + camera_names/saved_at
      多余字段不影响 load_from_dict 解析
  [2] FixedMultiCamWorkflow.load_calibration 恢复后状态为 CALIBRATED，
      且无需标定帧即可 start_scanning（崩溃恢复路径的关键前提）
  [3] 相机组合不匹配 / 文件损坏时恢复优雅失败，不抛异常
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

print("=" * 60)
print("标定结果自动保存/恢复（core 层）测试")
print("=" * 60)

import numpy as np  # noqa: E402

from core.calibration_engine import CalibrationEngine  # noqa: E402
from core.fixed_multi_cam_workflow import FixedMultiCamWorkflow  # noqa: E402
from core.camera_manager import CameraManager  # noqa: E402
from core.marker_detector import MarkerDetector  # noqa: E402
from core.stitch_engine import StitchEngine  # noqa: E402


def make_workflow() -> FixedMultiCamWorkflow:
    return FixedMultiCamWorkflow(
        CameraManager(), MarkerDetector(), CalibrationEngine(), StitchEngine())

passed = []


def check(name: str, cond: bool, detail: str = ""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        print("\n测试失败：" + name)
        sys.exit(1)
    passed.append(name)


def make_engine_with_pair(rms=0.09) -> CalibrationEngine:
    """构造带一对成功标定结果的引擎（T = 4x4 单位阵）。"""
    engine = CalibrationEngine()
    engine.set_reference("cam0")
    engine.pair_results[("cam0", "cam1")] = {
        "success": True,
        "T": np.eye(4),
        "rms_mm": rms,
        "inlier_ratio": 1.0,
    }
    return engine


# ------------------------------------------------------------------
# [1] 自动保存格式兼容：多余字段不影响解析
# ------------------------------------------------------------------
print("\n[1] 自动保存格式 = 外参格式 + 元数据字段")
engine = make_engine_with_pair()
payload = engine.to_dict()
payload["camera_names"] = ["cam0", "cam1"]
payload["saved_at"] = "2026-10-09 15:30:00"

engine2 = CalibrationEngine()
ok, msg = engine2.load_from_dict(payload)
check("含 camera_names/saved_at 的 payload 可解析", ok, msg)
check("reference_id 恢复", engine2.reference_id == "cam0")
check("pair 数量恢复", len(engine2.pair_results) == 1)
T = engine2.pair_results[("cam0", "cam1")]["T"]
check("T 矩阵恢复为 4x4 ndarray", isinstance(T, np.ndarray) and T.shape == (4, 4))

# ------------------------------------------------------------------
# [2] load_calibration → CALIBRATED → 无标定帧也可 start_scanning
# ------------------------------------------------------------------
print("\n[2] 崩溃恢复路径：加载后可直接进入扫描阶段")
wf = make_workflow()
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "autosave_calibration.json")
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    check("初始无标定结果", not wf.calibration_engine.pair_results)
    ok, msg = wf.load_calibration(path)
    check("load_calibration 成功", ok, msg)
    check("状态为 CALIBRATED（外参锁定）",
          wf.get_state() == FixedMultiCamWorkflow.STATE_CALIBRATED)
    ok_scan, msg_scan = wf.start_scanning()
    check("无标定帧也可进入扫描阶段", ok_scan, msg_scan)
    check("状态为 SCANNING",
          wf.get_state() == FixedMultiCamWorkflow.STATE_SCANNING)

# ------------------------------------------------------------------
# [3] 异常输入优雅失败
# ------------------------------------------------------------------
print("\n[3] 异常输入优雅失败")
engine3 = CalibrationEngine()
ok, _ = engine3.load_from_dict({"pairs": {}})
check("空 pairs 返回失败", not ok)
ok, _ = engine3.load_from_dict("not-a-dict")
check("非 dict 返回失败", not ok)

wf2 = make_workflow()
with tempfile.TemporaryDirectory() as tmp:
    bad = os.path.join(tmp, "bad.json")
    with open(bad, "w", encoding="utf-8") as f:
        f.write("{corrupted json")
    try:
        wf2.load_calibration(bad)
        crashed = False
    except Exception:
        crashed = True
    check("损坏文件不抛异常", not crashed)

print("\n" + "=" * 60)
print(f"全部 {len(passed)} 项断言通过")
print("=" * 60)
