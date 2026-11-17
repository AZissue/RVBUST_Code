"""Offscreen UI smoke test; direct unittest-style script, no camera hardware."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import tempfile
import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parents[1] / 'src'))
sys.path.insert(0, str(HERE.parent))


def main():
    from PySide6.QtWidgets import QApplication
    from industrial_pointcloud_postprocess.app.window import PostProcessWorkbench
    from industrial_pointcloud_postprocess.core.processing import ortho_project, point_in_polygon
    from industrial_pointcloud_postprocess.core.session import read_cloud, write_cloud
    app = QApplication.instance() or QApplication([])
    win = PostProcessWorkbench(load_demo=True)
    win.resize(1440, 900)
    win.show()
    app.processEvents()

    layer = win.session.layers[0]
    total = len(layer.points)
    assert total > 0, 'demo layer empty'
    print(f'[OK] demo layer loaded: {total:,} points, backend={win.canvas.backend_name}')

    canvas = win.canvas
    params = dict(center=canvas.center.copy(), rotation_matrix=canvas.rotation.matrix.copy(),
                  extent=canvas.extent, zoom=canvas.zoom, pan=canvas.pan.copy(),
                  width=canvas.width(), height=canvas.height())
    xy, _ = ortho_project(layer.points, **params)
    xmin, xmax = xy[:, 0].min(), xy[:, 0].max()
    ymin, ymax = xy[:, 1].min(), xy[:, 1].max()
    mid = (xmin + xmax) / 2
    polygon = [(xmin - 5, ymin - 5), (mid, ymin - 5), (mid, ymax + 5), (xmin - 5, ymax + 5)]
    inside = int(point_in_polygon(xy, np.asarray(polygon)).sum())
    outside = total - inside
    assert 0 < inside < total, 'polygon does not split the cloud'

    win._actions['select'].setChecked(True)
    assert win.overlay.active, 'selection overlay not active'
    win.overlay._vertices = list(polygon)
    win.overlay._confirm()
    app.processEvents()
    assert win._segment is not None and win.overlay.has_mask, 'polygon not staged'
    assert f'框内 {inside:,}' in win.seg_state.text() and f'框外 {outside:,}' in win.seg_state.text()
    print(f'[OK] polygon staged: {len(polygon)} vertices, inside {inside:,} / outside {outside:,}')

    win._apply_segment(True)
    assert win._segment is None and not win.overlay.active, 'staged mask not cleared'
    assert len(win.session.layers) == 2, 'segment branch not appended'
    kept, branch = win.session.layers
    assert len(kept.points) == inside and kept.name == '演示点云 01', 'kept layer wrong'
    assert len(branch.points) == outside, 'branch point count wrong'
    assert branch.name == '演示点云 01 · 分割(框外)' and '多边形分割' in branch.source
    assert inside + outside == total, 'point conservation broken'
    print(f'[OK] segment in: kept {inside:,}, branch {outside:,}, total conserved')

    win.undo()
    assert len(win.session.layers) == 1 and len(win.session.layers[0].points) == total, 'undo split failed'
    print('[OK] undo restored pre-segment state (kept layer and branch both rolled back)')

    result = win.apply_polygon_split(0, polygon, False)
    assert result == (outside, inside), 'segment out counts wrong'
    assert len(win.session.layers[0].points) == outside
    assert win.session.layers[1].name == '演示点云 01 · 分割(框内)'
    win.undo()
    assert len(win.session.layers) == 1 and len(win.session.layers[0].points) == total
    print(f'[OK] segment out: kept {outside:,}, branch {inside:,}, undo restored')

    win.apply_polygon_split(0, polygon, True)
    assert len(win.session.layers) == 2
    assert win.remove_layer_indices([1]), 'branch removal rejected'
    assert len(win.session.layers) == 1 and len(win.session.removed) == 1
    assert win.restore_last_removal(), 'branch restore rejected'
    assert len(win.session.layers) == 2
    assert win.session.layers[1].name == '演示点云 01 · 分割(框外)'
    assert not win.session.removed
    win.undo()
    assert len(win.session.layers) == 1 and len(win.session.layers[0].points) == total
    print('[OK] segment branch: recycle-bin remove/restore works like any layer')

    extra = np.array([[1., 2., 3.], [4., 5., 6.], [7., 8., 9.]])
    win.load_layer_from_arrays('附加 A', extra)
    win.load_layer_from_arrays('附加 B', extra * 2)
    merged_count = win.merge_layers([1, 2])
    assert merged_count == 6, 'merged point count wrong'
    assert len(win.session.layers) == 2 and win.session.layers[1].name == '合并点云 (2 层)'
    assert '附加 A' in win.session.layers[1].source and '附加 B' in win.session.layers[1].source
    win.undo()
    assert [item.name for item in win.session.layers] == ['演示点云 01', '附加 A', '附加 B'], \
        'merge undo did not restore original layers'
    print('[OK] merge: 2 layers -> 6 points at first index, undo restored originals')

    win._actions['select'].setChecked(True)
    assert win.overlay.active
    win.overlay._vertices = [(10., 10.), (20., 20.), (30., 30.)]
    win.overlay.remove_last_vertex()
    assert win.overlay.vertex_count == 2, 'Alt+left vertex removal failed'
    win._discard_segment()
    assert not win.overlay.active and win._segment is None
    print('[OK] Alt+left click removes the last vertex; discard clears overlay')

    before_layers = len(win.session.layers)
    before_points = len(win.session.layers[0].points)
    undo_depth = len(win.session._undo)
    far = [(-10000., -10000.), (-9000., -10000.), (-9000., -9000.), (-10000., -9000.)]
    assert win.apply_polygon_split(0, far, True) is None, 'empty kept part should be rejected'
    assert len(win.session.layers) == before_layers
    assert len(win.session.layers[0].points) == before_points
    assert len(win.session._undo) == undo_depth, 'rejected split polluted the undo stack'
    print('[OK] empty kept part rejected without touching data or undo stack')

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'merged.ply'
        count = write_cloud(path, win.session.layers)
        back = read_cloud(path)
        expected = sum(len(item.points) for item in win.session.layers if item.visible)
        assert count == expected and len(back.points) == expected, 'PLY roundtrip mismatch'
    print(f'[OK] PLY export/read roundtrip: {expected:,} points')

    win.shutdown()
    win.close()
    app.processEvents()
    print('[OK] ui smoke test passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
