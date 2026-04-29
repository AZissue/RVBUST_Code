"""工程文件管理模块 - 保存/加载完整的拼接项目。"""
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

import numpy as np
import PyRVC as RVC
import cv2

from ..utils.logging_config import setup_module_logger

logger = setup_module_logger(__name__)


class ProjectManager:
    """管理编码圆拼接项目的保存和加载。
    
    工程文件格式 (.ccproj):
    {
        "version": "2.1",
        "created_at": "2026-04-15T09:30:00",
        "marker_params": {"N": 8, "r1": 2.0, "r2": 3.0},
        "capture_params": {"exp_2d": 20.0, "exp_3d": 20.0, "gain_2d": 0, "gain_3d": 0},
        "coord_mode": "first",
        "frames": [
            {
                "frame_id": 0,
                "marker_count": 5,
                "markers": [{"code": 1, "x": 100.0, "y": 200.0}, ...],
                "pose_to_prev": {"R": [[...]], "t": [...]},  # 相对位姿
                "image_file": "frame_0_image.png",
                "pointcloud_file": "frame_0_pointcloud.ply"
            }
        ],
        "poses": [  # 可选：累积位姿
            {"frame_id": 0, "R": [[...]], "t": [...]}
        ]
    }
    """
    
    CURRENT_VERSION = "2.1"
    
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.data_dir = self.project_path.parent / f"{self.project_path.stem}_data"
        self._metadata: Dict[str, Any] = {}
        
    def save_project(
        self,
        marker_params: Dict[str, float],
        capture_params: Dict[str, float],
        coord_mode: str,
        stitch_sessions: List[Any],
        poses: Optional[List[Tuple[np.ndarray, np.ndarray]]] = None,
        merged_o3d_pcd=None
    ) -> bool:
        """保存完整工程到指定路径。
        
        Args:
            marker_params: {"N": int, "r1": float, "r2": float}
            capture_params: {"exp_2d": float, "exp_3d": float, "gain_2d": int, "gain_3d": int}
            coord_mode: "first" or "last"
            stitch_sessions: List[CaptureSession]
            poses: List[(R, t)] 帧间位姿
            merged_o3d_pcd: 可选的合并点云
            
        Returns:
            bool: 是否成功
        """
        try:
            # 创建数据目录
            self.data_dir.mkdir(parents=True, exist_ok=True)
            
            # 构建工程元数据
            project_data = {
                "version": self.CURRENT_VERSION,
                "created_at": datetime.now().isoformat(),
                "marker_params": marker_params,
                "capture_params": capture_params,
                "coord_mode": coord_mode,
                "frames": [],
                "poses": []
            }
            
            # 保存每帧数据
            for i, session in enumerate(stitch_sessions):
                frame_data = {
                    "frame_id": session.frame_id,
                    "marker_count": session.marker_count,
                    "markers": session.markers if session.markers else []
                }
                
                # 保存图像
                if session.image_np is not None:
                    img_path = self.data_dir / f"frame_{i}_image.png"
                    cv2.imwrite(str(img_path), session.image_np)
                    frame_data["image_file"] = f"frame_{i}_image.png"
                    frame_data["image_size"] = {
                        "width": int(session.image_np.shape[1]),
                        "height": int(session.image_np.shape[0])
                    }
                
                # 保存点云 (带颜色，用于离线加载)
                if session.pointmap is not None and session.rvc_image is not None:
                    ply_path = self.data_dir / f"frame_{i}_pointcloud.ply"
                    ret = session.pointmap.SaveWithImage(
                        str(ply_path), session.rvc_image,
                        RVC.PointMapUnitEnum.Millimeter, True
                    )
                    if ret:
                        frame_data["pointcloud_file"] = f"frame_{i}_pointcloud.ply"
                        frame_data["pointcloud_unit"] = "millimeter"
                
                # 保存位姿（如果有）
                if poses and i < len(poses):
                    R, t = poses[i]
                    frame_data["pose_to_prev"] = {
                        "R": R.tolist(),
                        "t": t.tolist()
                    }
                    project_data["poses"].append({
                        "frame_id": i,
                        "R": R.tolist(),
                        "t": t.tolist()
                    })
                
                project_data["frames"].append(frame_data)
            
            # 保存合并点云（如果有）
            if merged_o3d_pcd is not None:
                try:
                    import open3d as o3d
                    merged_path = self.data_dir / "merged_pointcloud.ply"
                    o3d.io.write_point_cloud(str(merged_path), merged_o3d_pcd)
                    project_data["merged_pointcloud_file"] = "merged_pointcloud.ply"
                except Exception as e:
                    logger.warning(f"保存合并点云失败: {e}")
            
            # 写入 JSON 工程文件
            with open(self.project_path, 'w', encoding='utf-8') as f:
                json.dump(project_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"工程保存成功: {self.project_path} ({len(stitch_sessions)} 帧)")
            return True
            
        except Exception as e:
            logger.error(f"保存工程失败: {e}")
            return False
    
    def load_project(self) -> Optional[Dict[str, Any]]:
        """加载工程文件。
        
        Returns:
            Dict 包含所有工程数据，或 None 如果加载失败
        """
        try:
            if not self.project_path.exists():
                logger.error(f"工程文件不存在: {self.project_path}")
                return None
            
            with open(self.project_path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)
            
            # 版本检查
            version = project_data.get("version", "unknown")
            if version != self.CURRENT_VERSION:
                logger.warning(f"工程文件版本不匹配: {version} vs {self.CURRENT_VERSION}")
            
            # 验证数据目录
            if not self.data_dir.exists():
                logger.warning(f"工程数据目录不存在: {self.data_dir}")
            
            logger.info(f"工程加载成功: {self.project_path} ({len(project_data.get('frames', []))} 帧)")
            return project_data
            
        except Exception as e:
            logger.error(f"加载工程失败: {e}")
            return None
    
    def get_frame_files(self, frame_idx: int) -> Tuple[Optional[str], Optional[str]]:
        """获取指定帧的图像和点云文件路径。
        
        Returns:
            (image_path, pointcloud_path) 或 (None, None)
        """
        if not self.data_dir.exists():
            return None, None
        
        img_path = self.data_dir / f"frame_{frame_idx}_image.png"
        ply_path = self.data_dir / f"frame_{frame_idx}_pointcloud.ply"
        
        return (
            str(img_path) if img_path.exists() else None,
            str(ply_path) if ply_path.exists() else None
        )
    
    def export_poses(self, output_path: str) -> bool:
        """导出位姿矩阵到单独的 JSON 文件。
        
        Args:
            output_path: 输出文件路径
        """
        try:
            project_data = self.load_project()
            if not project_data:
                return False
            
            poses_data = {
                "project": str(self.project_path),
                "exported_at": datetime.now().isoformat(),
                "coord_mode": project_data.get("coord_mode", "first"),
                "poses": project_data.get("poses", [])
            }
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(poses_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"位姿导出成功: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"导出位姿失败: {e}")
            return False
