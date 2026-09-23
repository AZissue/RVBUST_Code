# -*- coding: utf-8 -*-
"""
A10 手眼矩阵落文件测试（test_handeye_file）。

跑法（REGRESSION §0 第 4 条，conda rvc python 直跑，看退出码）：

    cd D:/RVC_SRC/Python/MultiCameraCalibration
    unset PYTHONPATH; export QT_QPA_PLATFORM=offscreen
    "D:/Program Files/Anaconda/envs/rvc/python.exe" \
        prototypes/robot_handeye_transform/tests/test_handeye_file.py; echo exit=$?

覆盖：
  [1] A10-1 写→读→逐元素比对（16 元素）：max|Δ| < 1e-12，mm 域实测应为 0.0
  [2] A10-2 必填字段：逐个删除必填字段 / euler 子字段 → 拒且报字段名；
      version≠1、created_at 无时区、source 空、eye_in_hand 非 bool → 拒
  [3] A10-3 单位单一真相源：文件有 unit 以文件为准 / unit 冲突必拒 /
      旧 JSON 无 unit 时 unit_override 必填
  [4] A10-4 负向四类（缺 unit / 单位冲突 / eye_in_hand 与矩阵键不一致 / 非刚性）
      + 单实现证明（改 unit_guard.ORTH_TOL 必须同时放行两侧 = 无第二份校验）
  [5] A10-5 并存不回归：旧 MCC JSON 经新入口与 HandEyeResult.load 逐元素一致；
      test_handeye_result.py 子进程 exit=0
  [6] 留痕语义：文件里的 validated 不被信任（读回恒 False）；euler /
      pose_order_detect 块往返保留；非刚性矩阵拒绝落盘且不留半截文件
"""

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "core"))

import numpy as np

import handeye_file as hf
import unit_guard
from handeye_file import read_matrix_file, roundtrip_check, write_matrix_file
from handeye_result import HandEyeResult

FAILURES = []
TMP = tempfile.mkdtemp(prefix="mcc_hefile_")
TEXT = "abc"


def check(cond: bool, label: str, detail: str = ""):
    tag = "OK  " if cond else "FAIL"
    print(f"  [{tag}] {label}" + (f" | {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def p(*parts) -> str:
    return os.path.join(TMP, *parts)


def write_json(path: str, data: dict) -> str:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def rot_zyx(rz_deg: float, ry_deg: float, rx_deg: float) -> np.ndarray:
    """Rz·Ry·Rx（内旋 ZYX）—— 不用 scipy，保持本模块测试只依赖 numpy。"""
    cz, sz = math.cos(math.radians(rz_deg)), math.sin(math.radians(rz_deg))
    cy, sy = math.cos(math.radians(ry_deg)), math.sin(math.radians(ry_deg))
    cx, sx = math.cos(math.radians(rx_deg)), math.sin(math.radians(rx_deg))
    Rz = np.array([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]])
    Ry = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
    Rx = np.array([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]])
    return Rz @ Ry @ Rx


def make_T(t=(120.5, -33.25, 88.125)) -> np.ndarray:
    """一般位姿（‖t‖≈153 mm，落在眼在手上窗口 [5,2000] 内），带非平凡旋转。"""
    T = np.eye(4)
    T[:3, :3] = rot_zyx(30.0, -10.0, 5.0)
    T[:3, 3] = list(t)
    return T


T0 = make_T()
EULER_OK = {"order": "ZYX", "intrinsic": True,
            "output_format": "xyz Rx Ry Rz", "angle_unit": "deg"}


def legacy_json(eye_in_hand=True, T=None, **extra) -> dict:
    """模拟 src/core/handeye.py 的输出（无 format / 无 unit 字段）。"""
    T = np.asarray(T if T is not None else T0, dtype=np.float64)
    d = {"success": True, "eye_in_hand": eye_in_hand, "method": 0,
         "n_samples": 9, "rms_t_mm": 0.12, "rms_r_deg": 0.05}
    if eye_in_hand:
        d["T_cam2tool"] = T.tolist()
        d["T_tool2cam"] = np.linalg.inv(T).tolist()
    else:
        d["T_cam2base"] = T.tolist()
        d["T_base2cam"] = np.linalg.inv(T).tolist()
    d.update(extra)
    return d


def main():
    print("=" * 74)
    print(f"[0] 环境：numpy {np.__version__} / handeye_file {hf.FORMAT_NAME} v{hf.FORMAT_VERSION}"
          f" / tmp={TMP}")

    # ==================================================================
    print("=" * 74)
    print("[1] A10-1 写→读→逐元素比对（16 元素，门槛 1e-12）")
    f_mm = p("m1_mm.json")
    ok, msg = write_matrix_file(f_mm, T0, eye_in_hand=True, unit="mm",
                                source=hf.SOURCE_TOOL, rms=(0.12, 0.05),
                                n_samples=9, euler=EULER_OK,
                                created_at="2026-09-23T15:40:00+08:00")
    check(ok, "mm 域落盘", msg)
    print(f"       sha256(程序打印，供复核) = {msg.split('sha256=')[-1]}")
    ok, msg, res = read_matrix_file(f_mm)
    d16 = (float(np.max(np.abs(res.T_handeye_mm - T0))) if ok else float("nan"))
    print(f"       写→读逐元素 max|Δ| = {d16:.3e}（mm 域）")
    check(ok and np.array_equal(res.T_handeye_mm, T0) and d16 < hf.RT_TOL,
          "mm 域写→读 16 元素逐元素一致", f"max|Δ|={d16:.3e}")

    f_m = p("m1_m.json")
    ok, msg = write_matrix_file(f_m, T0, eye_in_hand=True, unit="m",
                                source="manual", euler=EULER_OK,
                                created_at="2026-09-23T15:40:00+08:00")
    check(ok, "m 域落盘", msg)
    raw_m = np.asarray(read_json(f_m)["matrix"]).reshape(4, 4)
    print(f"       文件里的米制平移列 = {raw_m[:3, 3].tolist()}")
    ok, msg, res = read_matrix_file(f_m)
    dm = (float(np.max(np.abs(res.T_handeye_mm - T0))) if ok else float("nan"))
    print(f"       m 域写→读逐元素 max|Δ| = {dm:.3e}")
    check(ok and dm < hf.RT_TOL, "m 域写→读（毫米域比对）一致", f"max|Δ|={dm:.3e}")
    okr, msgr, maxd = roundtrip_check(f_m)
    check(okr and maxd < hf.RT_TOL, "roundtrip_check（米制文件：原值 vs 读回）", msgr)
    okr2, msgr2, maxd2 = roundtrip_check(f_mm)
    check(okr2 and maxd2 == 0.0, "roundtrip_check（mm 域：应为 0.0）", msgr2)

    # 非刚性不得落盘（fail-closed：校验不过不留半截文件）
    bad_T = T0.copy()
    bad_T[:3, :3] = np.array([[1.0, 0.5, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])  # det=+1 shear
    f_bad = p("m1_bad.json")
    ok, msg = write_matrix_file(f_bad, bad_T, eye_in_hand=True, unit="mm",
                                source="manual", euler=EULER_OK)
    check(not ok and not os.path.exists(f_bad), "非刚性矩阵（shear）拒绝落盘且不留文件", msg)

    # ==================================================================
    print("=" * 74)
    print("[2] A10-2 必填字段（缺一即拒，不许补默认值）")
    good = read_json(f_mm)
    for field in hf.REQUIRED_FIELDS:
        d = read_json(f_mm)
        del d[field]
        path = write_json(p(f"m2_miss_{field}.json"), d)
        ok, msg, res = read_matrix_file(path)
        check(not ok and res is None and field in msg, f"缺 {field} → 拒", msg[:96])
    for field in hf.REQUIRED_EULER_FIELDS:
        d = read_json(f_mm)
        del d["euler"][field]
        path = write_json(p(f"m2_miss_euler_{field}.json"), d)
        ok, msg, res = read_matrix_file(path)
        check(not ok and field in msg, f"euler 缺 {field} → 拒", msg[:96])

    d = read_json(f_mm); d["version"] = 2
    ok, msg, _ = read_matrix_file(write_json(p("m2_ver.json"), d))
    check(not ok, "version=2 → 拒（不猜字段语义）", msg[:96])
    d = read_json(f_mm); d["created_at"] = "2026-09-23T15:40:00"
    ok, msg, _ = read_matrix_file(write_json(p("m2_tz.json"), d))
    check(not ok and "时区" in msg, "created_at 无时区 → 拒", msg[:96])
    d = read_json(f_mm); d["created_at"] = "昨天"
    ok, msg, _ = read_matrix_file(write_json(p("m2_tz2.json"), d))
    check(not ok, "created_at 非 ISO8601 → 拒", msg[:96])
    d = read_json(f_mm); d["source"] = "   "
    ok, msg, _ = read_matrix_file(write_json(p("m2_src.json"), d))
    check(not ok, "source 空白 → 拒", msg[:96])
    d = read_json(f_mm); d["eye_in_hand"] = "true"
    ok, msg, _ = read_matrix_file(write_json(p("m2_eih.json"), d))
    check(not ok and "true/false" in msg, "eye_in_hand 写字符串 'true' → 拒（K6 反装风险）", msg[:96])
    d = read_json(f_mm); d["matrix"] = d["matrix"][:15]
    ok, msg, _ = read_matrix_file(write_json(p("m2_m15.json"), d))
    check(not ok and "16" in msg, "matrix 只有 15 个数 → 拒", msg[:96])
    d = read_json(f_mm); d["euler"]["output_format"] = "rpy(deg)"
    ok, msg, _ = read_matrix_file(write_json(p("m2_fmt.json"), d))
    check(not ok and "唯一口径" in msg, "euler.output_format 换成别的口径 → 拒（U5 唯一口径）", msg[:96])
    d = read_json(f_mm); d["format"] = "other_tool_v9"
    ok, msg, _ = read_matrix_file(write_json(p("m2_fmt2.json"), d))
    check(not ok and "不是 v1 矩阵文件" in msg, "format 非本工具 → 走旧格式分支并拒（带说明）", msg[:96])
    d = read_json(f_mm); d["pose_order_detect"] = [1, 2, 3]
    ok, msg, _ = read_matrix_file(write_json(p("m2_pod.json"), d))
    check(not ok, "pose_order_detect 非字典 → 拒", msg[:96])

    # ==================================================================
    print("=" * 74)
    print("[3] A10-3 单位单一真相源")
    d = read_json(f_m)
    check(d["unit"] == "m", "前置：米制文件 unit='m'")
    ok, msg, res = read_matrix_file(f_m)              # 不给 override → 以文件为准
    check(ok and abs(res.T_handeye_mm[0, 3] - 120.5) < 1e-9,
          "文件 unit=m，不给 override → 以文件为准读到毫米真值", msg[:96])
    ok, msg, res = read_matrix_file(f_m, unit_override="m")
    check(ok, "override 与文件一致 → 放行", msg[:96])
    ok, msg, res = read_matrix_file(f_m, unit_override="mm")
    check(not ok and "冲突" in msg and res is None,
          "文件 unit=m + 界面 mm → 拒（禁止静默取其一）", msg[:110])
    ok, msg, res = read_matrix_file(f_m, unit_override="auto")
    check(not ok and res is None, "override='auto' → 拒（无 auto，D4）", msg[:96])

    f_legacy = write_json(p("m3_legacy.json"), legacy_json(True))
    ok, msg, res = read_matrix_file(f_legacy)
    check(not ok and "无 unit 字段" in msg and res is None,
          "旧 JSON（无 unit）不给 override → 拒（单位仍必选）", msg[:110])
    ok, msg, res = read_matrix_file(f_legacy, unit_override="mm")
    check(ok and np.allclose(res.T_handeye_mm, T0), "旧 JSON + override=mm → 正常加载", msg[:96])

    # ==================================================================
    print("=" * 74)
    print("[4] A10-4 负向四类 + 单实现证明")
    d = read_json(f_mm); del d["unit"]
    ok, msg, _ = read_matrix_file(write_json(p("m4_nounit.json"), d))
    check(not ok and "unit" in msg, "缺 unit → 拒", msg[:96])

    d = read_json(f_mm); d["eye_in_hand"] = True
    d["T_cam2base"] = np.eye(4).tolist()          # 并存反装分支键
    ok, msg, _ = read_matrix_file(write_json(p("m4_key.json"), d))
    check(not ok and "矩阵键不一致" in msg,
          "eye_in_hand=true 却并存 'T_cam2base' → 拒", msg[:110])

    d = read_json(f_mm); d["eye_in_hand"] = True
    d["T_cam2tool"] = T0.copy().tolist()
    d["T_cam2tool"][0][3] += 1.0                  # 与 matrix 不一致
    ok, msg, _ = read_matrix_file(write_json(p("m4_key2.json"), d))
    check(not ok and "不一致" in msg, "旧键 'T_cam2tool' 与 'matrix' 不一致 → 拒", msg[:110])
    d = read_json(f_mm); d["eye_in_hand"] = True; d["T_cam2tool"] = T0.tolist()
    ok, msg, _ = read_matrix_file(write_json(p("m4_key3.json"), d))
    check(ok, "旧键与 matrix 自洽 → 放行（并存不误伤）", msg[:96])

    for label, mut in (
            ("det=-1 镜像", lambda T: _set_mirror(T)),
            ("det=+1 shear 非正交", lambda T: _set_shear(T)),
            ("末行非 [0,0,0,1]", lambda T: T.__setitem__(3, [0.0, 0.0, 1.0, 1.0])),
            ("含 NaN", lambda T: T.__setitem__((0, 3), np.nan))):
        Tb = T0.copy(); mut(Tb)
        d = read_json(f_mm); d["matrix"] = Tb.tolist()
        ok, msg, _ = read_matrix_file(write_json(p("m4_rigid.json"), d))
        check(not ok, f"非刚性：{label} → 拒", msg[:96])

    # 单实现证明（RG-04 手法）：关掉 unit_guard 的正交容差，两侧必须同时放行
    f_shear = write_json(p("m4_shear.json"),
                         {**read_json(f_mm),
                          "matrix": _set_shear(T0.copy()).tolist()})
    old_tol = unit_guard.ORTH_TOL
    try:
        ok_before, msg_before, _ = read_matrix_file(f_shear)
        ok_hr, _, _ = HandEyeResult.load(f_legacy, "mm")      # 对照组：合法文件正常放行
        unit_guard.ORTH_TOL = 1e9
        ok_after, _, _ = read_matrix_file(f_shear)
        hr_after = HandEyeResult.from_matrix(_set_shear(T0.copy()), "mm", True)[0]
    finally:
        unit_guard.ORTH_TOL = old_tol
    print(f"       容差正常：read_matrix_file(shear)={ok_before}（合法旧文件 HandEyeResult.load="
          f"{ok_hr}）／容差置 1e9：read_matrix_file={ok_after}, "
          f"HandEyeResult.from_matrix={hr_after}")
    check((not ok_before) and ok_after and hr_after and ok_hr,
          "单实现：改 unit_guard.ORTH_TOL 两侧同时放行（无第二份校验）")

    # ==================================================================
    print("=" * 74)
    print("[5] A10-5 与既有加载器并存不回归")
    ok_new, msg_new, res_new = read_matrix_file(f_legacy, unit_override="mm")
    ok_old, msg_old, res_old = HandEyeResult.load(f_legacy, "mm")
    same = (ok_new and ok_old
            and np.array_equal(res_new.T_handeye_mm, res_old.T_handeye_mm)
            and res_new.eye_in_hand == res_old.eye_in_hand)
    dlt = (float(np.max(np.abs(res_new.T_handeye_mm - res_old.T_handeye_mm)))
           if (ok_new and ok_old) else float("nan"))
    check(same, "旧 MCC JSON：新入口与 HandEyeResult.load 逐元素一致", f"max|Δ|={dlt:.3e}")
    ok, msg, res = read_matrix_file(f_legacy, unit_override="mm", eye_in_hand=False)
    check(not ok, "旧 JSON：eye_in_hand 与文件不一致 → 拒（键分支防错）", msg[:96])
    t_old = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "test_handeye_result.py")],
        capture_output=True, text=True)
    last = [ln for ln in t_old.stdout.strip().splitlines() if ln.strip()][-1:]
    print(f"       test_handeye_result.py 子进程 exit={t_old.returncode}，末行 = {last}")
    check(t_old.returncode == 0, "test_handeye_result.py 子进程 exit=0（不回归）")

    # ==================================================================
    print("=" * 74)
    print("[6] 留痕语义：validated 不信文件声明 / euler 与 pose_order_detect 往返")
    pod = {"detected": "ZYX", "external": False, "n_candidates": 12,
           "residuals": [{"order": "ZYX", "rms": 0.0}, {"order": "XYZ", "rms": 103.5}]}
    f6 = p("m6.json")
    ok, msg = write_matrix_file(f6, T0, eye_in_hand=True, unit="mm", source="manual",
                                rms=(0.12, 0.05), n_samples=9, euler=EULER_OK,
                                order_detect=pod, validated=True,
                                created_at="2026-09-23T15:40:00+08:00")
    check(ok, "带 euler/pose_order_detect 落盘", msg[:130])
    ok, msg, res = read_matrix_file(f6)
    check(ok and res.euler["order"] == "ZYX" and res.euler["intrinsic"] is True,
          "euler 块往返保留（order/intrinsic）", str(res.euler))
    check(ok and res.pose_order_detect == pod,
          "pose_order_detect 块往返保留（A11 结论与矩阵同一份落盘）")
    check(ok and res.validated is False and res.file_meta["validated_claim"] is True,
          "文件声明 validated=true → 读回仍 UNVERIFIED（A3 fail-closed）")
    check(ok and res.rms_t_mm == 0.12 and res.n_samples == 9 and res.source.endswith("m6.json"),
          "rms/n_samples 保留，source 指向文件路径")
    f7 = p("m6_manual.json")
    ok, msg = write_matrix_file(f7, T0, eye_in_hand=True, unit="mm", source="manual")
    d = read_json(f7)
    check(ok and d["rms_t_mm"] == 0.0 and d["n_samples"] == 0
          and d["euler"]["order"] is None and d["euler"]["intrinsic"] is None,
          "无 rms/n_samples/order 时写 0.0 / null（UI 必须标注'未知'，不许装成完美标定）")
    ok, msg = write_matrix_file(p("m6_e2.json"), T0, eye_in_hand=True, unit="mm",
                                source="manual",
                                euler={"order": "ZYX", "intrinsic": "yes",
                                       "output_format": hf.EULER_OUTPUT_FORMAT,
                                       "angle_unit": hf.EULER_ANGLE_UNIT})
    check(not ok, "euler.intrinsic 非 bool → 写入即拒", msg[:96])
    ok, msg = write_matrix_file(p("m6_e3.json"), T0, eye_in_hand=1, unit="mm",
                                source="manual")
    check(not ok, "eye_in_hand 传 1（非 bool）→ 写入即拒", msg[:96])
    ok, msg = write_matrix_file(p("m6_e4.json"), T0, eye_in_hand=True, unit=None,
                                source="manual")
    check(not ok, "unit=None → 写入即拒（无 auto，D4）", msg[:96])
    ok, msg = write_matrix_file(p("m6_e5.json"), T0, eye_in_hand=True, unit="mm",
                                source="")
    check(not ok, "source 空 → 写入即拒", msg[:96])

    shutil.rmtree(TMP, ignore_errors=True)
    print("=" * 74)
    if FAILURES:
        print(f"[FAILED] {len(FAILURES)} 项失败:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("[ALL OK] test_handeye_file")
    sys.exit(0)


def _set_mirror(T: np.ndarray) -> np.ndarray:
    """整块镜像：正交但 det=-1 → 必须由 det 分支单独抓住（不是靠正交分支）。"""
    T[:3, :3] = np.diag([-1.0, 1.0, 1.0])
    return T


def _set_shear(T: np.ndarray) -> np.ndarray:
    T[:3, :3] = np.array([[1.0, 0.5, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    return T


if __name__ == "__main__":
    main()
