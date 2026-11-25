from __future__ import annotations

from vtkmodules.vtkRenderingCore import vtkActor, vtkRenderer


class SceneManager:
    def __init__(self, renderer: vtkRenderer) -> None:
        self.renderer = renderer
        self.actors: dict[str, list[vtkActor]] = {}

    def add_object(self, object_id: str, actor: vtkActor | list[vtkActor]) -> None:
        self.remove_object(object_id)
        actors = actor if isinstance(actor, list) else [actor]
        for item in actors:
            self.renderer.AddActor(item)
        self.actors[object_id] = actors

    def remove_object(self, object_id: str) -> None:
        for actor in self.actors.pop(object_id, []):
            self.renderer.RemoveActor(actor)

    def set_visible(self, object_id: str, visible: bool) -> None:
        for actor in self.actors.get(object_id, []):
            actor.SetVisibility(int(visible))

    def actor(self, object_id: str) -> vtkActor | None:
        actors = self.actors.get(object_id, [])
        return actors[0] if actors else None

    def clear(self) -> None:
        for object_id in list(self.actors):
            self.remove_object(object_id)
