# -*- coding: utf-8 -*-
"""
位姿入口守卫测试（test_pose_source）—— 批 1.5 / 方案 v4 §4.2（A2 位姿侧）。

跑法同 test_unit_guard.py（conda rvc python 直跑，看退出码，勿用 pytest）。

覆盖（@qa 缺陷① 的复现与回归）：
  [1] 元数据三件套必填：unit / pose_type 无默认；order 无 "ZYX" 默认
  [2] 米制误读：xyz=[0.4,0.1,0.2] 当毫米 → 必须被拦（旧版端到端静默错 457.799 mm）
      正确声明 unit="m" → 与毫米真值一致
  [3] 四类必拒：NaN 位姿 / det=-1 镜像 / 非正交 / 末行错
  [4] 尺寸与类型错误：np.eye(3) / 9 个数 → 自家可读报错（不抛 numpy 原生异常）
  [5] pose_type 锁定与 delta 窗口
  [6] CSV：16 列 / 7 列放行；6 列 / 缺 pose_type 声明 / 声明不一致 / 列数怪 → 拒
  [7] 端到端：位姿 + 手眼矩阵 → 基座系点云（正确路径算对；误读路径不产生静默错值）
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "core"))

import numpy as np

import pose_source
import transform_chain
from pose_source import (CsvPoseSource, ManualPoseSource, MockPoseSource,
                         PoseError, euler_to_matrix)

FAILURES = []


def check(cond: bool, label: str, detail: str = ""):
    tag = "OK  " if cond else "FAIL"
    print(f"  [{tag}] {label}" + (f" | {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def T(t=(300.0, 100.0, 420.0)) -> np.ndarray:
    M = np.eye(4)
    M[:3, 3] = list(t)
    return M


def write_csv(text: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".csv", prefix="mcc_pose_")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def main():
    print("=" * 70)
    print("[1] 元数据三件套必填（无默认）")
    m = ManualPoseSource()
    ok, msg = m.set_pose_xyz_rpy([0.0, 0.0, 500.0], [0, 0, 0], None, "mm", "absolute")
    check(not ok and "order" in msg, "order=None → 拒绝（无 ZYX 默认）", msg[:50])
    ok, msg = m.set_pose_xyz_rpy([0.0, 0.0, 500.0], [0, 0, 0], "QQQ", "mm", "absolute")
    check(not ok and "不支持的欧拉顺序" in msg, "order 非法 → 拒绝", msg[:50])
    ok, msg = m.set_pose_xyz_rpy([0.0, 0.0, 500.0], [0, 0, 0], "ZYX", None, "absolute")
    check(not ok and "单位必须显式选择" in msg, "unit=None → 拒绝（无默认）", msg[:50])
    ok, msg = m.set_pose_xyz_rpy([0.0, 0.0, 500.0], [0, 0, 0], "ZYX", "mm", None)
    check(not ok and "pose_type 必须显式选择" in msg, "pose_type=None → 拒绝", msg[:50])
    try:
        MockPoseSource([T()])
        check(False, "MockPoseSource(poses) 缺 unit/pose_type 必须报错")
    except PoseError as e:
        check("初始化失败" in str(e), "MockPoseSource 构造缺元数据 → PoseError", str(e)[:60])

    print("=" * 70)
    print("[2] 米制误读（@qa 缺陷① 回归）")
    m = ManualPoseSource()
    ok, msg = m.set_pose_xyz_rpy([0.4, 0.1, 0.2], [0, 0, 0], "ZYX", "mm", "absolute")
    check(not ok, "米制数值当毫米 → 拒绝（旧版静默错 457.799 mm）", msg[:70])
    ok, msg = m.set_pose_xyz_rpy([0.4, 0.1, 0.2], [0, 0, 0], "ZYX", "m", "absolute")
    check(ok and m.get_pose()[0], "unit='m' 正确声明 → 放行", msg)
    got = m.get_pose()[2]
    check(np.allclose(got[:3, 3], [400.0, 100.0, 200.0], atol=1e-9),
          "米制位姿换算为毫米真值 400/100/200", f"‖t‖={np.linalg.norm(got[:3,3]):.3f}")
    ok, msg = m.set_pose_matrix(T((0.45, 0.1, 0.42)), "m", "absolute")
    check(ok, "set_pose_matrix 米制 → 放行", msg)
    ok, msg = m.set_pose_matrix(T((0.45, 0.1, 0.42)), "mm", "absolute")
    check(not ok, "set_pose_matrix 米制数值当毫米 → 拒绝", msg[:70])

    print("=" * 70)
    print("[3] 四类必拒（NaN / 镜像 / 非正交 / 末行）")
    cases = []
    bad = T(); bad[0, 3] = np.nan
    cases.append(("NaN 位姿", bad))
    bad = T(); bad[0, 0] = -1.0
    cases.append(("det=-1 镜像位姿", bad))
    shear = T(); shear[:3, :3] = [[1.0, 0.5, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    cases.append(("det=+1 shear", shear))
    bad = T(); bad[3] = [0.0, 0.0, 1.0, 1.0]
    cases.append(("末行错", bad))
    for name, TT in cases:
        ok, msg, Tm = pose_source.admit_pose(TT, "mm", "absolute")
        check(not ok and Tm is None, f"拒绝 {name}", msg[:70])
    ok, msg = MockPoseSource().append_pose(T(), "mm", "absolute")
    check(ok, "合法位姿放行", msg)

    print("=" * 70)
    print("[4] 尺寸/类型错误自家可读报错")
    src = MockPoseSource()
    ok, msg = src.append_pose(np.eye(3), "mm", "absolute")
    check(not ok and "4×4" in msg and "shape=(3, 3)" in msg,
          "append_pose(np.eye(3)) → 自家报错（旧版抛 numpy 原生 reshape）", msg)
    ok, msg = src.append_pose([0.0] * 9, "mm", "absolute")
    check(not ok and "16 个数" in msg, "9 个数 → 自家报错", msg)
    ok, msg = src.append_pose(["a", "b"], "mm", "absolute")
    check(not ok and "4×4" in msg, "非数值 → 自家报错", msg)
    check(src.count() == 0, "失败录入不留半截序列（count=0）", f"count={src.count()}")

    print("=" * 70)
    print("[5] pose_type 锁定与 delta 窗口")
    src = MockPoseSource()
    ok, _ = src.set_poses([T((300.0, 0, 0))], "mm", "absolute")
    check(ok, "absolute 序列载入")
    ok, msg = src.append_pose(T((301.0, 0, 0)), "mm", "delta")
    check(not ok and "锁定" in msg, "中途改 pose_type → 拒绝", msg)
    src2 = MockPoseSource()
    ok, msg = src2.set_poses([T((1.0, 0, 0)), T((2.0, 0, 0))], "mm", "delta")
    check(ok, "delta 1mm/2mm 步长放行", msg)
    ok, msg = src2.set_poses([T((1000.0, 0, 0))], "mm", "delta")
    check(not ok, "delta 1000mm（1mm×1000 误读）→ 拒绝", msg[:70])
    ok, msg = src2.set_poses([T((0.5, 0, 0))], "mm", "delta")
    check(not ok, "delta 0.5mm（低于窗口下界）→ 拒绝", msg[:70])

    print("=" * 70)
    print("[6] CSV 入口")
    p16 = write_csv("# pose_type: absolute\n" + " ".join(map(str, T().reshape(-1))) + "\n")
    ok, msg, s = CsvPoseSource.load(p16, "mm", "absolute")
    check(ok and s.count() == 1, "16 列矩阵 + pose_type 声明 → 放行", msg)
    p7 = write_csv("# pose_type: absolute\n400 100 200 0 0 0 ZYX\n")
    ok, msg, s = CsvPoseSource.load(p7, "mm", "absolute")
    check(ok and s.count() == 1, "7 列（含 order，空格分隔）→ 放行", msg)
    p7c = write_csv("# pose_type: absolute\n400,100,200,0,0,0,ZYX\n")
    ok, msg, s = CsvPoseSource.load(p7c, "mm", "absolute")
    check(ok and s.count() == 1, "7 列（含 order，逗号分隔标准 CSV）→ 放行", msg)
    p6 = write_csv("# pose_type: absolute\n400 100 200 0 0 0\n")
    ok, msg, s = CsvPoseSource.load(p6, "mm", "absolute")
    check(not ok and "6 列" in msg, "6 列格式 → 拒收", msg[:70])
    p_no_decl = write_csv("400 100 200 0 0 0 ZYX\n")
    ok, msg, s = CsvPoseSource.load(p_no_decl, "mm", "absolute")
    check(not ok and "缺少" in msg, "缺 pose_type 声明行 → 拒收", msg[:70])
    p_delta = write_csv("# pose_type: delta\n400 100 200 0 0 0 ZYX\n")
    ok, msg, s = CsvPoseSource.load(p_delta, "mm", "absolute")
    check(not ok and "不一致" in msg, "声明 absolute/delta 与入参不一致 → 拒", msg[:70])
    p_bad_pt = write_csv("# pose_type: 也许\n400 100 200 0 0 0 ZYX\n")
    ok, msg, s = CsvPoseSource.load(p_bad_pt, "mm", "absolute")
    check(not ok and "声明非法" in msg, "声明值非法 → 拒", msg[:70])
    p_nan = write_csv("# pose_type: absolute\nnan 100 200 0 0 0 ZYX\n")
    ok, msg, s = CsvPoseSource.load(p_nan, "mm", "absolute")
    check(not ok, "CSV 内 NaN 位姿 → 拒", msg[:70])
    p_small = write_csv("# pose_type: absolute\n0.4 0.1 0.2 0 0 0 ZYX\n")
    ok, msg, s = CsvPoseSource.load(p_small, "mm", "absolute")
    check(not ok, "CSV 米制数值当毫米 → 拒", msg[:70])
    for p in (p16, p7, p7c, p6, p_no_decl, p_delta, p_bad_pt, p_nan, p_small):
        os.unlink(p)

    print("=" * 70)
    print("[7] 端到端：位姿 + 手眼矩阵 → 基座系点云")
    T_cam2tool = np.eye(4); T_cam2tool[1, 3] = -10.0; T_cam2tool[2, 3] = 120.0
    T_cam2tool[0, 3] = 20.0
    truth_pose = euler_to_matrix([400.0, 100.0, 420.0], [0.0, 0.0, 15.0], "ZYX")
    m = ManualPoseSource()
    ok, msg = m.set_pose_xyz_rpy([0.4, 0.1, 0.42], [0.0, 0.0, 15.0], "ZYX", "m", "absolute")
    check(ok, "端到端正路：米制录入接受", msg[:60])
    ok, msg, T_bt = m.get_pose()
    check(ok and np.allclose(T_bt, truth_pose, atol=1e-9),
          "端到端位姿 = 毫米真值", f"maxdiff={np.max(np.abs(T_bt - truth_pose)):.3e}")
    T_cb = transform_chain.compute_cam2base(True, T_cam2tool, T_bt)
    p_cam = np.array([[10.0, 20.0, 500.0], [0.0, -30.0, 480.0]])
    got = transform_chain.transform_points_mm(p_cam, T_cb)
    want = (truth_pose @ T_cam2tool @ np.concatenate(
        [p_cam, np.ones((2, 1))], axis=1).T).T[:, :3]
    check(float(np.max(np.abs(got - want))) < 1e-9,
          "端到端单点偏差 < 1e-9 mm", f"err={float(np.max(np.abs(got - want))):.3e}")
    m2 = ManualPoseSource()
    ok2, msg2 = m2.set_pose_xyz_rpy([0.4, 0.1, 0.2], [0, 0, 0], "ZYX", "mm", "absolute")
    check(not ok2 and m2.get_pose()[0] is False,
          "端到端误路：被拦后 get_pose 无位姿 → 不会产生 457.8mm 静默错值", msg2[:60])

    print("=" * 70)
    if FAILURES:
        print(f"[FAILED] {len(FAILURES)} 项失败:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("[ALL OK] test_pose_source")
    sys.exit(0)


if __name__ == "__main__":
    main()
