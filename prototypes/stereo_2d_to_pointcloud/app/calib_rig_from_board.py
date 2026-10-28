# -*- coding: utf-8 -*-
"""
calib_rig_from_board.py —— 出厂外参组合法求左右相机 rig（出路 A 实机验证脚本）

原理
----
SDK 暴露的 GetExtrinsicMatrix(cid) 返回「标定板坐标系 → 指定相机」的 4x4 变换。
单独看两个相机的矩阵不能组合（两路可能来自不同标定时刻，标定板系非同源——
本仓库已在 M3GM150W005 数据上实证：组合出 14.2°/423mm 的荒谬 rig）。
但如果**同一块板同时位于左右相机视野内**，同一时刻调两个相机的
GetExtrinsicMatrix，两个矩阵共享同一个标定板坐标系，组合即真 rig：

    rig = T_right @ inv(T_left)     （左相机系 → 右相机系）

板的几何由 SDK 检测，平移量自带米制单位 → rig 直接有尺度。

用法
----
    python calib_rig_from_board.py --sn M3GM150W005 --samples 8 --out rig.json
    python calib_rig_from_board.py --sn M3GM150W005 --scene-dir <数据目录>
        （出 rig 后立即用该 rig 重建历史数据，验证尺度是否恢复为米制）

流程：提示放板 → 采 N 个样本（**请逐个样本微调板的角度/位置**）→
     逐样本组合 rig → 合理性/离散度检查 → 保存 rig.json。

可行性判据（脚本自动判定并打印结论）
-------------------------------------
1. 【新鲜度】各样本的 T_left/T_right 矩阵随板位变化 → 证明 API 返回的是当前
   板位姿而非固化历史值（若无变化 → 本路线失败，转问原厂）；
2. 【合理性】每个 rig 样本相对旋转 < 1.5°、基线 10~300mm；
3. 【离散度】N 个 rig 的基线 std < 1mm、旋转 < 0.2°（板位不同会平均掉检测噪声）；
4. （可选）--scene-dir 重建出 Z 中位数为合理米制值（如墙面 2~6m）。

退出码：0 = 通过并保存；1 = 采集/检查失败（原因已打印）；2 = 无相机。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

try:
    import PyRVC as RVC
except ImportError:
    RVC = None

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "..")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _rel_rot_deg(R: np.ndarray) -> float:
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0))))


def compose_rig(T_l: np.ndarray, T_r: np.ndarray):
    T_rel = T_r @ np.linalg.inv(T_l)
    return T_rel[:3, :3], T_rel[:3, 3]


def quat_avg(Rs):
    """多旋转矩阵平均（四元数法，带符号对齐）。"""
    Q = []
    for R in Rs:
        t = np.trace(R)
        if t > 0:
            s = 0.5 / np.sqrt(t + 1.0)
            q = [0.25 / s, (R[2, 1] - R[1, 2]) * s, (R[0, 2] - R[2, 0]) * s, (R[1, 0] - R[0, 1]) * s]
        else:
            i = int(np.argmax(np.diag(R)))
            j, k = (i + 1) % 3, (i + 2) % 3
            s = 2.0 * np.sqrt(max(1e-12, 1.0 + R[i, i] - R[j, j] - R[k, k]))
            q = [(R[k, j] - R[j, k]) / s, 0.25 * s]
            q[1 + i] = 0.25 * s
            q[1 + j] = (R[j, i] + R[i, j]) / s
            q[1 + k] = (R[k, i] + R[i, k]) / s
        Q.append(np.array(q))
    Q = np.array(Q)
    Q[Q[:, 0] < 0] *= -1                     # 符号对齐
    w, v = np.linalg.eigh(Q.T @ Q)
    q_avg = v[:, -1]
    q_avg /= np.linalg.norm(q_avg)
    w_, x_, y_, z_ = q_avg
    return np.array([
        [1 - 2 * (y_ ** 2 + z_ ** 2), 2 * (x_ * y_ - w_ * z_), 2 * (x_ * z_ + w_ * y_)],
        [2 * (x_ * y_ + w_ * z_), 1 - 2 * (x_ ** 2 + z_ ** 2), 2 * (y_ * z_ - w_ * x_)],
        [2 * (x_ * z_ - w_ * y_), 2 * (y_ * z_ + w_ * x_), 1 - 2 * (x_ ** 2 + y_ ** 2)]])


def main() -> int:
    ap = argparse.ArgumentParser(description="出厂外参组合法求左右 rig（需实机+标定板）")
    ap.add_argument("--sn", required=True, help="相机 SN（多相机环境必传）")
    ap.add_argument("--samples", type=int, default=8, help="采样次数（建议 6~12，逐个微调板位）")
    ap.add_argument("--out", default="rig_board.json", help="rig 输出路径（JSON）")
    ap.add_argument("--exposure-2d-ms", type=float, default=50.0)
    ap.add_argument("--scene-dir", default=None,
                    help="可选：出 rig 后立即重建该目录（camera_parameters.json+左右PNG）")
    ap.add_argument("--clahe", action="store_true", help="scene-dir 重建时开 CLAHE")
    args = ap.parse_args()

    if RVC is None:
        print("[错误] 未安装 PyRVC")
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
            cap_opt = RVC.X2_CaptureOptions()
            cap_opt.exposure_time_2d = int(args.exposure_2d_ms)

            print("\n>>> 请将 RVC 标定板置于左右相机的共视视野内。")
            print(f">>> 采集 {args.samples} 个样本；每采一个请微调板的角度/位置。\n")

            samples = []          # (T_left, T_right)
            fails = 0
            for i in range(args.samples):
                input(f"  [{i + 1}/{args.samples}] 调整好板位后按回车采集...")
                got = {}
                for cid_name, cid in (("Left", RVC.CameraID_Left), ("Right", RVC.CameraID_Right)):
                    if not x.Capture2D(cid, cap_opt):
                        print(f"    Capture2D({cid_name}) 失败：{RVC.GetLastErrorMessage()}")
                        continue
                    try:
                        ret_e, M = x.GetExtrinsicMatrix(cid)
                    except Exception as e:
                        print(f"    GetExtrinsicMatrix({cid_name}) 异常：{e}")
                        continue
                    if ret_e:
                        got[cid_name] = np.array(M, dtype=np.float64).reshape(4, 4)
                    else:
                        print(f"    GetExtrinsicMatrix({cid_name}) 返回 false（板未检测到？）")
                if set(got) == {"Left", "Right"}:
                    samples.append((got["Left"], got["Right"]))
                    rig_R, rig_t = compose_rig(got["Left"], got["Right"])
                    print(f"    rig 样本: 基线 {np.linalg.norm(rig_t) * 1000:.1f}mm, "
                          f"相对旋转 {_rel_rot_deg(rig_R):.2f}°")
                else:
                    fails += 1
                    print("    本样本无效（两路外参未同时取到）")
                time.sleep(0.3)

            if len(samples) < 3:
                print(f"[失败] 有效样本不足（{len(samples)}/{args.samples}），无法评估")
                return 1

            # ---- 判据 1：新鲜度（矩阵随板位变化？）----
            TL = np.array([s[0] for s in samples])     # (N,4,4)
            TR = np.array([s[1] for s in samples])
            def _varied(T):
                return float(np.std(T[:, :3, 3], axis=0).max()) > 1e-4
            fresh = _varied(TL) and _varied(TR)
            print(f"\n[判据1 新鲜度] 矩阵随板位变化: {'是' if fresh else '否'}")
            if not fresh:
                print("  ⚠️ 两路外参在各样本间无变化 —— 该 API 返回的是固化历史值，")
                print("     本路线不可行。请改用 stereoCalibrate 棋盘格标定，或问原厂"
                      " 是否有左右相机出厂相对位姿的接口。")

            # ---- 判据 2：合理性 ----
            rigs = [compose_rig(a, b) for a, b in samples]
            rel_deg = np.array([_rel_rot_deg(R) for R, _ in rigs])
            base_mm = np.array([np.linalg.norm(t) * 1000.0 for _, t in rigs])
            sane = bool((rel_deg < 1.5).all() and (base_mm > 10).all() and (base_mm < 300).all())
            print(f"[判据2 合理性] 相对旋转 {rel_deg.min():.2f}~{rel_deg.max():.2f}°, "
                  f"基线 {base_mm.min():.1f}~{base_mm.max():.1f}mm → {'通过' if sane else '不通过'}")

            # ---- 判据 3：离散度（平均）----
            R_avg = quat_avg([R for R, _ in rigs])
            t_avg = np.median(np.array([t for _, t in rigs]), axis=0)
            base_spread = float(np.std(base_mm))
            rot_spread = float(np.std(rel_deg))
            print(f"[判据3 离散度] 基线 std {base_spread:.3f}mm, 旋转 std {rot_spread:.3f}°")
            tight = base_spread < 1.0 and rot_spread < 0.2
            print(f"             → {'通过' if tight else '偏大（板检测噪声大，增加样本数或换板位）'}")

            # ---- 保存 rig ----
            result = {
                "R": R_avg.tolist(),
                "T": t_avg.tolist(),
                "unit": "meter",
                "baseline_mm": round(float(np.linalg.norm(t_avg) * 1000.0), 3),
                "source": "GetExtrinsicMatrix board-composed (同帧同板)",
                "camera_sn": args.sn,
                "samples": len(samples),
                "valid_check": {"fresh": fresh, "sane": sane, "tight": tight,
                                "rel_rot_deg_each": np.round(rel_deg, 3).tolist(),
                                "baseline_mm_each": np.round(base_mm, 2).tolist()},
            }
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"\n[输出] rig → {args.out}  基线 {result['baseline_mm']}mm")

            if not (fresh and sane):
                print("[结论] 出厂外参组合法在本机/本固件上不可行（见上），请走棋盘格标定。")
                return 1

            # ---- 可选：立即重建历史数据验证尺度 ----
            if args.scene_dir:
                print("\n[验证] 用新 rig 重建 --scene-dir ...")
                import cv2
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
                zref = float(np.linalg.norm(t_avg)) * 57.0   # 特征三角化的经验场景深度(基线单位)
                keep = valid & (z > 0.25 * zref) & (z < 3.0 * zref)
                ply = os.path.join(args.scene_dir, "重建点云_boardrig.ply")
                save_ply(ply, points, keep)   # 真尺度 → 毫米
                zz = points[:, :, 2][keep]
                print(f"  有效点 {int(keep.sum())}, Z(米): p1={np.percentile(zz, 1):.2f} "
                      f"中位={np.median(zz):.2f} p99={np.percentile(zz, 99):.2f}")
                print(f"  → {ply}")
                print("  请对照卷尺/激光尺实测距离核对 Z 中位数，确认尺度正确。")

            print("\n[结论] 出厂外参组合法可行 ✅" if (fresh and sane and tight)
                  else "\n[结论] 可用但离散度偏大，建议增加样本 ⚠️")
            return 0
        finally:
            x.Close()
            RVC.X2.Destroy(x)
    finally:
        RVC.SystemShutdown()


if __name__ == "__main__":
    sys.exit(main())
