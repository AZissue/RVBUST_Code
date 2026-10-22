"""Shared widget chrome settings, independent of any application theme."""
from dataclasses import dataclass


@dataclass(frozen=True)
class LoadingAppearance:
    background: str = '#27272B'
    border: str = '#4A4A50'
    accent: str = '#D32F2F'
    ring: str = '#404047'
    text: str = '#E8EAED'
    muted: str = '#9AA0A8'
    scrim: str = 'rgba(35,35,35,235)'
    card_width: int = 380


@dataclass(frozen=True)
class ImagePreviewAppearance:
    background: str = "#1A1A20"
    border: str = "#2A2A34"
    empty_color: str = "#5a5a5a"
    valid_color: str = "#00e650"
    invalid_color: str = "#ff3c3c"
    board_color: str = "#3ca0ff"
    marker_radius: int = 5


@dataclass(frozen=True)
class ViewerAppearance:
    canvas_background: str = "#1a1a1a"
    border: str = "#3a3a3a"
    toolbar_background: str = "#252525"
    text: str = "#cccccc"
    muted: str = "#888888"
    accent: str = "#2979FF"
    selection_background: str = "#1E3A5F"
    hover_background: str = "#3a3a3a"
