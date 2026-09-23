# -*- coding: utf-8 -*-
"""
矩阵文件读写（handeye_file）—— A10：手眼矩阵落成文件，不再靠"复制粘贴矩阵"传递。

格式 v1（补充方案 §1 A10-2，缺任一必填字段即拒，**不许补默认值**）：

    format        "rvc_handeye_matrix"
    version       1
    created_at    ISO8601 **带时区**（无时区的本地时间跨机不可复现 → 拒）
    source        产出工具名+版本，或 "manual"
    eye_in_hand   JSON true/false（**必须 bool**，字符串/数字一律拒）
    unit          "mm" | "m"
    matrix        16 个数，**行优先**（与官方 MAT 口径一致）
    rms_t_mm / rms_r_deg / n_samples  数值，或 **null**（= 未知，见下）
    euler         {order, intrinsic, output_format, angle_unit}
    可选：pose_order_detect（A11 顺序判定结论，与矩阵同一份落盘）
    可选：verification（A3 门禁留痕，写侧一律写出；缺失按 UNVERIFIED 处理）
    可选：validated（布尔冗余，与 verification 必须自洽，矛盾即拒）

规则（实现口径，均有对应验收条款）：

  - **内部统一毫米**（`unit_guard` 口径）：`unit` 只决定文件里的数值域，写出
    时 `to_unit`、读入时 `to_mm`；两侧共用 `unit_guard`，本模块不做第二份换算。
  - **单位单一真相源（A10-3）**：文件有 `unit` → 以文件为准；`unit_override`
    与之冲突 → 拒绝并提示（禁止静默取其一）。文件无 `unit`（= MCC 旧 JSON）→
    `unit_override` 必填，否则拒绝。
  - **校验全部委托既有单实现**：刚性走 `handeye_result.validate_matrix`
    （内含 `unit_guard.check_rigid_4x4`），单位归一 + 范数窗口走
    `HandEyeResult.from_matrix` —— 本模块不新增任何几何校验（方案 §4.2 禁第二份实现）。
  - **全精度落盘**：JSON 的 float 由 Python `repr` 序列化（不做 %.6f 之类的舍入），
    因此"写→读→逐元素比对"的 max|Δ| 实测为 **0.0**（A10-1，门槛 1e-12）。
  - **`null` = 未知，不是 0**（@lead v2 §10.4-②）：手动录入来源没有 rms/n_samples，
    写 `null`（写 0.0 会被读成"完美标定"）；读回时置 `res.rms_unknown = True`，
    UI 必须显示"未知"。数值字段只接受 JSON number（`"0.1"` 字符串、`true`
    一律拒 —— 强转会掩盖格式错误）。
  - **`validated` 不信文件声明**：读回后恒为 False（A3 fail-closed）；文件里的
    `validated` / `verification` 只作留痕，供人手看，不构成"已验证"。
  - **v1 文件里并存旧 MCC 键**（`T_cam2tool` / `T_cam2base`）时必须自洽：与本文件
    `eye_in_hand` 不匹配的键、或数值与 `matrix` 不一致的键 → 拒绝（两个来源不允许并存）。
  - **近似键名要拦**（@verify 复核备注②）：把 `pose_order_detect` 拼成 `order_detect`
    会被"未知字段"规则静默吞掉 → 与已知键名近似的未知键直接拒（`difflib` 相似度
    ≥ 0.7），提示正确键名；完全无关的未知键仍容忍（前向兼容）。
  - **原子写**：先写同目录 `a.tmp.json` 再 `os.replace`（照 `src/core/utils.py:56` 配方），
    避免半写文件被下游当成有效矩阵读走。

本模块为纯 numpy/json 实现，不依赖 `src/`，便于离线单测。
"""

from __future__ import annotations

import datetime
import difflib
import hashlib
import json
import os
from typing import Optional

import numpy as np

try:
    from .handeye_result import HandEyeResult, validate_matrix
    from .unit_guard import UNITS, normalize_unit, to_unit
except ImportError:  # 测试以顶层模块方式引入时
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from handeye_result import HandEyeResult, validate_matrix
    from unit_guard import UNITS, normalize_unit, to_unit

FORMAT_NAME = "rvc_handeye_matrix"
FORMAT_VERSION = 1

#: 产出工具标识（写进文件的 source 字段；"manual" 表示人工粘贴）
SOURCE_TOOL = "robot_handeye_transform (MultiCameraCalibration prototype)"

#: U5 / A11-④ 输出口径：本文件只承认这一份，出现别的值即拒（防口径漂移）
EULER_OUTPUT_FORMAT = "xyz Rx Ry Rz"
EULER_ANGLE_UNIT = "deg"

REQUIRED_FIELDS = ("format", "version", "created_at", "source", "eye_in_hand",
                   "unit", "matrix", "rms_t_mm", "rms_r_deg", "n_samples",
                   "euler")
REQUIRED_EULER_FIELDS = ("order", "intrinsic", "output_format", "angle_unit")

#: 旧 MCC JSON 的正/反变换键（K6）；v1 文件里若并存，必须与 eye_in_hand 自洽
LEGACY_KEY = {True: "T_cam2tool", False: "T_cam2base"}
LEGACY_KEY_OPPOSITE = {True: "T_cam2base", False: "T_cam2tool"}

#: v1 已知键（含可选块）；不在表内且与表内键名**近似**的键 → 拒（见 _check_near_miss_keys）
KNOWN_KEYS = (set(REQUIRED_FIELDS) | {"validated", "pose_order_detect", "verification"}
              | set(LEGACY_KEY.values()) | set(LEGACY_KEY_OPPOSITE.values()))
NEAR_MISS_CUTOFF = 0.7      # difflib 相似度门槛

#: verification.state 允许值（写侧一律写出；读侧缺失按 UNVERIFIED 处理）
VERIFICATION_STATES = ("VERIFIED", "UNVERIFIED", "FAILED")

RT_TOL = 1e-12  #: 写→读→逐元素比对门槛（A10-1）


# ----------------------------------------------------------------------
# 小工具
# ----------------------------------------------------------------------
def _atomic_tmp_path(path: str) -> str:
    """原子写临时路径：`a.json` → `a.tmp.json`（保留原扩展名，照 src/core/utils.py:56）。"""
    base, ext = os.path.splitext(path)
    return f"{base}.tmp{ext}"


def _sha256(path: str) -> str:
    """文件 sha256（RG-08：供复核用的值一律程序打印，不靠人工转录）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now_iso() -> str:
    """当前本地时间 ISO8601（**带时区偏移**）。"""
    return datetime.datetime.now().astimezone().isoformat()


def _check_created_at(value) -> tuple[bool, str]:
    """created_at 必须是可解析且**带时区**的 ISO8601 字符串。"""
    if not isinstance(value, str) or not value.strip():
        return False, "created_at 必须是非空 ISO8601 字符串"
    try:
        dt = datetime.datetime.fromisoformat(value)
    except ValueError as e:
        return False, f"created_at 不是合法 ISO8601（{value!r}）：{e}"
    if dt.tzinfo is None:
        return False, (f"created_at 缺时区偏移（{value!r}）："
                       f"无时区的本地时间跨机不可复现，拒绝加载")
    return True, value


def _check_euler(euler) -> tuple[bool, str, Optional[dict]]:
    """euler 块校验（读写共用）。`order`/`intrinsic` 允许为 null（= 未判定）。"""
    if not isinstance(euler, dict):
        return False, "euler 必须是字典（order/intrinsic/output_format/angle_unit）", None
    missing = [k for k in REQUIRED_EULER_FIELDS if k not in euler]
    if missing:
        return False, f"euler 缺字段 {missing}", None
    if euler["output_format"] != EULER_OUTPUT_FORMAT \
            or euler["angle_unit"] != EULER_ANGLE_UNIT:
        return False, (f"euler 输出口径必须是 {EULER_OUTPUT_FORMAT!r} / "
                       f"{EULER_ANGLE_UNIT!r}（U5/A11-④ 唯一口径），收到 "
                       f"{euler['output_format']!r} / {euler['angle_unit']!r}"), None
    order, intrinsic = euler["order"], euler["intrinsic"]
    if order is not None and not isinstance(order, str):
        return False, f"euler.order 必须是字符串或 null，收到 {order!r}", None
    if intrinsic is not None and not isinstance(intrinsic, bool):
        return False, f"euler.intrinsic 必须是 true/false 或 null，收到 {intrinsic!r}", None
    return True, "ok", {"order": order, "intrinsic": intrinsic,
                        "output_format": EULER_OUTPUT_FORMAT,
                        "angle_unit": EULER_ANGLE_UNIT}


def _check_numeric_or_null(value, name: str, *, integer: bool = False
                           ) -> tuple[bool, str]:
    """数值字段校验：JSON number 或 null；**字符串/bool 一律拒**（强转会掩盖格式错误）。

    null = 未知（@lead v2 §10.4-②：rms/n_samples 未知时写 null，不写 0）。
    """
    if value is None:
        return True, "ok"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False, (f"{name} 必须是 JSON 数值或 null（未知），收到 {value!r}："
                       f"字符串/bool 不接受（强转会掩盖格式错误）")
    if integer and not isinstance(value, int):
        return False, f"{name} 必须是整数或 null（未知），收到 {value!r}"
    if not np.isfinite(float(value)):
        return False, f"{name} 必须是有限数值，收到 {value!r}"
    return True, "ok"


def _check_verification(verification, validated_claim: Optional[bool]
                        ) -> tuple[bool, str, Optional[dict]]:
    """verification 块校验（A3 门禁留痕，@lead v2 §10.4-①）。

    - `state` 必填且 ∈ VERIFICATION_STATES；
    - `validated`（可选）必须与 `state` 自洽，且与顶层 `validated` 不矛盾（两个来源不许并存）。
    - 本块**只是留痕**：读回后矩阵状态一律 UNVERIFIED（A3）。
    """
    if not isinstance(verification, dict):
        return False, ("verification 必须是字典"
                       f"（state/validated/tip_verdict/err_mean_mm），收到 "
                       f"{type(verification).__name__}"), None
    if "state" not in verification:
        return False, "verification 缺 state（VERIFIED / UNVERIFIED / FAILED）", None
    state = verification["state"]
    if state not in VERIFICATION_STATES:
        return False, (f"verification.state 必须是 {VERIFICATION_STATES} 之一，"
                       f"收到 {state!r}"), None
    block = dict(verification)
    if "validated" in block:
        v = block["validated"]
        if not isinstance(v, bool):
            return False, f"verification.validated 必须是 true/false，收到 {v!r}", None
        if v != (state == "VERIFIED"):
            return False, (f"verification 自相矛盾：state={state} 但 validated={v}"
                           f"（应 {state == 'VERIFIED'}）"), None
        if validated_claim is not None and bool(v) != bool(validated_claim):
            return False, (f"verification.validated={v} 与顶层 validated="
                           f"{validated_claim} 矛盾：同一事不许两个来源"), None
    else:
        block["validated"] = (state == "VERIFIED")
    return True, "ok", block


def _check_near_miss_keys(data: dict) -> tuple[bool, str]:
    """近似键名守卫（@verify 复核备注②）。

    把 `pose_order_detect` 拼成 `order_detect` 会被"未知字段容忍"静默吞掉 ——
    与已知键名相似度 ≥ 0.7 的未知键直接拒并提示正确键名；完全无关的未知键仍容忍。
    """
    for key in data:
        if key in KNOWN_KEYS:
            continue
        near = difflib.get_close_matches(key, sorted(KNOWN_KEYS), n=1,
                                         cutoff=NEAR_MISS_CUTOFF)
        if near:
            return False, (f"未知字段 '{key}' 与已知字段 '{near[0]}' 名字近似："
                           f"拒绝（拼错的字段会被静默忽略，结论就丢了）")
    return True, "ok"


def _check_legacy_keys(data: dict, eye_in_hand: bool, matrix_mm: np.ndarray
                       ) -> tuple[bool, str]:
    """v1 文件里并存旧 MCC 键时必须自洽（A10-4 第 3 类）。"""
    op_key = LEGACY_KEY_OPPOSITE[eye_in_hand]
    if data.get(op_key) is not None:
        return False, (f"eye_in_hand={'眼在手上' if eye_in_hand else '眼在手外'}"
                       f"（T_handeye={LEGACY_KEY[eye_in_hand]}），但文件里并存 "
                       f"'{op_key}'（反装分支键）：安装方式与矩阵键不一致，拒绝加载")
    own = data.get(LEGACY_KEY[eye_in_hand])
    if own is None:
        return True, "ok"
    try:
        arr = np.asarray(own, dtype=np.float64).reshape(4, 4)
    except (TypeError, ValueError):
        return False, f"'{LEGACY_KEY[eye_in_hand]}' 不是 4×4 数值"
    if not np.allclose(arr, matrix_mm, rtol=0.0, atol=1e-12):
        return False, (f"'{LEGACY_KEY[eye_in_hand]}' 与 'matrix' 逐元素不一致："
                       f"两个来源不允许并存（max|Δ|="
                       f"{float(np.max(np.abs(arr - matrix_mm))):.3e}）")
    return True, "ok"


# ----------------------------------------------------------------------
# 写
# ----------------------------------------------------------------------
def write_matrix_file(path: str, T_handeye_mm, *, eye_in_hand: bool, unit: str,
                      source: str, rms=(None, None), n_samples=None,
                      euler=None, order_detect=None, validated: bool = False,
                      verification=None, created_at: Optional[str] = None
                      ) -> tuple[bool, str]:
    """把毫米域手眼矩阵写成 v1 矩阵文件（fail-closed：先校验，校验不过不落盘）。

    Args:
        path: 目标路径（父目录不存在则创建）。
        T_handeye_mm: 4×4 或 16 数（行优先）矩阵，**毫米域**（内部统一口径）。
        eye_in_hand: True=T_cam2tool（眼在手上）/ False=T_cam2base，**必须显式 bool**。
        unit: 文件里数值的单位 "mm" | "m"（必填，无 auto，A2/D4）。
        source: 产出工具名+版本，或 "manual"。
        rms: (rms_t_mm, rms_r_deg)；None → 写 **null = 未知**（不许写 0.0：
            会被读成"完美标定"，@lead v2 §10.4-②）。
        n_samples: 标定样本数；None → 写 null（未知）。
        euler: {order, intrinsic, output_format, angle_unit}；None → order/intrinsic
            写 null（= 未判定），口径两项写死常量。
        order_detect: A11 判定结论块（可选，程序写入，本模块不解释其内容）。
        validated: 门禁状态；仅留痕，读回时一律 False（A3）。
        verification: A3 门禁留痕块；None → 由 validated 生成
            `{"state": "VERIFIED"|"UNVERIFIED", "validated": <bool>}`。
        created_at: 测试注入用；None → 当前本地时间（带时区）。

    Returns:
        (ok, message)。message 含落盘路径与 **sha256**（RG-08 复核锚点）。
    """
    # ---- 入参（先校验，绝不让"写出去读不回来"的文件过）----
    if not isinstance(eye_in_hand, bool):
        return False, (f"eye_in_hand 必须显式给出 True/False（收到 {eye_in_hand!r}）："
                       f"无默认，取错分支等于写出反装矩阵（K6）")
    try:
        unit = normalize_unit(unit)
    except ValueError as e:
        return False, str(e)
    if not isinstance(source, str) or not source.strip():
        return False, "source 必填（产出工具名+版本，或 'manual'）"
    if not isinstance(validated, bool):
        return False, f"validated 必须是 bool（收到 {validated!r}）"
    arr = np.asarray(T_handeye_mm, dtype=np.float64)
    if arr.size != 16:
        return False, f"矩阵必须是 16 个数（行优先）或 4×4，实际 {arr.size} 个"
    arr = arr.reshape(4, 4)

    ok, msg = validate_matrix(arr)          # A7：正交/det/末行（单实现）
    if not ok:
        return False, f"矩阵非法，拒绝落盘：{msg}"
    ok, msg, res = HandEyeResult.from_matrix(arr, "mm", eye_in_hand)
    if not ok:                              # A2：范数物理窗口（单实现）
        return False, f"矩阵非法，拒绝落盘：{msg}"
    assert res is not None                  # ok=True 时必有结果（供类型检查）

    ok, msg, euler_block = _check_euler(
        euler if euler is not None
        else {"order": None, "intrinsic": None,
              "output_format": EULER_OUTPUT_FORMAT,
              "angle_unit": EULER_ANGLE_UNIT})
    if not ok:
        return False, msg
    if order_detect is not None and not isinstance(order_detect, dict):
        return False, f"order_detect 必须是字典或 None（收到 {type(order_detect).__name__}）"

    rms_t, rms_r = (rms or (None, None))
    ok, msg = _check_numeric_or_null(rms_t, "rms_t_mm")
    if ok:
        ok, msg = _check_numeric_or_null(rms_r, "rms_r_deg")
    if ok:
        ok, msg = _check_numeric_or_null(n_samples, "n_samples", integer=True)
    if not ok:
        return False, f"拒绝落盘：{msg}"

    ok, msg, ver_block = _check_verification(
        verification if verification is not None
        else {"state": "VERIFIED" if validated else "UNVERIFIED",
              "validated": validated}, validated)
    if not ok:
        return False, msg

    if created_at is None:
        created_at = _now_iso()
    else:
        okc, msgc = _check_created_at(created_at)
        if not okc:
            return False, f"created_at 注入值非法：{msgc}"

    T_file = to_unit(res.T_handeye_mm, unit)   # 内部毫米 → 文件单位（单实现换算）
    data = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "created_at": created_at,
        "source": source,
        "eye_in_hand": eye_in_hand,
        "unit": unit,
        "matrix": [float(v) for v in T_file.reshape(-1)],   # 行优先
        "rms_t_mm": None if rms_t is None else float(rms_t),
        "rms_r_deg": None if rms_r is None else float(rms_r),
        "n_samples": None if n_samples is None else int(n_samples),
        "euler": euler_block,
        "validated": validated,     # 留痕；读回后一律 False
        "verification": ver_block,
    }
    if order_detect is not None:
        data["pose_order_detect"] = order_detect

    # ---- 原子写 ----
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    tmp = _atomic_tmp_path(path)
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False, f"矩阵文件写出失败：{e}"

    sha = _sha256(path)
    return True, (f"矩阵文件已写出：{os.path.abspath(path)}"
                  f"（unit={unit}, eye_in_hand={'眼在手上' if eye_in_hand else '眼在手外'}, "
                  f"source={source}, validated={validated}）；sha256={sha}")


# ----------------------------------------------------------------------
# 读
# ----------------------------------------------------------------------
def read_matrix_file(path: str, *, unit_override: Optional[str] = None,
                     eye_in_hand: Optional[bool] = None
                     ) -> tuple[bool, str, Optional[HandEyeResult]]:
    """读矩阵文件（v1 或 MCC 旧 JSON，A10-5 并存不回归）。

    Args:
        path: 文件路径。
        unit_override: 界面/调用方选定的单位（可 None）。
            v1 文件：None → 以文件 unit 为准；给了且与文件冲突 → 拒绝（A10-3）。
            旧格式：必填，None → 拒绝（旧 JSON 无 unit，不可推断，D4）。
        eye_in_hand: 显式安装方式（可 None）。给了且与文件不一致 → 拒绝（防取错键分支，K6）。

    Returns:
        (ok, message, HandEyeResult|None)。返回对象的附加属性（**非
        HandEyeResult 契约字段**）：`file_meta`（format/version/created_at/unit/
        source/validated_claim）、`euler`、`pose_order_detect`。
        注意 `validated` 恒为 False（A3：文件声明不算验证）。
    """
    if unit_override is not None:
        try:
            unit_override = normalize_unit(unit_override)
        except ValueError as e:
            return False, str(e), None
    if not os.path.exists(path):
        return False, f"文件不存在: {path}", None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return False, f"JSON 解析失败: {e}", None
    if not isinstance(data, dict):
        return False, "JSON 顶层必须是对象", None

    # ---- 旧格式（MCC handeye.py 输出）走既有加载器，不另起一套 ----
    if data.get("format") != FORMAT_NAME:
        if unit_override is None:
            return False, (f"不是 v1 矩阵文件（缺 format={FORMAT_NAME!r}）：按 MCC 旧 JSON "
                           f"加载，而该格式**无 unit 字段**，必须显式指定 unit（mm/m），"
                           f"不允许自动推断（A10-3/D4）"), None
        return HandEyeResult.load(path, unit_override, eye_in_hand)

    # ---- v1 ----
    ok, msg = _check_near_miss_keys(data)
    if not ok:
        return False, msg, None
    missing = [k for k in REQUIRED_FIELDS if k not in data]
    if missing:
        return False, (f"矩阵文件缺必填字段 {missing}（v1 不允许补默认值，A10-2）："
                       f"{path}"), None
    if isinstance(data["version"], bool) or data["version"] != FORMAT_VERSION:
        return False, (f"版本不支持：version={data['version']!r}，本工具只认 "
                       f"{FORMAT_VERSION}（拒绝猜测字段语义）"), None
    ok, msg = _check_created_at(data["created_at"])
    if not ok:
        return False, msg, None
    if not isinstance(data["source"], str) or not data["source"].strip():
        return False, "source 必须是非空字符串（产出工具名+版本，或 'manual'）", None

    eih = data["eye_in_hand"]
    if not isinstance(eih, bool):
        return False, (f"eye_in_hand 必须是 JSON true/false，收到 {eih!r}："
                       f"字符串/数字会让安装方式静默落到反装分支（K6）"), None
    if eye_in_hand is not None and bool(eye_in_hand) != eih:
        return False, (f"安装方式不一致：文件为 {'眼在手上' if eih else '眼在手外'}，"
                       f"传入为 {'眼在手上' if eye_in_hand else '眼在手外'}"), None

    fu = data["unit"]
    if not isinstance(fu, str) or fu.strip().lower() not in UNITS:
        return False, (f"unit 必须是 'mm' 或 'm'（收到 {fu!r}）："
                       f"矩阵单位由产出者决定，不可推断（A10-3）"), None
    fu = normalize_unit(fu)
    if unit_override is not None and unit_override != fu:
        return False, (f"单位冲突：文件 unit={fu!r}，界面选择 {unit_override!r}"
                       f"（A10-3：文件含 unit 时以文件为准，禁止静默取其一）"), None
    unit = fu

    ok, msg, euler_block = _check_euler(data["euler"])
    if not ok:
        return False, msg, None

    try:
        arr = np.asarray(data["matrix"], dtype=np.float64)
    except (TypeError, ValueError) as e:
        return False, f"matrix 必须是 16 个数（行优先）：{e}", None
    if arr.size != 16:
        return False, f"matrix 必须是 16 个数（行优先），实际 {arr.size} 个", None
    arr = arr.reshape(4, 4)

    ok, msg = validate_matrix(arr)          # A7（单实现）
    if not ok:
        return False, f"矩阵非法：{msg}", None
    ok, msg, res = HandEyeResult.from_matrix(arr, unit, eih)   # A2 单位+窗口（单实现）
    if not ok:
        return False, msg, None
    assert res is not None                  # ok=True 时必有结果（供类型检查）

    ok, msg = _check_legacy_keys(data, eih, res.T_handeye_mm)
    if not ok:
        return False, msg, None

    ok, msg = _check_numeric_or_null(data["rms_t_mm"], "rms_t_mm")
    if ok:
        ok, msg = _check_numeric_or_null(data["rms_r_deg"], "rms_r_deg")
    if ok:
        ok, msg = _check_numeric_or_null(data["n_samples"], "n_samples", integer=True)
    if not ok:
        return False, msg, None
    rms_t = float(data["rms_t_mm"]) if data["rms_t_mm"] is not None else 0.0
    rms_r = float(data["rms_r_deg"]) if data["rms_r_deg"] is not None else 0.0
    n_samples = int(data["n_samples"]) if data["n_samples"] is not None else 0
    # null = 未知（不是 0）：交给 UI 显示"未知"，不许当成"完美标定"（@lead v2 §10.4-②）
    rms_unknown = (data["rms_t_mm"] is None or data["rms_r_deg"] is None
                   or data["n_samples"] is None)

    validated_claim = data["validated"] if "validated" in data else None
    if validated_claim is not None and not isinstance(validated_claim, bool):
        return False, (f"validated 必须是 JSON true/false，收到 {validated_claim!r}"), None
    ver_block = None
    if "verification" in data:
        ok, msg, ver_block = _check_verification(data["verification"], validated_claim)
        if not ok:
            return False, msg, None

    pod = data.get("pose_order_detect")
    if pod is not None and not isinstance(pod, dict):
        return False, "pose_order_detect 必须是字典", None

    res = HandEyeResult(
        eye_in_hand=eih,
        T_handeye_mm=res.T_handeye_mm,
        rms_t_mm=rms_t, rms_r_deg=rms_r, n_samples=n_samples,
        source=os.path.abspath(path),
        validated=False)        # A3：文件说 validated 也不算，戳点门禁才算
    res.file_meta = {
        "format": FORMAT_NAME, "version": data["version"],
        "created_at": data["created_at"], "unit": unit,
        "source": data["source"], "validated_claim": bool(validated_claim),
        "verification_state": (ver_block or {}).get("state"),
    }
    res.euler = euler_block
    res.pose_order_detect = pod
    res.verification = ver_block          # None = 文件无该块（老文件）
    res.rms_unknown = rms_unknown

    ver_note = (f"verification.state={ver_block['state']}" if ver_block
                else "无 verification 块（按 UNVERIFIED 处理）")
    rms_note = "rms/n_samples=未知" if rms_unknown else \
        f"rms_t={rms_t:g} rms_r={rms_r:g} n={n_samples}"
    return True, (f"v1 矩阵文件已加载：unit={unit}"
                  f"（{'以文件为准' if unit_override is None else '文件与界面一致'}），"
                  f"source={data['source']}，created_at={data['created_at']}，"
                  f"euler.order={euler_block['order']!r}，{rms_note}；"
                  f"{ver_note} → 本工具一律置 UNVERIFIED（A3）"), res


# ----------------------------------------------------------------------
# 往返自检（供测试与 UI）
# ----------------------------------------------------------------------
def roundtrip_check(path: str, *, unit_override: Optional[str] = None
                    ) -> tuple[bool, str, float]:
    """往返自检：文件里的原始 16 数 vs （读入 → 毫米 → 换回文件单位）的 16 数。

    比对的单位域与文件一致（避免拿"米制原值"比"毫米读回值"的假失败），
    max|Δ| < 1e-12 判通过（A10-1）。

    Returns:
        (ok, message, max_abs_delta)。失败时 max_abs_delta = inf。
    """
    ok, msg, res = read_matrix_file(path, unit_override=unit_override)
    if not ok:
        return False, msg, float("inf")
    assert res is not None
    unit = getattr(res, "file_meta", {}).get("unit", unit_override)
    if unit is None:
        return False, "无法确定文件单位：旧格式请给 unit_override", float("inf")
    raw = _raw_matrix(path, unit_override)
    if raw is None:
        return False, "无法取出文件原始矩阵（格式不支持往返自检）", float("inf")
    back = to_unit(res.T_handeye_mm, unit).reshape(-1)
    maxd = float(np.max(np.abs(back - raw.reshape(-1))))
    ok = maxd < RT_TOL
    return ok, (f"往返自检：max|Δ|={maxd:.3e}（单位={unit}，门槛 {RT_TOL:g}）"), maxd


def _raw_matrix(path: str, unit_override: Optional[str]) -> Optional[np.ndarray]:
    """取出文件里的原始矩阵（数值域 = 文件声明/调用方声明的单位）。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("format") == FORMAT_NAME:
        return np.asarray(data["matrix"], dtype=np.float64).reshape(4, 4)
    eih = bool(data.get("eye_in_hand"))
    key = LEGACY_KEY[eih]
    if key not in data or data[key] is None:
        return None
    return np.asarray(data[key], dtype=np.float64).reshape(4, 4)
