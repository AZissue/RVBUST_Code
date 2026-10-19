"""Vendor-neutral OpenGL 3.3 point buffers, frame cache and interaction LOD.

No CUDA, VTK, driver path or vendor selection. CPU preparation runs on a worker;
GPU uploads happen with the widget context current. Camera changes reuse VBOs.
"""
import ctypes
import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QSurfaceFormat, QMatrix4x4, QPainter, QColor, QPen
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from ui_common.worker_thread import WorkerThread
from ..core.render_cache import FrameRenderCache, sources_from_layers, POLICIES
from .navigation import NavigationMixin

VERTEX_SHADER = '''#version 330 core
layout(location=0) in vec3 position;
layout(location=1) in vec4 color;
uniform mat4 mvp;
uniform vec3 offset;
uniform float pointSize;
uniform int colorMode;
uniform int markerMode;
uniform vec2 heightRange;
out vec4 pointColor;
void main() {
    vec3 p = position + offset;
    gl_Position = mvp * vec4(p, 1.0);
    if (markerMode == 1) gl_Position.z -= 0.00003 * gl_Position.w;
    gl_PointSize = pointSize;
    float h = clamp((p.z-heightRange.x)/max(heightRange.y-heightRange.x,0.00001),0.0,1.0);
    pointColor = colorMode==1 ? vec4(.25+.65*h,.7+.2*h,.95-.65*h,1) :
                 colorMode==2 ? vec4(.66,.81,.91,1) : color;
}'''
FRAGMENT_SHADER = '''#version 330 core
in vec4 pointColor;
uniform int markerMode;
out vec4 fragColor;
void main() {
    if (markerMode == 1) {
        float r = length(gl_PointCoord - vec2(0.5));
        if (r > 0.5 || r < 0.30) discard;
    }
    fragColor = pointColor;
}
'''


class GpuCloudCanvas(NavigationMixin, QOpenGLWidget):
    render_failed = Signal(str)
    status_changed = Signal()
    view_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        fmt.setDepthBufferSize(24)
        fmt.setSwapInterval(1)
        self.setFormat(fmt)
        self.setMinimumSize(360, 300)
        self.setCursor(Qt.OpenHandCursor)
        self.zoom = 1.
        self.pan = np.zeros(2)
        self.center = np.zeros(3)
        self.extent = 340.
        self.grid, self.axes = True, True
        self.point_size = 2
        self.color_mode = '原始颜色'
        self.total_points = 0
        self.policy = POLICIES['均衡']
        self.policy_name = '均衡'
        self.backend_name = 'OpenGL 3.3'
        self.scene = None
        self._cache = FrameRenderCache()
        self._worker = None
        self._request = 0
        self._pending = None
        self._fit_pending = False
        self._layers = []
        self._last = None
        self._moving = False
        self._ready = False
        self._failure = None
        self._closed = False
        self._buffers = {}
        self._program = None
        self._grid_buffer = None
        self._marker_buffer = None
        self._marker_points = []
        self._markers_dirty = True
        self.uploads = 0
        self._restore = QTimer(self)
        self._restore.setSingleShot(True)
        self._restore.timeout.connect(self._end_interaction)
        self._init_navigation()

    @property
    def is_busy(self):
        return self._worker is not None

    @property
    def displayed_points(self):
        return sum(self.scene.draw_counts(self._moving, self.policy)) if self.scene else 0

    def set_policy(self, name):
        self.policy_name = name
        self.policy = POLICIES[name]
        self.set_layers(self._layers)

    def set_layers(self, layers, fit=False):
        self._layers = list(layers)
        self.total_points = sum(len(layer.points) for layer in layers if layer.visible)
        self._request += 1
        self._pending = (self._request, sources_from_layers(layers), self.policy)
        self._fit_pending |= fit
        if not self.is_busy:
            self._start_prepare()

    def _start_prepare(self):
        if self._pending is None or self._closed:
            return
        version, sources, policy = self._pending
        self._pending = None
        self._worker = WorkerThread(lambda: (version, self._cache.prepare(sources, policy)))
        self._worker.result_ready.connect(self._prepared)
        self._worker.finished.connect(self._prepare_finished)
        self._worker.start()
        self.status_changed.emit()

    def _prepared(self, result, error):
        if error:
            self._fail(f'显示缓存准备失败：{error}')
        elif result[0] == self._request and not self._closed:
            self.scene = result[1]
            if self._fit_pending:
                self.fit_view()
                self._fit_pending = False
            self.update()
            self.status_changed.emit()

    def _prepare_finished(self):
        self._worker.deleteLater()
        self._worker = None
        if self._pending is not None:
            self._start_prepare()
        self.status_changed.emit()

    def _fail(self, message):
        if self._failure is None:
            self._failure = message
            QTimer.singleShot(0, lambda: self.render_failed.emit(message))

    def initializeGL(self):
        try:
            from OpenGL import GL
            from OpenGL.GL.shaders import compileProgram, compileShader
            self.gl = GL
            self._program = compileProgram(compileShader(VERTEX_SHADER, GL.GL_VERTEX_SHADER),
                                           compileShader(FRAGMENT_SHADER, GL.GL_FRAGMENT_SHADER))
            self._vao = GL.glGenVertexArrays(1)
            self._uniforms = {name: GL.glGetUniformLocation(self._program, name) for name in
                              ('mvp', 'offset', 'pointSize', 'colorMode', 'heightRange', 'markerMode')}
            GL.glEnable(GL.GL_DEPTH_TEST)
            GL.glEnable(GL.GL_PROGRAM_POINT_SIZE)
            self.context().aboutToBeDestroyed.connect(self.cleanup)
            vendor = GL.glGetString(GL.GL_RENDERER)
            self.backend_name = 'OpenGL / ' + vendor.decode(errors='replace')
            self._ready = True
            self.status_changed.emit()
        except Exception as exc:
            self._fail(f'OpenGL 3.3 初始化失败：{exc}')

    def _upload(self):
        gl = self.gl
        wanted = {frame.key for frame in self.scene.frames} if self.scene else set()
        for key in list(self._buffers):
            if key not in wanted:
                gl.glDeleteBuffers(1, [self._buffers.pop(key)[0]])
        if self.scene is None:
            return
        for frame in self.scene.frames:
            old = self._buffers.get(frame.key)
            if old is not None and old[1] is frame.packed:
                continue
            if old is not None:
                gl.glDeleteBuffers(1, [old[0]])
            buffer = gl.glGenBuffers(1)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, buffer)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, frame.packed.nbytes, frame.packed, gl.GL_STATIC_DRAW)
            self._buffers[frame.key] = (buffer, frame.packed)
            self.uploads += 1

    def _bind(self, buffer):
        gl = self.gl
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, buffer)
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, False, 16, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(1)
        gl.glVertexAttribPointer(1, 4, gl.GL_UNSIGNED_BYTE, True, 16, ctypes.c_void_p(12))

    def _matrix(self):
        scale = min(self.width(), self.height()) * 1.65 / self.extent * self.zoom
        matrix = QMatrix4x4()
        matrix.ortho(-self.width() / scale / 2, self.width() / scale / 2,
                     -self.height() / scale / 2, self.height() / scale / 2,
                     -self.extent * 4, self.extent * 4)
        matrix.translate(float(self.pan[0] / scale), float(-self.pan[1] / scale), 0)
        rotation = np.eye(4)
        rotation[:3, :3] = self.rotation.matrix
        matrix *= QMatrix4x4(*rotation.ravel().tolist())
        return matrix

    def paintGL(self):
        if not self._ready:
            return
        gl = self.gl
        try:
            gl.glViewport(0, 0, int(self.width()*self.devicePixelRatioF()), int(self.height()*self.devicePixelRatioF()))
            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glEnable(gl.GL_PROGRAM_POINT_SIZE)
            gl.glDepthMask(gl.GL_TRUE)
            gl.glClearColor(.29, .29, .29, 1.)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
            gl.glBindVertexArray(self._vao)
            self._upload()
            gl.glUseProgram(self._program)
            gl.glUniform1i(self._uniforms['markerMode'], 0)
            gl.glUniformMatrix4fv(self._uniforms['mvp'], 1, False, np.asarray(self._matrix().data(), dtype=np.float32))
            gl.glUniform1f(self._uniforms['pointSize'], self.point_size * self.devicePixelRatioF())
            mode = {'原始颜色': 0, '高度着色': 1, '统一颜色': 2}[self.color_mode]
            gl.glUniform1i(self._uniforms['colorMode'], mode)
            heights = (self.scene.bounds[:, 2] - self.center[2]) if self.scene and self.scene.bounds is not None else [-1, 1]
            gl.glUniform2f(self._uniforms['heightRange'], float(heights[0]), float(heights[1]))
            if self.scene:
                for frame, count in zip(self.scene.frames, self.scene.draw_counts(self._moving, self.policy)):
                    self._bind(self._buffers[frame.key][0])
                    gl.glUniform3f(self._uniforms['offset'], *(frame.origin - self.center).astype(float))
                    gl.glDrawArrays(gl.GL_POINTS, 0, count)
            self._draw_markers()
            if self.grid:
                self._draw_grid()
            gl.glBindVertexArray(0)
            gl.glUseProgram(0)
        except Exception as exc:
            self._fail(f'GPU 点云绘制失败：{exc}')
        painter = QPainter(self)
        painter.setPen(QColor('#dce4eb'))
        painter.drawText(18, 28, f'{self.displayed_points:,} / {self.total_points:,} 点 · {"交互降采样" if self._moving else "静止细节"} · {self.policy_name}')
        painter.drawText(18, 48, '正在后台准备显示缓存…' if self.is_busy else self.backend_name)
        painter.drawText(18, self.height() - 18, '左键轨迹球旋转 · 右键/中键平移 · 滚轮缩放 · 双击设旋转中心 · F/Z 适配')
        if self._last is not None:
            x, y = self._pivot_pixel()
            painter.setPen(QPen(QColor('#cccccc'), 1))
            painter.drawEllipse(int(x)-7, int(y)-7, 14, 14)
        if self.axes:
            for text, color, origin, end in self.axis_endpoints():
                painter.setPen(QPen(QColor(color), 2))
                painter.drawLine(int(origin[0]), int(origin[1]), int(end[0]), int(end[1]))
                painter.drawText(int(end[0])+3, int(end[1])-3, text)
        painter.end()

    def set_marker_annotations(self, points):
        self._marker_points = list(points)
        self._markers_dirty = True
        self.update()

    def _draw_markers(self):
        if not self._marker_points:
            return
        from ..core.render_cache import PACK_DTYPE
        gl = self.gl
        if self._markers_dirty:
            xyz = np.asarray([item[1][0] for item in self._marker_points], dtype=float)
            self._marker_origin = xyz.mean(axis=0)
            packed = np.empty(len(xyz), dtype=PACK_DTYPE)
            packed['position'] = xyz-self._marker_origin
            packed['color'] = [QColor(item[1][1]).getRgb() for item in self._marker_points]
            if self._marker_buffer is None:
                self._marker_buffer = gl.glGenBuffers(1)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._marker_buffer)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, packed.nbytes, packed, gl.GL_STATIC_DRAW)
            self._markers_dirty = False
        self._bind(self._marker_buffer)
        gl.glUniform3f(self._uniforms['offset'], *(self._marker_origin-self.center).astype(float))
        gl.glUniform1i(self._uniforms['colorMode'], 0)
        gl.glUniform1i(self._uniforms['markerMode'], 1)
        gl.glUniform1f(self._uniforms['pointSize'], 11*self.devicePixelRatioF())
        gl.glDepthFunc(gl.GL_LEQUAL)
        gl.glDepthMask(gl.GL_FALSE)
        gl.glDrawArrays(gl.GL_POINTS, 0, len(self._marker_points))
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDepthFunc(gl.GL_LESS)
        gl.glUniform1i(self._uniforms['markerMode'], 0)

    def _draw_grid(self):
        from ..core.render_cache import PACK_DTYPE
        gl = self.gl
        bounds = tuple(self.scene.bounds.ravel()) if self.scene and self.scene.bounds is not None else ()
        key = (bounds, self.extent, tuple(self.center))
        if getattr(self, '_grid_key', None) != key:
            step = 10 ** np.floor(np.log10(self.extent / 12))
            radius = step * 15
            z = float(self.scene.bounds[0, 2] - self.center[2] - .1) if bounds else -10.
            vertices = []
            for value in np.arange(-radius, radius + step / 2, step):
                vertices.extend([(value, -radius, z), (value, radius, z), (-radius, value, z), (radius, value, z)])
            packed = np.empty(len(vertices), dtype=PACK_DTYPE)
            packed['position'] = vertices
            packed['color'] = [120, 140, 100, 255]
            if self._grid_buffer is None:
                self._grid_buffer = gl.glGenBuffers(1)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._grid_buffer)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, packed.nbytes, packed, gl.GL_STATIC_DRAW)
            self._grid_count = len(vertices)
            self._grid_key = key
        self._bind(self._grid_buffer)
        gl.glUniform3f(self._uniforms['offset'], 0, 0, 0)
        gl.glUniform1i(self._uniforms['colorMode'], 0)
        gl.glDepthMask(gl.GL_FALSE)  # Background grid is not a pickable point.
        gl.glDrawArrays(gl.GL_LINES, 0, self._grid_count)
        gl.glDepthMask(gl.GL_TRUE)

    def pick_pivot(self, position):
        if not self._ready or not self.scene or not self.scene.frames:
            return None
        # A single depth read on double-click; never scans millions of CPU points.
        self.makeCurrent()
        gl = self.gl
        try:
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.defaultFramebufferObject())
            ratio = self.devicePixelRatioF()
            x = int(position.x()*ratio)
            y = int((self.height()-position.y())*ratio)-1
            if not 0 <= x < int(self.width()*ratio) or not 0 <= y < int(self.height()*ratio):
                return None
            depth = float(np.asarray(gl.glReadPixels(x, y, 1, 1, gl.GL_DEPTH_COMPONENT, gl.GL_FLOAT)).ravel()[0])
            if depth >= 1.:
                return None
            ndc = np.array([2*(x+.5)/(self.width()*ratio)-1,
                            2*(y+.5)/(self.height()*ratio)-1, 2*depth-1, 1.])
            matrix = np.asarray(self._matrix().data()).reshape(4, 4, order='F')
            hit = np.linalg.solve(matrix, ndc)
            return self.center+hit[:3]/hit[3]
        finally:
            self.doneCurrent()

    def fit_view(self):
        if self.scene is not None and self.scene.bounds is not None:
            low, high = self.scene.bounds
            self.center = (low + high) * .5
            self.extent = max(float(np.linalg.norm(high-low)), 10.)
        self.zoom = 1.
        self.pan[:] = 0
        self._notify_view_changed()

    def _begin_interaction(self):
        changed = not self._moving
        self._moving = True
        self._restore.start(self.policy.restore_ms)
        self._notify_view_changed()
        if changed:
            self.status_changed.emit()

    def _end_interaction(self):
        if self._last is not None:
            self._restore.start(self.policy.restore_ms)
            return
        self._moving = False
        self.update()
        self.status_changed.emit()

    def cleanup(self):
        if not self._ready:
            return
        self.makeCurrent()
        gl = self.gl
        for buffer, _ in self._buffers.values():
            gl.glDeleteBuffers(1, [buffer])
        self._buffers.clear()
        if self._marker_buffer is not None:
            gl.glDeleteBuffers(1, [self._marker_buffer])
            self._marker_buffer = None
            self._markers_dirty = True
        if self._grid_buffer is not None:
            gl.glDeleteBuffers(1, [self._grid_buffer])
            self._grid_buffer = None
            self._grid_key = None
        gl.glDeleteVertexArrays(1, [self._vao])
        gl.glDeleteProgram(self._program)
        self._ready = False
        self.doneCurrent()

    def shutdown(self):
        self._closed = True
        self._pending = None
        self._stop_navigation()
        self.cleanup()
