"""Marker display semantics, independent from the renderer and detector.

Green: unique 2D detection with valid measured XYZ, not selected for this pair.
Red overrides green: valid unique code in BOTH explicit frames, optionally
restricted to solver inliers. Yellow: detected in 2D but no usable depth.
"""
from collections import Counter
from dataclasses import dataclass
import math

GREEN = '#4ee887'
RED = '#ff5c63'
YELLOW = '#f1c86a'


def code_key(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value) if str(value).strip().lstrip('-').isdigit() else str(value)
    except (TypeError, ValueError):
        return None


def finite_values(marker, names):
    try:
        values = tuple(float(marker[name]) for name in names)
        return values if all(math.isfinite(v) for v in values) else None
    except (KeyError, TypeError, ValueError):
        return None


def position_2d(marker):
    return finite_values(marker, ('x_2d', 'y_2d')) or finite_values(marker, ('x', 'y'))


def valid_xyz(marker):
    if marker.get('valid_3d') is False:
        return None
    xyz = finite_values(marker, ('x_3d', 'y_3d', 'z_3d'))
    # Camera XYZ=(0,0,0) is an invalid SDK point. World origin may be valid.
    return xyz if xyz is not None and any(abs(v) > 1e-12 for v in xyz) else None


@dataclass(frozen=True)
class DisplayMarker:
    marker: dict
    code: object
    xy: tuple
    xyz: object
    color: str
    status: str


@dataclass(frozen=True)
class MarkerDisplay:
    rows: tuple
    red_codes: frozenset
    paired_codes: frozenset
    has_solver_result: bool

    @property
    def green_count(self):
        return sum(row.color == GREEN for row in self.rows)

    @property
    def red_count(self):
        return sum(row.color == RED for row in self.rows)

    @property
    def yellow_count(self):
        return sum(row.color == YELLOW for row in self.rows)


def classify_markers(markers, reference_markers=None, *, used_codes=None,
                     rejected_codes=(), registration_accepted=None):
    current = [(dict(m), code_key(m.get('code')), position_2d(m), valid_xyz(m)) for m in markers]
    reference = [(code_key(m.get('code')), position_2d(m), valid_xyz(m)) for m in (reference_markers or ())]
    counts = Counter(code for _, code, xy, _ in current if xy is not None and code is not None)
    ref_counts = Counter(code for code, xy, _ in reference if xy is not None and code is not None)
    available = {code for _, code, xy, xyz in current if xy is not None and xyz is not None
                 and code is not None and counts[code] == 1}
    ref_available = {code for code, xy, xyz in reference if xy is not None and xyz is not None
                     and code is not None and ref_counts[code] == 1}
    paired = available & ref_available
    red = paired - {code_key(code) for code in rejected_codes}
    if used_codes is not None:
        red &= {code_key(code) for code in used_codes}
    if registration_accepted is False:
        red.clear()
    rows = []
    for marker, code, xy, xyz in current:
        if xy is None:
            continue
        if xyz is None:
            color, status = YELLOW, '仅2D · 无有效3D'
        elif code in red:
            color, status = RED, '共有 · 配准内点' if used_codes is not None else '共有 · 可配对'
        else:
            color, status = GREEN, '3D有效'
            if code is None or counts[code] > 1:
                status += ' · ID不唯一'
            elif code in paired:
                status += ' · 未参与本次配准'
        rows.append(DisplayMarker(marker, code, xy, xyz, color, status))
    return MarkerDisplay(tuple(rows), frozenset(red), frozenset(paired), used_codes is not None)


def cumulative_world_markers(display, history, current_visible=True):
    """Keep historical valid points green, draw current red pair points last.

    Deduplicate by marker code, prefer the newest measured position. Only an
    explicit world coordinate is projected; raw camera XYZ is never guessed.
    """
    points = {}
    for markers in [*history, [row.marker for row in display.rows] if current_visible else []]:
        for marker in markers:
            if position_2d(marker) is None or valid_xyz(marker) is None:
                continue
            try:
                xyz = tuple(float(v) for v in marker['world'])
            except (KeyError, TypeError, ValueError):
                continue
            code = code_key(marker.get('code'))
            if code is not None and len(xyz) == 3 and all(math.isfinite(v) for v in xyz):
                points[code] = (xyz, RED if code in display.red_codes else GREEN)
    return sorted(points.items(), key=lambda item: item[1][1] == RED)
