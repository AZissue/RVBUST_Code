"""Standalone offline workspace for 固定多相机外参与拼接."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prototypes.offline_workspace import launch


def main():
    return launch(key='fixed_multi_camera', title='固定多相机外参与拼接', mode='multi_cam', editor_type=None)


if __name__ == '__main__':
    raise SystemExit(main())
