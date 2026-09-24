# -*- coding: utf-8 -*-
"""
CloudCompare 式高性能 3D 点云查看器（PointCloudViewerLOD）。

基于 viewer_3d.py 的 QOpenGLWidget + PyOpenGL 架构，集成 cc_octree_lod 的 LOD 系统：
  - 每朵点云构建 LOD 八叉树，渲染时动态查询；
  - 保留 ArcBall 相机、ROI 框选、包围盒线框等全部交互；
  - 新增 Colorbar 色条（标量场可视化）。

PyOpenGL import 延迟到 initializeGL 内。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMatrix4x4, QVector3D, QPainter, QPen, QColor, QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from core.utils import logger
from ui_v2.theme import ACCENT, ACCENT_DIM, BG_CARD, BORDER, TEXT_PRIMARY

# 尝试导入 LOD（失败不影响基本渲染）
try:
    from ..core.cc_octree_lod import PointCloudOctree, MultiCloudLODManager
    _HAS_LOD = True
except Exception:
    _HAS_LOD = False


# 背景色
BG_DARK = (0.10, 0.10, 0.13, 1.0)
BG_LIGHT = (0.90, 0.90, 0.92, 1.0)


def _app_font(widget: QWidget, point_size: int) -> QFont:
    """自绘 overlay 文字取控件自身字体（GLOBAL_QSS 作用后的字族），只调字号。

    §10.10① 裁定：取 `self.font()`，不用 `QApplication.font()`（实测 YaHei UI，
    不吃 QSS）；QFont 为值语义，拿到即副本，直接 setPointSize 即可。
    """
    font = widget.font()
    font.setPointSize(point_size)
    return font


def _jet_color(t: float) -> list:
    """单值 jet 色。"""
    t = max(0.0, min(1.0, t))
    r = np.interp(t, [0.0, 0.35, 0.66, 0.89, 1.0], [0.0, 0.0, 1.0, 1.0, 0.5])
    g = np.interp(t, [0.0, 0.125, 0.375, 0.64, 0.89, 1.0], [0.0, 0.0, 1.0, 1.0, 0.0, 0.0])
    b = np.interp(t, [0.0, 0.11, 0.34, 0.65, 1.0], [0.5, 1.0, 1.0, 0.0, 0.0])
    return [r, g, b]


class ScaleBarWidget(QWidget):
    """右下角比例尺叠加控件（子控件叠加方案）。

    不用 paintGL 内的 QPainter：Core Profile 下 Qt GL 绘制引擎的
    纹理 shader 无法编译，会产生 warning 甚至绘制失败。
    """

    BAR_PX = 100  # 比例尺像素长度

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.BAR_PX + 40, 34)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet("background: transparent;")
        self._extent = 0.0

    def set_extent(self, extent: float):
        self._extent = extent
        self.update()

    def paintEvent(self, event):
        if self._extent <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        world_len = _nice_step(self._extent / 10.0)
        x_start, x_end = 20, 20 + self.BAR_PX
        y = self.height() - 12
        painter.setPen(QPen(QColor(200, 200, 200), 2))
        painter.drawLine(x_start, y, x_end, y)
        painter.drawLine(x_start, y - 5, x_start, y + 5)
        painter.drawLine(x_end, y - 5, x_end, y + 5)
        painter.setFont(_app_font(self, 9))
        text = f"{world_len:.0f} mm" if world_len >= 1 else f"{world_len*1000:.0f} μm"
        text_width = painter.fontMetrics().horizontalAdvance(text)
        painter.drawText(x_start + (self.BAR_PX - text_width) // 2, y - 8, text)
        painter.end()


class ColorBarWidget(QWidget):
    """右侧 Colorbar 色条叠加控件（标量场可视化，同 ScaleBarWidget 理由）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(90, 230)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet("background: transparent;")
        self._min_val = 0.0
        self._max_val = 1.0
        self._label = ""
        self._bar_x = 8
        self._bar_y = 20
        self._bar_w = 20
        self._bar_h = 180

    def set_range(self, min_val: float, max_val: float, label: str = ""):
        self._min_val = min_val
        self._max_val = max_val
        self._label = label
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        x, y, w, h = self._bar_x, self._bar_y, self._bar_w, self._bar_h

        # 渐变色条（jet）
        for i in range(h):
            t = 1.0 - i / h
            c = _jet_color(t)
            painter.setPen(QPen(QColor(int(c[0]*255), int(c[1]*255), int(c[2]*255)), 1))
            painter.drawLine(x, y + i, x + w, y + i)

        painter.setPen(QPen(QColor(200, 200, 200), 1))
        painter.drawRect(x, y, w, h)

        painter.setFont(_app_font(self, 8))
        painter.setPen(QPen(QColor(200, 200, 200), 1))
        painter.drawText(x + w + 5, y + 10, f"{self._max_val:.2f}")
        painter.drawText(x + w + 5, y + h, f"{self._min_val:.2f}")
        if self._label:
            painter.drawText(x - 20, y - 8, w + 60, 15, Qt.AlignCenter, self._label)
        painter.end()


def _nice_step(raw: float) -> float:
    if raw <= 0 or not np.isfinite(raw):
        return 1.0
    exp = np.floor(np.log10(raw))
    base = raw / (10 ** exp)
    for m in (1.0, 2.0, 5.0, 10.0):
        if base <= m:
            return m * (10 ** exp)
    return 10.0 * (10 ** exp)


# =========================================================================
# PointCloudViewerLOD
# =========================================================================
class PointCloudViewerLOD(QOpenGLWidget):
    """集成 LOD 的高性能点云查看器。"""

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
        self._initialized = False
        self._has_gl = False

        # 多路点云数据
        self._clouds: Dict[str, dict] = {}
        self._lod_manager: Optional[Any] = None
        if _HAS_LOD:
            self._lod_manager = MultiCloudLODManager(budget_per_cloud=500_000)

        # 渲染选项
        self._point_size = 1.5
        self._bg_color = BG_DARK
        self._show_axes = False
        self._show_grid = True
        self._show_colorbar = False
        self._colorbar_min = 0.0
        self._colorbar_max = 1.0
        self._colorbar_label = ""

        # MVP 缓存
        self._mvp_matrix: Optional[np.ndarray] = None
        self._mvp_inv: Optional[np.ndarray] = None

        # 选中包围盒
        self._bbox_pos: Optional[np.ndarray] = None
        self._bbox_col: Optional[np.ndarray] = None
        self._bbox_vert_count = 0

        # 旋转中心
        self._pivot_visible = False
        self._pivot_pos: Optional[np.ndarray] = None

        # ROI 框选
        self._roi_mode = False
        self._roi_start = None
        self._roi_rect = None
        self._roi_rubberband = None
        self._roi_selected_indices: Dict[str, np.ndarray] = {}

        # 叠加层
        self._overlay_label = QLabel(self)
        self._overlay_label.setStyleSheet(
            f"QLabel {{ background-color: {BG_CARD}; color: {TEXT_PRIMARY}; "
            f"border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 10px; "
            f"font-size: 9pt; }}"
        )
        self._overlay_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._overlay_label.move(10, 10)
        self._overlay_label.hide()

        # 比例尺 / Colorbar：子控件叠加，避免 paintGL 内 QPainter 的 shader 警告
        self._scale_bar = ScaleBarWidget(self)
        self._scale_bar.show()
        self._colorbar_widget = ColorBarWidget(self)
        self._colorbar_widget.hide()

        self.setMinimumSize(400, 260)

    # ------------------------------------------------------------------
    # 点云管理
    # ------------------------------------------------------------------
    def set_pointcloud(self, cloud_id: str, points: np.ndarray = None,
                       colors: np.ndarray = None, visible: bool = True,
                       point_size: Optional[float] = None):
        """添加/更新/删除一路点云。"""
        if points is None:
            self._remove_cloud(cloud_id)
            return

        points = np.asarray(points, dtype=np.float32)
        assert points.ndim == 2 and points.shape[1] == 3
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
            "point_size": point_size,
            "vao": None, "vbo_pos": None, "vbo_col": None, "vbo_size": None,
            "point_count": 0,  # 实际上传到 GPU 的点数
            "uploaded": False,
        }

        # 构建 LOD
        if self._lod_manager is not None:
            self._lod_manager.add_cloud(cloud_id, points, colors)

        self._bounds_dirty = True
        self.update()

    def clear_pointclouds(self):
        for cid in list(self._clouds.keys()):
            self._remove_cloud(cid)
        if self._lod_manager is not None:
            self._lod_manager.clear()
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
        if self._lod_manager is not None:
            self._lod_manager.remove_cloud(cloud_id)

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

            # 线框 VAO
            self._line_vao = GL.glGenVertexArrays(1)
            self._line_vbo_pos, self._line_vbo_col = GL.glGenBuffers(2)

            self._bbox_vao = GL.glGenVertexArrays(1)
            self._bbox_vbo_pos, self._bbox_vbo_col = GL.glGenBuffers(2)

            self._pivot_vao = GL.glGenVertexArrays(1)
            self._pivot_vbo_pos, self._pivot_vbo_col = GL.glGenBuffers(2)
        except Exception as e:
            logger.error(f"OpenGL 初始化失败: {e}")
            self._has_gl = False

    def _compile_shader(self, vert_src, frag_src):
        from OpenGL import GL
        vs = GL.glCreateShader(GL.GL_VERTEX_SHADER)
        GL.glShaderSource(vs, vert_src)
        GL.glCompileShader(vs)
        fs = GL.glCreateShader(GL.GL_FRAGMENT_SHADER)
        GL.glShaderSource(fs, frag_src)
        GL.glCompileShader(fs)
        prog = GL.glCreateProgram()
        GL.glAttachShader(prog, vs)
        GL.glAttachShader(prog, fs)
        GL.glLinkProgram(prog)
        GL.glDeleteShader(vs)
        GL.glDeleteShader(fs)
        return prog

    # ------------------------------------------------------------------
    # 场景更新
    # ------------------------------------------------------------------
    def _update_scene_bounds(self):
        visible_points = []
        for cloud in self._clouds.values():
            if not cloud.get("visible", True):
                continue
            pts = cloud["points"]
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
        self._bounds_dirty = False
        self._scale_bar.set_extent(self._extent)

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def paintGL(self):
        if not self._has_gl:
            return
        from OpenGL import GL
        while GL.glGetError() != GL.GL_NO_ERROR:
            pass
        GL.glClearColor(*self._bg_color)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)

        if not self._clouds:
            return

        if getattr(self, '_bounds_dirty', True):
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

        self._mvp_matrix = np.array(mvp.data(), dtype=np.float64).reshape(4, 4, order='F')
        try:
            self._mvp_inv = np.linalg.inv(self._mvp_matrix)
        except np.linalg.LinAlgError:
            self._mvp_inv = None

        GL.glUseProgram(self._shader)
        GL.glUniformMatrix4fv(self._loc_u_mvp, 1, GL.GL_FALSE, mvp.data())

        # 渲染各点云（使用 LOD 或全量）
        camera_pos = self.camera.position()
        total_rendered = 0

        for cid, cloud in self._clouds.items():
            if not cloud.get("visible", True):
                continue

            # 使用 LOD 查询
            if self._lod_manager is not None and cid in getattr(self._lod_manager, '_octrees', {}):
                pts, cols = self._lod_manager._octrees[cid].query(camera_pos, 500_000)
            else:
                pts = cloud["points"]
                cols = cloud["colors"]

            if len(pts) == 0:
                continue
            if cols is None or len(cols) != len(pts):
                cols = np.tile(np.array([[0.5, 0.5, 0.5]], dtype=np.float32), (len(pts), 1))

            # LOD 结果未变化时跳过重复 VBO 上传（相机不动则每帧返回同一数组）
            cdata = self._clouds[cid]
            if cdata.get("_lod_cache_pts") is not pts:
                self._upload_cloud_direct(cid, pts, cols, cloud.get("point_size"))
                cdata["_lod_cache_pts"] = pts
            if cdata.get("point_count", 0) > 0:
                GL.glBindVertexArray(cdata["vao"])
                GL.glDrawArrays(GL.GL_POINTS, 0, cdata["point_count"])
                GL.glBindVertexArray(0)
                total_rendered += cdata["point_count"]

        # 参考线
        if self._show_axes or self._show_grid:
            if getattr(self, '_line_pos', None) is None:
                self._build_reference_lines()
                self._upload_reference_lines()
            GL.glBindVertexArray(self._line_vao)
            GL.glVertexAttrib1f(self._loc_a_size, 1.0)
            axes_count = getattr(self, '_axes_vert_count', 0)
            grid_count = getattr(self, '_grid_vert_count', 0)
            if self._show_axes and axes_count:
                GL.glDrawArrays(GL.GL_LINES, 0, axes_count)
            if self._show_grid and grid_count:
                GL.glDrawArrays(GL.GL_LINES, axes_count, grid_count)
            GL.glBindVertexArray(0)

        # 包围盒
        if self._bbox_pos is not None and self._bbox_vert_count > 0:
            self._upload_bbox_lines()
            GL.glBindVertexArray(self._bbox_vao)
            GL.glVertexAttrib1f(self._loc_a_size, 1.0)
            GL.glDrawArrays(GL.GL_LINES, 0, self._bbox_vert_count)
            GL.glBindVertexArray(0)

        # 旋转中心
        if self._pivot_visible and self._pivot_pos is not None:
            self._upload_pivot()
            GL.glBindVertexArray(self._pivot_vao)
            GL.glVertexAttrib1f(self._loc_a_size, max(self._point_size * 3.0, 8.0))
            GL.glDrawArrays(GL.GL_POINTS, 0, 1)
            GL.glBindVertexArray(0)

        GL.glUseProgram(0)

        self._update_overlay_text(total_rendered)

    def _upload_cloud_direct(self, cloud_id: str, points: np.ndarray,
                             colors: np.ndarray, point_size: Optional[float]):
        """直接上传点云数据到 GPU（用于 LOD 动态更新）。"""
        if not self._has_gl:
            return
        from OpenGL import GL

        cloud = self._clouds[cloud_id]
        if cloud.get("vao") is None:
            cloud["vao"] = GL.glGenVertexArrays(1)
            cloud["vbo_pos"], cloud["vbo_col"], cloud["vbo_size"] = GL.glGenBuffers(3)

        n = len(points)
        sizes = np.full(n, float(point_size) if point_size else self._point_size, dtype=np.float32)

        GL.glBindVertexArray(cloud["vao"])
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, cloud["vbo_pos"])
        GL.glBufferData(GL.GL_ARRAY_BUFFER, points.nbytes, points, GL.GL_DYNAMIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_position, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_position)

        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, cloud["vbo_col"])
        GL.glBufferData(GL.GL_ARRAY_BUFFER, colors.nbytes, colors, GL.GL_DYNAMIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_color, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_color)

        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, cloud["vbo_size"])
        GL.glBufferData(GL.GL_ARRAY_BUFFER, sizes.nbytes, sizes, GL.GL_DYNAMIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_size, 1, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_size)
        GL.glBindVertexArray(0)

        cloud["point_count"] = n
        cloud["uploaded"] = True

    # ------------------------------------------------------------------
    # 参考线/包围盒/旋转中心
    # ------------------------------------------------------------------
    def _build_reference_lines(self):
        c = self.centroid.astype(np.float64)
        origin = c + np.array([0, 0, self._extent * 0.2])
        axis_len = self._extent * 0.4
        arrow_len = axis_len * 0.15

        axes_lines = [
            (origin, origin + [axis_len, 0, 0]),
            (origin + [axis_len, 0, 0], origin + [axis_len - arrow_len, arrow_len * 0.5, 0]),
            (origin + [axis_len, 0, 0], origin + [axis_len - arrow_len, -arrow_len * 0.5, 0]),
            (origin, origin + [0, axis_len, 0]),
            (origin + [0, axis_len, 0], origin + [arrow_len * 0.5, axis_len - arrow_len, 0]),
            (origin + [0, axis_len, 0], origin + [-arrow_len * 0.5, axis_len - arrow_len, 0]),
            (origin, origin + [0, 0, axis_len]),
            (origin + [0, 0, axis_len], origin + [0, arrow_len * 0.5, axis_len - arrow_len]),
            (origin + [0, 0, axis_len], origin + [0, -arrow_len * 0.5, axis_len - arrow_len]),
        ]
        axes_pos = np.array(axes_lines, dtype=np.float32).reshape(-1, 3)
        axes_col = np.array([
            [1.0, 0.15, 0.15], [1.0, 0.15, 0.15],
            [1.0, 0.15, 0.15], [1.0, 0.15, 0.15],
            [1.0, 0.15, 0.15], [1.0, 0.15, 0.15],
            [0.15, 1.0, 0.15], [0.15, 1.0, 0.15],
            [0.15, 1.0, 0.15], [0.15, 1.0, 0.15],
            [0.15, 1.0, 0.15], [0.15, 1.0, 0.15],
            [0.25, 0.60, 1.0], [0.25, 0.60, 1.0],
            [0.25, 0.60, 1.0], [0.25, 0.60, 1.0],
            [0.25, 0.60, 1.0], [0.25, 0.60, 1.0],
        ], dtype=np.float32)

        step = _nice_step(self._extent / 10.0)
        half = step * 5.0
        gz = self._z_min
        offs = np.linspace(-half, half, 11)
        lines = []
        for v in offs:
            lines.append(([-half, v, gz], [half, v, gz]))
            lines.append(([v, -half, gz], [v, half, gz]))
        grid_pos = np.array(lines, dtype=np.float32).reshape(-1, 3)
        grid_col = np.tile(np.array([[0.45, 0.45, 0.45]], dtype=np.float32), (len(grid_pos), 1))

        self._line_pos = np.concatenate([axes_pos, grid_pos], axis=0)
        self._line_col = np.concatenate([axes_col, grid_col], axis=0)
        self._axes_vert_count = len(axes_pos)
        self._grid_vert_count = len(grid_pos)

    def _upload_reference_lines(self):
        if not self._has_gl or getattr(self, '_line_pos', None) is None:
            return
        from OpenGL import GL
        GL.glBindVertexArray(self._line_vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._line_vbo_pos)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, self._line_pos.nbytes, self._line_pos, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_position, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_position)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._line_vbo_col)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, self._line_col.nbytes, self._line_col, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_color, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_color)
        GL.glBindVertexArray(0)

    def set_selection_bbox(self, bounds_list: List[tuple]):
        if not bounds_list:
            self._bbox_pos = None
            self._bbox_vert_count = 0
            self.update()
            return
        lines = []
        for (bmin, bmax) in bounds_list:
            bmin = np.asarray(bmin, dtype=np.float32)
            bmax = np.asarray(bmax, dtype=np.float32)
            corners = np.array([
                [bmin[0], bmin[1], bmin[2]], [bmax[0], bmin[1], bmin[2]],
                [bmax[0], bmax[1], bmin[2]], [bmin[0], bmax[1], bmin[2]],
                [bmin[0], bmin[1], bmax[2]], [bmax[0], bmin[1], bmax[2]],
                [bmax[0], bmax[1], bmax[2]], [bmin[0], bmax[1], bmax[2]],
            ], dtype=np.float32)
            edges = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
            for i, j in edges:
                lines.append(corners[i])
                lines.append(corners[j])
        self._bbox_pos = np.array(lines, dtype=np.float32)
        self._bbox_col = np.tile(np.array([[1.0, 0.2, 0.2]], dtype=np.float32), (len(lines), 1))
        self._bbox_vert_count = len(lines)
        self.update()

    def _upload_bbox_lines(self):
        if not self._has_gl or self._bbox_pos is None:
            return
        from OpenGL import GL
        GL.glBindVertexArray(self._bbox_vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._bbox_vbo_pos)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, self._bbox_pos.nbytes, self._bbox_pos, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_position, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_position)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._bbox_vbo_col)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, self._bbox_col.nbytes, self._bbox_col, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_color, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_color)
        GL.glBindVertexArray(0)

    def set_pivot_visible(self, visible: bool):
        self._pivot_visible = bool(visible)
        self.update()

    def set_pivot_position(self, pos):
        self._pivot_pos = np.asarray(pos, dtype=np.float32).reshape(1, 3)
        self.update()

    def _upload_pivot(self):
        if not self._has_gl or self._pivot_pos is None:
            return
        from OpenGL import GL
        col = np.array([[1.0, 0.8, 0.2]], dtype=np.float32)
        GL.glBindVertexArray(self._pivot_vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._pivot_vbo_pos)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, self._pivot_pos.nbytes, self._pivot_pos, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_position, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_position)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._pivot_vbo_col)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, col.nbytes, col, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(self._loc_a_color, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glEnableVertexAttribArray(self._loc_a_color)
        GL.glBindVertexArray(0)

    # ------------------------------------------------------------------
    # 2D 叠加
    # ------------------------------------------------------------------
    def _update_overlay_text(self, total_rendered: int):
        n_clouds = len([c for c in self._clouds.values() if c.get("visible")])
        text = f"可见 {n_clouds} 朵 | 渲染 {total_rendered:,} 点"
        if self._overlay_label.text() == text:
            return  # 避免每帧重复 setText 触发重绘/布局
        self._overlay_label.setText(text)
        self._overlay_label.adjustSize()
        self._overlay_label.move(10, 10)
        self._overlay_label.show()

    # ------------------------------------------------------------------
    # 渲染选项
    # ------------------------------------------------------------------
    def set_point_size(self, size: float):
        self._point_size = float(max(1.0, min(5.0, size)))
        for cloud in self._clouds.values():
            cloud["uploaded"] = False
            cloud["_lod_cache_pts"] = None  # 强制下一帧重新上传
        self.update()

    def set_background(self, dark: bool):
        self._bg_color = BG_DARK if dark else BG_LIGHT
        self.update()

    def set_show_axes(self, on: bool):
        self._show_axes = bool(on)
        self.update()

    def set_show_grid(self, on: bool):
        self._show_grid = bool(on)
        self.update()

    def set_show_colorbar(self, on: bool, min_val: float = 0.0, max_val: float = 1.0, label: str = ""):
        self._show_colorbar = bool(on)
        self._colorbar_min = min_val
        self._colorbar_max = max_val
        self._colorbar_label = label
        self._colorbar_widget.set_range(min_val, max_val, label)
        self._colorbar_widget.setVisible(self._show_colorbar)
        self.update()

    def set_view_preset(self, preset: str):
        self.camera.set_preset(preset)
        self.update()

    def reset_view(self):
        self.camera.reset()
        self.update()

    def fit_to_cloud(self, cloud_id: str):
        """适配视角：相机对准指定点云（目标=质心，距离=包围 extent×1.5，口径同
        `_update_scene_bounds`）。点云不存在时保持现状。"""
        cloud = self._clouds.get(cloud_id)
        if not cloud:
            return
        pts = np.asarray(cloud["points"], dtype=np.float32)
        mask = np.isfinite(pts).all(axis=1)
        if not mask.any():
            return
        valid = pts[mask]
        centroid = valid.mean(axis=0)
        extent = max(float(np.linalg.norm(valid.max(axis=0) - valid.min(axis=0))), 1e-3)
        self.camera.target = centroid.astype(np.float32)
        self.camera.distance = max(extent * 1.5, 1.0)
        self.update()

    def resizeGL(self, w: int, h: int):
        if self._has_gl:
            from OpenGL import GL
            GL.glViewport(0, 0, w, h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 保持比例尺在右下角、Colorbar 在右侧
        self._scale_bar.move(self.width() - self._scale_bar.width() - 10,
                             self.height() - self._scale_bar.height() - 10)
        self._colorbar_widget.move(self.width() - self._colorbar_widget.width() - 10, 60)

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
        self.update()

    def mouseReleaseEvent(self, event):
        if self._roi_mode and event.button() == Qt.LeftButton and self._roi_start is not None:
            self._roi_rect = self._roi_rect_from_points(self._roi_start, event.pos())
            self._roi_start = None
            self._roi_rubberband.hide()
            self._compute_roi_selection()
            return
        self.camera.end_drag()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self.camera.zoom_in()
        else:
            self.camera.zoom_out()
        self.update()

    # ------------------------------------------------------------------
    # ROI
    # ------------------------------------------------------------------
    def set_roi_mode(self, enabled: bool):
        self._roi_mode = bool(enabled)
        if not self._roi_mode:
            self._roi_start = None
            self._roi_rect = None
            self._roi_selected_indices = {}
            if self._roi_rubberband is not None:
                self._roi_rubberband.hide()
        self.update()

    def clear_roi_selection(self):
        self._roi_rect = None
        self._roi_selected_indices = {}
        for cloud in self._clouds.values():
            if "orig_colors" in cloud and cloud["orig_colors"] is not None:
                cloud["colors"] = cloud["orig_colors"]
                cloud["orig_colors"] = None
                cloud["uploaded"] = False
        self.update()

    def get_roi_selection(self) -> Dict[str, np.ndarray]:
        return {k: v.copy() for k, v in self._roi_selected_indices.items()}

    def _ensure_rubberband(self):
        if self._roi_rubberband is None:
            from PySide6.QtWidgets import QRubberBand
            self._roi_rubberband = QRubberBand(QRubberBand.Rectangle, self)
            self._roi_rubberband.setStyleSheet(
                f"QRubberBand {{ border: 2px dashed {ACCENT}; "
                f"background-color: {ACCENT_DIM}; }}"
            )

    @staticmethod
    def _roi_rect_from_points(a, b):
        from PySide6.QtCore import QRect
        x1, y1 = a.x(), a.y()
        x2, y2 = b.x(), b.y()
        return QRect(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y1 - y2))

    def _compute_roi_selection(self):
        self._roi_selected_indices = {}
        if self._roi_rect is None or self._roi_rect.width() < 3 or self._roi_rect.height() < 3:
            return
        rect = self._roi_rect
        depth_buf = self._read_depth_rect(rect)
        if depth_buf is None:
            return
        h = self.height()
        for cloud_id, cloud in self._clouds.items():
            if not cloud.get("visible", True):
                continue
            pts = cloud["points"]
            if len(pts) == 0:
                continue
            screen = self.world_to_screen(pts)
            if screen is None:
                continue
            sx, sy, sz = screen[:, 0], screen[:, 1], screen[:, 2]
            in_rect = ((sx >= rect.left()) & (sx <= rect.right()) &
                       (sy >= rect.top()) & (sy <= rect.bottom()) &
                       (sz >= 0.0) & (sz <= 1.0))
            if not in_rect.any():
                continue
            ix = np.clip(np.round(sx[in_rect]).astype(np.int32), rect.left(), rect.right())
            iy = np.clip(np.round(h - 1 - sy[in_rect]).astype(np.int32),
                         h - 1 - rect.bottom(), h - 1 - rect.top())
            bufx = ix - rect.left()
            bufy = iy - (h - 1 - rect.bottom())
            buf_h, buf_w = depth_buf.shape
            bufx = np.clip(bufx, 0, buf_w - 1)
            bufy = np.clip(bufy, 0, buf_h - 1)
            sampled = depth_buf[bufy, bufx]
            tol = 0.005 + 0.01 * sampled
            visible = np.abs(sz[in_rect] - sampled) < tol
            idx_in_rect = np.nonzero(in_rect)[0]
            selected = idx_in_rect[visible]
            if len(selected) > 0:
                self._roi_selected_indices[cloud_id] = selected
        self._highlight_roi_selection()

    def _read_depth_rect(self, rect):
        try:
            from OpenGL import GL
            self.makeCurrent()
            # QOpenGLWidget 渲染在自身 FBO 中，paintGL 之外需先绑定
            prev_fbo = GL.glGetIntegerv(GL.GL_FRAMEBUFFER_BINDING)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
            x = max(0, rect.left())
            y = max(0, self.height() - rect.bottom() - 1)
            w = min(rect.width(), self.width() - x)
            h = min(rect.height(), self.height() - y)
            if w <= 0 or h <= 0:
                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, prev_fbo)
                return None
            buf = GL.glReadPixels(x, y, w, h, GL.GL_DEPTH_COMPONENT, GL.GL_FLOAT)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, prev_fbo)
            return np.asarray(buf, dtype=np.float32).reshape(h, w)
        except Exception:
            return None

    def _highlight_roi_selection(self):
        for cloud_id, indices in self._roi_selected_indices.items():
            cloud = self._clouds.get(cloud_id)
            if cloud is None:
                continue
            if cloud.get("orig_colors") is None:
                cloud["orig_colors"] = cloud["colors"].copy()
            colors = cloud["colors"].copy()
            colors[indices] = [1.0, 0.0, 0.0]
            cloud["colors"] = colors
            cloud["uploaded"] = False
        self.update()

    def _set_rotation_center(self, pos):
        if not self._has_gl:
            return
        depth = self._read_depth(pos.x(), pos.y())
        if depth is None or depth >= 0.99999:
            return
        world_pos = self.screen_to_world(pos.x(), pos.y(), depth)
        if world_pos is None:
            return
        self.camera.set_target(world_pos, keep_position=True)
        self.set_pivot_position(world_pos)
        self.set_pivot_visible(True)
        self.update()

    def _read_depth(self, x: int, y: int):
        """读取 (x,y) 处深度缓冲值，失败返回 None。

        QOpenGLWidget 渲染在自身 FBO 中，paintGL 之外绑定的是系统默认
        framebuffer，必须先绑定 defaultFramebufferObject() 才能读到真实深度。
        """
        try:
            from OpenGL import GL
            self.makeCurrent()
            prev_fbo = GL.glGetIntegerv(GL.GL_FRAMEBUFFER_BINDING)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
            px = max(0, min(x, self.width() - 1))
            py = max(0, min(self.height() - 1 - y, self.height() - 1))
            depth = GL.glReadPixels(px, py, 1, 1, GL.GL_DEPTH_COMPONENT, GL.GL_FLOAT)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, prev_fbo)
            return float(depth[0][0])
        except Exception:
            return None

    def screen_to_world(self, x: float, y: float, depth: float):
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


# =========================================================================
# ArcBall 相机（与 viewer_3d.py 保持一致）
# =========================================================================
class _ArcBallCamera:
    def __init__(self, distance: float = 2.0):
        self._rotation = np.eye(3, dtype=np.float32)
        self._distance = distance
        self.target = np.zeros(3, dtype=np.float32)
        self._last_pos = None
        self._tracking = False
        self.set_preset("iso")

    @property
    def distance(self) -> float:
        return self._distance

    @distance.setter
    def distance(self, value: float):
        self._distance = max(1e-4, value)

    def position(self) -> np.ndarray:
        offset = self._rotation @ np.array([0, 0, self._distance], dtype=np.float32)
        return self.target + offset

    def _basis(self):
        right = self._rotation[:, 0]
        up = self._rotation[:, 1]
        forward = -self._rotation[:, 2]
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
            sensitivity = max(0.1, self._distance * 0.02)
            angle_y = np.radians(dx * sensitivity)
            right, _, _ = self._basis()
            angle_x = np.radians(dy * sensitivity)
            R_y = self._rotation_matrix_from_axis_angle([0, 1, 0], angle_y)
            R_x = self._rotation_matrix_from_axis_angle(right, angle_x)
            self._rotation = R_x @ R_y @ self._rotation
            self._orthonormalize()
        elif buttons == Qt.RightButton:
            sens = self._distance * np.tan(np.radians(22.5)) * 2.0 / 1000.0
            right, up, _ = self._basis()
            delta = -dx * sens * right + dy * sens * up
            self.target += delta

    @staticmethod
    def _rotation_matrix_from_axis_angle(axis, angle: float) -> np.ndarray:
        axis = np.asarray(axis, dtype=np.float32)
        norm = np.linalg.norm(axis)
        if norm < 1e-9:
            return np.eye(3, dtype=np.float32)
        axis = axis / norm
        K = np.array([[0, -axis[2], axis[1]],
                      [axis[2], 0, -axis[0]],
                      [-axis[1], axis[0], 0]], dtype=np.float32)
        I = np.eye(3, dtype=np.float32)
        return I + np.sin(angle) * K + (1.0 - np.cos(angle)) * (K @ K)

    def _orthonormalize(self):
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
        target = np.asarray(target, dtype=np.float32)
        if keep_position:
            pos = self.position()
            old_distance = self._distance
            self.target = target
            diff = pos - self.target
            d = float(np.linalg.norm(diff))
            if d > 1e-9:
                forward = -diff / d
                world_up = np.array([0.0, 0.0, 1.0], dtype=np.float32)
                right = np.cross(forward, world_up)
                rnorm = np.linalg.norm(right)
                if rnorm < 1e-9:
                    right = np.array([1.0, 0.0, 0.0], dtype=np.float32)
                else:
                    right = right / rnorm
                up = np.cross(right, forward)
                self._rotation = np.column_stack([right, up, -forward])
            self._distance = old_distance
        else:
            self.target = target

    def set_preset(self, preset: str):
        presets = {
            "top": (np.array([0, 0, 1]), np.array([0, 1, 0])),
            "front": (np.array([0, -1, 0]), np.array([0, 0, 1])),
            "side": (np.array([1, 0, 0]), np.array([0, 0, 1])),
            "iso": (np.array([1, -1, 1]) / np.sqrt(3), np.array([0, 0, 1])),
        }
        camera_pos_dir, up_hint = presets.get(preset, presets["iso"])
        camera_pos_dir = np.asarray(camera_pos_dir, dtype=np.float32)
        camera_pos_dir = camera_pos_dir / np.linalg.norm(camera_pos_dir)
        up_hint = np.asarray(up_hint, dtype=np.float32)
        forward = -camera_pos_dir
        z_axis = -forward  # 相机 +Z（指向相机后方）
        # 右手系：right = forward × up_hint, up = z × right，保证 det=+1
        right = np.cross(forward, up_hint)
        right = right / max(np.linalg.norm(right), 1e-9)
        up = np.cross(z_axis, right)
        self._rotation = np.column_stack([right, up, z_axis])
        self.target = np.zeros(3, dtype=np.float32)

    def reset(self):
        self.set_preset("iso")
