# -*- coding: utf-8 -*-
"""
reconstruct_from_files.py —— 用已保存的左右 2D 图 + camera_parameters.json 离线重建点云。

数据来源约定（与 capture_m_dual_2d_and_params.py 的输出格式兼容）：
  <data_dir>/camera_parameters.json   intrinsic（含两种畸变顺序）+ extrinsic（标定板→相机）
  <data_dir>/左相机_2D.png / 右相机_2D.png

左右相对位姿的来源（--rig）：
  composed  : R,T = extrinsic[右] @ inv(extrinsic[左])。⚠️ 仅当两个外参基于**同一标定板
              位姿**采集时才成立；若两路外参来自不同标定时刻（固件各自保存），组合结果
              物理上不合理（实测 M3GM150W005：相对旋转 ~14°、基线 423mm 以 Y 为主），
              脚本会做合理性检查并在报告中红字告警。
  features  : SIFT 特征 + 本质矩阵从当前图像对在线估计 R,T（旋转/基线方向可靠，
              **尺度任意**，report 中 baseline_units=1）。
  <路径.json>: 直接给定 {"R": 3x3, "T": [3]}（如实机 stereoCalibrate 一次标定的结果，
              刚体常量可复用于历史图像）。

输出（写入 --out，默认 = data_dir）：
  重建点云_<rig>.ply   单位毫米（features 模式为基线单位，见报告）
  视差图_<rig>.png     turbo 伪彩，灰度=无效
  重建报告_<rig>.json  位姿来源 / 合理性检查 / 有效点统计 / Z 分布 / 分段计时

退出码：0 = 成功（含告警）；1 = 数据缺失或重建失败。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import cv2
import numpy as np

# 定位仓库根（含 src/ 或 prototypes/ 的祖先），加入 sys.path 后 import 原型 core
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "..")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from core.stereo_reconstruct import StereoReconstructor, rvc_dist_to_opencv  # noqa: E402


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def _imread_unicode(path: str, flags: int = cv2.IMREAD_UNCHANGED):
    """支持中文路径的 imread（OpenCV 在 Windows 下按 ANSI 解析路径会读不了中文）。"""
    buf = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(buf, flags)
    return img


def _imwrite_unicode(path: str, img: np.ndarray) -> bool:
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if ok:
        buf.tofile(path)
    return bool(ok)


def load_dataset(data_dir: str):
    json_path = os.path.join(data_dir, "camera_parameters.json")
    if not os.path.isfile(json_path):
        raise FileNotFoundError(f"缺少 {json_path}")
    with open(json_path, encoding="utf-8") as f:
        params = json.load(f)

    imgs = {}
    for label, key in (("left", "左相机"), ("right", "右相机")):
        file_name = params["images"][key]["file"]
        path = os.path.join(data_dir, file_name)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"缺少 {path}")
        img = _imread_unicode(path)
        if img is None:
            raise ValueError(f"图像读取失败: {path}")
        imgs[label] = img

    def _intr(label_key):
        intr = params["intrinsic"][label_key]
        K = np.asarray(intr["matrix_3x3"], dtype=np.float64).reshape(3, 3)
        k1, k2, k3, p1, p2 = intr["distortion_k1k2k3p1p2"]
        dist = rvc_dist_to_opencv(k1, k2, k3, p1, p2)  # 走一遍重排，不直接用现成字段
        return K, dist

    K_l, d_l = _intr("左相机")
    K_r, d_r = _intr("右相机")
    h, w = imgs["left"].shape[:2]
    if imgs["right"].shape[:2] != (h, w):
        raise ValueError("左右图尺寸不一致")
    return {
        "params": params, "imgs": imgs,
        "K_left": K_l, "dist_left": d_l, "K_right": K_r, "dist_right": d_r,
        "image_size": (w, h),
    }


# ---------------------------------------------------------------------------
# 位姿来源
# ---------------------------------------------------------------------------
def _rel_rotation_deg(R: np.ndarray) -> float:
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0))))


def compose_rig_from_extrinsics(params: dict):
    """由两个「标定板→相机」4x4 组合出「左→右」相对位姿，并做合理性检查。"""
    T_l = np.asarray(params["extrinsic"]["左相机"]["matrix_4x4"], dtype=np.float64).reshape(4, 4)
    T_r = np.asarray(params["extrinsic"]["右相机"]["matrix_4x4"], dtype=np.float64).reshape(4, 4)
    T_rel = T_r @ np.linalg.inv(T_l)
    R, t = T_rel[:3, :3], T_rel[:3, 3]
    base_mm = float(np.linalg.norm(t) * 1000.0)
    rel_deg = _rel_rotation_deg(R)
    warnings = []
    if rel_deg > 3.0:
        warnings.append(
            f"左右相机相对旋转 {rel_deg:.2f}° —— 刚性双目机构不应超过 ~1°，"
            "说明两个外参不是基于同一标定板位姿，组合结果不可用于重建")
    if not (10.0 <= base_mm <= 300.0):
        warnings.append(
            f"基线长度 {base_mm:.1f}mm 超出刚性双目常见范围 (10~300mm)，"
            "同样指向外参非同源")
    return R, t, {
        "mode": "composed",
        "relative_rotation_deg": round(rel_deg, 3),
        "baseline_mm": round(base_mm, 2),
        "translation": [round(float(v), 6) for v in t],
        "warnings": warnings,
    }


def estimate_rig_from_features(K_l, d_l, K_r, d_r, img_l, img_r,
                               image_size=None, dy_max_px: float = 15.0):
    """SIFT + 本质矩阵估计左→右 R,T（尺度任意）。返回 R,t,info。

    弱纹理场景两步防错配：
    1. contrastThreshold 降到 0.01（默认 0.04 在平板画面上几乎提不出点），
       但不到 1e-3 —— 那个量级提出来的全是噪声点，误配淹没问题结构；
    2. 出厂双目机构已近似行对准，真匹配 |v_l - v_r| 只有几个像素 ——
       用它做几何先验过滤，随机误配的 dy 是百像素量级，一滤就掉。
    """
    sift = cv2.SIFT_create(contrastThreshold=0.01, edgeThreshold=24, sigma=2.0)
    kp_l, des_l = sift.detectAndCompute(img_l, None)
    kp_r, des_r = sift.detectAndCompute(img_r, None)
    if des_l is None or des_r is None or len(kp_l) < 50 or len(kp_r) < 50:
        raise RuntimeError("特征点过少，无法估计位姿")
    matches = cv2.BFMatcher(cv2.NORM_L2).knnMatch(des_l, des_r, k=2)
    good = [m for m, n in matches if m.distance < 0.75 * n.distance]
    if len(good) < 30:
        raise RuntimeError(f"good 匹配太少 ({len(good)})，无法估计位姿")

    pts_l = np.float32([kp_l[m.queryIdx].pt for m in good])
    pts_r = np.float32([kp_r[m.trainIdx].pt for m in good])
    # 几何先验过滤：行对准机构纵向视差小；按档放宽直到剩余足够对数
    n_before = len(good)
    dy = np.abs(pts_l[:, 1] - pts_r[:, 1])
    dy_used = None
    for cand in (15.0, 25.0, 40.0, 80.0):
        keep = dy <= cand
        if int(keep.sum()) >= 20:
            dy_used = cand
            pts_l, pts_r = pts_l[keep], pts_r[keep]
            break
    if dy_used is None:
        raise RuntimeError(
            f"|dy| 放到 80px 仍不足 20 对（best={int((dy <= 80).sum())}），无法估计位姿")
    pts_l = pts_l.reshape(-1, 1, 2)
    pts_r = pts_r.reshape(-1, 1, 2)

    # 各自去畸变到归一化坐标，再用单位内参求 E（兼容两相机内参不同）
    n_l = cv2.undistortPoints(pts_l, K_l, d_l).reshape(-1, 2)
    n_r = cv2.undistortPoints(pts_r, K_r, d_r).reshape(-1, 2)
    E, mask = cv2.findEssentialMat(
        n_l, n_r, focal=1.0, pp=(0.0, 0.0),
        method=cv2.RANSAC, prob=0.999, threshold=1e-3)
    if E is None or E.shape[0] != 3:
        raise RuntimeError("本质矩阵估计失败")
    if E.shape[1] != 3:          # findEssentialMat 偶尔返回多解横排 (3x6)，取第一解
        E = E[:, :3]
    inl = mask.ravel() > 0
    # 点已各自去畸变并归一化，传单位内参的 4 参数重载（points 为 Nx2 float）
    # 注意：本版本 recoverPose 的 mask 内点写 255 而非 1，不能 sum() 计数
    n_ret, R, t, pose_mask = cv2.recoverPose(E, n_l[inl], n_r[inl], np.eye(3))
    inliers = int(n_ret)
    n_in = n_l[inl]
    n_in_r = n_r[inl]

    # T 符号自定：弱纹理下 recoverPose 的 cheirality 不可信，用自己的三角化
    # 取 RANSAC 内点（不只 cheirality 幸存点）判深度符号
    P1 = np.hstack([np.eye(3), np.zeros((3, 1))])

    def _med_z(R_, t_):
        P2 = np.hstack([R_, t_.reshape(3, 1)])
        X = cv2.triangulatePoints(P1, P2, n_in.T, n_in_r.T)
        return float(np.median(X[2] / X[3]))

    t = t.ravel()
    if _med_z(R, t) < 0:
        t = -t
    t = t / (np.linalg.norm(t) + 1e-12)  # 尺度归一：基线 = 1 单位
    z_median_units = _med_z(R, t)

    # 内点极线误差中位数（归一化坐标 ×f 折算像素量级）
    Fn_l = np.column_stack([n_in, np.ones(len(n_in))])
    Fn_r = np.column_stack([n_in_r, np.ones(len(n_in_r))])
    E_full = skew(t) @ R
    line_r = Fn_l @ E_full.T                      # 右图对应极线
    num = np.abs((Fn_r * line_r).sum(axis=1))
    den = np.linalg.norm(line_r[:, :2], axis=1) + 1e-12
    epi_inlier = float(np.median(num / den)) * float(K_l[0, 0])

    # 矫正系真实视差带：把 RANSAC 内点投进矫正坐标系，给 SGBM 定搜索范围。
    # 弱纹理下误配视差趋于 0（Z→∞ 的扇形飞点长尾），把搜索带收紧到匹配支持
    # 的区间能从源头掐掉飞点。
    disp_band = None
    if image_size is not None:
        R1, R2, P1, P2, _Q, *_ = cv2.stereoRectify(
            K_l, d_l, K_r, d_r, tuple(image_size), R, t,
            flags=cv2.CALIB_ZERO_DISPARITY)
        q_l = cv2.undistortPoints(n_in.reshape(-1, 1, 2), K_l, d_l, R=R1, P=P1).reshape(-1, 2)
        q_r = cv2.undistortPoints(n_in_r.reshape(-1, 1, 2), K_r, d_r, R=R2, P=P2).reshape(-1, 2)
        d_rect = q_l[:, 0] - q_r[:, 0]
        v_rect = q_l[:, 1] - q_r[:, 1]
        disp_band = {
            "min": round(float(np.percentile(d_rect, 1)), 1),
            "median": round(float(np.median(d_rect)), 1),
            "max": round(float(np.percentile(d_rect, 99)), 1),
            "row_misalign_max_px": round(float(np.abs(v_rect).max()), 2),
        }

    return R, t, {
        "mode": "features",
        "sift_keypoints": (len(kp_l), len(kp_r)),
        "good_matches": n_before,
        "dy_used_px": dy_used,
        "dy_filtered_matches": int(len(pts_l)),
        "ransac_inliers": int(inl.sum()),
        "pose_inliers": inliers,
        "mean_epipolar_error_px": round(epi_inlier, 3),
        "triangulated_z_median_baseline_units": round(z_median_units, 2),
        "disp_band_rectified_px": disp_band,
        "baseline_units": 1.0,
        "scale": "ARBITRARY —— 旋转与基线方向可靠，绝对尺度=数值×基线长度",
    }


def skew(v):
    return np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0.0]])


def load_rig_json(path: str):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    R = np.asarray(d["R"], dtype=np.float64).reshape(3, 3)
    t = np.asarray(d["T"], dtype=np.float64).reshape(3)
    return R, t, {"mode": "json", "source": path,
                  "baseline_mm": round(float(np.linalg.norm(t) * 1000.0), 2)}


# ---------------------------------------------------------------------------
# 重建与落盘
# ---------------------------------------------------------------------------
def try_reconstruct(rec_factory, img_l, img_r, clahe: bool, try_both_signs: bool = True):
    """重建一次（或 ±T 各一次取有效率最高）。features 模式已用三角化定号，不必试双号。"""
    signs = (+1.0, -1.0) if try_both_signs else (+1.0,)
    results = []
    for sign in signs:
        rec = rec_factory(sign)
        if clahe:
            enh = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            disp = rec.compute_disparity(enh.apply(img_l), enh.apply(img_r))
        else:
            disp = rec.compute_disparity(img_l, img_r)
        points, valid = rec.disparity_to_points(disp)
        ratio = float(valid.mean())
        results.append((ratio, sign, disp, points, valid))
    results.sort(key=lambda x: -x[0])
    return results[0]


def save_ply(path: str, points_m: np.ndarray, valid: np.ndarray,
             max_points: int = 500_000, unit_scale: float = 1000.0,
             unit_name: str = "毫米"):
    pts = points_m[valid].reshape(-1, 3).astype(np.float64)
    if len(pts) > max_points:
        idx = np.random.default_rng(0).choice(len(pts), max_points, replace=False)
        pts = pts[idx]
    pts_out = pts * unit_scale
    with open(path, "w", encoding="utf-8") as f:
        f.write("ply\nformat ascii 1.0\n")
        f.write(f"comment 单位: {unit_name}; 坐标系: 左相机; 点数: {len(pts_out)}\n")
        f.write(f"element vertex {len(pts_out)}\n")
        f.write("property double x\nproperty double y\nproperty double z\nend_header\n")
        for x, y, z in pts_out:
            f.write(f"{x:.4f} {y:.4f} {z:.4f}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="离线重建：左右 2D 图 + camera_parameters.json")
    ap.add_argument("--data", required=True, help="数据目录（含 camera_parameters.json 与 PNG）")
    ap.add_argument("--rig", default="composed",
                    help="composed | features | <rig.json 路径>")
    ap.add_argument("--out", default=None, help="输出目录（默认 = --data）")
    ap.add_argument("--num-disparities", type=int, default=384)
    ap.add_argument("--clahe", action="store_true", help="SGBM 前对两图做 CLAHE 增强（弱纹理场景建议开）")
    args = ap.parse_args()
    out_dir = args.out or args.data
    os.makedirs(out_dir, exist_ok=True)

    data = load_dataset(args.data)
    img_l = data["imgs"]["left"]
    img_r = data["imgs"]["right"]
    if img_l.ndim == 3:
        img_l = cv2.cvtColor(img_l, cv2.COLOR_BGR2GRAY)
    if img_r.ndim == 3:
        img_r = cv2.cvtColor(img_r, cv2.COLOR_BGR2GRAY)

    # -- 位姿 --
    if args.rig == "composed":
        R, t, rig_info = compose_rig_from_extrinsics(data["params"])
    elif args.rig == "features":
        R, t, rig_info = estimate_rig_from_features(
            data["K_left"], data["dist_left"], data["K_right"], data["dist_right"],
            img_l, img_r, image_size=data["image_size"])
    else:
        R, t, rig_info = load_rig_json(args.rig)

    # -- SGBM 搜索范围：features 模式用匹配支持的矫正视差带（收紧+对齐 16），
    #    其余模式用宽默认带 --
    band = (rig_info.get("disp_band_rectified_px") or {})
    if band:
        lo = max(0, int(np.floor((band["min"] - 12) / 16.0)) * 16)
        hi = int(np.ceil((band["max"] + 12) / 16.0)) * 16
        num_disp = max(16, min(512, hi - lo))
        sgbm_params = {"minDisparity": lo, "numDisparities": num_disp,
                       "uniquenessRatio": 15, "speckleWindowSize": 150}
    else:
        sgbm_params = {"numDisparities": args.num_disparities}

    # -- 重建（尝试 T 正负号，取有效率最高） --
    def make_rec(sign):
        return StereoReconstructor(
            data["K_left"], data["dist_left"], data["K_right"], data["dist_right"],
            R, sign * t, data["image_size"], sgbm_params=sgbm_params)

    t0 = time.perf_counter()
    ratio, sign, disp, points, valid = try_reconstruct(
        make_rec, img_l, img_r, args.clahe,
        try_both_signs=(args.rig != "features"))
    elapsed = time.perf_counter() - t0

    pts = points[valid]
    z_stats = {}
    # 场景先验飞点过滤：features 模式有匹配特征三角化的深度中位数，只保留
    # [0.2, 2.5]×该值 的点 —— 弱纹理误配的极小视差会放大成锥状长尾（见侧视投影）
    n_fly_removed = 0
    z_ref = rig_info.get("triangulated_z_median_baseline_units")
    if z_ref and len(pts):
        z = pts[:, 2].astype(np.float64)
        keep = (z >= 0.2 * z_ref) & (z <= 2.5 * z_ref)
        n_fly_removed = int((~keep).sum())
        valid = valid.copy()
        valid[valid] = keep
        pts = points[valid]
    if len(pts):
        z = pts[:, 2].astype(np.float64)
        z_stats = {
            "z_min": round(float(np.percentile(z, 1)), 4),
            "z_median": round(float(np.median(z)), 4),
            "z_max": round(float(np.percentile(z, 99)), 4),
        }

    tag = os.path.splitext(os.path.basename(args.rig))[0] if args.rig.endswith(".json") else args.rig
    ply_path = os.path.join(out_dir, f"重建点云_{tag}.ply")
    disp_path = os.path.join(out_dir, f"视差图_{tag}.png")
    report_path = os.path.join(out_dir, f"重建报告_{tag}.json")
    if args.rig == "features":
        # 尺度任意：数值直接以基线为单位（不乘 1000），PLY 头注明
        save_ply(ply_path, points, valid, unit_scale=1.0,
                 unit_name="基线单位(尺度任意,绝对尺寸=数值×基线长度)")
    else:
        save_ply(ply_path, points, valid)

    disp_vis = np.zeros((*disp.shape, 3), dtype=np.uint8)
    dmin, dmax = disp[valid].min(), disp[valid].max()
    if dmax > dmin:
        norm = ((disp - dmin) / (dmax - dmin) * 255.0).astype(np.uint8)
        disp_vis = cv2.applyColorMap(norm, cv2.COLORMAP_TURBO)
    disp_vis[~valid] = (40, 40, 40)
    _imwrite_unicode(disp_path, disp_vis)

    report = {
        "data_dir": os.path.abspath(args.data),
        "camera": data["params"].get("camera", {}),
        "image_size": list(data["image_size"]),
        "rig": rig_info,
        "t_sign_used": int(sign),
        "clahe": bool(args.clahe),
        "num_disparities": args.num_disparities,
        "reconstruct": {
            "valid_ratio": round(ratio, 4),
            "valid_points": int(valid.sum()),
            "fly_points_removed": n_fly_removed,
            **z_stats,
            "elapsed_s": round(elapsed, 2),
        },
        "outputs": {
            "pointcloud": os.path.basename(ply_path),
            "disparity": os.path.basename(disp_path),
        },
        "notes": [
            "输出点云位于左相机坐标系，Z 沿光轴（分量深度，非台面垂直距离）",
            "features 模式尺度任意：PLY 数值以基线为单位，绝对尺寸=数值×基线长度",
            "rig.triangulated_z_median_baseline_units 为匹配特征的场景深度中位数（基线单位），"
            "可与真基线相乘估算实际距离",
            "composed 模式若带 warnings，点云不可用于测量，仅作流程验证",
        ],
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"[rig] {json.dumps(rig_info, ensure_ascii=False)}")
    print(f"[重建] 有效率 {ratio * 100:.1f}%  有效点 {int(valid.sum())}  "
          f"Z中位 {z_stats.get('z_median', float('nan'))}  耗时 {elapsed:.1f}s  T符号={int(sign)}")
    print(f"[输出] {ply_path}")
    print(f"[输出] {disp_path}")
    print(f"[输出] {report_path}")
    for w in rig_info.get("warnings", []):
        print(f"[告警] {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
