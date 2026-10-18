"""The composition root: swap layout, reusable components and icons in one place.

Factories receive keyword arguments. Replacement views keep the public commands,
signals and result methods documented in docs/UI架构与替换指南.md.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional
from .components import UiComponents


def _multi(**kwargs):
    from .workspaces.multi_cam_workspace import MultiCamWorkspace
    return MultiCamWorkspace(**kwargs)


def _mobile(**kwargs):
    from .workspaces.mobile_chain_workspace import MobileChainWorkspace
    return MobileChainWorkspace(**kwargs)


def _turntable(**kwargs):
    from .workspaces.turntable_workspace import TurntableWorkspace
    return TurntableWorkspace(**kwargs)


def _launcher(**kwargs):
    from .launcher_dialog import LauncherDialog
    return LauncherDialog(**kwargs)


def _shell(**kwargs):
    from .main_window import MainWindowShell
    return MainWindowShell(**kwargs)


@dataclass(frozen=True)
class WorkspaceFactories:
    multi: Callable = _multi
    mobile: Callable = _mobile
    turntable: Callable = _turntable


@dataclass(frozen=True)
class UiComposition:
    """One QApplication/presentation at a time; configure before creating widgets."""
    components: UiComponents = field(default_factory=UiComponents)
    workspaces: WorkspaceFactories = field(default_factory=WorkspaceFactories)
    launcher_factory: Callable = _launcher
    shell_factory: Callable = _shell
    stylesheet: Optional[str] = None
    icons: Optional[Callable] = None

    def configure(self, app):
        from .theme import GLOBAL_QSS
        from .icons import set_icon_provider
        set_icon_provider(self.icons)
        app.setStyleSheet(GLOBAL_QSS if self.stylesheet is None else self.stylesheet)

    def create_launcher(self, parent=None):
        return self.launcher_factory(parent=parent)

    def create_shell(self, parent=None):
        return self.shell_factory(parent=parent, components=self.components,
                                  workspace_factories=self.workspaces,
                                  launcher_factory=self.create_launcher)
