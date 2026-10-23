"""Independent detector instances and portable per-frame recognition results."""
import copy
import hashlib
import json
import numpy as np
from .marker_detector import MarkerDetector


def configuration(source, marker_type):
    coded = source._coded_marker_type
    return dict(algorithm=1, marker_type=marker_type,
        circle=[getattr(coded, 'N', 8), getattr(coded, 'r1_to_r0_ratio', 2.),
                getattr(coded, 'r2_to_r0_ratio', 3.)],
        boards=copy.deepcopy(source.get_board_specs()), gamma=source._board_detector.gamma)


def fingerprint(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def detect(frame, config):
    # No shared last_board_result, mutable SDK marker type, or capture handles.
    detector = MarkerDetector(config['marker_type'])
    detector.save_debug_images = False
    detector.raise_errors = True
    detector.set_params(*config['circle'])
    detector.set_board_specs(config['boards'])
    detector.set_board_gamma(config['gamma'])
    markers = detector.detect_3d(frame.image_np, offline_ply_path=frame.offline_pointmap_path,
                                 include_invalid=True)
    board = detector.last_board_result
    return dict(state='done', key=fingerprint(config), marker_type=config['marker_type'],
        markers=markers, board_pose=board['T_board_in_cam'].tolist() if board else None,
        board_pattern=list(board['pattern_size']) if board else None,
        board_pattern_name=board['pattern_name'] if board else None,
        board_rms_mm=board['rms_mm'] if board else 0.)


def apply(frame, result):
    frame.recognition_key = result.get('key') if result.get('state') == 'done' else None
    frame.markers_all = copy.deepcopy(result.get('markers', []))
    frame.markers = [row for row in frame.markers_all if row.get('valid_3d', True)]
    frame.board_pose = np.asarray(result['board_pose'], dtype=float) if result.get('board_pose') is not None else None
    frame.board_pattern = tuple(result['board_pattern']) if result.get('board_pattern') else None
    frame.board_pattern_name = result.get('board_pattern_name')
    frame.board_rms_mm = result.get('board_rms_mm', 0.)
