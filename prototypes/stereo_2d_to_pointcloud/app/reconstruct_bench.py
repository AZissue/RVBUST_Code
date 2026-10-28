# -*- coding: utf-8 -*-
"""
reconstruct_bench.py —— M 系列双目相机左右 2D 图 + 内外参离线重建点云实机基准。

验证目标：X2 单次采集拿到左右 2D 图后，仅靠内外参 + SGBM 离线算出点云，
并实测各阶段耗时与端到端帧率（对照 SDK 原生 GetPointMap 的 Z 中位数数量级）。

用法：
    python reconstruct_bench.py [--frames 30] [--out out_dir] [--calib calib.json] [--skip-calib]

退出码：0 = 成功；2 = 无 SDK / 无相机 / 打开失败 / 无标定 / 右图不可用。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

try:
    import PyRVC as RVC
except ImportError:
    RVC = None


# ---------------------------------------------------------------------------
# 路径定位：从本文件向上找含 src/ 的仓库根，把本原型目录加进 sys.path
# ---------------------------------------------------------------------------
def _find_repo_root(start: str) -> str:
    d = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(d, "src")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            raise RuntimeError(f"从 {start} 向上未找到含 src/ 的仓库根目录")
        d = parent


_REPO_ROOT = _find_repo_root(os.path.dirname(os.path.abspath(__file__)))
_PROTO_DIR = os.path.join(_REPO_ROOT, "prototypes", "stereo_2d_to_pointcloud")
if _PROTO_DIR not in sys.path:
    sys.path.insert(0, _PROTO_DIR)

from core.stereo_reconstruct import (  # noqa: E402
    DEFAULT_SGBM_PARAMS,
    StereoReconstructor,
    rvc_dist_to_opencv,
)

# 标定板约定：9x6 内角点、20mm 方格
BOARD_SIZE = (9, 6)
SQUARE_M = 0.02
CALIB_PAIRS_TARGET = 10


# ---------------------------------------------------------------------------
# 相机封装（打开方式参照 prototypes/sync_capture_stress/app/repro_sync_capture.py）
# ---------------------------------------------------------------------------
class CamHandle:
    def __init__(self, device):
        self.device = device
        self.camera = None

    def open(self) -> bool:
        try:
            self.camera = RVC.X2.Create(self.device)
            if self.camera and self.camera.Open() and self.camera.IsOpen():
                return True
        except Exception:
            pass
        self._destroy()
        return False

    def _destroy(self):
        try:
            if self.camera is not None:
                RVC.X2.Destroy(self.camera)
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


# ---------------------------------------------------------------------------
# 内参读取（防御式；RVC 畸变顺序 k1 k2 k3 p1 p2，日志必须打印取到的原始顺序）
# ---------------------------------------------------------------------------
def extract_intrinsics(ip, label: str):
    """从 GetIntrinsicParameters 返回对象取 K 与 RVC 顺序畸变系数。

    返回 (K 3x3, dist_rvc 长度5, dist_cv 长度5)。假定对象含 fx/fy/cx/cy
    与 5 个畸变成员；优先按名字 k1..k3/p1..p2 取，缺失则按 dir() 顺序兜底。
    """
    def _num(name):
        if not hasattr(ip, name):
            raise RuntimeError(f"{label} 内参对象缺少成员 {name}（dir={dir(ip)}）")
        return float(getattr(ip, name))

    fx, fy, cx, cy = _num("fx"), _num("fy"), _num("cx"), _num("cy")
    K = np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64)

    picked: List[float] = []
    order_log: List[str] = []
    for want in ("k1", "k2", "k3", "p1", "p2"):
        if hasattr(ip, want):
            picked.append(float(getattr(ip, want)))
            order_log.append(want)
    if len(picked) != 5:
        # 兜底：dir() 中除 fx/fy/cx/cy 外的数值属性，按定义顺序
        picked, order_log = [], []
        for n in dir(ip):
            if n.startswith("_") or n in ("fx", "fy", "cx", "cy"):
                continue
            v = getattr(ip, n)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                picked.append(float(v))
                order_log.append(n)
        picked = picked[:5]
    if len(picked) != 5:
        raise RuntimeError(f"{label} 畸变系数取不到 5 个（dir={dir(ip)}）")
    dist_rvc = np.asarray(picked, dtype=np.float64)
    print(f"[INFO] {label} 畸变原始成员顺序（SDK 约定 k1 k2 k3 p1 p2）: "
          f"{order_log} = {[round(v, 6) for v in picked]}")
    return K, dist_rvc, rvc_dist_to_opencv(*picked)


# ---------------------------------------------------------------------------
# 取图策略探测：single / switch / unavailable
# ---------------------------------------------------------------------------
def _grab_np(x2, cam_id) -> Optional[np.ndarray]:
    """GetImage → 校验 IsValid → 拷贝为 numpy；失败返回 None。"""
    try:
        img = x2.GetImage(cam_id)
        if img is None or not img.IsValid():
            return None
        return np.asarray(img, copy=True)
    except Exception:
        return None


def grab_pair(x2) -> Tuple[str, Optional[np.ndarray], Optional[np.ndarray], str]:
    """探测取图模式并取一对左右 2D 图。

    返回 (mode, left_np, right_np, note)：
    - single      一次 Capture() 左右均有效；
    - switch      右图需第二次采集（优先 Capture2D()，否则再 Capture() 一次），
                  左右来自不同采集，存在帧不同步；
    - unavailable 拿不到右图。
    """
    if not x2.Capture():
        return "unavailable", None, None, "Capture() 失败"
    left = _grab_np(x2, RVC.CameraID_Left)
    right = _grab_np(x2, RVC.CameraID_Right)
    if left is not None and right is not None:
        return "single", left, right, "单次 Capture(): 左+右均有效"
    if left is None:
        return "unavailable", None, None, "左图无效（enable_2d_in_capture 未生效？）"

    # 右图缺失：优先试 Capture2D()（若 SDK 提供）
    if hasattr(x2, "Capture2D"):
        try:
            if x2.Capture2D():
                right = _grab_np(x2, RVC.CameraID_Right)
                if right is not None:
                    return "switch", left, right, (
                        "Capture2D() 后取得右图（左图来自上一次 Capture，帧不同步）")
        except Exception:
            pass
    # 兜底：连续第二次 Capture() 近似
    if x2.Capture():
        right = _grab_np(x2, RVC.CameraID_Right)
        if right is not None:
            return "switch", left, right, (
                "第二次 Capture() 后取得右图（左图来自上一次 Capture，帧不同步）")
    return "unavailable", None, None, "右图始终无效"


# ---------------------------------------------------------------------------
# 交互式双目外参标定（GetExtrinsicMatrix 是"标定板→相机"，不能当左右外参用）
# ---------------------------------------------------------------------------
def calibrate_interactive(x2, K_l, K_r, dist_l_rvc, dist_r_rvc, img_size):
    objp = np.zeros((BOARD_SIZE[0] * BOARD_SIZE[1], 3), dtype=np.float64)
    objp[:, :2] = np.mgrid[0:BOARD_SIZE[0], 0:BOARD_SIZE[1]].T.reshape(-1, 2) * SQUARE_M

    objpts, lpts, rpts = [], [], []
    print(f"\n=== 双目外参标定（棋盘格 {BOARD_SIZE[0]}x{BOARD_SIZE[1]} 内角点，"
          f"{int(SQUARE_M * 1000)}mm 方格，目标 {CALIB_PAIRS_TARGET} 对）===")
    print("将棋盘格置于双目公共视野，按回车采集一对，输入 q 回车提前结束。")
    while len(lpts) < CALIB_PAIRS_TARGET:
        s = input(f"[{len(lpts)}/{CALIB_PAIRS_TARGET}] 回车采集 / q 结束: ").strip().lower()
        if s == "q":
            break
        mode, l, r, note = grab_pair(x2)
        print(f"  取图模式 {mode}: {note}")
        if l is None or r is None:
            print("  取图失败，跳过本对")
            continue
        gl = cv2.cvtColor(l, cv2.COLOR_BGR2GRAY) if l.ndim == 3 else l
        gr = cv2.cvtColor(r, cv2.COLOR_BGR2GRAY) if r.ndim == 3 else r
        ok_l, cl = cv2.findChessboardCornersSB(gl, BOARD_SIZE)
        ok_r, cr = cv2.findChessboardCornersSB(gr, BOARD_SIZE)
        if not (ok_l and ok_r):
            print("  未在左右图同时检测到棋盘格，跳过本对")
            continue
        objpts.append(objp)
        lpts.append(cl)
        rpts.append(cr)
        print(f"  已采集 {len(lpts)}/{CALIB_PAIRS_TARGET} 对")

    if len(lpts) < 3:
        print("[ERROR] 成功对数 < 3，无法 stereoCalibrate")
        return None

    dist_l_cv = rvc_dist_to_opencv(*dist_l_rvc)
    dist_r_cv = rvc_dist_to_opencv(*dist_r_rvc)
    criteria = (cv2.TERM_CRITERIA_MAX_ITER | cv2.TERM_CRITERIA_EPS, 100, 1e-5)
    print(f"stereoCalibrate（CALIB_FIX_INTRINSIC，{len(lpts)} 对）...")
    rms, _K1, _d1, _K2, _d2, R, T, _E, _F = cv2.stereoCalibrate(
        objpts, lpts, rpts, K_l, dist_l_cv, K_r, dist_r_cv, img_size,
        criteria=criteria, flags=cv2.CALIB_FIX_INTRINSIC)
    T = T.ravel().astype(np.float64)
    print(f"  RMS 重投影误差 = {rms:.4f} px，T = {T.tolist()} m，"
          f"基线 |T| = {float(np.linalg.norm(T)) * 1000:.1f} mm")
    return {
        "K_left": K_l.tolist(),
        "dist_left_rvc": dist_l_rvc.tolist(),
        "K_right": K_r.tolist(),
        "dist_right_rvc": dist_r_rvc.tolist(),
        "R": np.asarray(R, dtype=np.float64).tolist(),
        "T": T.tolist(),
        "image_size": [int(img_size[0]), int(img_size[1])],
        "stereo_calib_rms_px": float(rms),
        "convention": ("dist_*_rvc 为 RVC SDK 原始顺序 k1 k2 k3 p1 p2，"
                       "加载后经 rvc_dist_to_opencv 重排为 OpenCV 顺序；"
                       "T 单位米，OpenCV 约定 x_right = R x_left + T"),
    }


def load_calib(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 输出工具
# ---------------------------------------------------------------------------
def save_sample_ply(path: str, points_m: np.ndarray, valid_mask: np.ndarray,
                    max_points: int = 500000, seed: int = 0):
    """有效点随机下采样（<=max_points）保存 binary_little_endian PLY，单位毫米。"""
    pts = points_m[valid_mask]
    pts = pts[np.isfinite(pts).all(axis=1)]
    if len(pts) > max_points:
        rng = np.random.default_rng(seed)
        idx = rng.choice(len(pts), max_points, replace=False)
        pts = pts[idx]
    pts_mm = (pts * 1000.0).astype("<f4")  # 米 → 毫米
    header = (
        "ply\n"
        "comment unit: millimeter (internal unit is meter, scaled x1000 on save)\n"
        "comment coordinate: left camera frame, origin at left optical center, "
        "Z along optical axis\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {len(pts_mm)}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "end_header\n"
    )
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(pts_mm.tobytes())
    return len(pts_mm)


def _stage_stats(samples: List[float]) -> Dict[str, float]:
    arr = np.asarray(samples, dtype=np.float64)
    return {"mean_ms": round(float(arr.mean()) * 1000.0, 2),
            "median_ms": round(float(np.median(arr)) * 1000.0, 2)}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="双目左右 2D 图 + 内外参离线重建点云实机基准")
    ap.add_argument("--frames", type=int, default=30)
    ap.add_argument("--out", default="tmp_stereo_bench")
    ap.add_argument("--calib", default=None, help="标定 JSON 路径（默认 <out>/calib.json）")
    ap.add_argument("--skip-calib", action="store_true",
                    help="无 JSON 时不进入交互标定，直接退出码 2")
    args = ap.parse_args()

    if RVC is None:
        print("[EXIT 2] 未安装 PyRVC")
        return 2

    RVC.SystemInit()
    cam = None
    try:
        _ret, devices = RVC.SystemListDevices(RVC.SystemListDeviceTypeEnum.All)
        if not devices:
            print("[EXIT 2] 未发现相机")
            return 2
        cam = CamHandle(devices[0])
        if not cam.open():
            print("[EXIT 2] 第一台 X2 打开失败")
            return 2
        x2 = cam.camera
        print(f"已打开设备 0（X2），将跑 {args.frames} 轮")

        # 采集参数读-改-写（铁律：禁止默认构造 X2_CaptureOptions 直接用）
        try:
            opt = x2.LoadCaptureOptionParameters()
            opt.enable_2d_in_capture = True
            x2.SaveCaptureOptionParameters(opt)
            print("已开启 enable_2d_in_capture（Load → 改 → Save）")
        except Exception as e:
            print(f"[EXIT 2] 采集参数读写失败: {e}")
            return 2

        # 内参（RVC 畸变顺序 k1 k2 k3 p1 p2，取原始顺序打日志后重排）
        K_l, dist_l_rvc, dist_l_cv = extract_intrinsics(
            x2.GetIntrinsicParameters(RVC.CameraID_Left), "Left")
        K_r, dist_r_rvc, dist_r_cv = extract_intrinsics(
            x2.GetIntrinsicParameters(RVC.CameraID_Right), "Right")

        # 外参：--calib JSON 优先；否则交互标定；--skip-calib 且无 JSON 则退出 2
        os.makedirs(args.out, exist_ok=True)
        calib_path = args.calib or os.path.join(args.out, "calib.json")
        if os.path.isfile(calib_path):
            calib = load_calib(calib_path)
            print(f"已加载标定: {calib_path}")
        elif args.skip_calib:
            print(f"[EXIT 2] --skip-calib 且标定 JSON 不存在: {calib_path}")
            return 2
        else:
            # 标定前先导出一对图确定分辨率
            mode0, l0, r0, note0 = grab_pair(x2)
            if l0 is None:
                print(f"[EXIT 2] 标定前取图失败（{mode0}: {note0}）")
                return 2
            img_size = (l0.shape[1], l0.shape[0])
            calib = calibrate_interactive(x2, K_l, K_r, dist_l_rvc, dist_r_rvc, img_size)
            if calib is None:
                return 2
            with open(calib_path, "w", encoding="utf-8") as f:
                json.dump(calib, f, ensure_ascii=False, indent=2)
            print(f"标定已保存: {calib_path}")

        R = np.asarray(calib["R"], dtype=np.float64).reshape(3, 3)
        T = np.asarray(calib["T"], dtype=np.float64).reshape(3)

        # 取图模式探测（第 1 轮复用本次结果）
        print("\n=== 取图模式探测 ===")
        mode, left0, right0, note = grab_pair(x2)
        print(f"模式 = {mode}: {note}")
        if mode == "unavailable":
            print("[EXIT 2] 右图不可用，无法做双目重建")
            return 2
        w, h = int(left0.shape[1]), int(left0.shape[0])
        image_size = tuple(calib.get("image_size") or [w, h])
        if tuple(image_size) != (w, h):
            print(f"[WARN] 标定 image_size={image_size} 与实测 {(w, h)} 不一致，以实测为准")
            image_size = (w, h)
        print(f"分辨率 = {image_size[0]}x{image_size[1]}")

        # 构造重建器（开销不计入帧耗时）
        recon = StereoReconstructor(K_l, dist_l_cv, K_r, dist_r_cv, R, T, image_size)

        # 计时基准：SDK 同帧 GetPointMap 的 Z 中位数（数量级对照，不做硬断言）
        sdk_z_med_mm = None
        try:
            pm = x2.GetPointMap()
            pm_np = np.asarray(pm.Clone(), copy=True)
            pmv = pm_np.reshape(-1, 3)
            z = pmv[:, 2]
            z = z[np.isfinite(z) & (np.abs(z) > 1e-6)]
            if len(z):
                sdk_z_med_mm = float(np.median(z))
        except Exception as e:
            print(f"[WARN] GetPointMap 对照读取失败: {e}")

        # 帧循环：4 阶段计时（采集 / 拷贝 / remap+SGBM / reproject）
        stages: Dict[str, List[float]] = {"capture": [], "copy": [],
                                          "match": [], "reproject": []}
        first = {"left": left0, "right": right0, "disp": None,
                 "points": None, "valid": None}
        print(f"\n=== 计时基准（{args.frames} 轮）===")
        wall0 = time.perf_counter()
        for i in range(args.frames):
            t0 = time.perf_counter()
            if i == 0:
                mode_i, left, right = mode, left0, right0
            else:
                mode_i, left, right, _note = grab_pair(x2)
                if left is None or right is None:
                    print(f"[WARN] 第 {i} 轮取图失败，跳过")
                    continue
            t1 = time.perf_counter()
            left_np = np.asarray(left, copy=True)
            right_np = np.asarray(right, copy=True)
            t2 = time.perf_counter()
            disp = recon.compute_disparity(left_np, right_np)
            t3 = time.perf_counter()
            points, valid = recon.disparity_to_points(disp)
            t4 = time.perf_counter()
            stages["capture"].append(t1 - t0)
            stages["copy"].append(t2 - t1)
            stages["match"].append(t3 - t2)
            stages["reproject"].append(t4 - t3)
            if i == 0:
                first.update({"disp": disp, "points": points, "valid": valid})
        wall = time.perf_counter() - wall0
        n_frames = len(stages["capture"])
        if n_frames == 0:
            print("[EXIT 2] 没有成功采集到任何帧")
            return 2
        e2e_fps = n_frames / wall if wall > 0 else 0.0

        # 第 1 轮结果落盘
        left_png = os.path.join(args.out, "left.png")
        right_png = os.path.join(args.out, "right.png")
        disp_png = os.path.join(args.out, "disparity.png")
        ply_path = os.path.join(args.out, "sample.ply")
        cv2.imwrite(left_png, first["left"])
        cv2.imwrite(right_png, first["right"])
        disp_vis = cv2.normalize(first["disp"], None, 0, 255,
                                 cv2.NORM_MINMAX, dtype=cv2.CV_8U)
        cv2.imwrite(disp_png, cv2.applyColorMap(disp_vis, cv2.COLORMAP_JET))
        n_pts = save_sample_ply(ply_path, first["points"], first["valid"])

        recon_z_med_m = 0.0
        fv = first["valid"]
        if fv.any():
            recon_z_med_m = float(np.median(first["points"][..., 2][fv]))

        # 报告
        report = {
            "grab_mode": mode,
            "grab_mode_note": note,
            "image_size": [image_size[0], image_size[1]],
            "frames_requested": args.frames,
            "frames_ok": n_frames,
            "wall_time_s": round(wall, 3),
            "end_to_end_fps": round(e2e_fps, 2),
            "stages_ms": {k: _stage_stats(v) for k, v in stages.items()},
            "sgbm_params": recon.sgbm_params,
            "sdk_pointmap_z_median_mm": sdk_z_med_mm,
            "reconstructed_z_median_m": round(recon_z_med_m, 5),
            "reconstructed_z_median_mm": round(recon_z_med_m * 1000.0, 2),
            "outputs": {"left": left_png, "right": right_png,
                        "disparity": disp_png, "sample_ply": ply_path,
                        "sample_ply_points": n_pts},
            "unit_convention": ("内部点云单位米（左相机系）；sample.ply 保存为毫米"),
        }
        report_path = os.path.join(args.out, "report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print("\n=== 结果汇总 ===")
        print(f"取图模式      : {mode} ({note})")
        print(f"分辨率        : {image_size[0]}x{image_size[1]}")
        print(f"成功帧数      : {n_frames}/{args.frames}")
        for k, label in (("capture", "采集一对图"), ("copy", "图像数据拷贝"),
                         ("match", "remap+SGBM"), ("reproject", "reproject3D")):
            s = report["stages_ms"][k]
            print(f"{label:<12}: 均值 {s['mean_ms']:>8.2f} ms / 中位 {s['median_ms']:>8.2f} ms")
        print(f"端到端        : {e2e_fps:.2f} 点云对/秒（含采集）")
        if sdk_z_med_mm is not None:
            print(f"Z 中位数对照  : SDK GetPointMap = {sdk_z_med_mm:.1f} mm，"
                  f"离线重建 = {recon_z_med_m * 1000.0:.1f} mm（仅数量级参考）")
        print(f"输出          : {left_png}, {right_png}, {disp_png}, "
              f"{ply_path} ({n_pts} 点, 毫米)")
        print(f"报告          : {report_path}")
        return 0
    finally:
        if cam is not None:
            cam.close()
        RVC.SystemShutdown()


if __name__ == "__main__":
    sys.exit(main())
