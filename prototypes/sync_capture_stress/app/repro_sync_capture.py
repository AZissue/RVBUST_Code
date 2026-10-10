# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
repro_sync_capture.py —— 多相机并发采集污染复现脚本（需实机）。

复刻 MCC sync-capture 的采集方式（每相机一线程并发 Capture），与串行
基线对比每相机深度健康指标，定位 2026-10-09 双 RVC-I540 并发采集污染
cam1 深度数据的根因。设计意图详见 ../README.md。

用法：
    python repro_sync_capture.py [--rounds 10] [--indices 0 1]
                                 [--mode all|serial|concurrent|barrier]
                                 [--json out.json]

退出码：0 = 无污染；1 = 检测到污染；2 = 无 SDK/无相机，跳过。
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from typing import Dict, List, Optional

import numpy as np

try:
    import PyRVC as RVC
except ImportError:
    RVC = None


# ---------------------------------------------------------------------------
# 相机封装（SDK 层最小实现，独立于 src，避免主程序逻辑干扰根因定位）
# ---------------------------------------------------------------------------
class CamHandle:
    """单台相机的连接/采集封装，行为对齐 MCC SingleCameraController。"""

    def __init__(self, device):
        self.device = device
        self.camera = None
        self.camera_type = None

    def open(self) -> bool:
        try:
            self.camera = RVC.X2.Create(self.device)
            if self.camera and self.camera.Open() and self.camera.IsOpen():
                self.camera_type = "X2"
                return True
            self._destroy()
        except Exception:
            self._destroy()
        try:
            self.camera = RVC.X1.Create(self.device, RVC.CameraID_Left)
            if self.camera.IsValid() and self.camera.Open() and self.camera.IsOpen():
                self.camera_type = "X1"
                return True
        except Exception:
            pass
        self._destroy()
        return False

    def _destroy(self):
        try:
            if self.camera is not None:
                if self.camera_type == "X2" or (hasattr(self.camera, "IsValid") and not self.camera.IsValid()):
                    RVC.X2.Destroy(self.camera)
                else:
                    RVC.X1.Destroy(self.camera)
        except Exception:
            pass
        self.camera = None

    def close(self):
        try:
            if self.camera:
                self.camera.Close()
        except Exception:
            pass
        self._destroy()

    def capture(self) -> Optional[Dict]:
        """采集一帧，返回健康指标；失败返回 None。

        与 MCC capture_3d 一致：Capture() → GetImage → GetPointMap → Clone。
        """
        try:
            if not self.camera.Capture():
                return None
            if self.camera_type == "X2":
                img = self.camera.GetImage(RVC.CameraID_Left)
            else:
                img = self.camera.GetImage()
            pm = self.camera.GetPointMap()
            if img is None or pm is None:
                return None
            img_np = np.array(img, copy=True)
            pm_np = np.array(pm.Clone(), copy=True)
            pm.Close() if hasattr(pm, "Close") else None
            return health_metrics(pm_np, img_np)
        except Exception:
            return None


def health_metrics(pm_np: np.ndarray, img_np: np.ndarray) -> Dict:
    """深度健康指标：valid_ratio / z_span / 飞点率 / 亮度。"""
    pts = pm_np.reshape(-1, 3).astype(np.float64)
    finite = np.isfinite(pts).all(axis=1)
    nonzero = np.abs(pts).sum(axis=1) > 0
    valid = finite & nonzero
    valid_ratio = float(valid.mean())
    z_span = mad_outlier = 0.0
    if valid.sum() > 100:
        z = pts[valid, 2]
        p1, p99 = np.percentile(z, [1, 99])
        z_span = float(p99 - p1)
        med = np.median(z)
        mad = np.median(np.abs(z - med)) + 1e-9
        mad_outlier = float((np.abs(z - med) > 20 * mad).mean())
    return {
        "valid_ratio": round(valid_ratio, 4),
        "z_span_p99_p1": round(z_span, 2),
        "z_mad_outlier_ratio": round(mad_outlier, 4),
        "image_mean": round(float(img_np.mean()), 2),
    }


# ---------------------------------------------------------------------------
# 拍摄模式
# ---------------------------------------------------------------------------
def run_serial(cams: List[CamHandle], rounds: int) -> Dict[int, List[Dict]]:
    """串行：一台拍完再拍下一台（基线）。"""
    results: Dict[int, List[Dict]] = {i: [] for i in range(len(cams))}
    for r in range(rounds):
        for i, cam in enumerate(cams):
            m = cam.capture()
            if m:
                m["round"] = r
                results[i].append(m)
    return results


def run_concurrent(cams: List[CamHandle], rounds: int,
                   use_barrier: bool) -> Dict[int, List[Dict]]:
    """并发：每相机一线程（MCC sync-capture 复刻）；可选 Barrier 同步起点。"""
    results: Dict[int, List[Dict]] = {i: [] for i in range(len(cams))}
    lock = threading.Lock()
    barrier = threading.Barrier(len(cams)) if use_barrier else None

    def _work(i: int, cam: CamHandle):
        for r in range(rounds):
            if barrier:
                barrier.wait()
            m = cam.capture()
            if m:
                m["round"] = r
                with lock:
                    results[i].append(m)

    threads = [threading.Thread(target=_work, args=(i, c), name=f"cam{i}-thread")
               for i, c in enumerate(cams)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------
def summarize(results: Dict[int, List[Dict]]) -> Dict[int, Dict]:
    agg = {}
    for i, frames in results.items():
        if not frames:
            agg[i] = {"frames": 0}
            continue
        agg[i] = {
            "frames": len(frames),
            "valid_ratio_min": min(f["valid_ratio"] for f in frames),
            "valid_ratio_mean": round(float(np.mean([f["valid_ratio"] for f in frames])), 4),
            "z_span_max": max(f["z_span_p99_p1"] for f in frames),
            "z_span_mean": round(float(np.mean([f["z_span_p99_p1"] for f in frames])), 2),
            "mad_outlier_mean": round(float(np.mean([f["z_mad_outlier_ratio"] for f in frames])), 4),
            "image_mean": round(float(np.mean([f["image_mean"] for f in frames])), 2),
        }
    return agg


def judge(baseline: Dict[int, Dict], test: Dict[int, Dict]) -> List[str]:
    """相对每相机串行基线判定污染，返回问题描述列表。"""
    problems = []
    for i, b in baseline.items():
        t = test.get(i, {})
        if not b.get("frames") or not t.get("frames"):
            problems.append(f"cam{i}: 帧数不足（baseline={b.get('frames')}, test={t.get('frames')}）")
            continue
        dv = b["valid_ratio_mean"] - t["valid_ratio_mean"]
        if dv > 0.10:
            problems.append(f"cam{i}: valid_ratio 下降 {dv * 100:.1f}pp "
                            f"({b['valid_ratio_mean']:.3f} → {t['valid_ratio_mean']:.3f})")
        if t["z_span_mean"] > max(b["z_span_mean"] * 1.5, b["z_span_mean"] + 10):
            problems.append(f"cam{i}: z_span 膨胀 {b['z_span_mean']:.1f} → {t['z_span_mean']:.1f}mm")
        dm = t["mad_outlier_mean"] - b["mad_outlier_mean"]
        if dm > 0.05:
            problems.append(f"cam{i}: 飞点率上升 {dm * 100:.1f}pp "
                            f"({b['mad_outlier_mean']:.3f} → {t['mad_outlier_mean']:.3f})")
    return problems


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="多相机并发采集污染复现")
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--indices", type=int, nargs="+", default=None)
    ap.add_argument("--mode", choices=["serial", "concurrent", "barrier", "all"],
                    default="all")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    if RVC is None:
        print("[SKIP] 未安装 PyRVC")
        return 2

    RVC.SystemInit()
    try:
        ret, devices = RVC.SystemListDevices(RVC.SystemListDeviceTypeEnum.All)
        if not devices:
            print("[SKIP] 未发现相机")
            return 2
        indices = args.indices if args.indices else list(range(len(devices)))
        print(f"发现 {len(devices)} 台设备，测试索引: {indices}")

        cams: List[CamHandle] = []
        for idx in indices:
            cam = CamHandle(devices[idx])
            if not cam.open():
                print(f"[ERROR] 索引 {idx} 打开失败")
                for c in cams:
                    c.close()
                return 2
            cams.append(cam)
            print(f"索引 {idx}: 已连接 ({cam.camera_type})")

        report = {"rounds": args.rounds, "indices": indices, "modes": {}}
        baseline_summary: Dict[int, Dict] = {}

        modes = (["serial", "concurrent", "barrier"] if args.mode == "all"
                 else [args.mode])
        for mode in modes:
            print(f"\n=== 模式 {mode}（{args.rounds} 轮）===")
            t0 = time.perf_counter()
            if mode == "serial":
                res = run_serial(cams, args.rounds)
            else:
                res = run_concurrent(cams, args.rounds, use_barrier=(mode == "barrier"))
            elapsed = time.perf_counter() - t0
            summary = summarize(res)
            report["modes"][mode] = {"summary": summary, "elapsed_s": round(elapsed, 2)}
            for i, s in summary.items():
                print(f"  cam{i}: {s}")
            print(f"  耗时 {elapsed:.1f}s")
            if mode == "serial":
                baseline_summary = summary

        print("\n=== 判定（相对 serial 基线）===")
        all_problems = []
        for mode in modes:
            if mode == "serial":
                continue
            problems = judge(baseline_summary, report["modes"][mode]["summary"])
            report["modes"][mode]["problems"] = problems
            for p in problems:
                print(f"  [{mode}] {p}")
            all_problems.extend(problems)
        if not all_problems:
            print("  未发现污染迹象")

        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print(f"\n报告已保存: {args.json}")

        for c in cams:
            c.close()
        return 1 if all_problems else 0
    finally:
        RVC.SystemShutdown()


if __name__ == "__main__":
    sys.exit(main())
