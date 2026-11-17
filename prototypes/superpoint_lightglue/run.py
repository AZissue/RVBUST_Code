"""Standalone SuperPoint + LightGlue experiment in the industrial workspace."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prototypes.offline_workspace import launch
from prototypes.superpoint_lightglue.editor import FeatureMatchEditor


def main():
    return launch(key='superpoint_lightglue', title='SuperPoint + LightGlue 无标记拼接',
                  mode=None, editor_type=FeatureMatchEditor)


if __name__ == '__main__':
    raise SystemExit(main())
