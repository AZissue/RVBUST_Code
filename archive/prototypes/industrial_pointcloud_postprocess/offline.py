"""Standalone offline workspace for 几何后处理."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prototypes.offline_workspace import launch
from ui_v2.postprocess.window import PostprocessWindow

def main():
    return launch(key='industrial_pointcloud_postprocess', title='几何后处理', mode=None, editor_type=PostprocessWindow)


if __name__ == '__main__':
    raise SystemExit(main())
