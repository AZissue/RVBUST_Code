"""
3D 点云可视化窗口组件。
使用 pyqtgraph GLViewWidget 渲染点云，支持旋转/缩放和预设视角。
优化：像素级点渲染、彩虹色映射、坐标轴、自适应网格。
支持：鼠标中键设旋转中心、右键拖拽平移、点形状选择、颜色模式选择。
CloudCompare 风格鼠标交互：左键旋转、右键锚点平移、滚轮向光标缩放。
"""

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QComboBox,
)

from OpenGL.GL import (
    glReadPixels, glGetDoublev, glGetIntegerv,
    GL_DEPTH_COMPONENT, GL_MODELVIEW_MATRIX, GL_PROJECTION_MATRIX,
    GL_VIEWPORT, GL_FLOAT,
)
from OpenGL.GLU import gluUnProject

import pyqtgraph as pg
import pyqtgraph.opengl as gl

import resources as res


def _turbo_colormap(z_norm):
    """
    近似 Turbo 色图：蓝→青→绿→黄→红。
    相比简单蓝红渐变，中间色调更丰富，深度层次更清晰。
    """
    r = np.clip(np.interp(z_norm, [0, 0.25, 0.5, 0.75, 1.0],
                          [0.1, 0.2, 0.6, 1.0, 1.0]), 0, 1)
    g = np.clip(np.interp(z_norm, [0, 0.25, 0.5, 0.75, 1.0],
                          [0.1, 0.6, 1.0, 0.6, 0.1]), 0, 1)
    b = np.clip(np.interp(z_norm, [0, 0.25, 0.5, 0.75, 1.0],
                          [0.6, 1.0, 0.5, 0.1, 0.0]), 0, 1)
    return r, g, b


def _heatmap_colormap(z_norm):
    """热力图色图：蓝(远) → 红(近)"""
    r = z_norm
    g = np.zeros_like(z_norm)
    b = 1.0 - z_norm
    return r, g, b


class CustomGLViewWidget(gl.GLViewWidget):
    """
    模拟 CloudCompare 鼠标交互的自定义 GL 视图：
    - 左键拖拽：绕旋转中心轨道旋转（pyqtgraph 默认行为）
    - 右键拖拽：锚点式平移——抓取光标下的 3D 点随鼠标移动
    - 滚轮：向光标位置缩放（光标下的 3D 点保持屏幕位置不变）
    - 中键点击：在点云上拾取旋转中心（深度缓冲区 → 搜索 → 射线投射回退）
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._point_cloud_data = None
        self._pan_start_pos = None
        self._pan_anchor = None
        self._MIN_DIST = 5
        self._MAX_DIST = 20000

    def set_point_cloud_data(self, pts):
        self._point_cloud_data = pts

    # ─── OpenGL 坐标转换辅助 ───

    def _screen_to_gl(self, pos):
        """Qt 逻辑坐标 → OpenGL 物理像素坐标（y 翻转）"""
        vp = glGetIntegerv(GL_VIEWPORT)
        ratio = self.devicePixelRatioF()
        return int(pos.x() * ratio), vp[3] - int(pos.y() * ratio), vp

    def _view_params(self):
        """返回 (view_dir, camera_pos, center_pos, distance) numpy 数组"""
        elev = np.radians(self.opts.get('elevation', 30))
        azim = np.radians(self.opts.get('azimuth', 45))
        dist = float(self.opts.get('distance', 100))
        center = self.opts.get('center', pg.Vector(0, 0, 0))
        # pyqtgraph 在某些版本中会把 center 存为 QVector3D，不能直接传给 np.array
        if hasattr(center, 'x') and callable(getattr(center, 'x', None)):
            ctr = np.array([center.x(), center.y(), center.z()], dtype=np.float64)
        else:
            ctr = np.array(center, dtype=np.float64)
        # 视线方向：摄像机 → 中心
        view_dir = np.array([
            -np.cos(elev) * np.sin(azim),
            np.cos(elev) * np.cos(azim),
            -np.sin(elev),
        ], dtype=np.float64)
        view_dir /= np.linalg.norm(view_dir)
        cam = ctr - view_dir * dist
        return view_dir, cam, ctr, dist

    def _screen_axes(self, view_dir):
        """屏幕空间在世界的 right / up 轴"""
        world_up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        right = np.cross(view_dir, world_up)
        nr = np.linalg.norm(right)
        right = np.array([1.0, 0.0, 0.0]) if nr < 1e-8 else right / nr
        screen_up = np.cross(right, view_dir)
        screen_up /= np.linalg.norm(screen_up)
        return right, screen_up

    def _world_per_pixel(self, depth):
        """沿视线方向深度 depth 处，每像素对应的世界单位"""
        h = float(self.height())
        if h <= 0:
            return 1e-3
        fov = np.radians(self.opts.get('fov', 60))
        return depth * np.tan(fov / 2.0) * 2.0 / h

    def _pick_world_point(self, pos):
        """
        从深度缓冲区读取 pos 处的 3D 世界坐标。
        若该像素无几何体则搜索周围 → 回退为射线投射点云。
        返回 numpy 数组 (x, y, z) 或 None。
        """
        self.makeCurrent()
        try:
            gl_x, gl_y, vp = self._screen_to_gl(pos)
            mv = glGetDoublev(GL_MODELVIEW_MATRIX)
            proj = glGetDoublev(GL_PROJECTION_MATRIX)

            # 1) 深度缓冲区
            depth = glReadPixels(gl_x, gl_y, 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT)
            d = float(depth.ravel()[0])

            if d >= 1.0:
                for radius in range(1, 8):
                    ok = False
                    for rx in range(-radius, radius + 1):
                        for ry in range(-radius, radius + 1):
                            sx, sy = gl_x + rx, gl_y + ry
                            if sx < 0 or sy < 0 or sx >= vp[2] or sy >= vp[3]:
                                continue
                            nd = float(glReadPixels(sx, sy, 1, 1,
                                            GL_DEPTH_COMPONENT, GL_FLOAT).ravel()[0])
                            if nd < 1.0:
                                d, gl_x, gl_y, ok = nd, sx, sy, True
                                break
                        if ok:
                            break
                    if ok:
                        break

            if d < 1.0:
                wx, wy, wz = gluUnProject(gl_x, gl_y, d, mv, proj, vp)
                return np.array([wx, wy, wz], dtype=np.float64)

            # 2) 射线投射点云回退
            pts = self._point_cloud_data
            if pts is not None and len(pts) > 0:
                nx, ny, nz = gluUnProject(gl_x, gl_y, 0.0, mv, proj, vp)
                fx, fy, fz = gluUnProject(gl_x, gl_y, 1.0, mv, proj, vp)
                origin = np.array([nx, ny, nz])
                ray = np.array([fx - nx, fy - ny, fz - nz])
                ray /= np.linalg.norm(ray)

                to_pts = pts - origin
                proj_len = np.dot(to_pts, ray)
                ahead = proj_len > 0
                if ahead.any():
                    v = to_pts[ahead]
                    perp = v - proj_len[ahead, np.newaxis] * ray
                    idx = np.argmin(np.linalg.norm(perp, axis=1))
                    return pts[ahead][idx].astype(np.float64)
        except Exception:
            pass
        return None

    # ─── 滚轮：向光标缩放 ───

    def wheelEvent(self, event):
        self.makeCurrent()
        try:
            P = self._pick_world_point(event.pos())
            view_dir, cam, ctr, dist = self._view_params()
            if P is None:
                P = ctr
            # 摄像机到目标点的视线深度
            t = float(np.dot(P - cam, view_dir))
            t = max(t, 1.0)

            delta = event.angleDelta().y()
            factor = 1.15 if delta > 0 else 1.0 / 1.15
            new_dist = dist / factor
            new_dist = max(self._MIN_DIST, min(self._MAX_DIST, new_dist))

            # 调整中心使 P 的屏幕投影保持不变
            new_ctr = P - view_dir * (t - new_dist)
            self.opts['distance'] = new_dist
            self.opts['center'] = pg.Vector(*new_ctr)
            self.update()
        except Exception:
            pass
        event.accept()

    # ─── 中键：拾取旋转中心 ───

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.makeCurrent()
            P = self._pick_world_point(event.pos())
            if P is not None:
                self.opts['center'] = pg.Vector(float(P[0]), float(P[1]), float(P[2]))
                self.update()
            return
        if event.button() == Qt.RightButton:
            self._pan_start_pos = event.pos()
            self.makeCurrent()
            self._pan_anchor = self._pick_world_point(event.pos())
            self.setCursor(Qt.ClosedHandCursor)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.RightButton and self._pan_start_pos is not None:
            self._do_pan(event.pos())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            self._pan_start_pos = None
            self._pan_anchor = None
            self.setCursor(Qt.ArrowCursor)
            return
        super().mouseReleaseEvent(event)

    # ─── 右键平移：锚点跟随鼠标 ───

    def _do_pan(self, new_pos):
        dx = new_pos.x() - self._pan_start_pos.x()
        dy = new_pos.y() - self._pan_start_pos.y()
        if dx == 0 and dy == 0:
            return

        view_dir, cam, ctr, dist = self._view_params()
        anchor = self._pan_anchor if self._pan_anchor is not None else ctr
        t = float(np.dot(anchor - cam, view_dir))
        t = max(t, 1.0)

        wpp = self._world_per_pixel(t)
        right, screen_up = self._screen_axes(view_dir)

        # 鼠标右移 → 画面右移 → 中心左移
        new_ctr = ctr + right * (-dx * wpp) + screen_up * (dy * wpp)
        self.opts['center'] = pg.Vector(*new_ctr)
        self.update()

        # 增量更新锚点和起点
        self._pan_start_pos = new_pos
        if self._pan_anchor is not None:
            self._pan_anchor = anchor + right * (-dx * wpp) + screen_up * (dy * wpp)


class PointCloud3DView(QWidget):
    """3D 点云查看器，包含标题栏、GL 视图区域、底部视角预设按钮"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.setStyleSheet(f"""
            PointCloud3DView {{
                border: 2px solid {res.BORDER_DEFAULT};
                border-radius: {res.BORDER_RADIUS}px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 标题栏 ──
        title_bar = QWidget()
        title_bar.setFixedHeight(36)
        title_bar.setStyleSheet(f"""
            background-color: {res.BG_CARD};
            border-top-left-radius: {res.BORDER_RADIUS}px;
            border-top-right-radius: {res.BORDER_RADIUS}px;
        """)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(12, 0, 8, 0)

        title = QLabel("3D 标定场景")
        title.setStyleSheet(
            f"font-size: {res.FONT_H2}px; font-weight: 600; "
            f"color: {res.TEXT_TITLE}; border: none;"
        )
        title_layout.addWidget(title)
        title_layout.addStretch()

        btn_clear = QPushButton("\U0001f5d1")
        btn_clear.setFixedSize(16, 16)
        btn_clear.setToolTip("清空视图")
        btn_clear.clicked.connect(self.clear)
        btn_clear.setStyleSheet(f"border: none; font-size: 12px; color: {res.TEXT_HINT};")
        title_layout.addWidget(btn_clear)

        layout.addWidget(title_bar)

        # ── GL 视图 ──
        self._gl_widget = CustomGLViewWidget()
        self._gl_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._gl_widget.setBackgroundColor(pg.mkColor((26, 31, 46)))
        layout.addWidget(self._gl_widget, 1)

        # ── 底部工具栏 ──
        btn_bar = QWidget()
        btn_bar.setFixedHeight(32)
        btn_bar.setStyleSheet("background-color: rgba(0,0,0,0.5);")
        btn_layout = QHBoxLayout(btn_bar)
        btn_layout.setContentsMargins(8, 0, 8, 0)
        btn_layout.setSpacing(6)

        for text, slot in [
            ("俯视", self._view_top),
            ("正视", self._view_front),
            ("侧视", self._view_side),
            ("复位", self._reset_view),
        ]:
            btn = QPushButton(text)
            btn.setFixedHeight(24)
            btn.clicked.connect(slot)
            btn.setStyleSheet(f"""
                QPushButton {{
                    color: #CCC;
                    background: transparent;
                    border: 1px solid #555;
                    border-radius: 4px;
                    font-size: {res.FONT_HINT}px;
                    padding: 0 8px;
                }}
                QPushButton:hover {{
                    border-color: {res.PRIMARY};
                    color: {res.PRIMARY};
                }}
            """)
            btn_layout.addWidget(btn)

        btn_layout.addStretch()

        # 颜色模式选择
        lbl_color = QLabel("颜色")
        lbl_color.setStyleSheet(f"color: #999; font-size: {res.FONT_HINT}px; border: none;")
        btn_layout.addWidget(lbl_color)

        self._color_combo = QComboBox()
        self._color_combo.addItems(["彩虹", "热力图", "白色"])
        self._color_combo.setCurrentIndex(0)
        self._color_combo.setFixedWidth(72)
        self._color_combo.currentIndexChanged.connect(self._on_color_changed)
        self._color_combo.setStyleSheet(f"""
            QComboBox {{
                color: #CCC;
                background: #2a2a3a;
                border: 1px solid #555;
                border-radius: 4px;
                font-size: {res.FONT_HINT}px;
                padding: 1px 4px;
                min-height: 20px;
            }}
            QComboBox:hover {{ border-color: {res.PRIMARY}; }}
            QComboBox QAbstractItemView {{
                background: #2a2a3a;
                color: #CCC;
                selection-background-color: {res.PRIMARY};
            }}
        """)
        btn_layout.addWidget(self._color_combo)

        # 点形状选择
        lbl_shape = QLabel("形状")
        lbl_shape.setStyleSheet(f"color: #999; font-size: {res.FONT_HINT}px; border: none;")
        btn_layout.addWidget(lbl_shape)

        self._shape_combo = QComboBox()
        self._shape_combo.addItems(["方块", "圆点", "六边形"])
        self._shape_combo.setCurrentIndex(0)
        self._shape_combo.setFixedWidth(72)
        self._shape_combo.currentIndexChanged.connect(self._on_shape_changed)
        self._shape_combo.setStyleSheet(self._color_combo.styleSheet())
        btn_layout.addWidget(self._shape_combo)

        # 点大小滑块
        lbl_size = QLabel("大小")
        lbl_size.setStyleSheet(f"color: #999; font-size: {res.FONT_HINT}px; border: none;")
        btn_layout.addWidget(lbl_size)

        from PyQt5.QtWidgets import QSlider
        self._size_slider = QSlider(Qt.Horizontal)
        self._size_slider.setRange(1, 8)
        self._size_slider.setValue(3)
        self._size_slider.setFixedWidth(60)
        self._size_slider.valueChanged.connect(self._on_size_changed)
        self._size_slider.setStyleSheet("""
            QSlider::groove:horizontal { height: 4px; background: #444; border-radius: 2px; }
            QSlider::handle:horizontal { width: 12px; margin: -4px 0; background: #1677FF; border-radius: 6px; }
        """)
        btn_layout.addWidget(self._size_slider)

        layout.addWidget(btn_bar)

        self._scatter_item = None
        self._highlight_items = []
        self._hex_items = []           # 六边形 mesh 项
        self._current_pts = None
        self._current_colors = None
        self._point_size = 3
        self._color_mode = "彩虹"
        self._point_shape = "方块"

        self._add_grid()
        self._add_axes()

    def _add_grid(self):
        gz = gl.GLGridItem()
        gz.setSize(500, 500)
        gz.setSpacing(100, 100)
        gz.setColor(pg.mkColor((50, 50, 55, 60)))
        self._gl_widget.addItem(gz)

    def _add_axes(self):
        axis_len = 100
        for pts, color in [
            (np.array([[0, 0, 0], [axis_len, 0, 0]]), (1, 0.2, 0.2, 0.8)),
            (np.array([[0, 0, 0], [0, axis_len, 0]]), (0.2, 1, 0.2, 0.8)),
            (np.array([[0, 0, 0], [0, 0, axis_len]]), (0.2, 0.4, 1, 0.8)),
        ]:
            line = gl.GLLinePlotItem(pos=pts, color=color, width=2, antialias=True)
            self._gl_widget.addItem(line)

    def update_point_cloud(self, np_xyz):
        if np_xyz is None or len(np_xyz) == 0:
            return

        if len(np_xyz) > 80000:
            step = len(np_xyz) // 80000
            pts = np_xyz[::step].copy()
        else:
            pts = np_xyz.copy()

        self._current_pts = pts
        self._gl_widget.set_point_cloud_data(pts)
        self._apply_colors()
        self._render_points()

    def _apply_colors(self):
        pts = self._current_pts
        if pts is None:
            return

        z_vals = pts[:, 2]
        z_min, z_max = z_vals.min(), z_vals.max()
        if z_max > z_min:
            z_norm = (z_vals - z_min) / (z_max - z_min)
        else:
            z_norm = np.zeros_like(z_vals)

        if self._color_mode == "白色":
            r = np.ones_like(z_vals)
            g = np.ones_like(z_vals)
            b = np.ones_like(z_vals)
        elif self._color_mode == "热力图":
            r, g, b = _heatmap_colormap(z_norm)
        else:
            r, g, b = _turbo_colormap(z_norm)

        self._current_colors = np.column_stack(
            [r, g, b, np.full_like(r, 0.85)]
        ).astype(np.float32)

    def _render_points(self):
        self._clear_scatter()
        self._clear_hex_meshes()

        if self._current_pts is None:
            return

        shape = self._shape_combo.currentText()

        if shape == "六边形":
            self._render_hexagon_mesh()
        else:
            self._scatter_item = gl.GLScatterPlotItem(
                pos=self._current_pts,
                color=self._current_colors,
                size=self._point_size,
                pxMode=True,
            )
            self._gl_widget.addItem(self._scatter_item)

    def _render_hexagon_mesh(self):
        """将每个点渲染为小型六边形 mesh，最多 5000 个以保证性能"""
        pts = self._current_pts
        colors = self._current_colors

        if len(pts) > 5000:
            step = max(1, len(pts) // 5000)
            pts = pts[::step]
            colors = colors[::step]

        n = len(pts)
        if n == 0:
            return

        hex_size = self._point_size * 0.8

        angles = np.linspace(0, 2 * np.pi, 7)[:6]
        hx = np.cos(angles) * hex_size
        hy = np.sin(angles) * hex_size

        verts = np.zeros((n * 7, 3), dtype=np.float32)
        for i in range(n):
            base = i * 7
            verts[base] = pts[i]
            verts[base + 1] = pts[i] + np.array([hx[0], hy[0], 0])
            verts[base + 2] = pts[i] + np.array([hx[1], hy[1], 0])
            verts[base + 3] = pts[i] + np.array([hx[2], hy[2], 0])
            verts[base + 4] = pts[i] + np.array([hx[3], hy[3], 0])
            verts[base + 5] = pts[i] + np.array([hx[4], hy[4], 0])
            verts[base + 6] = pts[i] + np.array([hx[5], hy[5], 0])

        faces = np.zeros((n * 6, 3), dtype=np.uint32)
        for i in range(n):
            base = i * 7
            fbase = i * 6
            faces[fbase + 0] = [base, base + 1, base + 2]
            faces[fbase + 1] = [base, base + 2, base + 3]
            faces[fbase + 2] = [base, base + 3, base + 4]
            faces[fbase + 3] = [base, base + 4, base + 5]
            faces[fbase + 4] = [base, base + 5, base + 6]
            faces[fbase + 5] = [base, base + 6, base + 1]

        fc = np.repeat(colors[:, :3], 6, axis=0)
        fc = np.clip(fc, 0, 1)

        mesh = gl.GLMeshItem(
            vertexes=verts,
            faces=faces,
            faceColors=fc,
            smooth=False,
            shader='shaded',
        )
        self._gl_widget.addItem(mesh)
        self._hex_items.append(mesh)

    def _clear_scatter(self):
        if self._scatter_item is not None:
            self._gl_widget.removeItem(self._scatter_item)
            self._scatter_item = None

    def _clear_hex_meshes(self):
        for item in self._hex_items:
            self._gl_widget.removeItem(item)
        self._hex_items.clear()

    def _on_size_changed(self, value):
        self._point_size = value
        self._render_points()

    def _on_color_changed(self, idx):
        self._color_mode = self._color_combo.itemText(idx)
        self._apply_colors()
        self._render_points()

    def _on_shape_changed(self, idx):
        self._render_points()

    def highlight_points(self, points_3d):
        self._clear_highlights()
        if not points_3d:
            return
        pts = np.array(points_3d, dtype=np.float32)
        colors = np.tile([0.1, 1.0, 0.3, 1.0], (len(pts), 1)).astype(np.float32)
        item = gl.GLScatterPlotItem(pos=pts, color=colors, size=10, pxMode=True)
        self._gl_widget.addItem(item)
        self._highlight_items.append(item)

        for p in pts:
            cx, cy, cz = float(p[0]), float(p[1]), float(p[2])
            xline = np.array([[cx - 5, cy, cz], [cx + 5, cy, cz]])
            yline = np.array([[cx, cy - 5, cz], [cx, cy + 5, cz]])
            for ln in [xline, yline]:
                item = gl.GLLinePlotItem(pos=ln, color=(0, 1, 0.5, 1), width=1)
                self._gl_widget.addItem(item)
                self._highlight_items.append(item)

    def _clear_highlights(self):
        for item in self._highlight_items:
            self._gl_widget.removeItem(item)
        self._highlight_items.clear()

    def clear(self):
        self._clear_scatter()
        self._clear_hex_meshes()
        self._current_pts = None
        self._current_colors = None
        self._clear_highlights()

    def _view_top(self):
        self._gl_widget.setCameraPosition(
            pos=pg.Vector(0, 0, 500), distance=None, elevation=90, azimuth=0
        )

    def _view_front(self):
        self._gl_widget.setCameraPosition(
            pos=pg.Vector(0, -500, 0), distance=None, elevation=0, azimuth=0
        )

    def _view_side(self):
        self._gl_widget.setCameraPosition(
            pos=pg.Vector(500, 0, 0), distance=None, elevation=0, azimuth=90
        )

    def _reset_view(self):
        self._gl_widget.setCameraPosition(
            pos=pg.Vector(300, -300, 300), distance=None, elevation=30, azimuth=45
        )
