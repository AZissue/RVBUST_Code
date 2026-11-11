"""MCC Python stitching examples with a shared input manifest and output contract."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import open3d as o3d
from core.calibration_engine import CalibrationEngine
from core.chain_stitcher import ChainStitcher
from core.frame_data import FrameData
from core.marker_detector import MarkerDetector
from core.offline_pairs import FramePair, OfflinePairLoader
from core.point_cloud_processor import PointCloudProcessor
from core.postprocess.fpfh_registration import DEFAULTS, merge_chain, solve_chain, validate_transform
from core.postprocess.session import CloudLayer
from core.stitch_engine import StitchEngine


def stitch_fixed(frames, calibration):
    """Transform each camera from its local coordinates to the reference camera."""
    engine = CalibrationEngine()
    ok, message = engine.load_from_dict(calibration)
    if not ok:
        raise ValueError(message)
    reference = engine.reference_id
    if reference not in frames:
        raise ValueError('外参的参考相机必须参与拼接')
    poses = {name: validate_transform(engine.get_transform(name, reference)).tolist()
             for name in frames}
    # Filter invalid organized-cloud placeholders before applying the camera poses.
    class ValidFrame:
        def __init__(self, source):
            self.source = source

        def load_pointcloud_o3d(self):
            cloud = self.source.load_pointcloud_o3d()
            return PointCloudProcessor._filter_valid(cloud)[0]

    cloud, message = StitchEngine().stitch(
        {name: ValidFrame(frame) for name, frame in frames.items()}, engine, reference)
    return cloud, dict(reference=reference, transforms_to_reference=poses, message=message)


def stitch_markers(frames):
    """Use identified 3D markers to register successive captures."""
    engine = ChainStitcher(MarkerDetector(), CalibrationEngine(), StitchEngine())
    for name, frame in frames.items():
        ok, message, _ = engine.add_frame(frame, detect_markers=False)
        if not ok:
            raise ValueError(f'{name}：{message}')
    poses = {name: node.T_world.tolist()
             for name, node in zip(frames, engine.nodes.values())}
    return engine.get_merged_pointcloud(), dict(
        reference=next(iter(frames)), transforms_to_reference=poses,
        edges=[dict(rmse_mm=e.rms_mm, inlier_ratio=e.inlier_ratio,
                    common_markers=e.common_markers) for e in engine.edges])


def stitch_fpfh(clouds, overrides):
    """Register adjacent point clouds and compose poses to the first frame."""
    layers = [
        CloudLayer(name, np.asarray(cloud.points),
                   np.asarray(cloud.colors) if cloud.has_colors() else None,
                   origins=((name, 1),))
        for name, cloud in clouds.items()
    ]
    report = solve_chain(layers, {**DEFAULTS, **overrides}, progress=print)
    layer = merge_chain(layers, report)
    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(layer.points.copy()))
    if layer.colors is not None:
        cloud.colors = o3d.utility.Vector3dVector(layer.colors.copy())
    return cloud, report


def run(mode, manifest, output):
    """Write merged.ply and report.json to a new directory after successful stitching."""
    manifest, output = Path(manifest).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    data = json.loads(manifest.read_text(encoding='utf-8-sig'))
    if data['unit'] != 'mm':
        raise ValueError('输入点云、标记物坐标和矩阵平移必须使用毫米')
    frames = {}
    clouds = {}
    for entry in data['frames']:
        name = entry['id']
        if not isinstance(name, str) or not name or name in frames:
            raise ValueError('每帧需要唯一的非空字符串 ID')
        path = manifest.parent / entry['ply']
        cloud, _ = PointCloudProcessor._filter_valid(o3d.io.read_point_cloud(str(path)))
        if not len(cloud.points):
            raise ValueError(f'点云为空或无有效点：{path}')
        clouds[name] = cloud
        if mode == 'markers' and 'image' in entry:
            frame = OfflinePairLoader().load_pair(
                FramePair(name, str(manifest.parent / entry['image']), str(path)))
        else:
            frame = FrameData(len(frames), name, is_offline=True,
                              offline_pointmap_path=str(path), markers=entry.get('markers', []))
        frames[name] = frame
    if len(frames) < 2:
        raise ValueError('至少需要两帧')
    if mode == 'fixed':
        cloud, report = stitch_fixed(frames, data['calibration'])
    elif mode == 'markers':
        cloud, report = stitch_markers(frames)
    elif mode == 'fpfh':
        cloud, report = stitch_fpfh(clouds, data.get('fpfh', {}))
    else:
        raise ValueError(f'未知拼接方式：{mode}')
    if cloud is None or not len(cloud.points):
        raise ValueError('拼接结果为空')
    report.update(mode=mode, unit='mm', points=len(cloud.points), inputs=list(frames))
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as tmp:
        staged = Path(tmp) / 'result'
        staged.mkdir()
        if not o3d.io.write_point_cloud(str(staged / 'merged.ply'), cloud):
            raise OSError('拼接点云导出失败')
        (staged / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        staged.rename(output)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('fixed', 'markers', 'fpfh'))
    parser.add_argument('manifest', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        result = run(args.mode, args.manifest, args.output)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'拼接失败：{exc}\n')
    print(f"完成：{result['points']} 点，输出到 {args.output}")
