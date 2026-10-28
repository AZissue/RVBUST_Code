# -*- coding: utf-8 -*-
"""
calib_rig_from_coded_circle.py —— 编码圆自检测法求左右相机 rig（不依赖 SDK 板检测）

与 calib_rig_from_board.py 的区别：不用 GetExtrinsicMatrix（板→相机），而是
**自己检测**编码圆——src/core/marker_detector.py 的 detect() 走
``RVC.DetectCodedCircleMarker``，返回每个编码圆的 (code, x, y)。编码圆自带唯一
编号，左右图按 code 配对零歧义；圆心亚像素精度；板面圆心间距是生成时设定的物理
尺寸 → rig 自带米制尺度。 stereoCalibrate(CALIB_FIX_INTRINSIC) 一次解出 R/T。

用法（三步）
----------
1. 生成标定板（会同时产出 board.png 与 layout.json，两者必须配套打印）：
     python calib_rig_from_coded_circle.py --gen-board board_out
     可选：--radius-mm 6 --page A4 --scale 1.0 --margin-mm 5 --dpi 300
           （板太远检测不到就把 --radius-mm 加大到 10~12、换 A3）

2. 打印 board_out/board.png（实际尺寸 100%，不要缩放），贴到平整板面上。

3a. 实机采样式标定（相机连上，逐个样本微调板位）：
     python calib_rig_from_coded_circle.py --sn M3GM150W005 \
         --layout board_out/layout.json --samples 8 --out rig.json \
         [--scene-dir <历史数据目录> --clahe]

3b. 或离线图片对（早已拍好的左右图，每对之间用逗号）：
     python calib_rig_from_coded_circle.py --layout board_out/layout.json \
         --pairs L1.png,R1.png L2.png,R2.png --out rig.json

判据
----
- 每对图公共编码圆 ≥6（建议 ≥8），打印检出数便于诊断曝光/尺寸问题；
- 每样本 rig 相对旋转 <1.5°、基线 10~300mm；
- 多样本基线 std <1mm；
- 可选 --scene-dir 重建出米制 Z，用卷尺核对。

退出码：0 = 通过并保存；1 = 失败（原因已打印）；2 = 无相机/无 SDK。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import cv2

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_HERE, _REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import PyRVC as RVC
except ImportError:
    RVC = None

from reconstruct_from_files import _imread_unicode  # noqa: E402
from calib_rig_from_board import quat_avg            # noqa: E402

# A 系页面尺寸（与 prototypes/coded_circle_ui/generator.py 一致）
_PAGE_MM = {"A1": (594, 841), "A2": (420, 594), "A3": (297, 420),
            "A4": (210, 297), "A5": (148, 210), "A6": (105, 148)}


# ---------------------------------------------------------------------------
# 标定板生成 + 布局（圆心物理坐标，mm，板系：x 向右，y 向下，z=0）
# ---------------------------------------------------------------------------
def board_layout(radius_mm, scale, page, dpi, margin_mm, n_codes):
    """生成板图并给出每个编码圆圆心的物理坐标（mm，板系：x 向右，y 向下，z=0）。

    布局公式与 generator.generate_page **像素级一致**：先按生成器的 px 公式排版，
    再把圆心 px 换算回 mm —— 保证 layout 与实际打印/显示严格对应。
    """
    sys.path.insert(0, os.path.join(_REPO, "prototypes", "coded_circle_ui"))
    from generator import (generate_valid_codes, generate_full_board,
                           CodedCircleParams, _mm_to_px, _page_size_px)

    radius_eff = radius_mm * scale
    width_px, height_px = _page_size_px(page.upper(), dpi)
    radius_px = _mm_to_px(radius_eff, dpi)
    margin_px = _mm_to_px(margin_mm, dpi)
    cell_px = int(2 * radius_px * 5.0)
    cols = max(1, (width_px - 2 * margin_px) // cell_px)
    rows = max(1, (height_px - 2 * margin_px) // cell_px)
    cap = min(n_codes, cols * rows)
    codes = generate_valid_codes(8)[:cap]

    px_to_mm = 25.4 / dpi
    points = {}
    for idx, code in enumerate(codes):
        row, col = idx // cols, idx % cols
        cx_px = margin_px + col * cell_px + cell_px / 2.0
        cy_px = margin_px + row * cell_px + cell_px / 2.0
        points[int(code)] = [round(cx_px * px_to_mm, 4), round(cy_px * px_to_mm, 4)]
    params = CodedCircleParams(radius_mm=radius_mm, scale=scale,
                               page_type=page.upper(), dpi=dpi, margin_mm=margin_mm)
    img, codes_used, _ = generate_full_board(params, codes=codes)
    return img, {"params": {"radius_mm": radius_mm, "scale": scale, "page": page.upper(),
                            "dpi": dpi, "margin_mm": margin_mm,
                            "cell_mm": round(cell_px * px_to_mm, 4),
                            "cols": cols, "rows": rows},
                 "codes": [int(c) for c in codes_used],
                 "points": {str(k): v for k, v in points.items()}}


def cmd_gen_board(args) -> int:
    os.makedirs(args.gen_board, exist_ok=True)
    img, layout = board_layout(args.radius_mm, args.scale, args.page, args.dpi,
                               args.margin_mm, args.codes_count)
    png = os.path.join(args.gen_board, "board.png")
    meta = os.path.join(args.gen_board, "layout.json")
    ok, buf = __import__("cv2").imencode(".png", img)
    buf.tofile(png)
    with open(meta, "w", encoding="utf-8") as f:
        json.dump(layout, f, ensure_ascii=False, indent=2)
    p = layout["params"]
    print(f"[板] {p['cols']}×{p['rows']} 个编码圆, 圆心距 {p['cell_mm']}mm, "
          f"半径 {args.radius_mm * args.scale}mm, {p['page']} {p['dpi']}dpi")
    print(f"[输出] {png}")
    print(f"[输出] {meta}  ← 标定时必须传 --layout 指向它（与打印件配套）")
    print("\n打印要求：实际尺寸 100%（关闭'适应页面'），贴到平整刚性板面。")
    return 0


# ---------------------------------------------------------------------------
# 检测
# ---------------------------------------------------------------------------
def make_detector():
    from src.core.marker_detector import MarkerDetector, MARKER_TYPE_CODED_CIRCLE
    det = MarkerDetector(marker_type=MARKER_TYPE_CODED_CIRCLE)
    return det


def detect_map(detector, gray) -> dict:
    """返回 {code: (x, y)}（全分辨率像素系）。"""
    out = {}
    for m in detector.detect(gray):
        out[int(m["code"])] = (float(m["x"]), float(m["y"]))
    return out


# ---------------------------------------------------------------------------
# 单对左右图 → rig（stereoCalibrate，内参固定出厂值）
# ---------------------------------------------------------------------------
def rig_from_pair(layout, det_l, det_r, K_l, d_l, K_r, d_r, image_size):
    common = sorted(set(det_l) & set(det_r))
    if len(common) < 6:
        return None, len(det_l), len(det_r), len(common), 0.0
    obj = np.array([layout["points"][str(c)] for c in common], dtype=np.float32)
    obj = np.column_stack([obj, np.zeros(len(obj), dtype=np.float32)])  # N×3, 板系 Z=0, 米
    obj = obj / 1000.0
    pl = np.array([det_l[c] for c in common], dtype=np.float32)
    pr = np.array([det_r[c] for c in common], dtype=np.float32)
    rms, _, _, _, _, R, T, _, _ = cv2.stereoCalibrate(
        [obj], [pl], [pr], K_l, d_l, K_r, d_r,
        imageSize=tuple(image_size), flags=cv2.CALIB_FIX_INTRINSIC,
        criteria=(cv2.TERM_CRITERIA_MAX_ITER + cv2.TERM_CRITERIA_EPS, 200, 1e-7))
    return (R, T.ravel()), len(det_l), len(det_r), len(common), float(rms)


def _rel_rot_deg(R) -> float:
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0))))


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="编码圆自检测法求左右 rig")
    ap.add_argument("--gen-board", default=None, metavar="DIR",
                    help="生成标定板 PNG+layout.json 到该目录后退出")
    ap.add_argument("--radius-mm", type=float, default=6.0)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--page", default="A4")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--margin-mm", type=float, default=5.0)
    ap.add_argument("--codes-count", type=int, default=12)
    ap.add_argument("--layout", default=None, help="layout.json 路径（标定必传）")
    ap.add_argument("--sn", default=None, help="相机 SN（实机模式；内参实时从相机读）")
    ap.add_argument("--pairs", nargs="*", default=None,
                    help="离线模式：每对 '左图,右图'；此时必须 --intrinsics")
    ap.add_argument("--intrinsics", default=None,
                    help="camera_parameters.json（capture_m_dual_2d_and_params.py 输出格式）")
    ap.add_argument("--samples", type=int, default=8)
    ap.add_argument("--exposure-2d-ms", type=float, default=30.0)
    ap.add_argument("--out", default="rig_codedcircle.json")
    ap.add_argument("--scene-dir", default=None)
    ap.add_argument("--clahe", action="store_true")
    args = ap.parse_args()

    if args.gen_board:
        return cmd_gen_board(args)

    if not args.layout:
        print("[错误] 标定模式必须 --layout 指向生成板时的 layout.json")
        return 1
    with open(args.layout, encoding="utf-8") as f:
        layout = json.load(f)

    from core.stereo_reconstruct import rvc_dist_to_opencv

    def _parse_intr(params_json, key):
        intr = params_json["intrinsic"][key]
        K = np.asarray(intr["matrix_3x3"], dtype=np.float64).reshape(3, 3)
        k1, k2, k3, p1, p2 = intr["distortion_k1k2k3p1p2"]
        return K, rvc_dist_to_opencv(k1, k2, k3, p1, p2)

    K_l = d_l = K_r = d_r = None

    # ---- 采集/载入左右图对 ----
    pairs = []    # (gray_left, gray_right)
    if args.sn:
        if RVC is None:
            print("[错误] 无 PyRVC")
            return 2
        RVC.SystemInit()
        try:
            device = RVC.SystemFindDevice(args.sn)
            if not device.IsValid():
                print(f"[错误] 未找到 SN={args.sn}")
                return 2
            ok, info = device.GetDeviceInfo()
            print(f"[相机] {info.name}  SN={info.sn}")
            x = RVC.X2.Create(device)
            if not x.Open() or not x.IsOpen():
                print(f"[错误] 打开失败：{RVC.GetLastErrorMessage()}")
                return 2
            try:
                # 内参：实机模式直接从相机读（出厂固化值）
                for name, cid, slot in (("左相机", RVC.CameraID_Left, "l"),
                                        ("右相机", RVC.CameraID_Right, "r")):
                    ret_i, K, dist = x.GetIntrinsicParameters(cid)
                    if not ret_i:
                        print(f"[错误] {name} 内参读取失败")
                        return 1
                    K = np.asarray(K, dtype=np.float64).reshape(3, 3)
                    d = np.asarray(dist, dtype=np.float64).flatten()
                    if slot == "l":
                        K_l, d_l = K, rvc_dist_to_opencv(*d)
                    else:
                        K_r, d_r = K, rvc_dist_to_opencv(*d)
                print(f"[内参] 左 fx={K_l[0,0]:.1f} 右 fx={K_r[0,0]:.1f}（相机实时读取）")

                cap_opt = RVC.X2_CaptureOptions()
                cap_opt.exposure_time_2d = int(args.exposure_2d_ms)
                print(f"\n>>> 打印好的编码圆板置于左右共视视野；采 {args.samples} 个样本，"
                      f"每个样本微调板位。\n")
                for i in range(args.samples):
                    input(f"  [{i + 1}/{args.samples}] 调整好板位后按回车采集...")
                    frames = {}
                    for name, cid in (("左", RVC.CameraID_Left), ("右", RVC.CameraID_Right)):
                        if not x.Capture2D(cid, cap_opt):
                            print(f"    Capture2D({name}) 失败：{RVC.GetLastErrorMessage()}")
                            continue
                        img = x.GetImage(cid)
                        arr = np.asarray(img, copy=True) if img is not None else None
                        if arr is not None and arr.ndim == 3:
                            arr = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
                        frames[name] = arr
                    if frames.get("左") is not None and frames.get("右") is not None:
                        pairs.append((frames["左"], frames["右"]))
                    else:
                        print("    本样本取图失败")
            finally:
                x.Close()
                RVC.X2.Destroy(x)
        finally:
            RVC.SystemShutdown()
    elif args.pairs:
        if not args.intrinsics:
            print("[错误] 离线 --pairs 模式必须 --intrinsics 指定 camera_parameters.json")
            return 1
        with open(args.intrinsics, encoding="utf-8") as f:
            params_json = json.load(f)
        K_l, d_l = _parse_intr(params_json, "左相机")
        K_r, d_r = _parse_intr(params_json, "右相机")
        for spec in args.pairs:
            a, b = spec.split(",")
            pairs.append((_imread_unicode(a.strip()), _imread_unicode(b.strip())))
    else:
        print("[错误] 需 --sn（实机）或 --pairs（离线图片对）之一")
        return 1

    if not pairs:
        print("[失败] 没有可用图对")
        return 1

    # ---- 逐对检测 + 求 rig ----
    detector = make_detector()
    rig_samples, rms_list = [], []
    for i, (gl, gr) in enumerate(pairs):
        dl = detect_map(detector, gl)
        dr = detect_map(detector, gr)
        if not dl or not dr:
            print(f"  [样本{i+1}] 检出 左{len(dl)} 右{len(dr)} → 跳过（检查曝光/板距/打印比例）")
            continue
        res, nl, nr, nc, rms = rig_from_pair(
            layout, dl, dr, K_l, d_l, K_r, d_r,
            image_size=(gl.shape[1], gl.shape[0]))
        if res is None:
            print(f"  [样本{i+1}] 检出 左{nl} 右{nr} 公共{nc} <6 → 跳过")
            continue
        R, T = res
        base_mm = float(np.linalg.norm(T) * 1000.0)
        deg = _rel_rot_deg(R)
        print(f"  [样本{i+1}] 公共圆 {nc} 个, rms {rms:.3f}px, "
              f"基线 {base_mm:.1f}mm, 相对旋转 {deg:.2f}°")
        if deg >= 1.5 or not (10.0 <= base_mm <= 300.0):
            print(f"    ⚠️ 超出合理性范围（旋转<1.5°、基线10~300mm），丢弃该样本")
            continue
        rig_samples.append((R, T))
        rms_list.append(rms)

    if len(rig_samples) < 1:
        print("[失败] 无有效 rig 样本。诊断：打印是否 100% 实际尺寸？"
              "板距是否太远（圆太小）？曝光是否过曝/欠曝？")
        return 1

    # ---- 聚合 + 保存 ----
    R_avg = quat_avg([R for R, _ in rig_samples])
    t_avg = np.median(np.array([T for _, T in rig_samples]), axis=0)
    base_mm = float(np.linalg.norm(t_avg) * 1000.0)
    base_spread = float(np.std([np.linalg.norm(T) * 1000.0 for _, T in rig_samples]))
    result = {
        "R": R_avg.tolist(),
        "T": t_avg.tolist(),
        "unit": "meter",
        "baseline_mm": round(base_mm, 3),
        "source": "coded_circle self-detect + stereoCalibrate(FIX_INTRINSIC)",
        "layout": os.path.abspath(args.layout),
        "samples": len(rig_samples),
        "stereo_rms_px_each": [round(v, 3) for v in rms_list],
        "baseline_spread_mm": round(base_spread, 3),
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n[输出] rig → {args.out}  基线 {result['baseline_mm']}mm "
          f"(多样本 std {base_spread:.3f}mm), 平均 rms {np.mean(rms_list):.3f}px")

    # ---- 可选：立即重建历史数据验证尺度 ----
    if args.scene_dir:
        print("\n[验证] 用新 rig 重建 --scene-dir（米制）...")
        from reconstruct_from_files import load_dataset, save_ply
        from core.stereo_reconstruct import StereoReconstructor
        data = load_dataset(args.scene_dir)
        il, ir = data["imgs"]["left"], data["imgs"]["right"]
        if il.ndim == 3:
            il = cv2.cvtColor(il, cv2.COLOR_BGR2GRAY)
        if ir.ndim == 3:
            ir = cv2.cvtColor(ir, cv2.COLOR_BGR2GRAY)
        rec = StereoReconstructor(
            data["K_left"], data["dist_left"], data["K_right"], data["dist_right"],
            R_avg, t_avg, data["image_size"],
            sgbm_params={"numDisparities": 384, "uniquenessRatio": 15,
                         "speckleWindowSize": 150})
        if args.clahe:
            enh = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            disp = rec.compute_disparity(enh.apply(il), enh.apply(ir))
        else:
            disp = rec.compute_disparity(il, ir)
        disp_f = cv2.medianBlur(np.clip(disp * 16, -32768, 32767).astype(np.int16), 5
                                ).astype(np.float32) / 16.0
        points, valid = rec.disparity_to_points(disp_f)
        z = points[:, :, 2]
        keep = valid & (z > 0.5) & (z < 15.0)     # 室内场景合理深度带（米）
        ply = os.path.join(args.scene_dir, "重建点云_ccrig.ply")
        save_ply(ply, points, keep)               # 真尺度 → 毫米
        zz = points[:, :, 2][keep]
        if len(zz):
            print(f"  有效点 {int(keep.sum())}, Z(米): p1={np.percentile(zz, 1):.2f} "
                  f"中位={np.median(zz):.2f} p99={np.percentile(zz, 99):.2f}")
        print(f"  → {ply}")
        print("  请用卷尺/激光尺实测核对 Z 中位数。")

    print("\n[结论] 编码圆自检测标定完成 ✅" if len(rig_samples) >= 3 else
          "\n[结论] 完成但有效样本 <3，精度有限 ⚠️")
    return 0


if __name__ == "__main__":
    sys.exit(main())
