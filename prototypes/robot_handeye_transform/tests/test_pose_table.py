# -*- coding: utf-8 -*-
"""
A11-② 位姿数据列表测试（test_pose_table）。

跑法（REGRESSION §0 第 4 条，conda rvc python 直跑，看退出码）：

    cd D:/RVC_SRC/Python/MultiCameraCalibration
    unset PYTHONPATH; export QT_QPA_PLATFORM=offscreen
    "D:/Program Files/Anaconda/envs/rvc/python.exe" \
        prototypes/robot_handeye_transform/tests/test_pose_table.py; echo exit=$?

覆盖：
  [1] 行号 idx 单调不回收（删行后不复用）—— 结论的唯一索引不许漂移
  [2] 录入校验与 A11-6 单位归一（m → mm；米制数值当 mm 被 A2 范数窗口拒）
  [3] 角度单位不进模型（deg/rad 是待判定量）+ 声明顺序只回显 + 非法声明拒
  [4] 判定只读数值：声明顺序故意写错 → detect() 仍必须给出真实顺序
  [5] 相机侧配对：绑定/解绑、未配对行显形、纯位姿表直接拒
  [6] CSV 导入：6/7 列收，16 列与列数错拒，非数值报行号，delta 声明拒，整体原子
  [7] update / bind_target：行号不变、非法值整行不改
  [8] to_arrays：无声明顺序 → 明确报错并提示走 detect()（不许硬猜顺序）
"""

import os
import sys
import tempfile

import numpy as np
from scipy.spatial.transform import Rotation as Rot

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "core"))

import order_detect as od  # noqa: E402
from pose_table import PoseTable, PoseTableError  # noqa: E402

FAILURES = []
TMP = tempfile.mkdtemp(prefix="mcc_posetable_")
CLOCK = lambda: "2026-09-23T16:00:00+08:00"      # noqa: E731 —— 固定时间戳保证可复现


def check(cond: bool, label: str, detail: str = ""):
    tag = "OK  " if cond else "FAIL"
    print(f"  [{tag}] {label}" + (f" | {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def p(*parts) -> str:
    return os.path.join(TMP, *parts)


def oracle(n=5, seed=7, conv="XYZ", unit="deg"):
    """合成 oracle：真值手眼 X + 真值 T_target2base，产出机器人位姿原文与相机侧观测。"""
    rng = np.random.default_rng(seed)
    X = np.eye(4)
    X[:3, :3] = Rot.random(random_state=rng).as_matrix()
    X[:3, 3] = rng.uniform(-50, 50, 3)
    Tt2b = np.eye(4)
    Tt2b[:3, :3] = Rot.random(random_state=rng).as_matrix()
    Tt2b[:3, 3] = rng.uniform(200, 500, 3)
    xyz, abc, Tgb = [], [], []
    for _ in range(n):
        r = Rot.random(random_state=rng)
        t = rng.uniform(-300, 300, 3)
        A = np.eye(4)
        A[:3, :3] = r.as_matrix()
        A[:3, 3] = t
        Tgb.append(A)
        xyz.append(t)
        abc.append(r.as_euler(conv, degrees=(unit == "deg")))
    Ttc = [X @ np.linalg.inv(A) @ Tt2b for A in Tgb]
    return np.array(xyz), np.array(abc), Ttc


def fill(table, n=5, **kw):
    xyz, abc, Ttc = oracle(n, **kw)
    for i in range(n):
        ok, msg, idx = table.add(xyz[i], abc[i], unit="mm",
                                 T_target2cam=Ttc[i])
        assert ok, msg
    return xyz, abc, Ttc


print("=" * 78)
print("[1] 行号 idx 单调不回收（结论的唯一索引）")
t = PoseTable(now_fn=CLOCK)
xyz, abc, Ttc = oracle(3)
idxs = []
for i in range(3):
    ok, msg, idx = t.add(xyz[i], abc[i], unit="mm")
    idxs.append(idx)
check(idxs == [1, 2, 3], "add 依次给行号 1/2/3", f"{idxs}")
ok, msg = t.remove(2)
check(ok and t.get(2) is None and t.index_list() == [1, 3],
      "删除第 2 行后行号列表为 [1,3]", f"{t.index_list()}")
ok, msg, idx = t.add(xyz[0], abc[0], unit="mm")
check(idx == 4, "删行后新行拿 4（不复用 2）", f"{idx}")
ok, msg = t.clear()
check(ok and len(t) == 0, "clear 清空", msg)
ok, msg, idx = t.add(xyz[0], abc[0], unit="mm")
check(idx == 5, "clear 后行号继续（不复用）", f"{idx} | {msg}")

print("=" * 78)
print("[2] 录入校验 + A11-6 单位归一")
t = PoseTable(now_fn=CLOCK)
ok, msg, idx = t.add([0.4, 0.1, 0.2], [0, 0, 0], unit="m")
check(ok and np.allclose(t.get(idx).xyz_mm, [400.0, 100.0, 200.0]),
      "unit=m 的 0.4/0.1/0.2 → mm 域 400/100/200", msg)
ok, msg, idx = t.add([0.4, 0.1, 0.2], [0, 0, 0], unit="mm")
check((not ok) and idx is None and ("范数" in msg or "窗口" in msg or "超出" in msg),
      "米制数值当 mm 被 A2 范数窗口拒（静默错 1000× 的老坑）", msg)
ok, msg, idx = t.add([100, 200, 300], [1, 2], unit="mm")
check((not ok) and "3 个数" in msg, "角度只有 2 个数 → 拒", msg)
ok, msg, idx = t.add([100, 200, 300], [1, float("nan"), 3], unit="mm")
check((not ok) and "非有限值" in msg, "角度含 NaN → 拒", msg)
ok, msg, idx = t.add([100, 200, 300], [1, 2, 3], unit="inch")
check((not ok) and "单位" in msg, "单位非 mm/m → 拒", msg)

print("=" * 78)
print("[3] 角度单位不进模型 + 声明顺序只回显")
t = PoseTable(now_fn=CLOCK)
ok, msg, idx = t.add([100, 200, 300], [0.5, 0.2, 0.3], unit="mm")
check(ok and t.get(idx).abc_raw == (0.5, 0.2, 0.3),
      "原始角度按原样存（不做 deg/rad 单位假设）", f"{t.get(idx).abc_raw}")
check(ok and t.get(idx).T_base2tool_mm is None,
      "未声明顺序 → T_base2tool_mm 为 None（顺序未知时 T 根本不存在）")
ok, msg, idx = t.add([100, 200, 300], [1, 2, 3], unit="mm",
                     order_declared="ZYX")
check(ok and t.get(idx).declared_order() == "ZYX"
      and t.get(idx).T_base2tool_mm is not None,
      "声明顺序合法 → 存 raw 且可构造 T_base2tool（仅回显用）", msg)
ok, msg, idx = t.add([100, 200, 300], [1, 2, 3], unit="mm",
                     order_declared="XYZ_RPY")
check((not ok) and "不在候选集" in msg, "声明顺序不在候选集 → 拒", msg)

print("=" * 78)
print("[4] 判定只读数值：声明顺序故意写错，detect() 仍须给出真实顺序")
t = PoseTable(now_fn=CLOCK)
xyz, abc, Ttc = oracle(6, seed=19, conv="XYZ")
for i in range(6):
    ok, msg, idx = t.add(xyz[i], abc[i], unit="mm", T_target2cam=Ttc[i],
                         order_declared="ZYX")        # ← 故意全写错
    assert ok, msg
res = t.detect(n_starts=1, leave_one_out=False)
check(res["verdict"] == "OK" and res["order"] == "XYZ"
      and res["angle_unit"] == "deg",
      "6 行声明 ZYX（真值 XYZ）→ 判定仍给 XYZ/deg（声明不参与判定）",
      f"verdict={res['verdict']} order={res['order']}")
check(len(res["ranking"]) == len(od.CANDIDATE_BRANCHES)
      and res["row_idx"] == [1, 2, 3, 4, 5, 6],
      "结论带全部候选排名 + 指回行号 1~6", f"候选 {len(res['ranking'])} 行号 {res['row_idx']}")

print("=" * 78)
print("[5] 相机侧配对显形 / 纯位姿表直接拒")
t = PoseTable(now_fn=CLOCK)
xyz, abc, Ttc = oracle(4, seed=23)
for i in range(3):
    t.add(xyz[i], abc[i], unit="mm", T_target2cam=Ttc[i])
t.add(xyz[3], abc[3], unit="mm")           # 第 4 行不配对
d = t.detect_inputs()
check(d["n_paired"] == 3 and d["unpaired_idx"] == [4],
      "配对 3 行、未配对行显形（行号 [4]）", f"{d['n_paired']} / {d['unpaired_idx']}")
rep = t.excitation_report()
check(rep["ok"] is False and any("缺相机侧配对" in s for s in rep["reasons"]),
      "激励报告把未配对行算作不可判定原因", f"{rep['reasons']}")
res = t.detect(n_starts=1, leave_one_out=False)
check(res["dropped_idx"] == [4] and res["n_records"] == 3,
      "detect() 用配对行并把剔除行写进报告（R22 不许悄悄挑）",
      f"dropped={res['dropped_idx']}")
ok, msg = t.bind_target(4, Ttc[3])
check(ok and t.detect_inputs()["n_paired"] == 4, "bind_target 补绑定", msg)
ok, msg = t.bind_target(4, None)
check(ok and t.detect_inputs()["unpaired_idx"] == [4], "解绑", msg)

t2 = PoseTable(now_fn=CLOCK)
for i in range(4):
    t2.add(xyz[i], abc[i], unit="mm")      # 全不配对 = 纯位姿表
res = t2.detect(n_starts=1, leave_one_out=False)
check(res["verdict"] == "INVALID"
      and any("纯位姿表" in s for s in res["notes"])
      and res["order"] is None,
      "纯位姿表（无相机侧）→ 直接拒绝、不给答案", f"{res['verdict']} | {res['notes']}")
check(res["dropped_idx"] == [1, 2, 3, 4],
      "拒绝时仍带全部行号（谁没配对要看得见）", f"{res['dropped_idx']}")

print("=" * 78)
print("[6] CSV 导入")
t = PoseTable(now_fn=CLOCK)
csv6 = p("ok6.csv")
with open(csv6, "w", encoding="utf-8") as f:
    f.write("# pose_type: absolute\n")
    f.write("x y z a b c\n")
    for i in range(4):
        f.write(f"{xyz[i][0]},{xyz[i][1]},{xyz[i][2]},"
                f"{abc[i][0]},{abc[i][1]},{abc[i][2]}\n")
ok, msg = t.import_csv(csv6, unit="mm")
check(ok and t.count() == 4, "6 列 CSV 导入 4 行", msg)
check("表头" in msg, "表头行被跳过且报数（不静默）", msg)
check(t.get(1).abc_raw == tuple(float(v) for v in abc[0]),
      "导入行的角度原文正确", f"{t.get(1).abc_raw}")
csv7 = p("ok7.csv")
with open(csv7, "w", encoding="utf-8") as f:
    for i in range(2):
        f.write(f"{xyz[i][0]} {xyz[i][1]} {xyz[i][2]} "
                f"{abc[i][0]} {abc[i][1]} {abc[i][2]} XYZ\n")     # 空白分隔 + 声明列
t3 = PoseTable(now_fn=CLOCK)
ok, msg = t3.import_csv(csv7, unit="mm")
check(ok and t3.count() == 2 and t3.get(1).declared_order() == "XYZ",
      "7 列（空白分隔 + 声明顺序）导入", msg)

bad16 = p("bad16.csv")
with open(bad16, "w", encoding="utf-8") as f:
    f.write(" ".join(str(v) for v in np.eye(4).reshape(-1)) + "\n")
t4 = PoseTable(now_fn=CLOCK)
ok, msg = t4.import_csv(bad16, unit="mm")
check((not ok) and "16 列" in msg and t4.count() == 0,
      "16 列矩阵行拒收（不含欧拉原文）+ 一行不留", msg)
badnum = p("badnum.csv")
with open(badnum, "w", encoding="utf-8") as f:
    f.write("1 2 3 0 0 0\n4 5 6 0 x 0\n")
t5 = PoseTable(now_fn=CLOCK)
ok, msg = t5.import_csv(badnum, unit="mm")
check((not ok) and "第 2 行" in msg and t5.count() == 0,
      "非数值报行号且整体原子（导入 0 行）", msg)
baddelta = p("baddelta.csv")
with open(baddelta, "w", encoding="utf-8") as f:
    f.write("# pose_type: delta\n1 2 3 0 0 0\n")
t6 = PoseTable(now_fn=CLOCK)
ok, msg = t6.import_csv(baddelta, unit="mm")
check((not ok) and "delta" in msg, "delta 声明拒（R11 fail-closed）", msg)
csv_m = p("meter.csv")
with open(csv_m, "w", encoding="utf-8") as f:
    f.write("0.4 0.1 0.2 0 0 0\n")
t7 = PoseTable(now_fn=CLOCK)
ok, msg = t7.import_csv(csv_m, unit="m")
check(ok and np.allclose(t7.get(1).xyz_mm, [400, 100, 200]),
      "CSV 单位 m → mm 归一", msg)

print("=" * 78)
print("[7] update / bind_target：行号不变、非法值整行不改")
t = PoseTable(now_fn=CLOCK)
fill(t, n=3)
before = t.get(2).xyz_raw
ok, msg = t.update(2, xyz=[123.0, 456.0, 789.0])
check(ok and t.get(2).xyz_raw == (123.0, 456.0, 789.0) and t.index_list() == [1, 2, 3],
      "update 生效且行号不变", msg)
ok, msg = t.update(2, xyz=[0.001, 0.001, 0.001])
check((not ok) and t.get(2).xyz_raw == (123.0, 456.0, 789.0),
      "非法 update → 整行不改（保留原值）", msg)
ok, msg = t.update(99, xyz=[1, 2, 3])
check((not ok) and "不存在" in msg, "行号不存在 → 报错", msg)
ok, msg = t.update(2, abc=[1, 2, 3], order_declared="XYZ")
check(ok and t.get(2).declared_order() == "XYZ", "update 可带声明顺序", msg)
ok, msg = t.bind_target(2, np.eye(4) * 2.0)
check(not ok, "非刚性相机侧位姿 → 拒", msg)

print("=" * 78)
print("[8] to_arrays：无声明顺序必须明确报错")
t = PoseTable(now_fn=CLOCK)
fill(t, n=3)
try:
    t.to_arrays()
    ok = False
    err = ""
except PoseTableError as e:
    ok, err = True, str(e)
check(ok and "未声明欧拉顺序" in err and "detect()" in err,
      "无声明顺序 → 报错并指向 detect()（禁硬猜顺序）", err)
ok, msg, idx = t.add([100, 200, 300], [1, 2, 3], unit="mm", order_declared="XYZ")
gb, tc = t.to_arrays(order="XYZ")
check(len(gb) == t.count() and all(np.asarray(m).shape == (4, 4) for m in gb),
      "显式 order → 返回 4×4 序列", f"n={len(gb)}")

print("=" * 78)
if FAILURES:
    print(f"[FAIL] test_pose_table：{len(FAILURES)} 项失败 -> {FAILURES}")
    sys.exit(1)
print("[ALL OK] test_pose_table")
