# -*- coding: utf-8 -*-
"""
会话落盘/恢复测试（test_session）—— 批 3 / A6。

跑法：conda rvc python 直跑，看退出码，勿用 pytest。

覆盖：
  [1] 完整往返：handeye（含 validated 状态）/ poses / frames（含颜色点云）
      / error_report 四项落盘后恢复，点数一致、位姿一致、矩阵逐位一致
  [2] PLY 往返：xyz 逐位一致、颜色 1/255 量化误差内一致、无色帧只写 xyz
  [3] fail-closed：目录不存在 / 缺 handeye.json / 缺 poses.json /
      poses.json 位姿数非法 / 坏 JSON → 拒绝恢复，不返回半截会话
  [4] 入参守卫：坏帧（NaN/尺寸错）/ 坏位姿 / 坏矩阵 → 拒绝落盘（不写半截）
  [5] 覆盖写：同目录二次保存先清旧帧（不混入上次残留）
  [6] 原子写残留：frames/ 内 crash 残留的 `*.tmp.ply` 不被当有效帧读入
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "core"))

import numpy as np

import handeye_result
import session
from session import load_session, save_session, write_ply

FAILURES = []


def check(cond: bool, label: str, detail: str = ""):
    tag = "OK  " if cond else "FAIL"
    print(f"  [{tag}] {label}" + (f" | {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def rotz(deg):
    t = np.radians(deg)
    c, s = np.cos(t), np.sin(t)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], float)


def mkT(R, t):
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = np.asarray(t, float)
    return M


def make_frame(seed, n=500):
    rng = np.random.default_rng(seed)
    xyz = rng.uniform([0, 0, 300], [200, 150, 500], (n, 3))
    colors = np.clip(rng.random((n, 3)), 0.0, 1.0)
    return xyz, colors


ok_he, msg_he, he = handeye_result.HandEyeResult.from_matrix(
    [1, 0, 0, 20, 0, 1, 0, -10, 0, 0, 1, 120, 0, 0, 0, 1], "mm", True)
assert ok_he, msg_he
POSES = [mkT(rotz(10 * i), [400 + 10 * i, 100, 420]) for i in range(3)]
FRAMES = [make_frame(i) for i in range(3)]
ERR_REP = {"validator": "TipTouchValidator", "verdict": "PASS",
           "err_mean_mm": 0.12, "warnings": []}

work = tempfile.mkdtemp(prefix="mcc_session_test_")
sess_dir = os.path.join(work, "session_a")

print("=" * 70)
print("[1] 完整往返：四项落盘 → 恢复一致（A6）")
ok, msg = save_session(sess_dir, he, POSES, FRAMES, ERR_REP)
check(ok, "save_session 成功", msg)
for name in ("handeye.json", "poses.json", "error_report.json"):
    check(os.path.isfile(os.path.join(sess_dir, name)), f"落盘含 {name}")
check(os.path.isdir(os.path.join(sess_dir, "frames"))
      and len(os.listdir(os.path.join(sess_dir, "frames"))) == 3,
      "落盘含 frames/frame_*.ply × 3")

ok2, msg2, restored = load_session(sess_dir)
check(ok2, "load_session 成功", msg2)
rh = restored["handeye"]
check(np.array_equal(rh["T_handeye_mm"], he.T_handeye_mm),
      "手眼矩阵逐位一致（毫米）", f"‖t‖={np.linalg.norm(rh['T_handeye_mm'][:3, 3]):.3f}")
check(rh["validated"] == he.validated and rh["eye_in_hand"] == he.eye_in_hand,
      "validated / eye_in_hand 状态还原", f"validated={rh['validated']}")
check(len(restored["poses"]) == len(POSES)
      and all(np.array_equal(a, b) for a, b in zip(restored["poses"], POSES)),
      "位姿逐位一致（点数/内容）", f"poses={len(restored['poses'])}")
check(len(restored["frames"]) == 3, "帧数一致", f"frames={len(restored['frames'])}")
for i, fr in enumerate(restored["frames"]):
    n_match = len(fr["xyz"]) == len(FRAMES[i][0])
    xyz_match = np.allclose(fr["xyz"], FRAMES[i][0], atol=1e-4)
    check(n_match and xyz_match, f"第 {i + 1} 帧点数/坐标一致（≤1e-4 mm 文本量化）",
          f"n={len(fr['xyz'])}")
    col_match = fr["colors"] is not None and np.allclose(
        fr["colors"], FRAMES[i][1], atol=1.0 / 255.0 + 1e-9)
    check(col_match, f"第 {i + 1} 帧颜色一致（1/255 量化内）", "")
check(restored["error_report"].get("verdict") == "PASS",
      "error_report 还原", f"verdict={restored['error_report'].get('verdict')}")

print("=" * 70)
print("[2] PLY 往返与无色帧")
plain_dir = os.path.join(work, "plain")
xyz_only = FRAMES[0][0]
ok3, _ = save_session(plain_dir, he, POSES[:1], [xyz_only])
check(ok3, "无色帧保存成功", "")
with open(os.path.join(plain_dir, "frames", "frame_000.ply"),
          "r", encoding="utf-8") as f:
    header = f.read(400)
check("property uchar" not in header, "无色帧 PLY 不含 rgb 属性", "")
ok4, _, restored4 = load_session(plain_dir)
check(ok4 and restored4["frames"][0]["colors"] is None,
      "无色帧恢复 colors=None", "")

print("=" * 70)
print("[3] fail-closed：缺文件/坏格式拒绝恢复")
ok5, msg5, _ = load_session(os.path.join(work, "no_such_dir"))
check(not ok5, "目录不存在 → 拒绝", msg5[:40])

broken = os.path.join(work, "broken")
os.makedirs(broken)
ok6, msg6, _ = load_session(broken)
check(not ok6 and "handeye.json" in msg6, "缺 handeye.json → 拒绝（不返回半截）",
      msg6[:60])

shutil.copy(os.path.join(sess_dir, "handeye.json"),
            os.path.join(broken, "handeye.json"))
ok7, msg7, _ = load_session(broken)
check(not ok7 and "poses.json" in msg7, "缺 poses.json → 拒绝", msg7[:60])

with open(os.path.join(broken, "poses.json"), "w", encoding="utf-8") as f:
    json.dump({"unit": "mm", "poses": [[1.0, 2.0]]}, f)
ok8, msg8, _ = load_session(broken)
check(not ok8, "poses.json 位姿数非法（非 16 数）→ 拒绝", msg8[:60])

with open(os.path.join(broken, "poses.json"), "w", encoding="utf-8") as f:
    f.write("{not json")
ok9, msg9, _ = load_session(broken)
check(not ok9, "坏 JSON → 拒绝", msg9[:50])

print("=" * 70)
print("[4] 落盘入参守卫：坏帧/坏位姿/坏矩阵 → 不写盘")
bad_dir = os.path.join(work, "bad_input")
ok10, msg10 = save_session(
    bad_dir, he, POSES, [np.full((10, 3), np.nan)])
check(not ok10, "NaN 帧拒收", msg10[:40])
ok11, msg11 = save_session(
    bad_dir, he, POSES, [np.zeros((5, 2))])
check(not ok11, "尺寸错帧拒收", msg11[:40])
ok12, msg12 = save_session(
    bad_dir, he, [np.eye(3)], FRAMES[:1])
check(not ok12, "坏位姿拒收", msg12[:40])
ok13, msg13 = save_session(
    bad_dir, np.eye(3) * np.nan, POSES, FRAMES[:1])
check(not ok13, "坏矩阵拒收", msg13[:40])
ok13b, msg13b = save_session(
    bad_dir, {"eye_in_hand": True}, POSES, FRAMES[:1])
check(not ok13b, "缺 T_handeye_mm 字段的 handeye 字典拒收（不抛 KeyError）",
      msg13b[:50])
check(not os.path.exists(bad_dir), "拒绝时不写盘（无半截会话）",
      f"exists={os.path.exists(bad_dir)}")

print("=" * 70)
print("[5] 覆盖写：二次保存先清旧帧")
ok14, _ = save_session(sess_dir, he, POSES[:1], FRAMES[:1])
check(ok14, "二次保存（1 帧）成功", "")
ok15, msg15, restored15 = load_session(sess_dir)
check(ok15 and len(restored15["frames"]) == 1
      and len(restored15["poses"]) == 1,
      "旧帧被清掉，不混入上次残留", msg15)

print("=" * 70)
print("[6] 原子写残留：frames/ 内 .tmp.ply 不被当有效帧（加载侧过滤）")
ok16, msg16 = save_session(sess_dir, he, POSES, FRAMES)
check(ok16, "重建 3 帧会话", msg16[:40])
resid = os.path.join(sess_dir, "frames", "frame_003.tmp.ply")
write_ply(resid, np.zeros((7, 3)), None)
check(os.path.basename(resid).endswith(".ply"),
      "残留文件名确实以 .ply 结尾（旧判据会命中）", os.path.basename(resid))
ok17, msg17, restored17 = load_session(sess_dir)
check(ok17 and len(restored17["frames"]) == 3
      and all(len(fr["xyz"]) == 500 for fr in restored17["frames"]),
      "残留 .tmp.ply 未被读入（帧数仍 3、无 7 点帧）",
      f"frames={len(restored17['frames']) if restored17 else 'None'} "
      f"点数={[len(fr['xyz']) for fr in restored17['frames']] if restored17 else '-'}")

shutil.rmtree(work, ignore_errors=True)
print("=" * 70)
if FAILURES:
    print(f"[FAILED] {len(FAILURES)} 项失败:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("[ALL OK] test_session")
sys.exit(0)
