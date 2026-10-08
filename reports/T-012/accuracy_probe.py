#!/usr/bin/env python3
"""T-012 判据：五个特征 × N 次独立拍照的真机测量精度。

为什么要外层驱动：`measure_probe.py --matrix` 在**同一个程序会话**里连测多个特征时，
工具列表的切换与 ROI 重画会失效（实测：第 3~5 个特征读到的是前面特征的读数）。
所以这里一次只让 `measure_probe.py` 测**一个**特征：每个样本都是
"新起程序 → 连相机 → 拍照 → 框一个 ROI → 测量"，读数不可能串。

判据（人 2026-10-08 改判：误差 ≤ 0.5% × 标称；原口径 0.2% 已废）：
  * 每个特征 max|实测-标称| ≤ 0.5% × 标称；
  * 且每个特征 (max - min) ≤ 0.5% × 标称（重复性也在这个带里）。

为什么放宽：0.2% 在 Ø6 上要求 ±0.012 mm，而 3D 点距是 0.0755 mm ——
半像素修正后残差仍有 ±0.038 mm（在 Ø6 上已是 0.63%），纯 3D 网格路径**物理上够不到**，
不是投入不够。改判的来龙去脉见 BASELINE.md 末尾「判据变更」一节。

用法：
    python reports/T-012/accuracy_probe.py                  # 五特征 × 5 次（整套，约 20 分钟）
    python reports/T-012/accuracy_probe.py --reps 1 --only hole_d6_disc,hub_d26
输出：reports/T-012/results.json + 每步 JSON；退出码 0 = 全过。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                      # noqa: BLE001
    pass

OUT = Path(__file__).resolve().parent
PROBE = OUT / "measure_probe.py"

FEATURES = {
    "hole_d6_disc": (6.0, "孔径(孔洞边界法)", "447,335,492,380"),
    "hub_d26": (26.0, "圆环拟合", "395,283,545,433"),
    "disc_d63_5": (63.5, "圆环拟合", "285,140,655,515"),
    "plate_up_d9": (9.0, "孔径(孔洞边界法)", "45,122,105,182"),
    "plate_low_d5": (5.0, "孔径(孔洞边界法)", "58,135,92,169"),
}


def say(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def run_once(tool: str, roi: str) -> float | None:
    proc = subprocess.run(
        [sys.executable, str(PROBE), "--tool", tool, "--roi", roi],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(OUT.parents[1]), timeout=300,
    )
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("step") == "measured":
            for item in reversed(obj.get("results", [])):
                import re
                m = re.search(r"(?:孔|圆环)直径\s*=\s*([-\d.]+)\s*mm", item)
                if m:
                    return float(m.group(1))
    say(error="no reading", tool=tool, roi=roi, tail=proc.stdout[-300:])
    return None


def main() -> int:
    args = sys.argv[1:]
    reps = 5
    only = None
    for i, a in enumerate(args):
        if a == "--reps" and i + 1 < len(args):
            reps = int(args[i + 1])
        if a == "--only" and i + 1 < len(args):
            only = [s.strip() for s in args[i + 1].split(",") if s.strip()]

    names = only or list(FEATURES)
    samples: dict[str, list[float]] = {n: [] for n in names}
    for rep in range(reps):
        for name in names:
            nominal, tool, roi = FEATURES[name]
            value = run_once(tool, roi)
            if value is not None:
                samples[name].append(value)
            say(step="sample", feature=name, repeat=rep + 1,
                nominal=nominal, measured=value)

    rows, bad = [], 0
    for name in names:
        nominal, tool, roi = FEATURES[name]
        tol = round(nominal * 0.005, 4)
        vals = samples[name]
        if not vals:
            rows.append({"feature": name, "nominal": nominal, "tol": tol,
                         "n": 0, "ok": False, "note": "没有读到任何读数"})
            bad += 1
            continue
        max_err = max(abs(v - nominal) for v in vals)
        spread = max(vals) - min(vals)
        ok = max_err <= tol and spread <= tol
        rows.append({"feature": name, "nominal": nominal, "tol": tol,
                     "n": len(vals), "values": [round(v, 4) for v in vals],
                     "mean": round(sum(vals) / len(vals), 4),
                     "max_abs_err": round(max_err, 4),
                     "spread": round(spread, 4), "ok": ok})
        if not ok:
            bad += 1

    (OUT / "results.json").write_text(
        json.dumps({"reps": reps, "features": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    for r in rows:
        say(step="verdict", **r)
    say(step="done", bad=bad, total=len(rows), file=str(OUT / "results.json"))
    say(result="PASS" if bad == 0 else "FAIL")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
