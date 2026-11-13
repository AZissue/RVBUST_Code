"""Standalone offline workspace for FPFH 几何匹配."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prototypes.offline_workspace import launch
from ui_v2.postprocess.fpfh_editor import FPFHEditor

def main():
    return launch(key='fpfh_geometry_match', title='FPFH 几何匹配', mode=None, editor_type=FPFHEditor)


if __name__ == '__main__':
    raise SystemExit(main())
