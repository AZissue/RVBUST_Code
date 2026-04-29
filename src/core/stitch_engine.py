import os
import tempfile
import traceback
from typing import List, Tuple, Optional
import numpy as np
import PyRVC as RVC

from ..utils.logging_config import setup_module_logger
from .rvc_resource import safe_destroy

logger = setup_module_logger(__name__)

# Open3D 为可选依赖
try:
    import open3d as o3d
    HAS_OPEN3D = True
except ImportError:
    HAS_OPEN3D = False
    o3d = None


def _inv_rt(R: np.ndarray, t: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """求逆变换。"""
    R_inv = R.T
    t_inv = -R_inv @ t
    return R_inv, t_inv


# RVC GetTwoCameraTransformByCodedCircleMarker 错误码定义
# Source: RVCSDK/include/RVC/experimental/PointCloudStitching.h
STITCH_ERROR_CODES = {
    0: "成功",
    -1: "PointMap 无效，或 PointMap 与图像尺寸不匹配",
    -2: "Image 无效",
    -3: "检测到的编码圆数量不足",
    -4: "共有视场内编码圆太少（建议至少3个，6个以上更佳）",
    -5: "编码圆点云质量不佳",
    -6: "部分编码圆在拍摄过程中发生了移动",
}


def get_stitch_error_message(ret: int) -> str:
    """将拼接错误码转换为可读描述。"""
    desc = STITCH_ERROR_CODES.get(ret, "未知错误")
    return f"错误码 {ret}: {desc}"


def frame_to_o3d_pcd(pointmap, rvc_image, unit=RVC.PointMapUnitEnum.Millimeter):
    """通过临时 PLY 文件安全获取带颜色的点云（避免手动颜色映射错误）。"""
    if not HAS_OPEN3D:
        raise RuntimeError("需要安装 open3d: pip install open3d")

    fd, tmp_path = tempfile.mkstemp(suffix=".ply")
    os.close(fd)
    try:
        ret = pointmap.SaveWithImage(tmp_path, rvc_image, unit, True)
        if not ret:
            raise RuntimeError("SaveWithImage 保存临时PLY失败")
        pcd = o3d.io.read_point_cloud(tmp_path)
        if pcd is None or len(pcd.points) == 0:
            raise RuntimeError("读取临时PLY失败或点云为空")
        return pcd
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def stitch_chain(
    frames: List[RVC.PointMap],
    images: List[RVC.Image],
    marker_type: RVC.CodedCircleMarkerType,
    coord_mode: str = "first"   # "first" | "last"
) -> Tuple[bool, str, List[Tuple[np.ndarray, np.ndarray]]]:
    """链式拼接：第 i 帧与第 i-1 帧（已在参考系中）匹配。

    Args:
        frames: RVC PointMap 列表（会被原地修改！变换到参考系）
        images: 对应 RVC Image 列表
        marker_type: 编码圆参数
        coord_mode: "first" 或 "last"

    Returns:
        (success, message, poses)  poses[i] = (R, t) 表示 frame_i 相对于 frame_{i-1} 的变换
    """
    n = len(frames)
    if n < 2:
        return False, "至少需要2帧才能进行拼接", []
    if len(images) != n:
        return False, "图像数量与帧数不匹配", []

    poses = [None] * n
    poses[0] = (np.eye(3), np.zeros(3))

    for i in range(1, n):
        try:
            logger.info(f"匹配帧 {i} 与帧 {i-1}...")
            ret, R, t = RVC.GetTwoCameraTransformByCodedCircleMarker(
                frames[i - 1], images[i - 1],
                frames[i], images[i],
                marker_type
            )
            if ret != 0:
                err_msg = get_stitch_error_message(ret)
                msg = f"帧 {i-1} 和帧 {i} 编码圆匹配失败 ({err_msg})"
                logger.error(msg)
                return False, msg, poses

            poses[i] = (R, t)
            RVC.TransformPointCloud(R, t, frames[i])
            logger.info(f"帧 {i} 已变换到参考坐标系")
        except Exception as e:
            logger.critical(f"帧 {i} 处理异常: {e}")
            logger.critical(traceback.format_exc())
            return False, f"处理帧 {i} 时发生错误: {e}", poses

    # 转换到最后一帧坐标系
    if coord_mode == "last" and n > 1:
        logger.info("转换到最后一帧坐标系...")
        try:
            # 累积从第一帧到最后一帧的变换
            R_acc = np.eye(3)
            t_acc = np.zeros(3)
            for i in range(1, n):
                R, t = poses[i]
                t_acc = R_acc @ t + t_acc
                R_acc = R_acc @ R

            R_inv, t_inv = _inv_rt(R_acc, t_acc)
            for i in range(n - 1):
                RVC.TransformPointCloud(R_inv, t_inv, frames[i])
            logger.info("坐标系转换完成")
        except Exception as e:
            logger.error(f"坐标系转换失败: {e}")
            return False, f"坐标系转换失败: {e}", poses

    return True, f"成功拼接 {n} 帧", poses


def build_merged_pointcloud(
    frames: List[RVC.PointMap],
    images: List[RVC.Image],
    unit=RVC.PointMapUnitEnum.Millimeter
):
    """使用临时 PLY 方式构建合并后的 Open3D 点云（颜色映射完全正确）。"""
    if not HAS_OPEN3D:
        raise RuntimeError("需要安装 open3d")

    merged = o3d.geometry.PointCloud()
    total_points = 0
    for i, (pm, img) in enumerate(zip(frames, images)):
        try:
            pcd = frame_to_o3d_pcd(pm, img, unit)
            merged += pcd
            total_points += len(pcd.points)
            logger.debug(f"合并帧 {i}: {len(pcd.points)} 点")
        except Exception as e:
            logger.error(f"合并帧 {i} 失败: {e}")

    logger.info(f"合并点云完成: {total_points} 点")
    return merged


def extract_numpy_from_pcd(pcd):
    """从 Open3D 点云提取 numpy 数组。"""
    if pcd is None:
        return None, None
    points = np.asarray(pcd.points)
    colors = np.asarray(pcd.colors)
    if len(colors) > 0:
        colors = (colors * 255).astype(np.uint8)
        # RGB -> BGR 以兼容后续显示
        colors = colors[:, [2, 1, 0]]
    return points, colors
