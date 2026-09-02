# -*- coding: utf-8 -*-
"""
嵌入式 3D 点云查看器（N 路）。

渲染核心 PointCloudViewer + _ArcBallCamera 从 DualCameraFusion/src/app.py:1591-1900
原样抽取（QOpenGLWidget + PyOpenGL + ArcBall 相机），并修复了原实现
`_vbo_col` 未 glGenBuffers 的隐患。

EmbeddedPointCloudViewer 由 A/B 硬编码泛化为 N 路：
  - set_pointcloud(camera_id, pcd)：按 camera_id 管理任意数量点云；
  - set_pointcloud_merged(pcd)：拼接合并结果；
  - 每个 camera_id 分配固定颜色（参考相机白色，其余调色板循环）；
  - 显示模式下拉：全部叠加 / 合并结果 / 各单相机；
  - set_highlight(camera_id) / clear_highlight()。

Phase 6 UI 优化：
  - 顶部紧凑工具栏：折叠 / 显示模式 / 着色模式 / 点大小 / 视角预设 /
    重置视角 / 坐标轴 / 网格 / 背景切换 / 最大化；
  - 着色模式：按站位（调色板，默认）/ 按高度（jet 渐变）/ 灰度；
  - GL 内叠加信息层（透明 QLabel 子控件，替代原底部状态行）；
  - 参考元素：原点 RGB 坐标轴 + Z 最低点灰色网格地面；
  - 最大化：信号通知主窗口隐藏相机卡片区与左右面板。

性能约定（386 万点级别）：
  - 颜色数组全部 numpy 向量化，VBO 仅在数据 / 着色 / 点大小变化时重建；
  - 视角旋转 / 缩放 / 平移只改 MVP 矩阵，不触碰 VBO。

PyOpenGL import 延迟到 initializeGL 内，无 GL 环境仅查看器不可用，
不影响 UI 其余部分。
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

import open3d as o3d

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QSpinBox, QSizePolicy, QToolButton,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from core.utils import logger

from .icons import get_icon, has_icon, icon_text, apply_icon

# N 路点云调色板（参考相机固定白色，其余按添加顺序循环）
COLOR_REFERENCE = (0.95, 0.95, 0.95)   # 白色：参考相机
COLOR_PALETTE = [
    (0.20, 0.80, 1.00),   # 青
    (1.00, 0.60, 0.20),   # 橙
    (0.40, 1.00, 0.40),   # 绿
    (1.00, 0.40, 0.70),   # 品红
    (1.00, 1.00, 0.30),   # 黄
    (0.70, 0.50, 1.00),   # 紫
    (0.40, 0.90, 0.80),   # 蓝绿
    (0.95, 0.50, 0.50),   # 红
]
COLOR_MERGED = (0.40, 1.00, 0.40)      # 合并结果默认绿色（无自带颜色时）

# 背景色（深色 / 浅色）
BG_DARK = (0.12, 0.12, 0.15, 1.0)
BG_LIGHT = (0.90, 0.90, 0.92, 1.0)


def _jet_colormap(t: np.ndarray) -> np.ndarray:
    """matplotlib jet 的向量化实现：t (N,) in [0,1] → rgb (N,3) float32。"""
    t = np.clip(np.asarray(t, dtype=np.float64), 0.0, 1.0)
    xp = np.array([0.0, 0.125, 0.375, 0.64, 0.89, 1.0])
    r = np.interp(t, [0.0, 0.35, 0.66, 0.89, 1.0], [0.0, 0.0, 1.0, 1.0, 0.5])
    g = np.interp(t, xp, [0.0, 0.0, 1.0, 1.0, 0.0, 0.0])
    b = np.interp(t, [0.0, 0.11, 0.34, 0.65, 1.0], [0.5, 1.0, 1.0, 0.0, 0.0])
    return np.stack([r, g, b], axis=1).astype(np.float32)


def _nice_step(raw: float) -> float:
    """把 raw 间距取整到 1/2/5 × 10^k（网格间隔整数化）。"""
    if raw <= 0 or not np.isfinite(raw):
        return 1.0
    exp = np.floor(np.log10(raw))
    base = raw / (10 ** exp)
    for m in (1.0, 2.0, 5.0, 10.0):
        if base <= m:
            return m * (10 ** exp)
    return 10.0 * (10 ** exp)


# =========================================================================
# AxesIndicatorWidget —— 角落 2D 坐标轴指示器（类似 Blender/CloudCompare）
# =========================================================================
class AxesIndicatorWidget(QWidget):
    """在 3D 窗口角落绘制 2D 坐标轴指示器，显示当前视角方向。

    特点：
      - 始终悬浮在窗口角落，不被点云遮挡；
      - 红绿蓝三色箭头对应 XYZ 轴；
      - 箭头方向随相机旋转实时更新。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(64, 64)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet("background: transparent;")
        self._rotation_x = 30.0
        self._rotation_y = -45.0

    def set_rotation(self, rx: float, ry: float):
        """更新相机旋转角（度）。"""
        self._rotation_x = rx
        self._rotation_y = ry
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        cx, cy = self.width() / 2, self.height() / 2
        R = 20  # 指示器半径

        # 绘制背景圆
        painter.setBrush(QBrush(QColor(30, 30, 34, 180)))
        painter.setPen(QPen(QColor(60, 60, 66, 200), 1))
        painter.drawEllipse(int(cx - R - 4), int(cy - R - 4), int((R + 4) * 2), int((R + 4) * 2))

        # 计算各轴在屏幕上的投影方向（简化：根据旋转角计算 2D 投影）
        import math
        rx = math.radians(self._rotation_x)
        ry = math.radians(self._rotation_y)

        # X 轴（红）：初始指向右，受 ry 旋转影响
        x_dx = math.cos(ry) * R
        x_dy = math.sin(ry) * math.sin(rx) * R
        # Y 轴（绿）：初始指向上（屏幕下），受 rx 旋转影响
        y_dx = -math.sin(ry) * R * 0.5
        y_dy = -math.cos(rx) * R
        # Z 轴（蓝）：初始指向外（屏幕外），投影为垂直方向
        z_dx = math.sin(ry) * math.cos(rx) * R * 0.5
        z_dy = -math.sin(rx) * R

        # 绘制 X 轴（红）
        painter.setPen(QPen(QColor(255, 60, 60), 2.5))
        painter.drawLine(int(cx), int(cy), int(cx + x_dx), int(cy + x_dy))
        painter.setBrush(QBrush(QColor(255, 60, 60)))
        painter.drawEllipse(int(cx + x_dx - 3), int(cy + x_dy - 3), 6, 6)

        # 绘制 Y 轴（绿）
        painter.setPen(QPen(QColor(60, 255, 60), 2.5))
        painter.drawLine(int(cx), int(cy), int(cx + y_dx), int(cy + y_dy))
        painter.setBrush(QBrush(QColor(60, 255, 60)))
        painter.drawEllipse(int(cx + y_dx - 3), int(cy + y_dy - 3), 6, 6)

        # 绘制 Z 轴（蓝）
        painter.setPen(QPen(QColor(80, 140, 255), 2.5))
        painter.drawLine(int(cx), int(cy), int(cx + z_dx), int(cy + z_dy))
        painter.setBrush(QBrush(QColor(80, 140, 255)))
        painter.drawEllipse(int(cx + z_dx - 3), int(cy + z_dy - 3), 6, 6)

        # 中心点
        painter.setBrush(QBrush(QColor(200, 200, 200)))
        painter.drawEllipse(int(cx - 2), int(cy - 2), 4, 4)


# =========================================================================
# PointCloudViewer —— 基于 QOpenGLWidget + PyOpenGL
# =========================================================================
class PointCloudViewer(QOpenGLWidget):
    """将 numpy 格式点云渲染到 QOpenGLWidget 中。"""

    VERTEX_SHADER = """
    #version 130
    in vec3 a_position;
    in vec3 a_color;
    in float a_size;
    uniform mat4 u_mvp;
    out vec3 v_color;
    void main() {
        gl_Position = u_mvp * vec4(a_position, 1.0);
        gl_PointSize = a_size;
        v_color = a_color;
    }
    """

    FRAGMENT_SHADER = """
    #version 130
    in vec3 v_color;
    out vec4 fragColor;
    void main() {
        vec2 center = gl_PointCoord - vec2(0.5);
        float dist = length(center);
        if (dist > 0.5) discard;
        fragColor = vec4(v_color, 1.0);
    }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtGui import QSurfaceFormat
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 0)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        fmt.setSamples(4)
        self.setFormat(fmt)

        self.camera = _ArcBallCamera()
        self.points = None
        self.colors = None
        self.point_count = 0
        self.centroid = np.zeros(3, dtype=np.float32)
        self._extent = 10.0
        self._z_min = 0.0
        self._z_max = 0.0
        self._initialized = False
        self._has_gl = False
        self.highlight_indices = None

        # 多路点云 VBO 缓存（cloud_id -> metadata）
        self._clouds: Dict[str, dict] = {}
        self._bounds_dirty = True

        # 渲染选项（仅改标志，不重建点云 VBO）
        self._point_size = 1.0
        self._bg_color = BG_DARK
        self._show_axes = False   # 3D 坐标轴已改为角落 2D 指示器，默认关闭
        self._show_grid = True
        self._overlay_text = ""

        # MVP 矩阵缓存（用于屏幕/世界坐标互转）
        self._mvp_matrix: Optional[np.ndarray] = None
        self._mvp_inv: Optional[np.ndarray] = None

        # 旋转中心可视化
        self._pivot_visible = False
        self._pivot_position = np.zeros(3, dtype=np.float32)

        # ROI 框选
        self._roi_mode = False
        self._roi_start = None
        self._roi_rect = None
        self._roi_rubberband = None
        self._roi_selected_indices: Dict[str, np.ndarray] = {}

        # 信息叠加层：透明 QLabel 子控件（QPainter 在 3.0 Core Profile 下
        # 无法使用 Qt GL 绘制引擎，故改用控件叠加方案）
        self._overlay_label = QLabel(self)
        self._overlay_label.setStyleSheet(
            "QLabel { background-color: rgba(0, 0, 0, 150); color: #e6e6e6; "
            "border-radius: 6px; padding: 6px 10px; font-size: 9pt; }"
        )
        self._overlay_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._overlay_label.move(10, 10)
        self._overlay_label.hide()

        # 角落 2D 坐标轴指示器（始终显示，不被点云遮挡）
        self._axes_indicator = AxesIndicatorWidget(self)
        self._axes_indicator.move(10, self.height() - 74)
        self._axes_indicator.show()

        self.setMinimumSize(400, 260)

    def load_points(self, points: np.ndarray, colors: np.ndarray = None,
                    highlight_indices: list = None):
        assert points.ndim == 2 and points.shape[1] == 3, "points 必须是 (N, 3)"
        points = points.astype(np.float32)
        total = len(points)
        # 保留所有点，仅将 NaN/Inf 替换为 (0,0,0) 以维持 2D-3D 索引对应关系
        invalid_mask = np.isnan(points).any(axis=1) | np.isinf(points).any(axis=1)
        points[invalid_mask] = 0.0
        self.points = points
        self.point_count = len(self.points)
        if self.point_count == 0:
            raise ValueError("点云为空")
        # 计算质心时只考虑有效点（避免被大量零点拉偏）
        valid_points = points[~invalid_mask]
        if len(valid_points) > 0:
            self.centroid = valid_points.mean(axis=0)
            centered = valid_points - self.centroid
            extent_xyz = centered.max(axis=0) - centered.min(axis=0)
            self._z_min = float(valid_points[:, 2].min())
            self._z_max = float(valid_points[:, 2].max())
        else:
            self.centroid = np.zeros(3)
            extent_xyz = np.ones(3)
            self._z_min = self._z_max = 0.0
        self._extent = max(float(np.linalg.norm(extent_xyz)), 1e-3)
        self.camera.distance = max(self._extent * 1.5, 1.0)
        self.camera.target = self.centroid.astype(np.float32)
        if colors is not None:
            colors = np.asarray(colors, dtype=np.float32)
            if colors.shape != (self.point_count, 3):
                colors = np.tile(colors[:1], (self.point_count, 1))
            colors[invalid_mask] = [0.1, 0.1, 0.1]
            self.colors = colors.astype(np.float32)
        else:
            self.colors = np.tile([0.5, 0.5, 0.5], (self.point_count, 1)).astype(np.float32)
            self.colors[invalid_mask] = [0.1, 0.1, 0.1]
        self.highlight_indices = highlight_indices
        self._initialized = False
        self._bounds_dirty = True
        self.update()
        return {"total": total, "valid": int(total - invalid_mask.sum()),
                "invalid": int(invalid_mask.sum())}

    def set_highlight_indices(self, indices):
        self.highlight_indices = indices
        self._initialized = False
        self.update()

    def clear(self):
        self.points = None
        self.colors = None
        self.point_count = 0
        self.highlight_indices = None
        self._bounds_dirty = True
        self.update()

    def set_pointcloud(self, cloud_id: str, points: np.ndarray = None,
                       colors: np.ndarray = None, visible: bool = True,
                       highlight_indices: list = None,
                       point_size: Optional[float] = None):
        """添加/更新/删除一路独立点云 VBO。

        points=None 时删除该路点云及其 GPU 资源。
        point_size 为 None 时使用全局点大小。
        """
        if points is None:
            self._remove_cloud(cloud_id)
        else:
            points = np.asarray(points, dtype=np.float32)
            assert points.ndim == 2 and points.shape[1] == 3, "points 必须是 (N, 3)"
            n = len(points)
            invalid_mask = np.isnan(points).any(axis=1) | np.isinf(points).any(axis=1)
            points[invalid_mask] = 0.0
            if colors is not None:
                colors = np.asarray(colors, dtype=np.float32)
                if colors.shape != (n, 3):
                    colors = np.tile(colors[:1], (n, 1))
                colors[invalid_mask] = [0.1, 0.1, 0.1]
            else:
                colors = np.tile(np.array([0.5, 0.5, 0.5], dtype=np.float32), (n, 1))
                colors[invalid_mask] = [0.1, 0.1, 0.1]
            self._clouds[cloud_id] = {
                "points": points,
                "colors": colors.astype(np.float32),
                "visible": bool(visible),
                "highlight_indices": highlight_indices,
                "point_size": point_size,
                "vao": None,
                "vbo_pos": None,
                "vbo_col": None,
                "vbo_size": None,
                "point_count": n,
                "uploaded": False,
            }
            # 不在此处上传 VBO：set_pointcloud 可能在非 GL 上下文线程/时机被调用，
            # 统一延迟到 paintGL 中上传，避免生成无效 VAO。
        self._bounds_dirty = True
        self.update()

    def set_pointcloud_visible(self, cloud_id: str, visible: bool):
        """切换指定点云的可见性（不重建 VBO）。"""
        cloud = self._clouds.get(cloud_id)
        if cloud is None:
            return
        cloud["visible"] = bool(visible)
        self._bounds_dirty = True
        self.update()

    def clear_pointclouds(self):
        """删除所有多路点云及其 GPU 资源。"""
        for cloud_id in list(self._clouds.keys()):
            self._remove_cloud(cloud_id)
        self._bounds_dirty = True
        self.update()

    def _remove_cloud(self, cloud_id: str):
        cloud = self._clouds.pop(cloud_id, None)
        if cloud is None:
            return
        if self._has_gl and cloud.get("vao") is not None:
            from OpenGL import GL
            self.makeCurrent()
            try:
                GL.glDeleteVertexArrays(1, [cloud["vao"]])
                GL.glDeleteBuffers(3, [cloud["vbo_pos"], cloud["vbo_col"], cloud["vbo_size"]])
            finally:
                self.doneCurrent()

    def reset_view(self):
        self.camera.reset()
        self.update()

    # ------------------------------------------------------------------
    # 渲染选项（工具栏）
    # ------------------------------------------------------------------
    def set_point_size(self, size: float):
        """点大小 1~5 px，重建 size VBO（数据不变）。"""
        self._point_size = float(max(1.0, min(5.0, size)))
        self._initialized = False
        for cloud in self._clouds.values():
            cloud["uploaded"] = False
        self.update()

    def set_background(self, dark: bool):
        """深色 / 浅色背景切换（仅改清屏色）。"""
        self._bg_color = BG_DARK if dark else BG_LIGHT
        self.update()

    def set_show_axes(self, on: bool):
        self._show_axes = bool(on)
        self.update()

    def set_show_grid(self, on: bool):
        self._show_grid = bool(on)
        self.update()

    def set_view_preset(self, preset: str):
        """视角预设：top / front / side / iso。"""
        self.camera.set_preset(preset)
        self.update()

    def set_overlay_text(self, text: str):
        """GL 叠加层信息文字（左上角半透明条，QLabel 子控件实现）。"""
        self._overlay_text = text or ""
        self._overlay_label.setText(self._overlay_text)
        self._overlay_label.adjustSize()
        self._overlay_label.move(10, 10)
        self._overlay_label.setVisible(bool(self._overlay_text))
        self.update()

    # ------------------------------------------------------------------
    # OpenGL
    # ------------------------------------------------------------------
    def initializeGL(self):
        try:
            from OpenGL import GL
            self._has_gl = True
            GL.glClearColor(*self._bg_color)
            GL.glEnable(GL.GL_DEPTH_TEST)
            GL.glEnable(GL.GL_PROGRAM_POINT_SIZE)
            GL.glEnable(GL.GL_MULTISAMPLE)
            self._shader = self._compile_shader(self.VERTEX_SHADER, self.FRAGMENT_SHADER)
            self._loc_a_position = GL.glGetAttribLocation(self._shader, "a_position")
            self._loc_a_color = GL.glGetAttribLocation(self._shader, "a_color")
            self._loc_a_size = GL.glGetAttribLocation(self._shader, "a_size")
            self._loc_u_mvp = GL.glGetUniformLocation(self._shader, "u_mvp")
            self._vao = GL.glGenVertexArrays(1)
            # 修复原实现 _vbo_col 未创建的隐患：三个 VBO 一次性生成
            self._vbo_pos, self._vbo_col, self._vbo_size = GL.glGenBuffers(3)
            # 参考元素（坐标轴 + 网格地面）线段 VAO
            self._line_vao = GL.glGenVertexArrays(1)
            self._line_vbo_pos, self._line_vbo_col = GL.glGenBuffers(2)
            self._line_pos = None
            self._line_col = None
            self._axes_vert_count = 0
            self._grid_vert_count = 0

            # 选中包围盒 / 旋转中心 线框 VAO
            self._bbox_vao = GL.glGenVertexArrays(1)
            self._bbox_vbo_pos, self._bbox_vbo_col = GL.glGenBuffers(2)
            self._bbox_pos = None
            self._bbox_col = None
            self._bbox_vert_count = 0
            self._pivot_vao = GL.glGenVertexArrays(1)
            self._pivot_vbo_pos, self._pivot_vbo_col = GL.glGenBuffers(2)
            self._pivot_pos = None
            self._pivot_col = None
            self._pivot_vert_count = 0
        except Exception as e:
            logger.error(f"OpenGL 初始化失败: {e}")
            self._has_gl = False

    def _compile_shader(self, vert_src: str, frag_src: str):
        from OpenGL import GL
        vs = GL.glCreateShader(GL.GL_VERTEX_SHADER)
        GL.glShaderSource(vs, vert_src)
        GL.glCompileShader(vs)
        self._check_compile(vs, "vertex")
        fs = GL.glCreateShader(GL.GL_FRAGMENT_SHADER)
        GL.glShaderSource(fs, frag_src)
        GL.glCompileShader(fs)
        self._check_compile(fs, "fragment")
        prog = GL.glCreateProgram()
        GL.glAttachShader(prog, vs)
        GL.glAttachShader(prog, fs)
        GL.glLinkProgram(prog)
        self._check_link(prog)
        GL.glDeleteShader(vs)
        GL.glDeleteShader(fs)
        return prog

    def _check_compile(self, shader, label: str):
        from OpenGL import GL
        if GL.glGetShaderiv(shader, GL.GL_COMPILE_STATUS) != GL.GL_TRUE:
            log = GL.glGetShaderInfoLog(shader).decode()
            raise RuntimeError(f"{label} shader compile error: {log}")

    def _check_link(self, prog):
        from OpenGL import GL
        if GL.glGetProgramiv(prog, GL.GL_LINK_STATUS) != GL.GL_TRUE:
            log = GL.glGetProgramInfoLog(prog).decode()
            raise RuntimeError(f"shader link error: {log}")

    # ------------------------------------------------------------------
    # 参考元素：坐标轴 + 网格地面（世界坐标，数据已按质心居中故需平移）
    # ------------------------------------------------------------------
    def _build_reference_lines(self):
        """生成坐标轴 (18 顶点) + 网格地面线段顶点（世界坐标，由模型矩阵统一居中）。"""
        c = self.centroid.astype(np.float64)
        # 坐标轴原点放在点云质心上方（悬浮显示，避免被网格/点云遮挡）
        origin = c + np.array([0, 0, self._extent * 0.2], dtype=np.float64)
        axis_len = self._extent * 0.4                 # 包围盒对角线 ~40%，让坐标轴更明显
        arrow_len = axis_len * 0.15                   # 箭头长度

        # 坐标轴主线 + 末端箭头（每个轴 2 条箭头线段）
        axes_lines = [
            # X 轴（红）
            (origin, origin + [axis_len, 0, 0]),
            (origin + [axis_len, 0, 0], origin + [axis_len - arrow_len, arrow_len * 0.5, 0]),
            (origin + [axis_len, 0, 0], origin + [axis_len - arrow_len, -arrow_len * 0.5, 0]),
            # Y 轴（绿）
            (origin, origin + [0, axis_len, 0]),
            (origin + [0, axis_len, 0], origin + [arrow_len * 0.5, axis_len - arrow_len, 0]),
            (origin + [0, axis_len, 0], origin + [-arrow_len * 0.5, axis_len - arrow_len, 0]),
            # Z 轴（蓝）
            (origin, origin + [0, 0, axis_len]),
            (origin + [0, 0, axis_len], origin + [0, arrow_len * 0.5, axis_len - arrow_len]),
            (origin + [0, 0, axis_len], origin + [0, -arrow_len * 0.5, axis_len - arrow_len]),
        ]
        axes_pos = np.array(axes_lines, dtype=np.float32).reshape(-1, 3)
        axes_col = np.array([
            [1.0, 0.15, 0.15], [1.0, 0.15, 0.15],     # X 主线亮红
            [1.0, 0.15, 0.15], [1.0, 0.15, 0.15],     # X 箭头
            [1.0, 0.15, 0.15], [1.0, 0.15, 0.15],
            [0.15, 1.0, 0.15], [0.15, 1.0, 0.15],     # Y 主线亮绿
            [0.15, 1.0, 0.15], [0.15, 1.0, 0.15],     # Y 箭头
            [0.15, 1.0, 0.15], [0.15, 1.0, 0.15],
            [0.25, 0.60, 1.0], [0.25, 0.60, 1.0],     # Z 主线亮蓝
            [0.25, 0.60, 1.0], [0.25, 0.60, 1.0],     # Z 箭头
            [0.25, 0.60, 1.0], [0.25, 0.60, 1.0],
        ], dtype=np.float32)

        # 网格：点云 Z 最低点处，XY 以点云质心为中心，10×10 格
        step = _nice_step(self._extent / 10.0)
        half = step * 5.0
        gz = self._z_min
        offs = np.linspace(-half, half, 11)
        lines = []
        for v in offs:  # 22 条线段（常量循环仅 22 次，非点级循环）
            lines.append(([-half, v, gz], [half, v, gz]))
            lines.append(([v, -half, gz], [v, half, gz]))
        grid_pos = np.array(lines, dtype=np.float32).reshape(-1, 3)
        grid_col = np.tile(np.array([[0.45, 0.45, 0.45]], dtype=np.float32),
                           (len(grid_pos), 1))

        self._line_pos = np.concatenate([axes_pos, grid_pos], axis=0)
        self._line_col = np.concatenate([axes_col, grid_col], axis=0)
        self._axes_vert_count = len(axes_pos)
        self._grid_vert_count = len(grid_pos)

    def _upload_data(self):
        if not self._has_gl or self.points is None or self.point_count == 0:
            return
        from OpenGL import GL
        points = self.points.astype(np.float32)
        GL.glBindVertexArray(self._vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo_pos)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, points.nbytes, points, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_position, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_position)
        colors = self.colors.copy()
        sizes = np.full(self.point_count, self._point_size, dtype=np.float32)
        if self.highlight_indices is not None:
            for idx in self.highlight_indices:
                if 0 <= idx < self.point_count:
                    sizes[idx] = 10.0
                    colors[idx] = [1.0, 0.0, 0.0]
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo_col)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, colors.nbytes, colors, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_color, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_color)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo_size)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, sizes.nbytes, sizes, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_size, 1, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_size)
        GL.glBindVertexArray(0)
        self._initialized = True

    def _upload_cloud(self, cloud_id: str):
        """为指定 cloud_id 创建/更新 VAO/VBO（原始世界坐标，居中由模型矩阵完成）。"""
        if not self._has_gl:
            return
        cloud = self._clouds.get(cloud_id)
        if cloud is None:
            return
        from OpenGL import GL
        if cloud["vao"] is None:
            cloud["vao"] = GL.glGenVertexArrays(1)
            cloud["vbo_pos"], cloud["vbo_col"], cloud["vbo_size"] = GL.glGenBuffers(3)
        n = cloud["point_count"]
        points = cloud["points"].astype(np.float32)
        colors = cloud["colors"].copy()
        size = cloud.get("point_size")
        if size is None or size <= 0:
            size = self._point_size
        sizes = np.full(n, float(size), dtype=np.float32)
        hili = cloud.get("highlight_indices")
        if hili is not None:
            for idx in hili:
                if 0 <= idx < n:
                    sizes[idx] = 10.0
                    colors[idx] = [1.0, 0.0, 0.0]
        GL.glBindVertexArray(cloud["vao"])
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, cloud["vbo_pos"])
        GL.glBufferData(GL.GL_ARRAY_BUFFER, points.nbytes, points, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_position, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_position)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, cloud["vbo_col"])
        GL.glBufferData(GL.GL_ARRAY_BUFFER, colors.nbytes, colors, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_color, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_color)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, cloud["vbo_size"])
        GL.glBufferData(GL.GL_ARRAY_BUFFER, sizes.nbytes, sizes, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_size, 1, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_size)
        GL.glBindVertexArray(0)
        cloud["uploaded"] = True

    def _upload_reference_lines(self):
        """上传参考元素（坐标轴/网格）线段到 GPU。"""
        if not self._has_gl or self._line_pos is None or self._line_col is None:
            return
        from OpenGL import GL
        GL.glBindVertexArray(self._line_vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._line_vbo_pos)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, self._line_pos.nbytes,
                        self._line_pos, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_position, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_position)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._line_vbo_col)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, self._line_col.nbytes,
                        self._line_col, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_color, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_color)
        GL.glBindVertexArray(0)

    def set_selection_bbox(self, bounds_list: List[tuple]):
        """设置选中点云的包围盒线框；bounds_list 元素为 (min, max) 各为 3 元组。"""
        if not bounds_list:
            self._bbox_pos = None
            self._bbox_col = None
            self._bbox_vert_count = 0
            self.update()
            return
        lines = []
        for (bmin, bmax) in bounds_list:
            bmin = np.asarray(bmin, dtype=np.float32)
            bmax = np.asarray(bmax, dtype=np.float32)
            corners = np.array([
                [bmin[0], bmin[1], bmin[2]],
                [bmax[0], bmin[1], bmin[2]],
                [bmax[0], bmax[1], bmin[2]],
                [bmin[0], bmax[1], bmin[2]],
                [bmin[0], bmin[1], bmax[2]],
                [bmax[0], bmin[1], bmax[2]],
                [bmax[0], bmax[1], bmax[2]],
                [bmin[0], bmax[1], bmax[2]],
            ], dtype=np.float32)
            edges = [
                (0, 1), (1, 2), (2, 3), (3, 0),
                (4, 5), (5, 6), (6, 7), (7, 4),
                (0, 4), (1, 5), (2, 6), (3, 7),
            ]
            for i, j in edges:
                lines.append(corners[i])
                lines.append(corners[j])
        self._bbox_pos = np.array(lines, dtype=np.float32)
        self._bbox_col = np.tile(np.array([[1.0, 0.2, 0.2]], dtype=np.float32),
                                 (len(lines), 1))
        self._bbox_vert_count = len(lines)
        self.update()

    def _upload_bbox_lines(self):
        """上传包围盒线框到 GPU。"""
        if not self._has_gl or self._bbox_pos is None or self._bbox_col is None:
            return
        from OpenGL import GL
        GL.glBindVertexArray(self._bbox_vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._bbox_vbo_pos)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, self._bbox_pos.nbytes,
                        self._bbox_pos, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_position, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_position)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._bbox_vbo_col)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, self._bbox_col.nbytes,
                        self._bbox_col, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_color, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_color)
        GL.glBindVertexArray(0)

    def set_pivot_visible(self, visible: bool):
        """显示/隐藏旋转中心高亮圆点。"""
        self._pivot_visible = bool(visible)
        self.update()

    def set_pivot_position(self, pos):
        """设置旋转中心位置并更新高亮圆点。"""
        self._pivot_position = np.asarray(pos, dtype=np.float32)
        self._update_pivot_position(self._pivot_position)

    def _update_pivot_position(self, pos):
        """生成旋转中心高亮圆点（单点渲染，大尺寸）。"""
        pos = np.asarray(pos, dtype=np.float32)
        self._pivot_pos = pos.reshape(1, 3)
        # 高亮橙黄色
        self._pivot_col = np.array([[1.0, 0.8, 0.2]], dtype=np.float32)
        self._pivot_vert_count = 1
        self.update()

    def _upload_pivot_lines(self):
        """上传旋转中心圆点到 GPU（单点，大点尺寸）。"""
        if not self._has_gl or self._pivot_pos is None or self._pivot_col is None:
            return
        from OpenGL import GL
        GL.glBindVertexArray(self._pivot_vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._pivot_vbo_pos)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, self._pivot_pos.nbytes,
                        self._pivot_pos, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_position, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_position)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._pivot_vbo_col)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, self._pivot_col.nbytes,
                        self._pivot_col, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_color, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_color)
        # 单点：位置、颜色、大小（大小在 paintGL 中通过 glVertexAttrib1f 设置）
        GL.glBindVertexArray(0)

    def _update_scene_bounds(self):
        """根据当前可见点云（多路 + 遗留单路）重新计算场景质心与相机参数。"""
        visible_points = []
        for cloud in self._clouds.values():
            if not cloud.get("visible", True):
                continue
            pts = cloud["points"]
            mask = np.isfinite(pts).all(axis=1)
            if mask.any():
                visible_points.append(pts[mask])
        if self.points is not None and self.point_count > 0:
            pts = self.points
            mask = np.isfinite(pts).all(axis=1)
            if mask.any():
                visible_points.append(pts[mask])
        if visible_points:
            all_pts = np.concatenate(visible_points, axis=0)
            self.centroid = all_pts.mean(axis=0).astype(np.float32)
            extent_xyz = all_pts.max(axis=0) - all_pts.min(axis=0)
            self._extent = max(float(np.linalg.norm(extent_xyz)), 1e-3)
            self._z_min = float(all_pts[:, 2].min())
            self._z_max = float(all_pts[:, 2].max())
        else:
            self.centroid = np.zeros(3, dtype=np.float32)
            self._extent = 10.0
            self._z_min = self._z_max = 0.0
        self.camera.target = self.centroid.astype(np.float32)
        self.camera.distance = max(self._extent * 1.5, 1.0)
        self._bounds_dirty = True

    def paintGL(self):
        if not self._has_gl:
            return
        from OpenGL import GL
        # 排空上一帧 QPainter 叠加层 / Qt 绘制引擎遗留的良性 GL 错误标志，
        # 避免 PyOpenGL errorchecker 在本帧首个调用处误报
        while GL.glGetError() != GL.GL_NO_ERROR:
            pass
        GL.glClearColor(*self._bg_color)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)

        has_legacy = self.points is not None and self.point_count > 0
        has_multi = bool(self._clouds)
        if not has_legacy and not has_multi:
            return

        if self._bounds_dirty:
            self._update_scene_bounds()
            self._line_pos = None
            self._bounds_dirty = False

        aspect = self.width() / max(self.height(), 1)
        proj = QMatrix4x4()
        far_plane = max(self._extent * 5.0, 100.0)
        proj.perspective(45.0, aspect, max(self._extent * 0.001, 1e-4), far_plane)
        view = self.camera.view_matrix()
        model = QMatrix4x4()
        model.translate(-self.centroid[0], -self.centroid[1], -self.centroid[2])
        mvp = proj * view * model

        # 缓存 MVP 供反投影/投影使用（column-major）
        self._mvp_matrix = np.array(mvp.data(), dtype=np.float64).reshape(4, 4, order='F')
        try:
            self._mvp_inv = np.linalg.inv(self._mvp_matrix)
        except np.linalg.LinAlgError:
            self._mvp_inv = None

        GL.glUseProgram(self._shader)
        GL.glUniformMatrix4fv(self._loc_u_mvp, 1, GL.GL_FALSE, mvp.data())

        if has_multi:
            for cid, cloud in self._clouds.items():
                if not cloud.get("visible", True):
                    continue
                if not cloud.get("uploaded"):
                    self._upload_cloud(cid)
                if cloud["point_count"] > 0:
                    GL.glBindVertexArray(cloud["vao"])
                    GL.glDrawArrays(GL.GL_POINTS, 0, cloud["point_count"])
                    GL.glBindVertexArray(0)
        elif has_legacy:
            if not self._initialized:
                self._upload_data()
            GL.glBindVertexArray(self._vao)
            GL.glDrawArrays(GL.GL_POINTS, 0, self.point_count)
            GL.glBindVertexArray(0)

        # 参考元素线段（同一 shader / MVP，点大小属性用常量 1）
        if self._show_axes or self._show_grid:
            if self._bounds_dirty or self._line_pos is None:
                self._build_reference_lines()
                self._upload_reference_lines()
                self._bounds_dirty = False
            GL.glBindVertexArray(self._line_vao)
            GL.glVertexAttrib1f(self._loc_a_size, 1.0)
            if self._show_axes and self._axes_vert_count:
                GL.glDrawArrays(GL.GL_LINES, 0, self._axes_vert_count)
            if self._show_grid and self._grid_vert_count:
                GL.glDrawArrays(GL.GL_LINES, self._axes_vert_count,
                                self._grid_vert_count)
            GL.glBindVertexArray(0)

        # 选中包围盒线框
        if self._bbox_pos is not None and self._bbox_vert_count > 0:
            self._upload_bbox_lines()
            GL.glBindVertexArray(self._bbox_vao)
            GL.glVertexAttrib1f(self._loc_a_size, 1.0)
            GL.glDrawArrays(GL.GL_LINES, 0, self._bbox_vert_count)
            GL.glBindVertexArray(0)

        # 旋转中心高亮圆点
        if self._pivot_visible and self._pivot_pos is not None and self._pivot_vert_count > 0:
            self._upload_pivot_lines()
            GL.glBindVertexArray(self._pivot_vao)
            # 大点尺寸：比点云点大 3 倍，至少 8px
            pivot_size = max(self._point_size * 3.0, 8.0)
            GL.glVertexAttrib1f(self._loc_a_size, pivot_size)
            GL.glDrawArrays(GL.GL_POINTS, 0, self._pivot_vert_count)
            GL.glBindVertexArray(0)

        GL.glUseProgram(0)

        # 2D 叠加层：比例尺（QPainter 绘制）
        self._draw_scale_bar()

    def _draw_scale_bar(self):
        """在右下角绘制比例尺（类似 CloudCompare）。"""
        if self._extent <= 0:
            return
        from PySide6.QtGui import QPainter, QPen, QColor, QFont
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 目标比例尺像素长度
        target_px = 100
        # 世界坐标中 100px 对应的长度（近似：根据当前缩放和视口）
        # 简化：用点云 extent 的 1/10 作为比例尺基准
        world_len = self._extent / 10.0
        # 取整到 1/2/5 × 10^k
        world_len = _nice_step(world_len)

        # 比例尺位置（右下角）
        margin = 20
        y = self.height() - margin - 10
        x_end = self.width() - margin
        x_start = x_end - target_px

        # 绘制比例尺线
        painter.setPen(QPen(QColor(200, 200, 200), 2))
        painter.drawLine(x_start, y, x_end, y)
        # 端点刻度
        painter.drawLine(x_start, y - 5, x_start, y + 5)
        painter.drawLine(x_end, y - 5, x_end, y + 5)

        # 绘制文字
        font = QFont("Arial", 9)
        painter.setFont(font)
        text = self._format_scale(world_len)
        text_width = painter.fontMetrics().horizontalAdvance(text)
        painter.drawText(x_start + (target_px - text_width) // 2, y - 8, text)

        painter.end()

    @staticmethod
    def _format_scale(length: float) -> str:
        """格式化比例尺文字。"""
        if length >= 1000:
            return f"{length / 1000:.1f} m"
        elif length >= 1:
            return f"{length:.0f} mm"
        else:
            return f"{length * 1000:.0f} μm"

    def resizeGL(self, w: int, h: int):
        if self._has_gl:
            from OpenGL import GL
            GL.glViewport(0, 0, w, h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 保持坐标轴指示器在左下角
        self._axes_indicator.move(10, self.height() - 74)

    # ------------------------------------------------------------------
    # 鼠标交互
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if self._roi_mode and event.button() == Qt.LeftButton:
            self._roi_start = event.pos()
            self._ensure_rubberband()
            self._roi_rubberband.setGeometry(event.x(), event.y(), 0, 0)
            self._roi_rubberband.show()
            return
        # 中键点击：设置旋转中心（单击，非双击）
        if event.button() == Qt.MiddleButton:
            self._set_rotation_center(event.pos())
            return
        self.camera.begin_drag(event.pos())

    def mouseMoveEvent(self, event):
        if self._roi_mode and self._roi_start is not None:
            rect = self._roi_rect_from_points(self._roi_start, event.pos())
            self._roi_rubberband.setGeometry(rect)
            return
        self.camera.drag(event.pos(), event.buttons())
        self._axes_indicator.set_rotation(self.camera.rotation_x, self.camera.rotation_y)
        self.update()

    def mouseReleaseEvent(self, event):
        if self._roi_mode and event.button() == Qt.LeftButton and self._roi_start is not None:
            self._roi_rect = self._roi_rect_from_points(self._roi_start, event.pos())
            self._roi_start = None
            self._roi_rubberband.hide()
            self._compute_roi_selection()
            return
        self.camera.end_drag()

    def screen_to_world(self, screen_pos):
        """把屏幕坐标反投影到世界坐标（读取深度缓冲精确求交）。"""
        if self._mvp_inv is None:
            return None
        # 读取深度缓冲获取点击位置深度
        try:
            from OpenGL import GL
            self.makeCurrent()
            x = int(screen_pos.x())
            y = int(self.height() - screen_pos.y() - 1)
            depth = GL.glReadPixels(x, y, 1, 1, GL.GL_DEPTH_COMPONENT, GL.GL_FLOAT)
            z = float(depth[0][0])
        except Exception:
            z = 0.5  # 失败时取中点

        # NDC 坐标
        ndc_x = (2.0 * screen_pos.x()) / self.width() - 1.0
        ndc_y = 1.0 - (2.0 * screen_pos.y()) / self.height()
        ndc_z = 2.0 * z - 1.0  # 深度 [0,1] -> NDC [-1,1]
        ndc = np.array([ndc_x, ndc_y, ndc_z, 1.0], dtype=np.float64)
        world = self._mvp_inv @ ndc
        if abs(world[3]) < 1e-12:
            return None
        world = world[:3] / world[3]
        return world.astype(np.float32)

    def set_roi_mode(self, enabled: bool):
        """进入/退出 ROI 矩形框选模式。"""
        self._roi_mode = bool(enabled)
        if not self._roi_mode:
            self._roi_start = None
            self._roi_rect = None
            self._roi_selected_indices = {}
            if self._roi_rubberband is not None:
                self._roi_rubberband.hide()
        self.update()

    def clear_roi_selection(self):
        """清除 ROI 高亮与选中索引。"""
        self._roi_rect = None
        self._roi_selected_indices = {}
        # 恢复所有点云原始颜色
        for cloud in self._clouds.values():
            if "orig_colors" in cloud and cloud["orig_colors"] is not None:
                cloud["colors"] = cloud["orig_colors"]
                cloud["orig_colors"] = None
                cloud["uploaded"] = False
        self._initialized = False
        self.update()

    def get_roi_selection(self) -> Dict[str, np.ndarray]:
        """返回当前 ROI 选中的各 cloud_id 索引数组。"""
        return {k: v.copy() for k, v in self._roi_selected_indices.items()}

    def _ensure_rubberband(self):
        if self._roi_rubberband is None:
            from PySide6.QtWidgets import QRubberBand
            self._roi_rubberband = QRubberBand(QRubberBand.Rectangle, self)
            self._roi_rubberband.setStyleSheet(
                "QRubberBand { border: 2px dashed #FF5252; background-color: rgba(255,82,82,30); }"
            )

    @staticmethod
    def _roi_rect_from_points(a, b):
        from PySide6.QtCore import QRect
        x1, y1 = a.x(), a.y()
        x2, y2 = b.x(), b.y()
        return QRect(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y1 - y2))

    def _compute_roi_selection(self):
        """根据 _roi_rect 计算每个可见点云的选中索引。"""
        self._roi_selected_indices = {}
        if self._roi_rect is None or self._roi_rect.width() < 3 or self._roi_rect.height() < 3:
            return
        rect = self._roi_rect
        # 读取矩形区域深度缓冲
        depth_buf = self._read_depth_rect(rect)
        if depth_buf is None:
            return
        h = self.height()
        # 反投影深度缓冲到世界坐标平面（可选：直接在屏幕空间比较深度）
        for cloud_id, cloud in self._clouds.items():
            if not cloud.get("visible", True):
                continue
            pts = cloud["points"]
            if len(pts) == 0:
                continue
            screen = self.world_to_screen(pts)
            if screen is None:
                continue
            sx = screen[:, 0]
            sy = screen[:, 1]
            sz = screen[:, 2]
            in_rect = (
                (sx >= rect.left()) & (sx <= rect.right()) &
                (sy >= rect.top()) & (sy <= rect.bottom()) &
                (sz >= 0.0) & (sz <= 1.0)
            )
            if not in_rect.any():
                continue
            # 对矩形内点采样深度缓冲
            ix = np.clip(np.round(sx[in_rect]).astype(np.int32), rect.left(), rect.right())
            iy = np.clip(np.round(h - 1 - sy[in_rect]).astype(np.int32),
                         h - 1 - rect.bottom(), h - 1 - rect.top())
            # depth_buf 索引：[y - rect.top(), x - rect.left()]
            bufx = ix - rect.left()
            bufy = iy - (h - 1 - rect.bottom())
            buf_h, buf_w = depth_buf.shape
            bufx = np.clip(bufx, 0, buf_w - 1)
            bufy = np.clip(bufy, 0, buf_h - 1)
            sampled = depth_buf[bufy, bufx]
            # 深度匹配：使用绝对容差 0.005 + 相对容差 1%
            tol = 0.005 + 0.01 * sampled
            visible = np.abs(sz[in_rect] - sampled) < tol
            idx_in_rect = np.nonzero(in_rect)[0]
            selected = idx_in_rect[visible]
            if len(selected) > 0:
                self._roi_selected_indices[cloud_id] = selected
        # 高亮显示选中点
        self._highlight_roi_selection()

    def _read_depth_rect(self, rect):
        """读取矩形区域深度缓冲，返回 float32 [h, w] 数组。"""
        try:
            from OpenGL import GL
            self.makeCurrent()
            x = max(0, rect.left())
            y = max(0, self.height() - rect.bottom() - 1)
            w = min(rect.width(), self.width() - x)
            h = min(rect.height(), self.height() - y)
            if w <= 0 or h <= 0:
                return None
            buf = GL.glReadPixels(x, y, w, h, GL.GL_DEPTH_COMPONENT, GL.GL_FLOAT)
            return np.asarray(buf, dtype=np.float32).reshape(h, w)
        except Exception:
            return None

    def _highlight_roi_selection(self):
        """将 ROI 选中点临时标红（保留原始颜色用于恢复）。"""
        for cloud_id, indices in self._roi_selected_indices.items():
            cloud = self._clouds.get(cloud_id)
            if cloud is None:
                continue
            # 首次高亮时保存原始颜色
            if cloud.get("orig_colors") is None:
                cloud["orig_colors"] = cloud["colors"].copy()
            colors = cloud["colors"].copy()
            colors[indices] = [1.0, 0.0, 0.0]
            cloud["colors"] = colors
            cloud["uploaded"] = False
        self.update()

    def _set_rotation_center(self, pos):
        """把旋转中心设置到鼠标点击位置对应的 3D 点（通过深度缓冲反投影）。"""
        if not self._has_gl:
            return
        depth = self._read_depth(pos.x(), pos.y())
        if depth is None or depth >= 0.99999:
            return
        world_pos = self.screen_to_world(pos.x(), pos.y(), depth)
        if world_pos is None:
            return
        self.camera.set_target(world_pos, keep_position=True)
        self._update_pivot_position(world_pos)
        self.set_pivot_visible(True)
        self.update()

    def _read_depth(self, x: int, y: int):
        """读取 (x,y) 处深度缓冲值，失败返回 None。"""
        try:
            from OpenGL import GL
            self.makeCurrent()
            px = max(0, min(x, self.width() - 1))
            # OpenGL 原点在左下角，y 需要翻转
            py = max(0, min(self.height() - 1 - y, self.height() - 1))
            depth = GL.glReadPixels(px, py, 1, 1, GL.GL_DEPTH_COMPONENT, GL.GL_FLOAT)
            return float(depth[0][0])
        except Exception:
            return None

    def screen_to_world(self, x: float, y: float, depth: float):
        """屏幕坐标 + 深度 → 世界坐标；depth 为 [0,1]（OpenGL 深度缓冲值）。"""
        if self._mvp_inv is None:
            return None
        w, h = max(self.width(), 1), max(self.height(), 1)
        ndc = np.array([
            2.0 * x / w - 1.0,
            1.0 - 2.0 * y / h,
            2.0 * depth - 1.0,
            1.0,
        ], dtype=np.float64)
        world_h = self._mvp_inv @ ndc
        if abs(world_h[3]) < 1e-9:
            return None
        return world_h[:3] / world_h[3]

    def world_to_screen(self, points: np.ndarray):
        """世界坐标 (N,3) → 屏幕坐标 (N,3)，第三列为 OpenGL 深度 [0,1]。"""
        if self._mvp_matrix is None:
            return None
        pts = np.asarray(points, dtype=np.float64)
        n = len(pts)
        homo = np.concatenate([pts, np.ones((n, 1), dtype=np.float64)], axis=1)
        clip = (self._mvp_matrix @ homo.T).T
        w = np.where(clip[:, 3:] != 0, clip[:, 3:], 1.0)
        ndc = clip[:, :3] / w
        sx = (ndc[:, 0] + 1.0) * 0.5 * self.width()
        sy = (1.0 - ndc[:, 1]) * 0.5 * self.height()
        sz = (ndc[:, 2] + 1.0) * 0.5
        return np.stack([sx, sy, sz], axis=1)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self.camera.zoom_in()
        else:
            self.camera.zoom_out()
        self.update()


class _ArcBallCamera:
    """轨道相机控制器（左键旋转 / 右键平移 / 滚轮缩放 / 中键设中心）。

    使用旋转矩阵累积旋转，避免欧拉角万向锁，实现真正的全方位旋转。
    相机位置 = target + R @ (0, 0, distance)，其中 R 为旋转矩阵。
    """

    def __init__(self, distance: float = 2.0):
        self._rotation = np.eye(3, dtype=np.float32)  # 旋转矩阵（行向量）
        self._distance = distance
        self.target = np.zeros(3, dtype=np.float32)
        self._last_pos = None
        self._tracking = False
        # 初始为等轴视图
        self.set_preset("iso")

    @property
    def distance(self) -> float:
        return self._distance

    @distance.setter
    def distance(self, value: float):
        self._distance = max(1e-4, value)

    def position(self) -> np.ndarray:
        """根据当前旋转矩阵计算相机 eye 位置。"""
        offset = self._rotation @ np.array([0, 0, self._distance], dtype=np.float32)
        return self.target + offset

    def _basis(self):
        """返回相机坐标系在世界坐标下的 (right, up, forward)。"""
        # 旋转矩阵的列向量即相机坐标系在世界中的方向
        right = self._rotation[:, 0]
        up = self._rotation[:, 1]
        forward = -self._rotation[:, 2]  # 相机看向 -Z
        return right, up, forward

    def begin_drag(self, pos):
        self._last_pos = pos
        self._tracking = True

    def drag(self, pos, buttons):
        if not self._tracking or self._last_pos is None:
            return
        dx = pos.x() - self._last_pos.x()
        dy = pos.y() - self._last_pos.y()
        self._last_pos = pos
        if buttons == Qt.LeftButton:
            # 左键旋转：灵敏度根据距离自适应（越远越灵敏，避免大场景转不动）
            sensitivity = max(0.1, self._distance * 0.02)
            # 绕世界 Y 轴旋转（水平拖动）
            angle_y = np.radians(dx * sensitivity)
            # 绕相机 right 轴旋转（垂直拖动）
            right, _, _ = self._basis()
            angle_x = np.radians(dy * sensitivity)
            # 累积旋转：先绕世界 Y 轴，再绕相机 right 轴
            R_y = self._rotation_matrix_from_axis_angle([0, 1, 0], angle_y)
            R_x = self._rotation_matrix_from_axis_angle(right, angle_x)
            self._rotation = R_x @ R_y @ self._rotation
            # 正交化，避免数值漂移
            self._orthonormalize()
        elif buttons == Qt.RightButton:
            # 右键平移
            sens = self._distance * np.tan(np.radians(22.5)) * 2.0 / 1000.0
            right, up, _ = self._basis()
            delta = -dx * sens * right + dy * sens * up
            self.target += delta

    @staticmethod
    def _rotation_matrix_from_axis_angle(axis, angle: float) -> np.ndarray:
        """Rodrigues 公式：轴角转旋转矩阵。"""
        axis = np.asarray(axis, dtype=np.float32)
        norm = np.linalg.norm(axis)
        if norm < 1e-9:
            return np.eye(3, dtype=np.float32)
        axis = axis / norm
        K = np.array([
            [0, -axis[2], axis[1]],
            [axis[2], 0, -axis[0]],
            [-axis[1], axis[0], 0],
        ], dtype=np.float32)
        I = np.eye(3, dtype=np.float32)
        return I + np.sin(angle) * K + (1.0 - np.cos(angle)) * (K @ K)

    def _orthonormalize(self):
        """Gram-Schmidt 正交化旋转矩阵。"""
        x = self._rotation[:, 0]
        y = self._rotation[:, 1]
        z = self._rotation[:, 2]
        x = x / max(np.linalg.norm(x), 1e-9)
        y = y - np.dot(y, x) * x
        y = y / max(np.linalg.norm(y), 1e-9)
        z = np.cross(x, y)
        self._rotation = np.column_stack([x, y, z])

    def end_drag(self):
        self._tracking = False

    def zoom_in(self, step: float = 0.1):
        self._distance = max(1e-4, self._distance * (1.0 - step))

    def zoom_out(self, step: float = 0.1):
        self._distance = max(1e-4, self._distance * (1.0 + step))

    def view_matrix(self) -> QMatrix4x4:
        m = QMatrix4x4()
        pos = self.position()
        _, up, _ = self._basis()
        m.lookAt(
            QVector3D(float(pos[0]), float(pos[1]), float(pos[2])),
            QVector3D(float(self.target[0]), float(self.target[1]), float(self.target[2])),
            QVector3D(float(up[0]), float(up[1]), float(up[2])),
        )
        return m

    def set_target(self, target, keep_position: bool = False):
        """设置旋转中心；keep_position=True 时保持相机 eye 位置不变（画面不跳）。"""
        target = np.asarray(target, dtype=np.float32)
        if keep_position:
            pos = self.position()  # 先保存当前位置
            old_distance = self._distance
            self.target = target
            # 重新计算旋转矩阵，使相机位置保持不变
            diff = pos - self.target
            d = float(np.linalg.norm(diff))
            if d > 1e-9:
                # 根据新 target 和旧 position 重建旋转矩阵
                forward = -diff / d  # 相机看向 target，所以 forward 是从 camera 指向 target
                world_up = np.array([0.0, 0.0, 1.0], dtype=np.float32)
                right = np.cross(forward, world_up)
                rnorm = np.linalg.norm(right)
                if rnorm < 1e-9:
                    right = np.array([1.0, 0.0, 0.0], dtype=np.float32)
                else:
                    right = right / rnorm
                up = np.cross(right, forward)
                # 旋转矩阵的列向量：right, up, -forward
                self._rotation = np.column_stack([right, up, -forward])
            self._distance = old_distance
        else:
            self.target = target

    def set_preset(self, preset: str):
        """设置视角预设。"""
        # camera_pos_dir: 相机位置相对于 target 的方向
        # up_hint: 世界上方向提示
        presets = {
            "top": (np.array([0, 0, 1]), np.array([0, 1, 0])),      # 相机在 +Z，看向 -Z
            "front": (np.array([0, -1, 0]), np.array([0, 0, 1])),   # 相机在 -Y，看向 +Y
            "side": (np.array([1, 0, 0]), np.array([0, 0, 1])),     # 相机在 +X，看向 -X
            "iso": (np.array([1, -1, 1]) / np.sqrt(3), np.array([0, 0, 1])),  # 等轴
        }
        camera_pos_dir, up_hint = presets.get(preset, presets["iso"])
        camera_pos_dir = np.asarray(camera_pos_dir, dtype=np.float32)
        camera_pos_dir = camera_pos_dir / np.linalg.norm(camera_pos_dir)
        up_hint = np.asarray(up_hint, dtype=np.float32)
        # 相机看向 target，所以 forward 是从 camera 指向 target
        forward = -camera_pos_dir
        # 构建旋转矩阵：right = up_hint × forward, up = forward × right
        right = np.cross(up_hint, forward)
        right = right / max(np.linalg.norm(right), 1e-9)
        up = np.cross(forward, right)
        # 旋转矩阵的列向量：right, up, -forward（相机看向 -Z）
        self._rotation = np.column_stack([right, up, -forward])
        self.target = np.zeros(3, dtype=np.float32)

    def reset(self):
        self.set_preset("iso")

    # 兼容旧接口（用于坐标轴指示器）
    @property
    def rotation_x(self) -> float:
        """从旋转矩阵提取近似俯仰角（仅用于显示，不用于控制）。"""
        # 从旋转矩阵第二行第三列提取
        return float(np.degrees(np.arcsin(np.clip(-self._rotation[1, 2], -1.0, 1.0))))

    @property
    def rotation_y(self) -> float:
        """从旋转矩阵提取近似水平角（仅用于显示，不用于控制）。"""
        return float(np.degrees(np.arctan2(self._rotation[0, 2], self._rotation[2, 2])))


# =========================================================================
# EmbeddedPointCloudViewer —— N 路嵌入式点云查看器（含顶部工具栏）
# =========================================================================
class EmbeddedPointCloudViewer(QWidget):
    """N 路嵌入式点云查看器：全部叠加 / 合并结果 / 单相机 三种显示模式。"""

    status_changed = Signal(str)    # 状态变化信号，用于输出到主窗口日志
    maximize_toggled = Signal(bool)  # 最大化切换（主窗口隐藏 / 恢复卡片区）
    collapse_toggled = Signal(bool)  # 折叠切换（True=展开，False=折叠，主窗口释放空间）

    MODE_OVERLAY = "__overlay__"   # 全部叠加
    MODE_MERGED = "__merged__"     # 合并结果

    # 单帧点云超过该阈值时先降采样再上传 VBO，保留原始 open3d 对象用于保存 PLY
    MAX_RENDER_POINTS = 1_500_000
    # 体素降采样最大体素尺寸（mm），防止大场景 AABB 过大时把有效点过度塌缩
    MAX_RENDER_VOXEL_MM = 3.0

    COLOR_STATION = "station"      # 按站位着色（默认）
    COLOR_HEIGHT = "height"        # 按高度着色（jet）
    COLOR_GRAY = "gray"            # 灰度

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pcds: Dict[str, object] = {}     # camera_id → open3d 点云
        self._pcd_merged = None
        self._camera_order: List[str] = []     # 颜色分配顺序
        self._reference_id: Optional[str] = None
        self._highlights: Dict[str, list] = {}  # camera_id → 高亮索引
        self._current_mode = self.MODE_OVERLAY
        self._viewer: Optional[PointCloudViewer] = None
        # 当前渲染数据缓存（着色模式切换时免重建点云读取）
        self._last_points: Optional[np.ndarray] = None
        self._last_base_colors: Optional[np.ndarray] = None
        self._last_name: str = ""
        self._last_highlight: Optional[list] = None
        self._maximized = False
        self._minimal_toolbar = False
        self._toolbar_widgets: List[QWidget] = []
        self._setup_ui()
        self._setup_viewer()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(2, 2, 2, 2)
        lo.setSpacing(2)

        lo.addWidget(self._build_toolbar())

        # OpenGL 渲染容器（叠加信息层在 GL 内部绘制，原底部状态行已移除）
        self.viewer_container = QWidget()
        self.viewer_container.setStyleSheet("background-color: #1a1a1a; border: 1px solid #3a3a3a;")
        self.viewer_container.setMinimumSize(320, 200)
        self.viewer_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lo.addWidget(self.viewer_container, 1)

    def _build_toolbar(self) -> QWidget:
        """顶部紧凑工具栏（~32px，深色主题）。"""
        bar = QWidget()
        bar.setFixedHeight(34)
        bar.setStyleSheet(
            "QWidget { background-color: #252525; border: 1px solid #3a3a3a; }"
            "QToolButton, QPushButton { background: transparent; border: none; "
            "color: #cccccc; font-size: 10pt; padding: 2px 5px; min-height: 20px; }"
            "QToolButton { icon-size: 16px; }"
            "QToolButton:hover, QPushButton:hover { color: #ffffff; background: #3a3a3a; "
            "border-radius: 3px; }"
            "QToolButton:checked, QPushButton:checked { color: #2979FF; background: #1E3A5F; "
            "border-radius: 3px; }"
            "QLabel { color: #888888; font-size: 10pt; background: transparent; border: none; }"
            "QComboBox, QSpinBox { font-size: 10pt; min-height: 22px; }"
        )
        tb = QHBoxLayout(bar)
        tb.setContentsMargins(6, 2, 6, 2)
        tb.setSpacing(6)

        # 折叠按钮（切换 GL 区域显隐，工具栏保留；view_iso.png 立方体图标）
        self.btn_collapse = QToolButton()
        self.btn_collapse.setText("▾ 3D")
        self.btn_collapse.setToolTip("折叠 / 展开点云查看区域")
        self.btn_collapse.setCheckable(True)
        self.btn_collapse.setChecked(True)
        self.btn_collapse.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_collapse.toggled.connect(self._on_collapse_toggled)
        apply_icon(self.btn_collapse, "view_iso")
        tb.addWidget(self.btn_collapse)
        self._toolbar_widgets.append(self.btn_collapse)

        # 显示模式
        lbl_mode = QLabel("显示:")
        tb.addWidget(lbl_mode)
        self._toolbar_widgets.append(lbl_mode)
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("全部叠加", self.MODE_OVERLAY)
        self.combo_mode.addItem("合并结果", self.MODE_MERGED)
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        tb.addWidget(self.combo_mode, 1)
        self._toolbar_widgets.append(self.combo_mode)

        # 着色模式
        lbl_color = QLabel("着色:")
        tb.addWidget(lbl_color)
        self._toolbar_widgets.append(lbl_color)
        self.combo_color = QComboBox()
        self.combo_color.addItem("按站位", self.COLOR_STATION)
        self.combo_color.addItem("按高度", self.COLOR_HEIGHT)
        self.combo_color.addItem("灰度", self.COLOR_GRAY)
        self.combo_color.currentIndexChanged.connect(self._on_color_mode_changed)
        tb.addWidget(self.combo_color)
        self._toolbar_widgets.append(self.combo_color)

        # 点大小
        lbl_size = QLabel("点大小:")
        tb.addWidget(lbl_size)
        self._toolbar_widgets.append(lbl_size)
        self.spin_point_size = QSpinBox()
        self.spin_point_size.setRange(1, 5)
        self.spin_point_size.setValue(1)
        self.spin_point_size.valueChanged.connect(self._on_point_size_changed)
        tb.addWidget(self.spin_point_size)
        self._toolbar_widgets.append(self.spin_point_size)

        # 视角预设（纯文字按钮；提供 view_top/view_front/view_side/view_iso
        # 图标文件后变为图标+文字）
        lbl_view = QLabel("视角:")
        tb.addWidget(lbl_view)
        self._toolbar_widgets.append(lbl_view)
        for text, preset in (("顶", "top"), ("前", "front"),
                             ("侧", "side"), ("等轴", "iso")):
            btn = QToolButton()
            btn.setText(text)
            btn.setToolTip(f"{text}视图")
            btn.clicked.connect(lambda _=False, p=preset: self.set_view_preset(p))
            apply_icon(btn, f"view_{preset}")
            tb.addWidget(btn)
            self._toolbar_widgets.append(btn)

        # 重置视角
        self.btn_reset_view = QToolButton()
        self.btn_reset_view.setText(icon_text("reset_view", "🔄 重置"))
        self.btn_reset_view.setToolTip("重置视角（等轴测）")
        self.btn_reset_view.clicked.connect(self.reset_view)
        apply_icon(self.btn_reset_view, "reset_view")
        tb.addWidget(self.btn_reset_view)
        self._toolbar_widgets.append(self.btn_reset_view)

        # 参考元素开关（checkable 图标按钮，checked 高亮由工具栏样式表区分）
        self.btn_axes = QToolButton()
        self.btn_axes.setText("坐标轴")
        self.btn_axes.setToolTip("显示 / 隐藏原点坐标轴")
        self.btn_axes.setCheckable(True)
        self.btn_axes.setChecked(True)
        self.btn_axes.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_axes.toggled.connect(self._on_axes_toggled)
        apply_icon(self.btn_axes, "view_axes")
        tb.addWidget(self.btn_axes)
        self._toolbar_widgets.append(self.btn_axes)
        self.btn_grid = QToolButton()
        self.btn_grid.setText("网格")
        self.btn_grid.setToolTip("显示 / 隐藏网格地面")
        self.btn_grid.setCheckable(True)
        self.btn_grid.setChecked(True)
        self.btn_grid.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_grid.toggled.connect(self._on_grid_toggled)
        apply_icon(self.btn_grid, "view_grid")
        tb.addWidget(self.btn_grid)
        self._toolbar_widgets.append(self.btn_grid)

        # 背景切换（theme.png：图标固定，仅文本随状态切换）
        self.btn_bg = QToolButton()
        self.btn_bg.setText(icon_text("theme", "🌓 浅色"))
        self.btn_bg.setToolTip("切换深色 / 浅色背景")
        self.btn_bg.setCheckable(True)
        self.btn_bg.toggled.connect(self._on_bg_toggled)
        apply_icon(self.btn_bg, "theme")
        tb.addWidget(self.btn_bg)
        self._toolbar_widgets.append(self.btn_bg)

        tb.addStretch(1)

        # 最大化（隐藏相机卡片区，查看器占满中央区域）
        self.btn_maximize = QToolButton()
        self.btn_maximize.setText(icon_text("maximize", "⛶ 最大化"))
        self.btn_maximize.setToolTip("最大化查看器（隐藏相机卡片与左右面板）")
        self.btn_maximize.setCheckable(True)
        self.btn_maximize.toggled.connect(self._on_maximize_toggled)
        apply_icon(self.btn_maximize, "maximize")
        tb.addWidget(self.btn_maximize)

        return bar

    def _setup_viewer(self):
        try:
            self._viewer = PointCloudViewer(parent=self.viewer_container)
            vlo = QVBoxLayout(self.viewer_container)
            vlo.setContentsMargins(0, 0, 0, 0)
            vlo.addWidget(self._viewer)
            self._update_overlay()
            logger.info("PointCloudViewer (QOpenGLWidget) 初始化成功")
        except Exception as e:
            logger.error(f"PointCloudViewer 初始化失败: {e}")
            self.status_changed.emit(f"渲染器初始化失败: {e}")
            self._viewer = None

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def set_reference(self, camera_id: Optional[str]):
        """设置参考相机（显示为白色）。"""
        self._reference_id = camera_id
        self._refresh_current()

    def set_pointcloud(self, camera_id: str, pcd):
        """设置某台相机的点云（None 表示清除）。"""
        try:
            if pcd is None:
                self._pcds.pop(camera_id, None)
                if camera_id in self._camera_order:
                    self._camera_order.remove(camera_id)
                self._remove_mode_entry(camera_id)
            else:
                if camera_id not in self._camera_order:
                    self._camera_order.append(camera_id)
                self._pcds[camera_id] = pcd
                self._add_mode_entry(camera_id)
            self._refresh_current()
        except Exception as e:
            logger.error(f"set_pointcloud({camera_id}) 异常: {e}")

    def set_pointcloud_merged(self, pcd):
        """设置拼接合并点云并切换到合并显示。"""
        self._pcd_merged = pcd
        has_points = pcd is not None and len(pcd.points) > 0
        if has_points:
            idx = self.combo_mode.findData(self.MODE_MERGED)
            if idx >= 0:
                self.combo_mode.setCurrentIndex(idx)
            self.status_changed.emit(f"拼接点云已加载: {len(pcd.points)} 点")
        self._refresh_current()

    def show_camera(self, camera_id: str):
        """切换到指定 camera_id 的单相机显示模式。"""
        idx = self.combo_mode.findData(camera_id)
        if idx >= 0:
            self.combo_mode.setCurrentIndex(idx)

    def set_highlight(self, camera_id: str, indices: Optional[list] = None):
        """高亮某台相机点云中的指定索引。"""
        self._highlights[camera_id] = indices or []
        self._refresh_current()

    def clear_highlight(self):
        self._highlights = {}
        if self._viewer:
            self._viewer.set_highlight_indices(None)

    def remove_camera(self, camera_id: str):
        """相机移除时同步清除其点云。"""
        self.set_pointcloud(camera_id, None)
        if self._viewer:
            self._viewer.set_pointcloud(camera_id, None)

    def clear_all(self):
        self._pcds = {}
        self._pcd_merged = None
        self._camera_order = []
        self._highlights = {}
        self._last_points = None
        self._last_base_colors = None
        while self.combo_mode.count() > 2:
            self.combo_mode.removeItem(2)
        self.combo_mode.setCurrentIndex(0)
        if self._viewer:
            self._viewer.clear()
            self._viewer.clear_pointclouds()
        self._update_overlay("未加载点云")

    def reset_view(self):
        if self._viewer:
            self._viewer.reset_view()

    def set_view_preset(self, preset: str):
        """视角预设：top / front / side / iso。"""
        if self._viewer:
            self._viewer.set_view_preset(preset)

    def set_point_size(self, size: int):
        """设置点大小（1~5 px），同步工具栏。"""
        self.spin_point_size.setValue(int(size))

    def set_maximized(self, on: bool):
        """外部同步最大化状态（不改变工具栏勾选状态时静默更新）。"""
        if self.btn_maximize.isChecked() != bool(on):
            self.btn_maximize.setChecked(bool(on))

    def is_collapsed(self) -> bool:
        """返回 3D 查看区域当前是否处于折叠状态（仅工具栏可见）。"""
        return not self.viewer_container.isVisible()

    def set_collapsed(self, collapsed: bool):
        """外部设置折叠状态（会触发 collapse_toggled 信号）。"""
        self.btn_collapse.setChecked(not collapsed)

    def viewer(self) -> Optional[PointCloudViewer]:
        """返回底层 OpenGL 渲染器（高级调试使用）。"""
        return self._viewer

    def set_toolbar_minimal(self, minimal: bool = True):
        """切换极简工具栏：仅保留最大化按钮。"""
        self._minimal_toolbar = bool(minimal)
        for w in self._toolbar_widgets:
            w.setVisible(not self._minimal_toolbar)

    def set_show_axes(self, on: bool):
        """显示/隐藏 3D 坐标轴。"""
        if self._viewer:
            self._viewer.set_show_axes(on)
        if not self._minimal_toolbar:
            self.btn_axes.setChecked(bool(on))

    def set_show_grid(self, on: bool):
        """显示/隐藏网格地面。"""
        if self._viewer:
            self._viewer.set_show_grid(on)
        if not self._minimal_toolbar:
            self.btn_grid.setChecked(bool(on))

    def set_background(self, dark: bool):
        """切换深色/浅色背景。"""
        if self._viewer:
            self._viewer.set_background(dark)
        if not self._minimal_toolbar:
            self.btn_bg.setChecked(not dark)

    def set_pivot_visible(self, visible: bool):
        """显示/隐藏旋转中心。"""
        if self._viewer:
            self._viewer.set_pivot_visible(visible)

    def set_pivot_position(self, pos):
        """设置旋转中心位置。"""
        if self._viewer:
            self._viewer.set_pivot_position(pos)

    def set_selection_bbox(self, bounds_list: List[tuple]):
        """设置选中点云的包围盒线框（bounds_list: [(min,max), ...]）。"""
        if self._viewer:
            self._viewer.set_selection_bbox(bounds_list)

    def set_roi_mode(self, enabled: bool):
        """进入/退出 ROI 框选模式。"""
        if self._viewer:
            self._viewer.set_roi_mode(enabled)

    def clear_roi_selection(self):
        """清除 ROI 选中高亮。"""
        if self._viewer:
            self._viewer.clear_roi_selection()

    def get_roi_selection(self) -> Dict[str, np.ndarray]:
        """返回当前 ROI 选中的各 cloud_id 索引数组。"""
        if self._viewer:
            return self._viewer.get_roi_selection()
        return {}

    # ------------------------------------------------------------------
    # 工具栏槽函数
    # ------------------------------------------------------------------
    def _on_collapse_toggled(self, checked: bool):
        self.viewer_container.setVisible(checked)
        self.btn_collapse.setText("▾ 3D" if checked else "▸ 3D")
        self.collapse_toggled.emit(checked)

    def _on_color_mode_changed(self, _idx):
        self._apply_color_mode()

    def _on_point_size_changed(self, value: int):
        if self._viewer:
            self._viewer.set_point_size(value)

    def _on_axes_toggled(self, checked: bool):
        if self._viewer:
            self._viewer.set_show_axes(checked)

    def _on_grid_toggled(self, checked: bool):
        if self._viewer:
            self._viewer.set_show_grid(checked)

    def _on_bg_toggled(self, checked: bool):
        # theme.png 固定；文本随状态切换（无图标文件时保留 emoji 兜底）
        self.btn_bg.setText(icon_text("theme", "🌓 深色" if checked else "🌓 浅色"))
        if self._viewer:
            self._viewer.set_background(dark=not checked)

    def _on_maximize_toggled(self, checked: bool):
        self._maximized = checked
        # 文本与图标同步切换：最大化 maximize.png ↔ 恢复 restore.png
        name = "restore" if checked else "maximize"
        self.btn_maximize.setText(icon_text(name, "⛶ 恢复" if checked else "⛶ 最大化"))
        if has_icon(name):
            self.btn_maximize.setIcon(get_icon(name))
        self.maximize_toggled.emit(checked)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _color_for(self, camera_id: str) -> tuple:
        """参考相机白色，其余按添加顺序循环调色板。"""
        if camera_id == self._reference_id:
            return COLOR_REFERENCE
        idx = self._camera_order.index(camera_id) if camera_id in self._camera_order else 0
        return COLOR_PALETTE[idx % len(COLOR_PALETTE)]

    def _add_mode_entry(self, camera_id: str):
        if self.combo_mode.findData(camera_id) < 0:
            self.combo_mode.addItem(f"相机 {camera_id}", camera_id)

    def _remove_mode_entry(self, camera_id: str):
        idx = self.combo_mode.findData(camera_id)
        if idx >= 0:
            self.combo_mode.removeItem(idx)

    def _on_mode_changed(self, _idx):
        self._current_mode = self.combo_mode.currentData()
        self._refresh_current()

    def _refresh_current(self):
        """按当前显示模式刷新渲染。"""
        mode = self.combo_mode.currentData()
        if mode == self.MODE_MERGED:
            self._show_merged()
        elif mode == self.MODE_OVERLAY:
            self._show_overlay()
        else:
            self._show_single(mode)

    @staticmethod
    def _downsample_pcd(pcd, target_count: int):
        """将 open3d 点云降采样到约 target_count 点，优先体素采样保留结构，
        失败或仍超阈值时回退到均匀采样。保留颜色/法线。

        关键点：
          1. 大数据量时先走 uniform_down_sample 粗降，避免全量复制 2600 万点；
          2. 再剔除 NaN/Inf 点得到"干净"点云做体素精修；
          3. 体素尺寸上限锁定到 MAX_RENDER_VOXEL_MM，防止大场景 AABB 过大时
             把有效点过度塌缩成稀疏点云。
        """
        n = len(pcd.points)
        if n <= target_count:
            return pcd
        try:
            pts = np.asarray(pcd.points)
            valid_mask = np.isfinite(pts).all(axis=1)
            n_valid = int(valid_mask.sum())
            if n_valid == 0:
                raise ValueError("无有效点，无法体素降采样")

            # 1. 快速粗降：有效点远超目标时，先在原始点云上均匀采样到约 2x 目标，
            #    避免后续把几千万点全量复制进 clean 点云。
            if n_valid > target_count * 4:
                k = max(1, int(np.ceil(n / (target_count * 2))))
                pcd = pcd.uniform_down_sample(every_k_points=k)
                n = len(pcd.points)
                pts = np.asarray(pcd.points)
                valid_mask = np.isfinite(pts).all(axis=1)
                n_valid = int(valid_mask.sum())
                if n_valid == 0:
                    raise ValueError("粗降后无有效点")

            # 2. 在已粗降的数据上剔除无效点并保留颜色/法线
            colors = np.asarray(pcd.colors) if pcd.has_colors() else None
            normals = np.asarray(pcd.normals) if pcd.has_normals() else None
            clean = o3d.geometry.PointCloud()
            clean.points = o3d.utility.Vector3dVector(pts[valid_mask])
            if colors is not None and len(colors) == n:
                clean.colors = o3d.utility.Vector3dVector(colors[valid_mask])
            if normals is not None and len(normals) == n:
                clean.normals = o3d.utility.Vector3dVector(normals[valid_mask])

            # 3. 在干净点云上估计体素尺寸，并加硬上限
            valid_pts = pts[valid_mask]
            min_b = valid_pts.min(axis=0)
            max_b = valid_pts.max(axis=0)
            extent = max_b - min_b
            if not np.isfinite(extent).all() or (extent <= 0).any():
                raise ValueError("AABB 异常，回退均匀采样")
            volume = max(float(extent.prod()), 1e-12)
            voxel_size = max((volume / target_count) ** (1.0 / 3.0), 1e-6)
            max_voxel = float(EmbeddedPointCloudViewer.MAX_RENDER_VOXEL_MM)
            # 体素尺寸上限：硬上限 + 不超过最小边长的 1/10
            voxel_size = min(voxel_size, max_voxel, float(extent.min()) / 10.0)
            voxel_size = max(voxel_size, 1e-6)

            logger.info(
                f"3D 查看器降采样: 输入 {n} 点(有效 {n_valid}), "
                f"AABB [{extent[0]:.1f}, {extent[1]:.1f}, {extent[2]:.1f}] mm, "
                f"体素 {voxel_size:.3f} mm, 目标 {target_count} 点")

            # 4. 体素降采样精修
            ds = clean.voxel_down_sample(voxel_size=voxel_size)
            # 若体素采样后仍超阈值，再均匀采样兜底
            if len(ds.points) > target_count:
                k = max(1, int(np.ceil(len(ds.points) / target_count)))
                ds = ds.uniform_down_sample(every_k_points=k)
            logger.info(f"3D 查看器降采样结果: {len(ds.points)} 点")
            return ds if len(ds.points) > 0 else clean
        except Exception:
            # 任何异常都回退到均匀采样（在原始云上）
            logger.warning("3D 查看器体素降采样失败，回退均匀采样", exc_info=True)
            k = max(1, int(np.ceil(n / target_count)))
            return pcd.uniform_down_sample(every_k_points=k)

    @classmethod
    def _pcd_to_arrays(cls, pcd, default_color: tuple, max_points: Optional[int] = None):
        """open3d 点云 → (points float32, colors float32)。

        若指定 max_points 且点数超过阈值，先对渲染副本降采样，原始点云对象不变。
        """
        if max_points is not None and len(pcd.points) > max_points:
            pcd = cls._downsample_pcd(pcd, max_points)
        points = np.asarray(pcd.points, dtype=np.float32)
        if pcd.has_colors():
            colors = np.asarray(pcd.colors, dtype=np.float32)
            if colors.size and colors.max() > 1.0:
                colors = colors / 255.0
        else:
            colors = np.tile(np.array(default_color, dtype=np.float32), (len(points), 1))
        return points, colors

    def _colors_for_mode(self, points: np.ndarray,
                         base_colors: np.ndarray) -> np.ndarray:
        """按当前着色模式计算顶点色（numpy 向量化）。"""
        mode = self.combo_color.currentData()
        if mode == self.COLOR_HEIGHT:
            z = points[:, 2].astype(np.float64)
            z = np.nan_to_num(z, nan=0.0, posinf=0.0, neginf=0.0)
            z_min, z_max = float(z.min()), float(z.max())
            span = max(z_max - z_min, 1e-9)
            return _jet_colormap((z - z_min) / span)
        if mode == self.COLOR_GRAY:
            return np.tile(np.array([0.5, 0.5, 0.5], dtype=np.float32),
                           (len(points), 1))
        return base_colors          # 按站位（默认调色板）

    def _apply_color_mode(self):
        """着色模式切换：基于缓存数据重算颜色并重新加载（不重建读取点云）。"""
        if self._last_points is None:
            return
        colors = self._colors_for_mode(self._last_points, self._last_base_colors)
        self._load_to_viewer(self._last_points, colors, self._last_name,
                             highlight=self._last_highlight, cache=False)

    def _update_overlay(self, text: Optional[str] = None):
        """更新 GL 叠加层信息。"""
        if self._viewer is None:
            return
        if text is None:
            text = self._compose_overlay()
        self._viewer.set_overlay_text(text)

    def _compose_overlay(self, name: str = "", valid: int = 0) -> str:
        """叠加层文字：当前模式 | 总点数 | 各站位点数（叠加模式时）。"""
        if not name:
            return "未加载点云"
        line1 = f"{name} | {valid:,} 点"
        mode = self.combo_mode.currentData()
        if mode == self.MODE_OVERLAY and len(self._camera_order) > 1:
            parts = []
            for cid in self._camera_order:
                pcd = self._pcds.get(cid)
                if pcd is not None and len(pcd.points) > 0:
                    parts.append(f"{cid}: {len(pcd.points):,}")
            if parts:
                line1 += "\n" + " | ".join(parts[:6])
        return line1

    def _load_to_viewer(self, points, colors, name: str, highlight=None,
                        cache: bool = True):
        if self._viewer is None:
            self.status_changed.emit(f"[{name}] 渲染器不可用")
            return
        try:
            if cache:
                self._last_points = points
                self._last_base_colors = colors
                self._last_name = name
                self._last_highlight = highlight
            result = self._viewer.load_points(points, colors, highlight_indices=highlight)
            valid = result["valid"]
            detail = f"{name} | 点数: {valid:,}"
            if result["invalid"] > 0:
                detail += f" (过滤 {result['invalid']} 个无效点)"
            self.status_changed.emit(detail)
            self._update_overlay(self._compose_overlay(name, valid))
        except Exception as e:
            logger.error(f"加载点云失败: {e}")
            self.status_changed.emit(f"{name} | 渲染失败: {e}")
            self._update_overlay("渲染失败")

    def _show_single(self, camera_id: str):
        if self._viewer:
            self._viewer.clear_pointclouds()
        pcd = self._pcds.get(camera_id)
        if pcd is None or len(pcd.points) == 0:
            self._update_overlay(f"相机 {camera_id} 无点云")
            if self._viewer:
                self._viewer.clear()
            return
        points, colors = self._pcd_to_arrays(
            pcd, self._color_for(camera_id), max_points=self.MAX_RENDER_POINTS)
        self._load_to_viewer(points, colors, f"{camera_id} 相机点云",
                             highlight=self._highlights.get(camera_id))

    def _show_merged(self):
        if self._viewer:
            self._viewer.clear_pointclouds()
        pcd = self._pcd_merged
        if pcd is None or len(pcd.points) == 0:
            self._update_overlay("无拼接点云")
            if self._viewer:
                self._viewer.clear()
            return
        points, colors = self._pcd_to_arrays(
            pcd, COLOR_MERGED, max_points=self.MAX_RENDER_POINTS)
        self._load_to_viewer(points, colors, "拼接点云")

    def _show_overlay(self):
        """全部相机按各自颜色叠加显示（多 VBO 缓存）。"""
        if self._viewer is None:
            return
        # 切换到多路模式前清空遗留单路数据，避免重复绘制
        self._viewer.clear()
        # 移除已不存在的相机 VBO
        for cid in list(self._viewer._clouds.keys()):
            if cid not in self._pcds:
                self._viewer.set_pointcloud(cid, None)

        total_valid = 0
        for cid in self._camera_order:
            pcd = self._pcds.get(cid)
            if pcd is None or len(pcd.points) == 0:
                continue
            points, colors = self._pcd_to_arrays(
                pcd, self._color_for(cid), max_points=self.MAX_RENDER_POINTS)
            self._viewer.set_pointcloud(
                cid, points, colors, visible=True,
                highlight_indices=self._highlights.get(cid))
            invalid = int((np.isnan(points).any(axis=1) | np.isinf(points).any(axis=1)).sum())
            total_valid += len(points) - invalid

        if not self._viewer._clouds:
            self._update_overlay("未加载点云")
            return

        name = f"全部叠加 ({len(self._viewer._clouds)} 台相机)"
        self.status_changed.emit(f"{name} | 点数: {total_valid:,}")
        self._update_overlay(self._compose_overlay(name, total_valid))

    def closeEvent(self, event):
        event.accept()
