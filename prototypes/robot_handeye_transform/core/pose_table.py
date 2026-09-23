# -*- coding: utf-8 -*-
"""位姿数据列表模型（pose_table）—— A11-②。

一行 = 一条记录：
   机器人拍照位姿**原文**（`x y z` + 角度三值 `a b c`）+ 长度单位 + 来源 + 时间
   [+ 相机侧目标位姿 `T_target2cam_mm`：工具在同一次采集里绑定到该条上（§10.1）]

三条口径（都是方案硬条款）：

1. **行号 `idx` 单调不回收**：删行后行号不复用 —— `idx` 是判定结论的唯一索引，
   复用会让"上次结论指的行"变成另一条数据（A11-②）。
2. **判定只读数值**：`raw`（含用户声明的欧拉顺序）**只用于回显**；`detect_order`
   不读它 —— 否则就变成"人给了答案、工具只做验证"，与 U4 的诉求相反。
   声明列保留是为了现场交接时能看出来源（且 6B-2 的表格要显示它）。
3. **角度单位不进模型**：`abc` 的 deg/rad 是**待判定量**（R19 把单位列为候选分支维数），
   所以这里只做"是 3 个有限数"的检查，绝不按 deg 或 rad 做任何单位假设。
   平移单位（mm/m）则必须声明，经 A2 入口（`pose_source.admit_pose`）归一到 mm（A11-6）。

相机侧位姿可选：没有它的记录是"纯位姿表"，`detect_order` 会直接拒绝（§10.1）。
本模块负责把它显形（`unpaired_idx`），不负责替调用方悄悄丢掉。
"""

from __future__ import annotations

import csv
import datetime as _dt
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    from . import order_detect, unit_guard
    from .pose_source import admit_pose, euler_to_matrix
except ImportError:  # 测试以顶层模块方式引入时
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import order_detect
    import unit_guard
    from pose_source import admit_pose, euler_to_matrix

CSV_MIN_COLS = 6
CSV_MAX_COLS = 7
SOURCE_MANUAL = "manual"


class PoseTableError(Exception):
    """位姿表使用错误（行号不存在、声明缺失等）。"""


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _as_3(v, label: str) -> Tuple[float, float, float]:
    arr = np.asarray(v, dtype=np.float64).reshape(-1)
    if arr.size != 3:
        raise PoseTableError(f"{label} 必须是 3 个数，实际 {np.shape(v)}")
    if not np.all(np.isfinite(arr)):
        raise PoseTableError(f"{label} 含非有限值（NaN/Inf）：{np.shape(v)}")
    return (float(arr[0]), float(arr[1]), float(arr[2]))


def _not_float(cell: str) -> bool:
    try:
        float(cell)
    except ValueError:
        return True
    return False


@dataclass
class PoseRecord:
    """一条记录。`T_base2tool_mm` 只在**已声明顺序**时才有值（见模块 docstring 第 3 条）。"""

    idx: int
    xyz_raw: Tuple[float, float, float]
    abc_raw: Tuple[float, float, float]
    unit: str
    xyz_mm: np.ndarray
    T_target2cam_mm: Optional[np.ndarray]
    source: str
    created_at: str
    raw: Dict[str, Any] = field(default_factory=dict)
    T_base2tool_mm: Optional[np.ndarray] = None

    def declared_order(self) -> Optional[str]:
        return self.raw.get("order_declared")

    def all_numerals(self) -> Tuple[float, ...]:
        return tuple(self.xyz_raw) + tuple(self.abc_raw)


class PoseTable:
    """数据列表模型（增 / 改 / 删 / 清空 / 导入 CSV / 行号索引）。"""

    def __init__(self, *, now_fn: Optional[Callable[[], str]] = None):
        self._rows: List[PoseRecord] = []
        self._next_idx = 1
        self._now = now_fn or _now_iso

    # ------------------------------------------------------------------
    # 基本访问
    # ------------------------------------------------------------------
    def rows(self) -> List[PoseRecord]:
        return list(self._rows)

    def count(self) -> int:
        return len(self._rows)

    def __len__(self) -> int:
        return len(self._rows)

    def get(self, idx: int) -> Optional[PoseRecord]:
        return next((r for r in self._rows if r.idx == idx), None)

    def index_list(self) -> List[int]:
        return [r.idx for r in self._rows]

    # ------------------------------------------------------------------
    # 增 / 改 / 删 / 清空
    # ------------------------------------------------------------------
    def _validate(self, xyz, abc, unit, order_declared, T_target2cam, ttc_unit
                  ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """共用校验（add / update 唯一实现）。返回 (ok, msg, 数据)。"""
        try:
            xyz_raw = _as_3(xyz, "xyz")
            abc_raw = _as_3(abc, "欧拉角三值")
            u = unit_guard.normalize_unit(unit)
            unit_guard.normalize_unit(ttc_unit)
        except (PoseTableError, ValueError) as e:
            return False, str(e), None
        if order_declared is not None and order_declared not in order_detect.CANDIDATE_ORDERS:
            return False, (f"声明顺序 {order_declared!r} 不在候选集内"
                           f"（只回显用，判定仍全枚举）：可选 "
                           f"{order_detect.CANDIDATE_ORDERS}"), None
        # A11-6：平移先归一到 mm（复用 A2 入口：单位换算 + 刚性 + 范数窗口）
        probe = np.eye(4, dtype=np.float64)
        probe[:3, 3] = np.asarray(xyz_raw, dtype=np.float64)
        ok, msg, T_mm = admit_pose(probe, u, "absolute", "拍照位姿平移")
        if not ok:
            return False, msg, None
        assert T_mm is not None
        ttc = None
        if T_target2cam is not None:
            try:
                ttc = np.asarray(T_target2cam, dtype=np.float64)
                if ttc.ndim == 1 and ttc.size == 16:
                    ttc = ttc.reshape(4, 4)
                if ttc.shape != (4, 4):
                    return False, (f"相机侧位姿必须是 4×4 或 16 个数（行优先），"
                                   f"实际 {np.shape(T_target2cam)}"), None
                ttc = unit_guard.to_mm(ttc, ttc_unit)
                ok, msg = unit_guard.check_rigid_4x4(ttc)
                if not ok:
                    return False, f"相机侧位姿非法：{msg}", None
            except ValueError as e:
                return False, str(e), None
        return True, "", {"xyz_raw": xyz_raw, "abc_raw": abc_raw, "unit": u,
                          "xyz_mm": np.asarray(T_mm[:3, 3], dtype=np.float64),
                          "T_target2cam_mm": ttc}

    def add(self, xyz, abc, *, unit: str, source: str = SOURCE_MANUAL,
            T_target2cam=None, ttc_unit: str = "mm",
            order_declared: Optional[str] = None,
            created_at: Optional[str] = None) -> Tuple[bool, str, Optional[int]]:
        """追加一行。任何一项不合法则**整行不生效**，返回 (False, 报错, None)。"""
        ok, msg, data = self._validate(xyz, abc, unit, order_declared,
                                       T_target2cam, ttc_unit)
        if not ok or data is None:
            return False, msg, None
        rec = PoseRecord(
            idx=self._next_idx,
            xyz_raw=data["xyz_raw"], abc_raw=data["abc_raw"], unit=data["unit"],
            xyz_mm=data["xyz_mm"], T_target2cam_mm=data["T_target2cam_mm"],
            source=source, created_at=created_at or self._now(),
            raw={"xyz": list(data["xyz_raw"]), "abc": list(data["abc_raw"]),
                 "unit": data["unit"], "order_declared": order_declared,
                 "ttc_bound": data["T_target2cam_mm"] is not None},
        )
        if order_declared:
            rec.T_base2tool_mm = unit_guard.to_mm(
                euler_to_matrix(data["xyz_raw"], data["abc_raw"], order_declared),
                data["unit"])
        self._rows.append(rec)
        self._next_idx += 1
        return True, (f"已录入第 {rec.idx} 行（{rec.unit}"
                      + ("，含相机侧配对）" if rec.T_target2cam_mm is not None
                         else "，无相机侧配对）")), rec.idx

    def update(self, idx: int, xyz=None, abc=None, *, unit: Optional[str] = None,
               source: Optional[str] = None,
               order_declared: Optional[str] = None) -> Tuple[bool, str]:
        """改一行的数值。**行号不变**（结论仍指得回同一行）。任一不合法 → 整行不改。"""
        rec = self.get(idx)
        if rec is None:
            return False, f"行号 {idx} 不存在"
        new_order = rec.declared_order() if order_declared is None else order_declared
        ok, msg, data = self._validate(
            rec.xyz_raw if xyz is None else xyz,
            rec.abc_raw if abc is None else abc,
            rec.unit if unit is None else unit,
            new_order, rec.T_target2cam_mm, "mm")
        if not ok or data is None:
            return False, f"第 {idx} 行未修改：{msg}"
        rec.xyz_raw = data["xyz_raw"]
        rec.abc_raw = data["abc_raw"]
        rec.unit = data["unit"]
        rec.xyz_mm = data["xyz_mm"]
        rec.T_target2cam_mm = data["T_target2cam_mm"]
        rec.source = rec.source if source is None else source
        rec.raw.update({"xyz": list(data["xyz_raw"]), "abc": list(data["abc_raw"]),
                        "unit": data["unit"], "order_declared": new_order,
                        "ttc_bound": data["T_target2cam_mm"] is not None})
        rec.T_base2tool_mm = None
        if new_order:
            rec.T_base2tool_mm = unit_guard.to_mm(
                euler_to_matrix(data["xyz_raw"], data["abc_raw"], new_order),
                data["unit"])
        return True, f"第 {idx} 行已更新（行号不变）"

    def bind_target(self, idx: int, T_target2cam=None, *,
                    ttc_unit: str = "mm") -> Tuple[bool, str]:
        """绑定/解绑该行的相机侧目标位姿（工具采集时调；None = 解绑）。"""
        rec = self.get(idx)
        if rec is None:
            return False, f"行号 {idx} 不存在"
        if T_target2cam is None:
            rec.T_target2cam_mm = None
            rec.raw["ttc_bound"] = False
            return True, f"第 {idx} 行已解绑相机侧位姿"
        try:
            ttc = np.asarray(T_target2cam, dtype=np.float64)
            if ttc.ndim == 1 and ttc.size == 16:
                ttc = ttc.reshape(4, 4)
            if ttc.shape != (4, 4):
                return False, f"相机侧位姿必须是 4×4 或 16 个数，实际 {np.shape(T_target2cam)}"
            ttc = unit_guard.to_mm(ttc, ttc_unit)
            ok, msg = unit_guard.check_rigid_4x4(ttc)
            if not ok:
                return False, f"相机侧位姿非法：{msg}"
        except ValueError as e:
            return False, str(e)
        rec.T_target2cam_mm = ttc
        rec.raw["ttc_bound"] = True
        return True, f"第 {idx} 行已绑定相机侧位姿（{ttc_unit} → mm）"

    def remove(self, idx: int) -> Tuple[bool, str]:
        rec = self.get(idx)
        if rec is None:
            return False, f"行号 {idx} 不存在"
        self._rows.remove(rec)
        return True, f"已删除第 {idx} 行（行号不复用）"

    def clear(self) -> Tuple[bool, str]:
        n = len(self._rows)
        self._rows = []
        return True, f"已清空 {n} 行（行号从 {self._next_idx} 继续，不复用）"

    # ------------------------------------------------------------------
    # 判定入口
    # ------------------------------------------------------------------
    def detect_inputs(self) -> Dict[str, Any]:
        """给 `order_detect.detect_order` 的入参（**角度单位不进模型**，见 docstring 第 3 条）。

        Returns:
            {"xyz_mm": (m,3), "abc": (m,3), "Ttc_mm": [4×4...], "paired_idx": [...],
             "unpaired_idx": [...], "n_paired": m, "n_total": n}
        """
        paired = [r for r in self._rows if r.T_target2cam_mm is not None]
        unpaired = [r.idx for r in self._rows if r.T_target2cam_mm is None]
        xyz = (np.array([r.xyz_mm for r in paired], dtype=np.float64)
               if paired else np.zeros((0, 3), dtype=np.float64))
        abc = (np.array([r.abc_raw for r in paired], dtype=np.float64)
               if paired else np.zeros((0, 3), dtype=np.float64))
        return {
            "xyz_mm": xyz, "abc": abc,
            "Ttc_mm": [r.T_target2cam_mm for r in paired],
            "paired_idx": [r.idx for r in paired],
            "unpaired_idx": unpaired,
            "n_paired": len(paired), "n_total": len(self._rows),
        }

    def detect(self, **kwargs) -> Dict[str, Any]:
        """直接跑判定：把配对行喂给 `order_detect.detect_order`。

        缺相机侧配对的行走 `dropped_idx`（R22：剔除必须落盘可见，不许悄悄挑）。
        """
        d = self.detect_inputs()
        return order_detect.detect_order(
            d["xyz_mm"], d["abc"], d["Ttc_mm"], unit="mm",
            row_idx=d["paired_idx"], dropped_idx=d["unpaired_idx"], **kwargs)

    def to_arrays(self, order: Optional[str] = None) -> Tuple[List[np.ndarray], List[Any]]:
        """(Tgb[], Ttc[])，`Tgb` 按 `order` 构造。

        `order` 缺省用各行声明值；**有行没声明 → 报错**并提示走 `detect()`：
        角度约定未知时 T_base2tool 根本不存在，硬猜一个顺序就是静默错姿态。
        """
        out_gb: List[np.ndarray] = []
        out_tc: List[Any] = []
        for r in self._rows:
            od = order or r.declared_order()
            if not od:
                raise PoseTableError(
                    f"第 {r.idx} 行未声明欧拉顺序：无法构造 T_base2tool。"
                    f"顺序未知时请用 detect()（全枚举判定），不要硬猜一个顺序。")
            T = euler_to_matrix(r.xyz_raw, r.abc_raw, od)
            out_gb.append(unit_guard.to_mm(T, r.unit))
            out_tc.append(None if r.T_target2cam_mm is None
                          else np.asarray(r.T_target2cam_mm, dtype=np.float64))
        return out_gb, out_tc

    def excitation_report(self) -> Dict[str, Any]:
        """激励质量（A11-③ 前置），UI 常驻徽标用；同时显形未配对行数。"""
        d = self.detect_inputs()
        rep = order_detect.excitation_report(d["xyz_mm"], d["abc"])
        rep["n_total"] = d["n_total"]
        rep["n_paired"] = d["n_paired"]
        rep["unpaired_idx"] = d["unpaired_idx"]
        if d["unpaired_idx"]:
            rep["ok"] = False
            rep["reasons"] = list(rep["reasons"]) + [
                f"{len(d['unpaired_idx'])} 行缺相机侧配对（行号 {d['unpaired_idx']}）："
                f"纯位姿表无法判定顺序"]
        return rep

    # ------------------------------------------------------------------
    # CSV 导入
    # ------------------------------------------------------------------
    def import_csv(self, path: str, *, unit: str, ttc_unit: str = "mm",
                   source: Optional[str] = None) -> Tuple[bool, str]:
        """导入 CSV。**整体原子**：任何一行不合法 → 一行都不导入。

        行格式（`#` 注释行、空行忽略；逗号 / 制表符 / 空格分隔都收）：
            6 列 —— `x y z a b c`（角度原文，**单位未知**，正是判定要解的东西）
            7 列 —— 多一列**声明顺序**（仅回显，判定仍全枚举；可选）
            16 列 —— **拒收**：矩阵行不含欧拉原文，参与不了顺序判定。
        若带 `# pose_type: absolute` 声明行则必须为 absolute（delta 属 R11 fail-closed）。
        """
        if not os.path.exists(path):
            return False, f"CSV 不存在: {path}"
        try:
            u = unit_guard.normalize_unit(unit)
        except ValueError as e:
            return False, str(e)
        try:
            unit_guard.normalize_unit(ttc_unit)
        except ValueError as e:
            return False, str(e)
        src = source or f"csv:{os.path.basename(path)}"
        staged: List[Tuple[Tuple[float, float, float], Tuple[float, float, float],
                           Optional[str]]] = []
        header_skipped = 0
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            for lineno, line in enumerate(f, start=1):
                raw_line = line.strip()
                if not raw_line:
                    continue
                cells = [c.strip() for c in next(csv.reader([raw_line])) if c.strip()]
                if len(cells) < 2:
                    cells = raw_line.split()
                if not cells:
                    continue
                if raw_line.startswith("#"):
                    if "pose_type:" in raw_line:
                        declared = raw_line.split("pose_type:", 1)[1].strip().lower()
                        if declared != "absolute":
                            return False, (f"第 {lineno} 行 pose_type 声明为 {declared!r}："
                                           f"本表只收绝对位姿（delta 未实现增量累积，R11）")
                    continue
                n = len(cells)
                if n == 16:
                    return False, (f"第 {lineno} 行为 16 列矩阵格式：拒收 —— 矩阵行不含欧拉"
                                   f"原文（角度三值），参与不了欧拉顺序判定。"
                                   f"请用 6 列 `x y z a b c` 原文。")
                if n not in (CSV_MIN_COLS, CSV_MAX_COLS):
                    return False, (f"第 {lineno} 行格式无法识别（{n} 列）：期望 "
                                   f"{CSV_MIN_COLS} 列 `x y z a b c`"
                                   f"（可加第 7 列声明顺序）")
                try:
                    nums = [float(c) for c in cells[:6]]
                except ValueError as e:
                    # 表头行（首个数据位置、且前 6 列全非数值）跳过并报数；其余一律报行号拒收
                    if not staged and header_skipped == 0 and all(
                            _not_float(c) for c in cells[:min(6, n)]):
                        header_skipped = lineno
                        continue
                    return False, f"第 {lineno} 行含非数值: {e}"
                order_col = cells[6] if n == CSV_MAX_COLS else None
                try:
                    xyz = _as_3(nums[0:3], f"第 {lineno} 行 xyz")
                    abc = _as_3(nums[3:6], f"第 {lineno} 行角度三值")
                except PoseTableError as e:
                    return False, str(e)
                staged.append((xyz, abc, order_col))
        if not staged:
            return False, f"CSV 无有效数据行: {path}"
        added: List[int] = []
        for xyz, abc, order_col in staged:
            ok, msg, idx = self.add(xyz, abc, unit=u, source=src,
                                    order_declared=order_col)
            if not ok:
                for i in added:      # 原子：回滚已导入的行
                    self.remove(i)
                return False, f"导入失败并已回滚（{len(added)} 行）：{msg}"
            assert idx is not None
            added.append(idx)
        head = f"（已跳过第 {header_skipped} 行表头）" if header_skipped else ""
        return True, (f"已从 {os.path.basename(path)} 导入 {len(added)} 行"
                      f"{head}（unit={u}，行号 {added[0]}~{added[-1]}）")
