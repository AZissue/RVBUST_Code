"""Isolate large Open3D operations from the GUI interpreter's GIL.

Input paths are read-only; the child can write only its private temporary result.
DB publication remains owned by the parent controller.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def run_job(paths, calibration, markers, steps, voxel=None, refine=False, *, planes=None):
    import open3d as o3d
    with tempfile.TemporaryDirectory(prefix='MCC_turntable_stitch_') as folder:
        root = Path(folder)
        request = dict(paths=list(map(str, paths)), calibration=calibration, markers=markers,
                       steps=steps, voxel=voxel, refine=refine, planes=planes)
        (root/'request.json').write_text(json.dumps(request), encoding='utf-8')
        env = os.environ.copy()
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
        env['OMP_NUM_THREADS'] = '2'
        env['OPENBLAS_NUM_THREADS'] = '1'
        completed = subprocess.run([sys.executable, '-m', 'core.turntable_stitch_job', str(root)],
            env=env, capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if completed.returncode:
            raise RuntimeError('独立拼接进程失败：' + completed.stderr[-1500:])
        metadata = json.loads((root/'result.json').read_text(encoding='utf-8'))
        cloud = o3d.io.read_point_cloud(str(root/'result.ply'))
        if not len(cloud.points):
            raise RuntimeError('独立拼接结果为空')
        return cloud, metadata


def child(root):
    import open3d as o3d
    from .marker_plane import filter_source_cloud
    from .point_cloud_processor import PointCloudProcessor
    from .turntable_calibrator import TurntableCalibrator
    root = Path(root)
    request = json.loads((root/'request.json').read_text(encoding='utf-8'))
    clouds, counts = [], []
    planes = request.get('planes')
    if planes is not None and len(planes) != len(request['paths']):
        raise ValueError('标记物平面与转台帧数不一致')
    for index, path in enumerate(request['paths']):
        cloud = o3d.io.read_point_cloud(path)
        if planes is None:
            cloud, _ = PointCloudProcessor._filter_valid(cloud)
            valid = len(cloud.points)
        else:
            try:
                cloud, valid = filter_source_cloud(cloud, planes[index])
            except ValueError as exc:
                raise ValueError(f'转台帧 {index + 1:03d}：{exc}') from exc
        if not len(cloud.points):
            raise ValueError('输入帧无有效点：' + path)
        clouds.append(cloud)
        counts.append(valid)
    calib = TurntableCalibrator()
    calib.set_calibration(**request['calibration'])
    merged, message = calib.stitch_pointclouds(clouds, downsample_voxel=request['voxel'],
        icp_refine=request['refine'], markers=request['markers'], step_indices=request['steps'])
    if merged is None:
        raise ValueError(message)
    if not o3d.io.write_point_cloud(str(root/'result.ply'), merged):
        raise IOError('独立拼接结果保存失败')
    if planes is not None:
        message = f'标记物平面过滤：{sum(counts):,} → {sum(len(p.points) for p in clouds):,} 点，' + message
    (root/'result.json').write_text(json.dumps(dict(message=message, counts=counts,
        transforms=[t.tolist() if t is not None else None for t in calib.last_stitch_transforms])), encoding='utf-8')


if __name__ == '__main__':
    child(sys.argv[1])
