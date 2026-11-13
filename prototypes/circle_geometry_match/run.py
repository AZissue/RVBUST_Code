"""Standalone offline workspace for 普通圆点三角形匹配."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prototypes.offline_workspace import launch
from prototypes.circle_geometry_match.editor import CircleMatchEditor

def main():
    return launch(key='circle_geometry_match', title='普通圆点三角形匹配', mode=None, editor_type=CircleMatchEditor)


if __name__ == '__main__':
    raise SystemExit(main())
