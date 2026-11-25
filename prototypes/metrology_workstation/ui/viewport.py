from __future__ import annotations

import math

import numpy as np
import vtkmodules.vtkRenderingOpenGL2  # noqa: F401
try:
    from vtkmodules.qt.QVTKOpenGLNativeWidget import QVTKOpenGLNativeWidget as VTKWidgetBase
except ImportError:
    from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor as VTKWidgetBase
from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkLine, vtkPolyData
from vtkmodules.vtkCommonTransforms import vtkTransform
from vtkmodules.vtkFiltersCore import vtkAppendPolyData, vtkPolyDataNormals
from vtkmodules.vtkFiltersSources import vtkCubeSource, vtkCylinderSource, vtkRegularPolygonSource
from vtkmodules.vtkInteractionWidgets import vtkOrientationMarkerWidget
from vtkmodules.vtkRenderingAnnotation import vtkAxesActor
from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper, vtkRenderer
from vtkmodules.util.numpy_support import numpy_to_vtk

from core.scene_manager import SceneManager


class VTKViewport(VTKWidgetBase):
    def __init__(self) -> None:
        super().__init__()
        self.setAccessibleName("统一三维视图")
        self.renderer = vtkRenderer()
        self.renderer.SetBackground(0.0667, 0.1098, 0.1686)
        self.GetRenderWindow().AddRenderer(self.renderer)
        self.GetRenderWindow().SetMultiSamples(4)
        self.scene = SceneManager(self.renderer)
        self.grid_actor = self._make_grid()
        self.renderer.AddActor(self.grid_actor)
        self._create_demo_scene()
        self.axes = vtkAxesActor()
        self.axes.SetTotalLength(24, 24, 24)
        self.axes.SetShaftTypeToCylinder()
        self.marker = vtkOrientationMarkerWidget()
        self.marker.SetOrientationMarker(self.axes)
        self.marker.SetInteractor(self.GetRenderWindow().GetInteractor())
        self.marker.SetViewport(0.0, 0.0, 0.16, 0.24)
        self.marker.SetEnabled(1)
        self.marker.InteractiveOff()
        self.reset_view()
        self.GetRenderWindow().Render()

    @staticmethod
    def _actor(poly_data: vtkPolyData, color: tuple[float, float, float], opacity: float = 1.0) -> vtkActor:
        mapper = vtkPolyDataMapper()
        mapper.SetInputData(poly_data)
        actor = vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetOpacity(opacity)
        actor.GetProperty().SetInterpolationToPhong()
        actor.GetProperty().SetAmbient(0.28)
        actor.GetProperty().SetDiffuse(0.72)
        actor.GetProperty().SetSpecular(0.22)
        actor.GetProperty().SetSpecularPower(28)
        return actor

    @staticmethod
    def _transformed(source, transform: vtkTransform) -> vtkPolyData:
        from vtkmodules.vtkFiltersGeneral import vtkTransformPolyDataFilter
        filt = vtkTransformPolyDataFilter()
        filt.SetInputConnection(source.GetOutputPort())
        filt.SetTransform(transform)
        filt.Update()
        return filt.GetOutput()

    def _create_demo_scene(self) -> None:
        pieces = []
        base = vtkCubeSource()
        base.SetXLength(142)
        base.SetYLength(94)
        base.SetZLength(12)
        pieces.append(base)
        for x in (-55, 55):
            for y in (-31, 31):
                boss = vtkCylinderSource()
                boss.SetRadius(10)
                boss.SetHeight(10)
                boss.SetResolution(48)
                transform = vtkTransform()
                transform.Translate(x, y, 10)
                pieces.append(self._transformed(boss, transform))
        body = vtkCylinderSource()
        body.SetRadius(38)
        body.SetHeight(38)
        body.SetResolution(96)
        transform = vtkTransform()
        transform.Translate(0, 0, 22)
        pieces.append(self._transformed(body, transform))
        ring = vtkRegularPolygonSource()
        ring.SetNumberOfSides(96)
        ring.SetRadius(29)
        ring.SetCenter(0, 0, 41.2)
        ring.SetGeneratePolygon(False)
        ring.SetGeneratePolyline(True)
        pieces.append(ring)
        append = vtkAppendPolyData()
        for piece in pieces:
            append.AddInputData(piece if isinstance(piece, vtkPolyData) else piece.GetOutput())
        append.Update()
        normals = vtkPolyDataNormals()
        normals.SetInputConnection(append.GetOutputPort())
        normals.SetFeatureAngle(45)
        normals.SplittingOn()
        normals.Update()
        mesh_actor = self._actor(normals.GetOutput(), (0.34, 0.52, 0.67))
        mesh_actor.GetProperty().SetEdgeVisibility(False)
        self.scene.add_object("mesh_001", mesh_actor)

        points = vtkPoints()
        rng = np.random.default_rng(17)
        count = 12500
        theta = rng.uniform(0, 2 * math.pi, count)
        radius = rng.uniform(38.03, 38.16, count)
        z = rng.uniform(3, 41, count)
        xyz = np.column_stack((radius * np.cos(theta), radius * np.sin(theta), z))
        points.SetData(numpy_to_vtk(xyz, deep=True))
        cloud = vtkPolyData()
        cloud.SetPoints(points)
        cells = vtkCellArray()
        cells.Allocate(count)
        for index in range(count):
            cells.InsertNextCell(1)
            cells.InsertCellPoint(index)
        cloud.SetVerts(cells)
        cloud_actor = self._actor(cloud, (0.30, 0.72, 0.94))
        cloud_actor.GetProperty().SetPointSize(2)
        cloud_actor.GetProperty().SetLighting(False)
        cloud_actor.SetVisibility(False)
        self.scene.add_object("cloud_fused", cloud_actor)

        cad_actor = self._actor(normals.GetOutput(), (0.93, 0.65, 0.26))
        cad_actor.GetProperty().SetRepresentationToWireframe()
        cad_actor.GetProperty().SetLineWidth(1.0)
        cad_actor.GetProperty().SetOpacity(0.45)
        cad_actor.SetVisibility(False)
        self.scene.add_object("cad_001", cad_actor)
        self.renderer.ResetCameraClippingRange()

    def _make_grid(self) -> vtkActor:
        points = vtkPoints()
        lines = vtkCellArray()
        extent, step = 120, 20
        for value in range(-extent, extent + 1, step):
            for start, end in (((value, -extent, -7), (value, extent, -7)), ((-extent, value, -7), (extent, value, -7))):
                line = vtkLine()
                line.GetPointIds().SetId(0, points.InsertNextPoint(*start))
                line.GetPointIds().SetId(1, points.InsertNextPoint(*end))
                lines.InsertNextCell(line)
        grid = vtkPolyData()
        grid.SetPoints(points)
        grid.SetLines(lines)
        actor = self._actor(grid, (0.18, 0.27, 0.36))
        actor.GetProperty().SetLighting(False)
        return actor

    def reset_view(self) -> None:
        self.renderer.ResetCamera()
        camera = self.renderer.GetActiveCamera()
        camera.SetPosition(190, -220, 175)
        camera.SetFocalPoint(0, 0, 15)
        camera.SetViewUp(0, 0, 1)
        self.renderer.ResetCamera()
        camera.Zoom(1.24)
        self.GetRenderWindow().Render()

    def set_standard_view(self, name: str) -> None:
        views = {
            "等轴测": ((190, -220, 175), (0, 0, 1)),
            "正视图": ((0, -280, 15), (0, 0, 1)),
            "俯视图": ((0, 0, 300), (0, 1, 0)),
            "左视图": ((-280, 0, 15), (0, 0, 1)),
            "右视图": ((280, 0, 15), (0, 0, 1)),
        }
        position, up = views[name]
        camera = self.renderer.GetActiveCamera()
        camera.SetPosition(*position)
        camera.SetFocalPoint(0, 0, 15)
        camera.SetViewUp(*up)
        self.renderer.ResetCamera()
        camera.Zoom(1.24)
        self.GetRenderWindow().Render()

    def set_module_scene(self, module: str) -> None:
        self.scene.set_visible("mesh_001", module not in ("数据采集", "三维重建"))
        self.scene.set_visible("cloud_fused", module in ("数据采集", "三维重建", "CAD 对比"))
        self.scene.set_visible("cad_001", module == "CAD 对比")
        self.reset_view()

    def show_node(self, node_id: str) -> None:
        mapping = {"cloud_original": "cloud_fused", "deviation_001": "cloud_fused", "dimensions": "mesh_001"}
        target = mapping.get(node_id, node_id)
        if target in self.scene.actors:
            for object_id in self.scene.actors:
                self.scene.set_visible(object_id, object_id == target)
            self.reset_view()

    def set_node_visible(self, node_id: str, visible: bool) -> None:
        target = "cloud_fused" if node_id == "cloud_original" else node_id
        self.scene.set_visible(target, visible)
        self.GetRenderWindow().Render()

    def set_grid_visible(self, visible: bool) -> None:
        self.grid_actor.SetVisibility(int(visible))
        self.GetRenderWindow().Render()

    def set_representation(self, representation: str) -> None:
        actor = self.scene.actor("mesh_001")
        if actor:
            actor.GetProperty().SetRepresentation({"实体": 2, "线框": 1, "顶点": 0}[representation])
            self.GetRenderWindow().Render()
