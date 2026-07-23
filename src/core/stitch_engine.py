# -*- coding: utf-8 -*-
"""
N 相机点云拼接引擎（StitchEngine）。

从 DualCameraFusion/src/app.py:3857-3905 `_do_stitch` 与 OfflineSession.stitch
逻辑泛化而来：
  - 原实现硬编码 A/B 两台相机 + 单一 T_ab；
  - 本实现支持任意 N 台相机：每台非参考相机通过
    CalibrationEngine.get_transform(cam_id, reference_id) 取变换
    （星型直达/求逆，链式自动走 pose_graph BFS），变换到参考坐标系后合并。

健壮性设计：
  - 单台相机取变换失败 / 点云为空 / 点云无效：log warning 并跳过，
    不中断整体拼接；
  - open3d 延迟导入（模块顶层无重依赖），无 SDK/无 GUI 环境可测试。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from .frame_data import FrameData
from .calibration_engine import CalibrationEngine
from .point_cloud_processor import PointCloudProcessor
from .utils import logger

if TYPE_CHECKING:
    import open3d as o3d


class StitchEngine:
    """N 相机点云拼接引擎：变换到参考坐标系并合并。"""

    def stitch(
        self,
        frames: Dict[str, FrameData],
        calibration_engine: CalibrationEngine,
        reference_id: str,
        processor: Optional[PointCloudProcessor] = None,
    ) -> Tuple[Optional['o3d.geometry.PointCloud'], str]:
        """把 N 台相机的点云变换到 reference_id 坐标系并合并。

        Args:
            frames: {camera_id: FrameData}，每台相机一帧
            calibration_engine: 标定引擎（提供 get_transform）
            reference_id: 参考坐标系相机 ID（其点云不做变换）
            processor: 可选，拼接合并后做后处理（裁切/下采样/离群点）

        Returns:
            (merged_open3d_pointcloud 或 None, 日志消息)；
            所有相机点云均不可用时返回 (None, 原因)。
        """
        import open3d as o3d

        if not frames:
            return None, "无帧数据"

        merged = o3d.geometry.PointCloud()
        logs: List[str] = []
        n_merged = 0

        for cam_id, frame in frames.items():
            # 1. 取变换（参考相机用单位阵，跳过查询）
            if cam_id == reference_id:
                T = None
            else:
                try:
                    T = calibration_engine.get_transform(cam_id, reference_id)
                except Exception as e:
                    logger.warning(f"拼接: 相机 '{cam_id}' 取变换失败，已跳过: {e}")
                    logs.append(f"{cam_id}: 取变换失败，跳过 ({e})")
                    continue

            # 2. 取 open3d 点云
            try:
                pcd = frame.load_pointcloud_o3d()
            except Exception as e:
                logger.warning(f"拼接: 相机 '{cam_id}' 点云加载异常，已跳过: {e}")
                logs.append(f"{cam_id}: 点云加载异常，跳过 ({e})")
                continue
            if pcd is None or len(pcd.points) == 0:
                logger.warning(f"拼接: 相机 '{cam_id}' 点云为空，已跳过")
                logs.append(f"{cam_id}: 点云为空，跳过")
                continue

            # 3. 变换到参考坐标系（参考相机不变换）
            if T is not None:
                pcd.transform(T)

            # 4. 合并
            merged += pcd
            n_merged += 1
            logs.append(f"{cam_id}: {len(pcd.points)} 点"
                        + ("" if T is None else "（已变换）"))

        if n_merged == 0 or len(merged.points) == 0:
            return None, "拼接失败: 所有相机点云均不可用\n" + "\n".join(logs)

        # 5. 可选后处理
        logs.insert(0, f"合并 {n_merged}/{len(frames)} 台相机, 原始点数: {len(merged.points)}")
        if processor is not None:
            merged, stats = processor.process(merged)
            if 'after_crop' in stats:
                logs.append(f"裁切后: {stats['after_crop']}")
            if 'after_downsample' in stats:
                logs.append(f"下采样后: {stats['after_downsample']}")
            if 'after_filter' in stats:
                logs.append(f"滤波后: {stats['after_filter']}")
            logs.append(f"后处理后点数: {len(merged.points)}")

        msg = "\n".join(logs)
        logger.info(f"拼接完成: {msg.replace(chr(10), ' | ')}")
        return merged, msg

    def stitch_offline(
        self,
        session_frames: List[Dict[str, FrameData]],
        calibration_engine: CalibrationEngine,
        reference_id: str,
        processor: Optional[PointCloudProcessor] = None,
    ) -> Tuple[Optional['o3d.geometry.PointCloud'], str]:
        """批量离线拼接：多对帧逐对拼接后全部合并到参考坐标系。

        每对帧（{camera_id: FrameData}）独立走 stitch（不做后处理），
        成功的部分再整体合并；processor 只在最终合并点云上应用一次。
        单对帧失败不中断批量流程。

        Returns:
            (merged_open3d_pointcloud 或 None, 日志消息)
        """
        import open3d as o3d

        if not session_frames:
            return None, "无离线帧数据"

        merged_all = o3d.geometry.PointCloud()
        logs: List[str] = []
        n_ok = 0

        for i, frames in enumerate(session_frames):
            try:
                merged, msg = self.stitch(frames, calibration_engine, reference_id,
                                          processor=None)
            except Exception as e:
                logger.warning(f"离线拼接: 第 {i} 对帧拼接异常，已跳过: {e}")
                logs.append(f"帧对 {i}: 异常跳过 ({e})")
                continue
            if merged is None or len(merged.points) == 0:
                logger.warning(f"离线拼接: 第 {i} 对帧结果为空，已跳过")
                logs.append(f"帧对 {i}: 结果为空，跳过")
                continue
            merged_all += merged
            n_ok += 1
            logs.append(f"帧对 {i}: +{len(merged.points)} 点")

        if n_ok == 0 or len(merged_all.points) == 0:
            return None, "离线拼接失败: 所有帧对均不可用\n" + "\n".join(logs)

        logs.insert(0, f"离线拼接 {n_ok}/{len(session_frames)} 对帧成功, "
                       f"总点数: {len(merged_all.points)}")
        if processor is not None:
            merged_all, stats = processor.process(merged_all)
            logs.append(f"后处理后点数: {len(merged_all.points)} "
                        f"({stats})")

        msg = "\n".join(logs)
        logger.info(f"离线拼接完成: {msg.replace(chr(10), ' | ')}")
        return merged_all, msg
