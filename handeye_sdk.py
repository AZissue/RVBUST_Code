"""
HandEyeSDK.dll 的 ctypes 封装层。
通过 Python 的 ctypes 库调用 C++ DLL 中的手眼标定辅助函数，
包括同心圆检测、标定板检测和标定计算。

注意：当前项目主要使用其中的标记物检测函数（DetectConcentricCircles 系列），
标定计算由 HandEyeManager.exe 完成。
"""

import ctypes
import os
import math

# ── DLL 路径 ─────────────────────────────────────────────────
# HandEyeSDK.dll 位于手眼标定软件的 SDK 目录中
_HANDEYE_DLL_PATH = os.path.join(
    "C:/Users/RVBUST/Desktop",
    "RVCHandEyeCalibration_v3.5.0_20260420_win_release",
    "RVCHandEyeCalibration",
    "SDK/C++/External/HandEyeSDK/Win64/bin",
    "HandEyeSDK.dll",
)

# DLL 实例缓存（懒加载，首次调用时初始化）
_dll = None


def _get_dll():
    """
    获取 HandEyeSDK.dll 的 ctypes 实例。
    首次调用时加载 DLL 并配置所有导出函数的参数类型和返回类型。
    """
    global _dll
    if _dll is not None:
        return _dll

    # 加载 DLL（__stdcall 调用约定，Win64 下与 __cdecl 等价）
    _dll = ctypes.CDLL(_HANDEYE_DLL_PATH)

    # ── DetectConcentricCircles2D ──
    # 输入: 图像路径 | 输出: 检测到的圆数量 + 像素坐标数组
    _dll.DetectConcentricCircles2D.argtypes = [
        ctypes.c_char_p,                          # imageFilePath
        ctypes.POINTER(ctypes.c_int),             # resultNum (输出)
        ctypes.c_float * 200,                     # resultPixelXy[200] (输出)
    ]
    _dll.DetectConcentricCircles2D.restype = None

    # ── DetectConcentricCircles3D ──
    # 输入: 图像路径 + 点云路径 | 输出: 数量 + 2D像素坐标 + 3D空间坐标
    _dll.DetectConcentricCircles3D.argtypes = [
        ctypes.c_char_p,                          # imageFilePath
        ctypes.c_char_p,                          # pointCloudFilePath
        ctypes.POINTER(ctypes.c_int),             # resultNum
        ctypes.c_float * 200,                     # resultPixelXy[200]
        ctypes.c_float * 300,                     # resultPointXyz[300]
    ]
    _dll.DetectConcentricCircles3D.restype = None

    # ── DetectCaliboard2D ──
    # 检测非对称黑底白圆标定板在 2D 图像中的圆心
    _dll.DetectCaliboard2D.argtypes = [
        ctypes.c_char_p,                          # imageFilePath
        ctypes.c_float * 9,                       # camera_intrinsic[9] (3x3)
        ctypes.c_float * 5,                       # camera_distortion[5] (k1,k2,p1,p2,k3)
        ctypes.c_int,                             # pattern_width
        ctypes.c_int,                             # pattern_height
        ctypes.c_float * 200,                     # resultPixelXy[200]
    ]
    _dll.DetectCaliboard2D.restype = None

    # ── DetectCaliboard3D ──
    # 检测标定板在 2D+3D 中的圆心位置
    _dll.DetectCaliboard3D.argtypes = [
        ctypes.c_char_p,                          # imageFilePath
        ctypes.c_char_p,                          # pointCloudFilePath
        ctypes.c_float * 9,                       # intrinsic[9]
        ctypes.c_float * 5,                       # distortion[5]
        ctypes.c_int,                             # pattern_w
        ctypes.c_int,                             # pattern_h
        ctypes.c_float,                           # circle_step
        ctypes.c_float * 200,                     # resultPixelXy[200]
        ctypes.c_float * 300,                     # resultPointXyz[300]
        ctypes.POINTER(ctypes.c_float),           # measuring_distance (输出)
        ctypes.POINTER(ctypes.c_float),           # error_percentage (输出)
    ]
    _dll.DetectCaliboard3D.restype = None

    # ── HandEyeCalibrationMarker ──
    # 标记物标定计算（本工具仅采集数据，此函数预留给后续使用）
    _dll.HandEyeCalibrationMarker.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        HandEyeParam,
        ctypes.POINTER(HandEyeResult),
    ]
    _dll.HandEyeCalibrationMarker.restype = ctypes.c_int

    # ── HandEyeCalibrationTcpTouch ──
    # TCP 戳点标定计算
    _dll.HandEyeCalibrationTcpTouch.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        HandEyeParam,
        ctypes.POINTER(HandEyeResult),
    ]
    _dll.HandEyeCalibrationTcpTouch.restype = ctypes.c_int

    # ── TransformPointCloudsToRobotBase ──
    # 将点云按标定结果变换到机器人基坐标系
    _dll.TransformPointCloudsToRobotBase.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_bool,
        ctypes.c_bool,
        ctypes.c_bool,
        ctypes.c_bool,
        ctypes.c_double * 16,
    ]
    _dll.TransformPointCloudsToRobotBase.restype = ctypes.c_int

    return _dll


# ═══════════════════════════════════════════════════════════════
# C 结构体定义（内存布局与 C++ struct 一致，按顺序排列，无填充）
# ═══════════════════════════════════════════════════════════════

class HandEyeParam(ctypes.Structure):
    """手眼标定算法参数结构体"""
    _fields_ = [
        ("poseType", ctypes.c_int),              # 位姿类型: 0=欧拉角, 1=wxyz, 2=xyzw, 3=矩阵
        ("markerType", ctypes.c_int),            # 标记物类型: 0=标定板, 1=同心圆
        ("isPointCloudMm", ctypes.c_bool),       # 点云单位是否为毫米
        ("isPoseMm", ctypes.c_bool),             # 平移单位是否为毫米
        ("isPoseDegree", ctypes.c_bool),         # 角度是否为度（否则为弧度）
        ("isEyeInHand", ctypes.c_bool),          # 是否为眼在手上模式
        ("dataMask", ctypes.c_bool * 100),       # 每组数据的启用标志（1=使用, 0=跳过）
        ("autoRemoveLargeErrorData", ctypes.c_bool),  # 是否自动剔除大误差数据
    ]


class HandEyeResult(ctypes.Structure):
    """手眼标定计算结果结构体"""
    _fields_ = [
        ("translationResult", ctypes.c_double * 3),   # 平移结果 [x, y, z]
        ("eulerAngleResult", ctypes.c_double * 3),    # 欧拉角结果（poseType=0 时有效）
        ("quaternionResult", ctypes.c_double * 4),    # 四元数结果（poseType=1/2 时有效）
        ("matrix", ctypes.c_double * 16),             # 4×4 变换矩阵（行主序）
        ("success2D", ctypes.c_int * 100),            # 每组 2D 检测状态（0=失败,1=成功）
        ("success3D", ctypes.c_int * 100),            # 每组 3D 检测状态
        ("error", ctypes.c_double * 100),             # 每组数据的标定误差
        ("totalMeanError", ctypes.c_double),          # 所有数据组的平均误差
    ]


# ═══════════════════════════════════════════════════════════════
# Pythonic 封装函数
# ═══════════════════════════════════════════════════════════════

def detect_concentric_circles_2d(image_path):
    """
    检测 2D 图像中的同心圆标记。
    输入: 图像文件路径（PNG 格式）
    返回: [(x, y), ...] 像素坐标列表
    算法: 调用 HandEyeSDK.dll 的 DetectConcentricCircles2D，
          内部使用霍夫圆检测 + 同心度验证算法。
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"图像文件不存在: {image_path}")

    dll = _get_dll()
    result_num = ctypes.c_int(0)            # 输出：检测到的圆数量
    pixel_xy = (ctypes.c_float * 200)()     # 输出：像素坐标数组 [x0,y0, x1,y1, ...]

    # 调用 DLL 函数，路径字符串需编码为 UTF-8 字节
    dll.DetectConcentricCircles2D(
        image_path.encode("utf-8") if isinstance(image_path, str) else image_path,
        ctypes.byref(result_num),
        pixel_xy,
    )

    # 按检测数量截取有效数据
    points = []
    for i in range(result_num.value):
        x = pixel_xy[i * 2]
        y = pixel_xy[i * 2 + 1]
        points.append((x, y))
    return points


def detect_concentric_circles_3d(image_path, ply_path):
    """
    检测 2D 图像 + 3D 点云中的同心圆标记。
    输入: 图像路径 + PLY 点云路径
    返回: (points_2d, points_3d)
      points_2d: [(x, y), ...] 像素坐标
      points_3d: [(x, y, z), ...] 3D 空间坐标（如果圆中心在点云孔洞中则为 None）
    算法: 先在 2D 图像中检测圆的像素位置，再在点云中采样对应 3D 坐标。
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"图像文件不存在: {image_path}")
    if not os.path.exists(ply_path):
        raise FileNotFoundError(f"点云文件不存在: {ply_path}")

    dll = _get_dll()
    result_num = ctypes.c_int(0)
    pixel_xy = (ctypes.c_float * 200)()
    point_xyz = (ctypes.c_float * 300)()

    dll.DetectConcentricCircles3D(
        image_path.encode("utf-8") if isinstance(image_path, str) else image_path,
        ply_path.encode("utf-8") if isinstance(ply_path, str) else ply_path,
        ctypes.byref(result_num),
        pixel_xy,
        point_xyz,
    )

    points_2d = []
    points_3d = []
    for i in range(result_num.value):
        x2 = pixel_xy[i * 2]
        y2 = pixel_xy[i * 2 + 1]
        x3 = point_xyz[i * 3]
        y3 = point_xyz[i * 3 + 1]
        z3 = point_xyz[i * 3 + 2]
        points_2d.append((x2, y2))
        # 如果点云在圆中心位置有孔洞（无数据），DLL 会返回 NaN
        if math.isnan(x3) or math.isnan(y3) or math.isnan(z3):
            points_3d.append(None)
        else:
            points_3d.append((x3, y3, z3))
    return points_2d, points_3d


def detect_caliboard_2d(image_path, intrinsic, distortion, pattern_w, pattern_h):
    """
    检测 2D 图像中的非对称标定板（黑底白圆）。
    输入:
      intrinsic: 3×3 相机内参矩阵（行主序 9 个 float）
      distortion: 5 个畸变系数 [k1, k2, p1, p2, k3]
      pattern_w/h: 标定板图案的宽高（如 7×11）
    返回: [x0, y0, x1, y1, ...] 检测到的圆心像素坐标列表
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"图像文件不存在: {image_path}")

    dll = _get_dll()
    img9 = (ctypes.c_float * 9)(*intrinsic)
    dist5 = (ctypes.c_float * 5)(*distortion)
    pixel_xy = (ctypes.c_float * 200)()

    dll.DetectCaliboard2D(
        image_path.encode("utf-8") if isinstance(image_path, str) else image_path,
        img9,
        dist5,
        ctypes.c_int(pattern_w),
        ctypes.c_int(pattern_h),
        pixel_xy,
    )

    return list(pixel_xy)


def detect_caliboard_3d(
    image_path, ply_path, intrinsic, distortion, pattern_w, pattern_h, circle_step
):
    """
    检测 2D+3D 中的非对称标定板圆心。
    circle_step: 标定板上相邻圆心之间的实际 3D 距离（用于验证和精度评估）
    返回: (pixel_xy_list, point_xyz_list, measuring_distance, error_percentage)
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"图像文件不存在: {image_path}")
    if not os.path.exists(ply_path):
        raise FileNotFoundError(f"点云文件不存在: {ply_path}")

    dll = _get_dll()
    img9 = (ctypes.c_float * 9)(*intrinsic)
    dist5 = (ctypes.c_float * 5)(*distortion)
    pixel_xy = (ctypes.c_float * 200)()
    point_xyz = (ctypes.c_float * 300)()
    measuring_dist = ctypes.c_float(0.0)   # 输出：实测距离
    error_pct = ctypes.c_float(0.0)        # 输出：误差百分比

    dll.DetectCaliboard3D(
        image_path.encode("utf-8") if isinstance(image_path, str) else image_path,
        ply_path.encode("utf-8") if isinstance(ply_path, str) else ply_path,
        img9,
        dist5,
        ctypes.c_int(pattern_w),
        ctypes.c_int(pattern_h),
        ctypes.c_float(circle_step),
        pixel_xy,
        point_xyz,
        ctypes.byref(measuring_dist),
        ctypes.byref(error_pct),
    )

    return list(pixel_xy), list(point_xyz), measuring_dist.value, error_pct.value
