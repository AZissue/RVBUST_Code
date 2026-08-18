# -*- coding: utf-8 -*-
"""
N 相机外参标定引擎（CalibrationEngine）。

算法核心从 DualCameraFusion/src/app.py 抽取并泛化：
  - _solve_rigid：SVD Kabsch 刚性变换求解（app.py:889-909）；
  - RANSAC 鲁棒估计框架（app.py:796-887 calibrate_from_markers 内逻辑）；
  - 多帧四元数平均（app.py:996-1013）——**已修复 q/-q 符号歧义 bug**：
    原实现直接 np.mean(quats)，当两帧四元数异号时平均结果错误；
    现在平均前先把所有四元数翻到同一半球（与参考四元数点积为负则取反）。

N 相机架构：
  - 星型拓扑：所有非参考相机分别对标参考相机，pair 结果存于
    pair_results[(ref_id, cam_id)]，T 为 cam→ref 的 4x4 变换；
  - 链式拓扑（相邻共视）：预留 pose_graph.find_path_transform hook，
    Phase 2 实现。

方向约定（与 DualCameraFusion 一致）：
  T 是 cam→ref 的变换：pts_ref ≈ pts_cam @ R.T + t
  （即 4x4 齐次矩阵左乘齐次坐标：p_ref = T @ p_cam）
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

import numpy as np

from .utils import logger


class CalibrationEngine:
    """基于编码圆对应点的 N 相机外参标定（星型拓扑）。"""

    def __init__(self):
        # pair 结果：{(ref_id, cam_id): {T, rms_mm, mean_mm, inlier_count, inlier_ratio,
        #   details, outlier_count, outlier_codes, rms_all_mm, ...}}
        # rms_mm 等误差统计只按内点计算；rms_all_mm 为含离群点的全量 RMS（参考）
        self.pair_results: Dict[Tuple[str, str], dict] = {}
        # 参考相机 ID（默认第一台参与标定的相机，也可显式指定）
        self.reference_id: Optional[str] = None
        # 多帧标定缓存：{(ref_id, cam_id): [(markers_ref, markers_cam), ...]}
        self._multi_frame_data: Dict[Tuple[str, str], list] = {}

    # ------------------------------------------------------------------
    # 参考相机
    # ------------------------------------------------------------------
    def set_reference(self, camera_id: str):
        """显式指定参考相机。"""
        self.reference_id = camera_id

    def _ensure_reference(self, ref_id: str):
        """首次标定时自动把 ref_id 设为参考相机。"""
        if self.reference_id is None:
            self.reference_id = ref_id
            logger.info(f"参考相机自动设为: {ref_id}")

    # ------------------------------------------------------------------
    # 算法核心：SVD Kabsch 求解（与相机数量无关）
    # ------------------------------------------------------------------
    @staticmethod
    def _solve_rigid(src: np.ndarray, dst: np.ndarray) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """SVD 求解 src → dst 的刚性变换（R, t 使得 dst ≈ src @ R.T + t）。

        返回 R, t 使得: dst[i] ≈ src[i] @ R.T + t  =>  dst ≈ (src @ R.T + t)
        即 src 坐标系下的点乘 R.T 加 t 转到 dst 坐标系。
        """
        if len(src) < 3:
            return None, None
        centroid_src = np.mean(src, axis=0)
        centroid_dst = np.mean(dst, axis=0)
        src_centered = src - centroid_src
        dst_centered = dst - centroid_dst
        H = src_centered.T @ dst_centered
        U, S, Vt = np.linalg.svd(H)
        R = Vt.T @ U.T
        if np.linalg.det(R) < 0:
            Vt[-1, :] *= -1
            R = Vt.T @ U.T
        t = centroid_dst - R @ centroid_src
        return R, t

    @staticmethod
    def _match_markers(markers_ref: List[Dict], markers_cam: List[Dict]) -> Tuple[List, np.ndarray, np.ndarray]:
        """按 code 匹配两组编码圆，过滤 NaN/Inf 点后返回 (common_codes, pts_ref, pts_cam)。"""
        dict_ref = {m['code']: m for m in markers_ref}
        dict_cam = {m['code']: m for m in markers_cam}
        raw_common_codes = sorted(set(dict_ref.keys()) & set(dict_cam.keys()))
        common_codes = []
        pts_ref = []
        pts_cam = []
        for c in raw_common_codes:
            p_ref = np.array([dict_ref[c]['x_3d'], dict_ref[c]['y_3d'], dict_ref[c]['z_3d']], dtype=np.float64)
            p_cam = np.array([dict_cam[c]['x_3d'], dict_cam[c]['y_3d'], dict_cam[c]['z_3d']], dtype=np.float64)
            if np.isfinite(p_ref).all() and np.isfinite(p_cam).all():
                common_codes.append(c)
                pts_ref.append(p_ref)
                pts_cam.append(p_cam)
        return common_codes, np.array(pts_ref, dtype=np.float64), np.array(pts_cam, dtype=np.float64)

    # ------------------------------------------------------------------
    # 单帧标定一对相机（RANSAC + 内点 refine）
    # ------------------------------------------------------------------
    def calibrate_pair(
        self,
        ref_id: str,
        cam_id: str,
        markers_ref: List[Dict],
        markers_cam: List[Dict],
        ransac_threshold: float = 2.0,
        min_pairs: int = 3,
    ) -> dict:
        """单帧标定一对相机：求 cam→ref 的刚性变换 T。

        Args:
            ref_id: 参考相机 ID
            cam_id: 待标定相机 ID
            markers_ref / markers_cam: 两台相机各自的编码圆 3D 检测结果
            ransac_threshold: RANSAC 内点阈值（单位与输入点一致，默认 0.002，
                输入为米时即 2mm；输入为毫米时请显式传 2.0）
            min_pairs: 最少匹配点对数

        Returns:
            dict: {T (4x4), rms_mm, mean_mm, inlier_count, inlier_ratio, details,
                   outlier_count, outlier_codes, rms_all_mm}
            rms_mm/mean_mm/min_mm/max_mm 只按内点误差统计（拟合质量），
            rms_all_mm 为含离群点的全量 RMS（仅参考）。
            失败时返回 {'success': False, 'message': str}
        """
        self._ensure_reference(ref_id)
        common_codes, pts_ref, pts_cam = self._match_markers(markers_ref, markers_cam)

        if len(common_codes) < min_pairs:
            return {'success': False,
                    'message': f"匹配编码圆不足: 仅 {len(common_codes)} 对 (需≥{min_pairs})"}

        # RANSAC 鲁棒估计
        best_R, best_t = None, None
        best_inliers = []
        best_error = float('inf')

        n_pairs = len(common_codes)
        if n_pairs >= 6:
            rng = np.random.default_rng(seed=42)
            for _ in range(100):
                idx = rng.choice(n_pairs, size=min(3, n_pairs), replace=False)
                R, t = self._solve_rigid(pts_cam[idx], pts_ref[idx])
                if R is None:
                    continue
                errs = np.linalg.norm(pts_ref - (pts_cam @ R.T + t), axis=1)
                inliers = np.where(errs < ransac_threshold)[0]
                if len(inliers) > len(best_inliers) or (len(inliers) == len(best_inliers) and len(inliers) > 0 and errs[inliers].mean() < best_error):
                    best_R, best_t = R, t
                    best_inliers = inliers
                    best_error = errs[inliers].mean()
        else:
            best_R, best_t = self._solve_rigid(pts_cam, pts_ref)
            if best_R is None:
                return {'success': False, 'message': "SVD 求解失败"}
            errs = np.linalg.norm(pts_ref - (pts_cam @ best_R.T + best_t), axis=1)
            best_inliers = np.where(errs < ransac_threshold)[0]

        if best_R is None or len(best_inliers) < min_pairs:
            return {'success': False,
                    'message': f"RANSAC 后内点不足: {len(best_inliers)} (需≥{min_pairs})"}

        # 用所有内点重新 refine
        R_refined, t_refined = self._solve_rigid(pts_cam[best_inliers], pts_ref[best_inliers])
        if R_refined is None:
            R_refined, t_refined = best_R, best_t

        # 构建 4x4 矩阵（cam→ref）
        T = np.eye(4)
        T[:3, :3] = R_refined
        T[:3, 3] = t_refined

        # 计算逐点误差详情
        pts_cam_transformed = pts_cam @ R_refined.T + t_refined
        errs = np.linalg.norm(pts_ref - pts_cam_transformed, axis=1)
        # 内点掩码：refine 后误差仍低于 RANSAC 阈值的点（与 details.is_inlier 一致）
        inlier_mask = errs < ransac_threshold

        details = []
        for i, code in enumerate(common_codes):
            details.append({
                'code': int(code),
                'error_mm': float(errs[i]),
                'pt_ref': pts_ref[i].tolist(),
                'pt_cam': pts_cam[i].tolist(),
                'pt_cam_transformed': pts_cam_transformed[i].tolist(),
                'is_inlier': bool(inlier_mask[i]),
            })
        # 按误差从大到小排序
        details.sort(key=lambda x: x['error_mm'], reverse=True)

        # 误差统计：只按内点计算（离群点已排除，不代表拟合质量）；
        # 全量 RMS 保留在 rms_all_mm 供参考
        inlier_errs = errs[inlier_mask]
        if len(inlier_errs) == 0:  # 兜底：理论上不会发生（RANSAC 内点 refine 后误差应低于阈值）
            inlier_errs = errs
        outlier_codes = [int(c) for c, m in zip(common_codes, inlier_mask) if not m]

        result = {
            'success': True,
            'T': T,
            'rms_mm': float(np.sqrt(np.mean(inlier_errs ** 2))),
            'mean_mm': float(np.mean(inlier_errs)),
            'min_mm': float(np.min(inlier_errs)),
            'max_mm': float(np.max(inlier_errs)),
            'rms_all_mm': float(np.sqrt(np.mean(errs ** 2))),
            'outlier_count': int(len(outlier_codes)),
            'outlier_codes': outlier_codes,
            'inlier_count': int(inlier_mask.sum()),
            'total_pairs': int(n_pairs),
            'inlier_ratio': float(inlier_mask.sum() / n_pairs) if n_pairs > 0 else 0.0,
            'details': details,
        }
        self.pair_results[(ref_id, cam_id)] = result
        logger.info(f"标定 {cam_id}→{ref_id}: 匹配 {n_pairs} 对, 内点 {len(best_inliers)}, "
                    f"RMS {result['rms_mm']:.4f}")
        return result

    # ------------------------------------------------------------------
    # 标定板位姿法（双视角拍同一块固定标定板）
    # ------------------------------------------------------------------
    def calibrate_pair_by_board_pose(
        self,
        ref_id: str,
        cam_id: str,
        T_board_in_ref: np.ndarray,
        T_board_in_cam: np.ndarray,
        pattern_name: str,
        inlier_count: int = 0,
        total_pairs: int = 0,
        rms_ref_mm: float = 0.0,
        rms_cam_mm: float = 0.0,
    ) -> dict:
        """通过标定板位姿求 cam→ref 外参。

        原理：两个视角拍摄同一块固定标定板，分别得到 T_board_in_ref 和
        T_board_in_cam，则 cam→ref 的变换为：
            T = T_board_in_ref @ inv(T_board_in_cam)

        返回结果格式与 calibrate_pair() 保持一致，便于复用 pair_results
        与 get_transform()。
        """
        self._ensure_reference(ref_id)

        if T_board_in_ref is None or T_board_in_cam is None:
            return {'success': False, 'message': "标定板位姿缺失"}

        T_board_in_ref = np.asarray(T_board_in_ref, dtype=np.float64)
        T_board_in_cam = np.asarray(T_board_in_cam, dtype=np.float64)

        if T_board_in_ref.shape != (4, 4) or T_board_in_cam.shape != (4, 4):
            return {'success': False, 'message': "标定板位姿矩阵维度错误"}

        try:
            T = T_board_in_ref @ np.linalg.inv(T_board_in_cam)
        except np.linalg.LinAlgError:
            return {'success': False, 'message': "标定板位姿矩阵不可逆"}

        rms_mm = float(max(rms_ref_mm, rms_cam_mm))
        mean_mm = rms_mm
        max_mm = rms_mm

        result = {
            'success': True,
            'T': T,
            'rms_mm': rms_mm,
            'mean_mm': mean_mm,
            'min_mm': 0.0,
            'max_mm': max_mm,
            'rms_all_mm': rms_mm,
            'outlier_count': 0,
            'outlier_codes': [],
            'inlier_count': int(inlier_count),
            'total_pairs': int(total_pairs),
            'inlier_ratio': float(inlier_count / total_pairs) if total_pairs > 0 else 0.0,
            'details': [],
            'board_pattern_name': pattern_name,
            'method': 'board_pose',
        }
        self.pair_results[(ref_id, cam_id)] = result
        logger.info(f"标定板位姿法 {cam_id}→{ref_id}: 规格 {pattern_name}, "
                    f"RMS {rms_mm:.4f}")
        return result

    # ------------------------------------------------------------------
    # 多帧标定（四元数平均，已修复 q/-q 符号歧义）
    # ------------------------------------------------------------------
    def add_frame_data(self, ref_id: str, cam_id: str,
                       markers_ref: List[Dict], markers_cam: List[Dict]):
        """添加一组标定数据到多帧缓存，用于后续平均标定。"""
        key = (ref_id, cam_id)
        self._multi_frame_data.setdefault(key, []).append((markers_ref, markers_cam))

    def clear_frame_data(self, ref_id: str = None, cam_id: str = None):
        """清空多帧标定缓存；不指定相机时全部清空。"""
        if ref_id is None and cam_id is None:
            self._multi_frame_data = {}
        else:
            self._multi_frame_data.pop((ref_id, cam_id), None)

    @staticmethod
    def _average_quaternions(quats: List[np.ndarray]) -> np.ndarray:
        """四元数平均（修复 q/-q 符号歧义）。

        四元数 q 与 -q 表示同一旋转，直接平均会相互抵消。
        修复：平均前把所有四元数翻到与第一个四元数相同的半球。
        """
        q_ref = np.asarray(quats[0], dtype=np.float64)
        fixed = []
        for q in quats:
            q = np.asarray(q, dtype=np.float64)
            if np.dot(q, q_ref) < 0:
                q = -q  # 翻到同一半球
            fixed.append(q)
        q_avg = np.mean(fixed, axis=0)
        return q_avg / np.linalg.norm(q_avg)

    def calibrate_multi_frame(
        self,
        ref_id: str,
        cam_id: str,
        ransac_threshold: float = 2.0,
        min_pairs: int = 3,
    ) -> dict:
        """使用多帧缓存数据分别标定，然后对变换取平均（四元数平均 + 平移平均）。

        旋转平均前统一四元数半球（修复 q/-q 符号歧义 bug）。
        结果写入 pair_results[(ref_id, cam_id)] 并返回。
        """
        from scipy.spatial.transform import Rotation

        key = (ref_id, cam_id)
        frames = self._multi_frame_data.get(key, [])
        if len(frames) == 0:
            return {'success': False, 'message': "无多帧数据"}

        # 清除旧结果，避免本次全部失败时仍显示上一次标定结果
        self.pair_results.pop(key, None)

        Ts = []
        all_rms = []
        for markers_ref, markers_cam in frames:
            # 单帧标定（不污染 pair_results，直接用内部 RANSAC）
            res = self.calibrate_pair(ref_id, cam_id, markers_ref, markers_cam,
                                      ransac_threshold, min_pairs)
            if res.get('success'):
                Ts.append(res['T'].copy())
                all_rms.append(res['rms_mm'])

        if len(Ts) == 0:
            return {'success': False, 'message': "所有帧标定均失败"}

        if len(Ts) == 1:
            result = self.pair_results[key]
            result['message'] = f"单帧标定成功 | RMS: {all_rms[0]:.4f}"
            return result

        # 多帧平均：旋转四元数平均（半球统一），平移直接平均
        Rs = [T[:3, :3] for T in Ts]
        ts = [T[:3, 3] for T in Ts]
        quats = [Rotation.from_matrix(R).as_quat() for R in Rs]
        q_avg = self._average_quaternions(quats)
        R_avg = Rotation.from_quat(q_avg).as_matrix()
        t_avg = np.mean(ts, axis=0)

        T_avg = np.eye(4)
        T_avg[:3, :3] = R_avg
        T_avg[:3, 3] = t_avg

        # 重新计算所有帧的误差（使用平均矩阵），并按 ransac_threshold 区分内点/离群点
        all_errors = []       # 全部匹配标记误差（参考用）
        inlier_errors = []    # 仅内点标记误差（拟合质量统计用）
        outlier_codes = []    # 离群标记 code（便于排查坏标记）
        total_matched = 0     # 所有帧的匹配标记总数
        for markers_ref, markers_cam in frames:
            common_codes, pts_ref, pts_cam = self._match_markers(markers_ref, markers_cam)
            if len(common_codes) < min_pairs:
                continue
            total_matched += len(common_codes)
            pts_cam_t = pts_cam @ R_avg.T + t_avg
            errs = np.linalg.norm(pts_ref - pts_cam_t, axis=1)
            all_errors.extend(errs.tolist())
            inlier_mask = errs < ransac_threshold
            inlier_errors.extend(errs[inlier_mask].tolist())
            outlier_codes.extend(int(c) for c, m in zip(common_codes, inlier_mask) if not m)

        if len(inlier_errors) == 0:  # 兜底：无内点时退化为全量统计
            inlier_errors = all_errors
        inlier_arr = np.asarray(inlier_errors)
        all_arr = np.asarray(all_errors)
        n_inlier = int(len(inlier_arr))
        rms_avg = float(np.sqrt(np.mean(inlier_arr ** 2))) if n_inlier else 0.0
        result = {
            'success': True,
            'T': T_avg,
            'rms_mm': rms_avg,
            'mean_mm': float(np.mean(inlier_arr)) if n_inlier else 0.0,
            'min_mm': float(np.min(inlier_arr)) if n_inlier else 0.0,
            'max_mm': float(np.max(inlier_arr)) if n_inlier else 0.0,
            'rms_all_mm': float(np.sqrt(np.mean(all_arr ** 2))) if len(all_arr) else 0.0,
            'outlier_count': int(len(outlier_codes)),
            'outlier_codes': outlier_codes,
            # 与单帧模式语义统一：内点数/总对数按标记统计（帧数见 valid_frames/total_frames）
            'inlier_count': n_inlier,
            'total_pairs': int(total_matched),
            'inlier_ratio': float(n_inlier / total_matched) if total_matched > 0 else 0.0,
            'details': [],
            'valid_frames': len(Ts),
            'total_frames': len(frames),
            'frame_rms': all_rms,
            'message': (f"多帧平均标定成功 | 有效帧: {len(Ts)}/{len(frames)} | "
                        f"内点标记: {n_inlier}/{total_matched} | "
                        f"平均 RMS: {rms_avg:.4f} | 单帧 RMS 范围: "
                        f"{min(all_rms):.4f} ~ {max(all_rms):.4f}"),
        }
        self.pair_results[key] = result
        logger.info(f"多帧标定 {cam_id}→{ref_id}: 有效帧 {len(Ts)}/{len(frames)}, "
                    f"RMS {result['rms_mm']:.4f}")
        return result

    # ------------------------------------------------------------------
    # 变换查询（星型直达 / 求逆 / 链式 hook）
    # ------------------------------------------------------------------
    def get_transform(self, from_id: str, to_id: str) -> np.ndarray:
        """获取 from_id→to_id 的 4x4 变换（pts_to = T @ pts_from 齐次左乘）。

        星型拓扑：
          - pair (to_id, from_id) 存在 → 直达（存储的 T 即 from→to）；
          - pair (from_id, to_id) 存在 → 求逆（存储的 T 是 to→from）。
        链式拓扑（预留 hook）：
          - 找不到直达 pair 时委托 pose_graph.find_path_transform（Phase 2）。
        """
        if from_id == to_id:
            return np.eye(4)

        # 直达：存储方向为 cam→ref，即 key=(ref, cam) 存的是 cam→ref
        if (to_id, from_id) in self.pair_results:
            return self.pair_results[(to_id, from_id)]['T'].copy()
        # 求逆：存储的是 to→from，返回其逆
        if (from_id, to_id) in self.pair_results:
            return np.linalg.inv(self.pair_results[(from_id, to_id)]['T'])

        # 链式拓扑 hook（Phase 2 实现）
        from . import pose_graph
        return pose_graph.find_path_transform(self.pair_results, from_id, to_id)

    def is_calibrated(self, ref_id: str, cam_id: str) -> bool:
        res = self.pair_results.get((ref_id, cam_id))
        return res is not None and res.get('success', False)

    def reset(self):
        """清空全部标定结果与多帧缓存。"""
        self.pair_results = {}
        self._multi_frame_data = {}
        self.reference_id = None

    # ------------------------------------------------------------------
    # 保存 / 加载
    # ------------------------------------------------------------------
    def save_calibration(self, path: str) -> bool:
        """JSON 保存全部 pair 结果 + reference_id。"""
        try:
            data = {
                'reference_id': self.reference_id,
                'pairs': {},
            }
            for (ref_id, cam_id), res in self.pair_results.items():
                entry = dict(res)
                entry['T'] = res['T'].tolist() if isinstance(res['T'], np.ndarray) else res['T']
                data['pairs'][f"{ref_id}|{cam_id}"] = entry
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"标定结果已保存: {path}")
            return True
        except Exception as e:
            logger.error(f"保存标定失败: {e}")
            return False

    def load_calibration(self, path: str) -> bool:
        """从 JSON 加载全部 pair 结果 + reference_id。"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.reference_id = data.get('reference_id')
            self.pair_results = {}
            for key, entry in data.get('pairs', {}).items():
                ref_id, cam_id = key.split('|', 1)
                entry = dict(entry)
                entry['T'] = np.array(entry['T'], dtype=np.float64)
                self.pair_results[(ref_id, cam_id)] = entry
            logger.info(f"标定结果已加载: {path} ({len(self.pair_results)} 对)")
            return True
        except Exception as e:
            logger.error(f"加载标定失败: {e}")
            return False
