"""Stage the customer Python kit from the current production source."""
import argparse
from pathlib import Path
import shutil

from make_demo import generate

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CORE_MODULES = (
    '__init__', 'calib_board_detector', 'calibration_engine', 'camera_manager',
    'capture_parameters', 'chain_stitcher', 'device_status', 'frame_data',
    'marker_detector', 'offline_pairs', 'pcd_utils', 'point_cloud_processor',
    'pose_graph', 'stitch_engine', 'utils', 'postprocess/__init__',
    'postprocess/fpfh_registration', 'postprocess/session',
)


def stage(target):
    target = Path(target)
    target.mkdir(parents=True, exist_ok=False)
    for filename in ('stitch.py', 'capture_rvc.py', 'make_demo.py', 'requirements.txt', 'README.md'):
        shutil.copy2(HERE / filename, target / filename)
    for module in CORE_MODULES:
        file = Path('core') / (module + '.py')
        destination = target / file
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / 'src' / file, destination)
    generate(target / 'demo')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', type=Path)
    stage(parser.parse_args().target)
