"""Standalone offline workspace for 机器人手眼变换与戳点验证."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prototypes.offline_workspace import launch


def main():
    return launch(key='robot_handeye_transform', title='机器人手眼变换与戳点验证', mode='robot_stitch', editor_type=None)


if __name__ == '__main__':
    raise SystemExit(main())
