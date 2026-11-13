"""Standalone offline workspace for 颜色后处理."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prototypes.offline_workspace import launch
from prototypes.color_postprocess.editor import ColorValidationWindow

def main():
    return launch(key='color_postprocess', title='颜色后处理', mode=None, editor_type=ColorValidationWindow)


if __name__ == '__main__':
    raise SystemExit(main())
