"""Capture one RVC frame as an organized PNG/PLY pair for MCC."""
import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from core.camera_manager import CameraManager
from core.utils import rvc_sdk_lock


def capture(serial, output):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    cameras = CameraManager()
    ok, message = cameras.initialize()
    if not ok:
        raise RuntimeError(message)
    frame = None
    try:
        cameras.add_camera('cam0')
        ok, message = cameras.connect('cam0', 0, expected_sn=serial)
        if not ok:
            raise RuntimeError(message)
        frame = cameras.capture('cam0')
        if frame is None or frame.pointcloud_aligned is False:
            raise RuntimeError('采集失败或点云未与2D对齐。请检查相机设置。')
        with TemporaryDirectory(dir=output.parent) as temporary:
            staging = Path(temporary) / 'frame'
            with rvc_sdk_lock:
                frame.save(temporary, frame_dir=str(staging))
            if not all((staging / name).is_file() for name in ('cam0.png', 'cam0.ply')):
                raise OSError('未生成完整图像/点云文件对')
            staging.rename(output)
    finally:
        try:
            if frame is not None:
                frame.release_rvc()
        finally:
            cameras.shutdown()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        capture(args.serial, args.output)
    except (RuntimeError, OSError) as exc:
        parser.exit(1, f'采集失败：{exc}\n')
    print(args.output.resolve())
