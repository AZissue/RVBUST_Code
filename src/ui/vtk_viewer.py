# -*- coding: utf-8 -*-
"""
VTK 内核 3D 点云控件骨架（P0：非破坏性新增，不接入主界面）。

设计口径（对齐 20260924 方案 §4/§5）：
  - 全量上传、零显式下采样：显示点数 == 输入点数（stats() 可查、demo 打印核对）；
  - 非有限点（NaN/Inf）只替换为 (0,0,0) 占位以维持索引对应，包围盒只按有效点计算
    （V4：NaN 云不导致 ResetCamera 失效）；
  - vtk 惰性导入：仅在控件构造时 import，主程序启动路径不付冷启动开销（G3）；
  - numpy → vtkPoints/vtkUnsignedCharArray 零拷贝上传（deep=0，numpy 缓冲由本控件持有）；
  - 拾取一律 vtkPointPicker（hardware picker 在 5M 点云上实测返回 id=-1）。

P0 范围：多图层（cloud_id → actor）、逐点颜色、点大小、背景、角落坐标轴、
网格地面、reset_view / 视角预设、点拾取、输入/显示点数统计。
ROI 框选、高亮索引、比例尺、pivot、overlay 文字属 P1~P3，后续在此类上扩展。
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

BG_DARK = (0.102, 0.102, 0.102)    # 与旧控件 BG_DARK 一致
BG_LIGHT = (0.92, 0.92, 0.92)


class VTKPointCloudView(QWidget):
    """VTK 内核点云控件：全量渲染，不做任何显式下采样。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # ---- 惰性导入：vtk 只在这里加载（冷启动 ~10s 级不进主程序启动路径）----
        import vtk
        from vtkmodules.util import numpy_support
        from vtkmodules.qt.QVTKRenderWindowInteractor import (
            QVTKRenderWindowInteractor,
        )

        self._vtk = vtk
        self._numpy_support = numpy_support

        self._clouds: Dict[str, dict] = {}   # cloud_id -> 渲染元数据
        self._point_size = 2.0
        self._bg = BG_DARK
        self._show_grid = True

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._ia = QVTKRenderWindowInteractor(self)
        self._ia.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self._ia)

        self._ren = vtk.vtkRenderer()
        self._ren.SetBackground(*self._bg)
        self._rw = self._ia.GetRenderWindow()
        self._rw.AddRenderer(self._ren)
        self._style = vtk.vtkInteractorStyleTrackballCamera()
        self._ia.SetInteractorStyle(self._style)

        # 角落坐标轴指示器（始终可见，不被点云遮挡）
        self._axes = vtk.vtkAxesActor()
        self._axes.SetTotalLength(1.0, 1.0, 1.0)
        self._marker = vtk.vtkOrientationMarkerWidget()
        self._marker.SetOrientationMarker(self._axes)
        self._marker.SetInteractor(self._ia)
        self._marker.SetViewport(0.0, 0.0, 0.18, 0.18)
        self._marker.EnabledOn()
        self._marker.InteractiveOff()

        # 网格地面 actor（按有效点云包围盒重建）
        self._grid_actor = None
        self._picker = vtk.vtkPointPicker()

        self.setMinimumSize(400, 260)

    # ------------------------------------------------------------------
    # 点云管理：全量上传，零下采样
    # ------------------------------------------------------------------
    def set_pointcloud(self, cloud_id: str, points: np.ndarray,
                       colors: np.ndarray = None):
        """加载一朵点云（全量，不抽稀）。points (N,3)，colors (N,3) uint8 可选。

        非有限点替换为 (0,0,0) 占位以维持 2D-3D 索引对应（与旧控件同口径），
        但包围盒只按有效点计算。
        """
        points = np.ascontiguousarray(points, dtype=np.float32)
        assert points.ndim == 2 and points.shape[1] == 3, "points 必须是 (N,3)"
        n = len(points)
        if n == 0:
            raise ValueError("点云为空")

        invalid = ~np.isfinite(points).all(axis=1)
        valid_pts = points[~invalid]
        if len(valid_pts) == 0:
            raise ValueError("点云全部为非有限点")
        if invalid.any():
            points = points.copy()
            points[invalid] = 0.0

        vtk = self._vtk
        ns = self._numpy_support

        vpts = vtk.vtkPoints()
        vpts.SetData(ns.numpy_to_vtk(points, deep=0))   # 零拷贝，缓冲由 self 持有

        poly = vtk.vtkPolyData()
        poly.SetPoints(vpts)

        if colors is not None:
            colors = np.ascontiguousarray(colors, dtype=np.uint8)
            assert colors.shape == (n, 3), "colors 必须是 (N,3) uint8"
            carr = ns.numpy_to_vtk(colors, deep=0)
            carr.SetName("Colors")
            poly.GetPointData().AddArray(carr)
            poly.GetPointData().SetActiveScalars("Colors")

        glyph = vtk.vtkVertexGlyphFilter()
        glyph.SetInputData(poly)
        glyph.Update()

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(glyph.GetOutputPort())
        if colors is not None:
            mapper.SetScalarModeToUsePointFieldData()
            mapper.SetColorModeToDirectScalars()
            mapper.SelectColorArray("Colors")

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetPointSize(self._point_size)

        old = self._clouds.pop(cloud_id, None)
        if old is not None:
            self._ren.RemoveActor(old["actor"])

        self._ren.AddActor(actor)
        self._clouds[cloud_id] = {
            "actor": actor,
            "points": points,          # 持有零拷贝缓冲
            "colors": colors,
            "input_count": n,          # 输入点数（原始，含非有限占位）
            "displayed_count": n,      # 显示点数：全量上传，恒等于输入
            "nonfinite_count": int(invalid.sum()),
            "bounds": (float(valid_pts[:, 0].min()), float(valid_pts[:, 0].max()),
                       float(valid_pts[:, 1].min()), float(valid_pts[:, 1].max()),
                       float(valid_pts[:, 2].min()), float(valid_pts[:, 2].max())),
        }
        self._rebuild_grid()
        self._ren.ResetCamera(*self._combined_bounds())

    def remove_pointcloud(self, cloud_id: str):
        meta = self._clouds.pop(cloud_id, None)
        if meta is not None:
            self._ren.RemoveActor(meta["actor"])
            self._rebuild_grid()
            self._ren.ResetCamera(*self._combined_bounds())

    def clear_pointclouds(self):
        for meta in self._clouds.values():
            self._ren.RemoveActor(meta["actor"])
        self._clouds.clear()
        self._rebuild_grid()
        self._ren.ResetCamera(-1.0, 1.0, -1.0, 1.0, -1.0, 1.0)

    def cloud_ids(self) -> list:
        return list(self._clouds.keys())

    def stats(self) -> Dict[str, dict]:
        """各 cloud_id 的 输入/显示/非有限 点数（供状态栏与 demo 核对）。"""
        return {cid: {k: m[k] for k in
                      ("input_count", "displayed_count", "nonfinite_count")}
                for cid, m in self._clouds.items()}

    # ------------------------------------------------------------------
    # 显示选项
    # ------------------------------------------------------------------
    def set_point_size(self, size: float):
        self._point_size = float(size)
        for meta in self._clouds.values():
            meta["actor"].GetProperty().SetPointSize(self._point_size)
        self._rw.Render()

    def set_background(self, color):
        """color: (r,g,b) 0~1 元组，或 True/False（True=深色）。"""
        if isinstance(color, (tuple, list, np.ndarray)):
            self._bg = tuple(float(c) for c in color[:3])
        else:
            self._bg = BG_DARK if color else BG_LIGHT
        self._ren.SetBackground(*self._bg)
        self._rw.Render()

    def set_show_grid(self, on: bool):
        self._show_grid = bool(on)
        if self._grid_actor is not None:
            self._grid_actor.SetVisibility(self._show_grid)
        self._rw.Render()

    def set_show_axes(self, on: bool):
        self._marker.SetEnabled(1 if on else 0)
        self._rw.Render()

    # ------------------------------------------------------------------
    # 视角
    # ------------------------------------------------------------------
    def _combined_bounds(self):
        if not self._clouds:
            return (-1.0, 1.0, -1.0, 1.0, -1.0, 1.0)
        bs = [m["bounds"] for m in self._clouds.values()]
        return (min(b[0] for b in bs), max(b[1] for b in bs),
                min(b[2] for b in bs), max(b[3] for b in bs),
                min(b[4] for b in bs), max(b[5] for b in bs))

    def _center_radius(self):
        x0, x1, y0, y1, z0, z1 = self._combined_bounds()
        c = np.array([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2])
        r = max(float(np.linalg.norm([x1 - x0, y1 - y0, z1 - z0])) * 0.5, 1e-3)
        return c, r

    def reset_view(self):
        """按有效点包围盒重置相机（等轴测视角）。"""
        self.set_view_preset("iso")

    def set_view_preset(self, preset: str):
        """视角预设：top / front / side / iso（Z 轴朝上，与 MCC 坐标口径一致）。"""
        cam = self._ren.GetActiveCamera()
        c, r = self._center_radius()
        d = 4.0 * r
        up = (0.0, 0.0, 1.0)
        if preset == "top":
            pos, up = c + (0.0, 0.0, d), (0.0, 1.0, 0.0)
        elif preset == "front":
            pos = c + (0.0, -d, 0.0)
        elif preset == "side":
            pos = c + (d, 0.0, 0.0)
        else:  # iso
            pos = c + (2.4 * r, -2.4 * r, 1.8 * r)
        cam.SetFocalPoint(*c)
        cam.SetPosition(*pos)
        cam.SetViewUp(*up)
        self._ren.ResetCameraClippingRange()
        self._rw.Render()

    # ------------------------------------------------------------------
    # 拾取（一律 vtkPointPicker，不用 hardware picker）
    # ------------------------------------------------------------------
    def pick(self, x: int, y: int):
        """屏幕坐标拾取 -> (point_id, world_xyz)；未命中返回 (-1, None)。"""
        self._picker.Pick(x, y, 0, self._ren)
        pid = self._picker.GetPointId()
        if pid < 0:
            return -1, None
        return int(pid), tuple(float(v) for v in self._picker.GetPickPosition())

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _rebuild_grid(self):
        """在有效点云 Z 最小值的 XY 平面上铺灰色网格线（对齐旧控件语义）。"""
        if self._grid_actor is not None:
            self._ren.RemoveActor(self._grid_actor)
            self._grid_actor = None
        if not self._clouds:
            return
        x0, x1, y0, y1, _, z0 = self._combined_bounds()
        if not all(np.isfinite([x0, x1, y0, y1, z0])):
            return
        span_x, span_y = x1 - x0, y1 - y0
        if span_x <= 0 or span_y <= 0:
            return
        step = 10.0 ** np.floor(np.log10(max(span_x, span_y) / 8.0))
        vtk = self._vtk
        pts = vtk.vtkPoints()
        lines = vtk.vtkCellArray()
        gx0, gx1 = np.floor(x0 / step) * step, np.ceil(x1 / step) * step
        gy0, gy1 = np.floor(y0 / step) * step, np.ceil(y1 / step) * step
        pid = 0
        x = gx0
        while x <= gx1 + 1e-9:
            pts.InsertNextPoint(x, gy0, z0)
            pts.InsertNextPoint(x, gy1, z0)
            lines.InsertNextCell(2)
            lines.InsertCellPoint(pid)
            lines.InsertCellPoint(pid + 1)
            pid += 2
            x += step
        y = gy0
        while y <= gy1 + 1e-9:
            pts.InsertNextPoint(gx0, y, z0)
            pts.InsertNextPoint(gx1, y, z0)
            lines.InsertNextCell(2)
            lines.InsertCellPoint(pid)
            lines.InsertCellPoint(pid + 1)
            pid += 2
            y += step
        grid = vtk.vtkPolyData()
        grid.SetPoints(pts)
        grid.SetLines(lines)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(grid)
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        dark = sum(self._bg) < 1.5
        actor.GetProperty().SetColor(*(0.35, 0.35, 0.35) if dark else (0.7, 0.7, 0.7))
        actor.SetVisibility(self._show_grid)
        self._ren.AddActor(actor)
        self._grid_actor = actor

    # ------------------------------------------------------------------
    def interactor(self):
        """返回底层 QVTKRenderWindowInteractor（调试用）。"""
        return self._ia

    def showEvent(self, event):
        super().showEvent(event)
        self._ia.Initialize()

    def closeEvent(self, event):
        try:
            self._rw.Finalize()
        except Exception:
            pass
        super().closeEvent(event)
