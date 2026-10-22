"""Temporary fixed-rig workflow. All geometry and exported translations are mm."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import sys
from itertools import combinations

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from core.frame_data import FrameData
from core.marker_detector import MarkerDetector
from core.calib_board_detector import DEFAULT_BOARD_SPECS
from core.calibration_engine import CalibrationEngine
from core.stitch_engine import StitchEngine
from core.utils import write_json_atomic, rvc_sdk_lock


def valid_markers(markers):
    result = []
    for m in markers:
        p = [m.get(k, float('nan')) for k in ('x_3d', 'y_3d', 'z_3d')]
        if m.get('valid_3d', True) and np.isfinite(p).all() and np.linalg.norm(p) > 1e-9:
            result.append(m)
    codes = [m['code'] for m in result]
    if len(codes) != len(set(codes)):
        raise ValueError('编码重复，请检查场景中是否存在同码标记')
    return result


def rigid_matrix(T):
    T = np.asarray(T, dtype=float)
    if (T.shape != (4, 4) or not np.isfinite(T).all()
            or not np.allclose(T[3], [0, 0, 0, 1], atol=1e-6)
            or not np.allclose(T[:3, :3].T @ T[:3, :3], np.eye(3), atol=1e-5)
            or not np.isclose(np.linalg.det(T[:3, :3]), 1, atol=1e-5)):
        raise ValueError('外参必须为有限的 4×4 刚体变换')
    return T


class Workflow:
    def __init__(self, output):
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.engine = CalibrationEngine()
        self.frames = {'calib': {}, 'scan': {}}
        self.frame_identities = {'calib': {}, 'scan': {}}
        self.detected = {}
        self.mode = None
        self.manager = None
        self.identities = {}
        self.calibration_identities = {}
        self.sequence = 0
        self.last_cloud = None

    def connect(self, indices):
        if len(indices) < 2 or len(set(indices)) != len(indices) or min(indices) < 0:
            raise ValueError('至少选择两台不同设备，索引不能为负数')
        self.disconnect()
        from core.camera_manager import CameraManager
        manager = CameraManager()
        ok, msg = manager.initialize()
        if not ok:
            raise RuntimeError(msg)
        try:
            ids = {}
            for index in indices:
                cid = f'cam{index}'
                manager.add_camera(cid)
                ids[cid] = index
            ok, msg = manager.connect_all(ids)
            if not ok:
                raise RuntimeError(msg)
            self.manager = manager
            self.identities = {cid: str(manager._cameras[cid].sn) for cid in ids}
            return '\n'.join(f'{cid}: SN {sn}' for cid, sn in self.identities.items())
        except Exception:
            manager.shutdown()
            raise

    def disconnect(self):
        if self.manager is not None:
            self.manager.shutdown()
        self.manager = None
        self.identities = {}

    def capture(self, kind):
        if self.manager is None:
            raise ValueError('请先连接相机，或使用离线文件入口')
        self.sequence += 1
        group = self.output / kind / f'{datetime.now():%Y%m%d_%H%M%S_%f}'
        frames = {}
        # Save and release each camera before triggering the next one.
        for cid in self.manager.get_connected_ids():
            frame = self.manager.capture(cid, frame_id=self.sequence)
            if frame is None:
                raise RuntimeError(f'{cid} 采集失败；本组未替换，已保存的原始帧位于 {group}')
            try:
                frame.kind = kind
                with rvc_sdk_lock:
                    folder = frame.save(str(group))
                ply = Path(folder) / 'pointmap.ply'
                image = Path(folder) / 'image.png'
                if not ply.is_file() or not ply.stat().st_size or not image.is_file():
                    raise RuntimeError(f'{cid} 原始帧保存失败')
                frames[cid] = FrameData.load(folder)
            finally:
                frame.release_rvc()
        if len(frames) < 2:
            raise ValueError('本组至少需要两台相机')
        self.frames[kind] = frames
        self.frame_identities[kind] = dict(self.identities)
        if kind == 'calib':
            self.detected = {}
        return f'{kind}: 已保存 {len(frames)} 路原始帧到 {group}'

    def load_pair(self, kind, cid, image_path, ply_path):
        if not cid or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in cid):
            raise ValueError('相机 ID 只能使用字母、数字、下划线和短横线')
        image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None or not Path(ply_path).is_file():
            raise ValueError('图像或 PLY 无效')
        frame = FrameData(0, cid, image_np=image, is_offline=True,
                          offline_image_path=str(Path(image_path).resolve()),
                          offline_pointmap_path=str(Path(ply_path).resolve()), kind=kind)
        self.frames[kind][cid] = frame
        self.frame_identities[kind].pop(cid, None)
        if kind == 'calib':
            self.detected = {}
        return f'{cid}: 已载入 {kind} 图像/点云（mm）'

    def detect(self, mode, specs, n=8, r1=2., r2=3.):
        if not self.frames['calib']:
            raise ValueError('请先采集或载入标定帧')
        if not (3 <= n <= 32 and 1 < r1 < r2):
            raise ValueError('编码圆要求 3≤N≤32，1<r1/r0<r2/r0')
        if not specs:
            raise ValueError('至少配置一种非对称圆板规格')
        names = set()
        for spec in specs:
            if (not isinstance(spec.get('cols'), int) or not isinstance(spec.get('rows'), int)
                    or min(spec['cols'], spec['rows']) < 2
                    or not np.isfinite(spec['spacing_mm']) or spec['spacing_mm'] <= 0
                    or not spec.get('name') or spec['name'] in names):
                raise ValueError('板规格名称须唯一，行列为≥2整数，间距为正数')
            names.add(spec['name'])
        detector = MarkerDetector(mode)
        detector.set_board_specs(specs)
        detector.set_params(n, r1, r2)
        self.detected = {}
        detected = {}
        self.mode = mode
        messages = []
        for cid, frame in self.frames['calib'].items():
            # Pixel correspondence is mandatory; do not accept filtered/unorganized clouds.
            cloud = frame.load_pointcloud_o3d()
            if cloud is None or len(cloud.points) != int(np.prod(frame.image_np.shape[:2])):
                raise ValueError(f'{cid}: PLY 必须保留全部像素（含无效点），点数须等于图像宽×高')
            markers = detector.detect_3d(frame.image_np,
                offline_ply_path=frame.offline_pointmap_path, include_invalid=True)
            board = detector.last_board_result
            frame.markers_all = markers
            frame.markers = valid_markers(markers)
            frame.board_pose = board['T_board_in_cam'] if board else None
            frame.board_pattern_name = board['pattern_name'] if board else None
            detected[cid] = {'markers': frame.markers, 'board': board}
            overlay = draw_overlay(frame.image_np, markers)
            cv2.imencode('.png', overlay)[1].tofile(str(self.output / f'detection_{cid}.png'))
            messages.append(f'{cid}: {frame.board_pattern_name or mode}，2D {len(markers)} / 有效3D {len(frame.markers)}')
        write_json_atomic(str(self.output / 'detection.json'), {
            'mode': mode, 'specs': specs, 'cameras': {
                cid: {'markers': f.markers_all, 'board_pattern': f.board_pattern_name}
                for cid, f in self.frames['calib'].items()}}, ensure_ascii=False, indent=2)
        self.detected = detected
        return '\n'.join(messages)

    def calibrate(self, reference, threshold=2., max_rms=2., min_ratio=.6):
        if reference not in self.detected or len(self.detected) < 2:
            raise ValueError('请先检测至少两路标定帧，并选择其中一台为参考')
        engine = CalibrationEngine()
        engine.set_reference(reference)
        messages = []
        # Pairwise edges support cameras that overlap through intermediate cameras.
        for a, b in combinations(self.detected, 2):
            da, db = self.detected[a], self.detected[b]
            if self.mode == 'asymmetric_grid':
                ba, bb = da['board'], db['board']
                if not ba or not bb or ba['pattern_size'] != bb['pattern_size']:
                    messages.append(f'{a}/{b}: 未检测到同规格圆板，跳过')
                    continue
            ma, mb = da['markers'], db['markers']
            codes, pa, pb = engine._match_markers(ma, mb)
            if len(codes) < 4 or np.linalg.matrix_rank(pa - pa.mean(0), tol=1e-6) < 2 or np.linalg.matrix_rank(pb - pb.mean(0), tol=1e-6) < 2:
                messages.append(f'{a}/{b}: 至少需要4个不共线同码有效点，跳过')
                continue
            result = engine.calibrate_pair(a, b, ma, mb, ransac_threshold=threshold, min_pairs=4)
            if (not result.get('success') or result['inlier_count'] < 4
                    or result['rms_mm'] > max_rms or result['inlier_ratio'] < min_ratio):
                engine.pair_results.pop((a, b), None)
                messages.append(f'{a}/{b}: 未通过 RMS/内点率门禁，{result.get("message", "请检查对应点")}')
            else:
                messages.append(f'{b}→{a}: RMS {result["rms_mm"]:.4f} mm，内点 {result["inlier_count"]}/{len(codes)}')
        for cid in self.detected:
            if cid != reference:
                try:
                    rigid_matrix(engine.get_transform(cid, reference))
                except Exception as exc:
                    raise ValueError('\n'.join(messages) + f'\n{cid} 无法连接到参考相机，外参未替换') from exc
        self.engine = engine
        self.calibration_identities = dict(self.frame_identities['calib'])
        self.last_cloud = None
        return '\n'.join(messages)

    def save(self, path):
        if not self.engine.pair_results:
            raise ValueError('尚无外参')
        data = self.engine.to_dict()
        data['quick_extrinsic'] = {'unit': 'mm', 'direction': 'cam_to_ref',
            'serial_numbers': self.calibration_identities, 'mode': self.mode}
        write_json_atomic(str(path), data, indent=2, ensure_ascii=False)
        return f'外参已保存: {path}'

    def load(self, path):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        metadata = data.get('quick_extrinsic', {})
        if metadata.get('unit') != 'mm' or metadata.get('direction') != 'cam_to_ref':
            raise ValueError('请载入本工具保存的 mm / cam_to_ref 外参文件')
        engine = CalibrationEngine()
        ok, message = engine.load_from_dict(data)
        if not ok or not engine.reference_id:
            raise ValueError(message)
        for pair in engine.pair_results.values():
            rigid_matrix(pair['T'])
        self.engine = engine
        self.calibration_identities = metadata.get('serial_numbers', {})
        self.mode = metadata.get('mode')
        self.last_cloud = None
        return f'已载入外参: {message}'

    def stitch(self, voxel=0.):
        import open3d as o3d
        frames = self.frames['scan']
        ref = self.engine.reference_id
        if len(frames) < 2 or ref not in frames or not self.engine.pair_results:
            raise ValueError('需要有效外参及含参考相机的至少两路扫描帧')
        calibrated_ids = {cid for pair in self.engine.pair_results for cid in pair}
        if set(frames) != calibrated_ids:
            raise ValueError(f'扫描相机集合与外参不一致：需要 {sorted(calibrated_ids)}，当前 {sorted(frames)}')
        if self.manager:
            if not self.calibration_identities:
                raise ValueError('载入的外参没有设备序列号，请用在线帧重新标定后再采集拼接')
            for cid in frames:
                if (self.identities.get(cid) != self.calibration_identities.get(cid)
                        or self.frame_identities['scan'].get(cid) != self.calibration_identities.get(cid)):
                    raise ValueError(f'{cid}: 设备序列号与外参不符，请重新标定')
        # Preflight prevents MCC's permissive skip behavior from hiding partial results.
        cleaned = {}
        folder = self.output / 'stitch_inputs' / f'{datetime.now():%Y%m%d_%H%M%S_%f}'
        folder.mkdir(parents=True)
        for cid, frame in frames.items():
            if cid != ref:
                rigid_matrix(self.engine.get_transform(cid, ref))
            pcd = frame.load_pointcloud_o3d()
            if pcd is None:
                raise ValueError(f'{cid}: 点云加载失败')
            pts = np.asarray(pcd.points)
            mask = np.isfinite(pts).all(1) & (np.linalg.norm(pts, axis=1) > 1e-9)
            pcd = pcd.select_by_index(np.flatnonzero(mask))
            if not len(pcd.points):
                raise ValueError(f'{cid}: 点云无有效点')
            path = folder / f'{cid}.ply'
            if not o3d.io.write_point_cloud(str(path), pcd):
                raise IOError(f'写入失败: {path}')
            cleaned[cid] = FrameData(0, cid, is_offline=True, offline_pointmap_path=str(path))
        merged, message = StitchEngine().stitch(cleaned, self.engine, ref, processor=None)
        if merged is None:
            raise ValueError(message)
        if voxel > 0:
            merged = merged.voxel_down_sample(voxel)
        path = self.output / f'merged_{datetime.now():%Y%m%d_%H%M%S_%f}.ply'
        if not o3d.io.write_point_cloud(str(path), merged):
            raise IOError('拼接结果保存失败')
        self.last_cloud = str(path)
        self.save(path.with_suffix('.extrinsics.json'))
        return f'{message}\n导出 {len(merged.points)} 点（mm）: {path}'

    def clear_frames(self):
        self.frames = {'calib': {}, 'scan': {}}
        self.frame_identities = {'calib': {}, 'scan': {}}
        self.detected = {}
        self.last_cloud = None
        return '已清空当前帧列表，保留外参与磁盘原始数据'


def draw_overlay(image, markers):
    canvas = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR) if image.ndim == 2 else image.copy()
    scale = max(1, round(max(canvas.shape[:2]) / 1200))
    for m in markers:
        x = int(round(m.get('x_2d', m.get('x', 0))))
        y = int(round(m.get('y_2d', m.get('y', 0))))
        color = (0, 210, 0) if valid_markers([m]) else (0, 0, 255)
        cv2.circle(canvas, (x, y), 7 * scale, color, 2 * scale)
        cv2.putText(canvas, str(m['code']), (x + 9 * scale, y - 8 * scale),
                    cv2.FONT_HERSHEY_SIMPLEX, .55 * scale, color, scale)
    return canvas
