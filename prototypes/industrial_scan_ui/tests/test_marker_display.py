"""Detection truth, pair filtering and workbench association regressions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import unittest
import numpy as np
HERE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(HERE.parents[1]/'src'),str(HERE.parent)]
from industrial_scan_ui.core.marker_display import classify_markers, cumulative_world_markers, GREEN, RED, YELLOW
from industrial_scan_ui.core.session import CloudLayer, crop_background
from industrial_scan_ui.app.window import ScanWorkbench
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication


def marker(code, **overrides):
    result=dict(code=code,x_2d=10,y_2d=20,x_3d=1,y_3d=2,z_3d=30,valid_3d=True,world=[code,2,3])
    result.update(overrides)
    return result


class MarkerTests(unittest.TestCase):
    def test_first_frame_and_real_pair(self):
        current=[marker(i) for i in range(5)]
        self.assertEqual(classify_markers(current).green_count,5)
        result=classify_markers(current,[marker(1),marker(2,valid_3d=False)])
        self.assertEqual([row.color for row in result.rows],[GREEN,RED,GREEN,GREEN,GREEN])

    def test_no_depth_never_red_and_counts_disjoint(self):
        current=[marker(1,valid_3d=False),marker(2,z_3d=float('nan')),marker(3,x_3d=0,y_3d=0,z_3d=0),marker(4)]
        result=classify_markers(current,current)
        self.assertEqual((result.green_count,result.red_count,result.yellow_count),(0,1,3))
        missing=marker(5);del missing['z_3d']
        self.assertEqual(classify_markers([missing]).rows[0].color,YELLOW)

    def test_solver_outliers_failure_and_duplicate_ids(self):
        current=[marker(1),marker(2),marker(3),marker(3)]
        reference=[marker(1),marker(2),marker(3)]
        result=classify_markers(current,reference,used_codes=[1,2],rejected_codes=[2])
        self.assertEqual(result.red_codes,{1})
        self.assertEqual(result.green_count,3)
        self.assertFalse(classify_markers(current,reference,registration_accepted=False).red_codes)
        self.assertFalse(classify_markers([marker(1)],[marker(1),marker(1)]).red_codes)

    def test_cumulative_world_and_no_forced_green_ratio(self):
        current=[marker(1),marker(2)]
        result=classify_markers(current,current)
        self.assertEqual(result.green_count,0)
        points=cumulative_world_markers(result,[[marker(1),marker(3)]])
        self.assertEqual({code:entry[1] for code,entry in points},{3:GREEN,1:RED,2:RED})
        no_world=marker(4);del no_world['world']
        self.assertEqual(cumulative_world_markers(classify_markers([no_world]),[]),[])

    def test_workbench_selection_image_clear_and_crop_preserves_observation(self):
        app=QApplication.instance() or QApplication([])
        win=ScanWorkbench(load_demo=False,renderer='software')
        win.session.layers=[CloudLayer('first',np.array([[0,0,10],[0,0,20]])),CloudLayer('second',np.array([[0,0,10]]))]
        win._refresh(select=0)
        image=QImage(100,100,QImage.Format_RGB32);image.fill(0)
        win.set_frame_observation(1,image,[marker(1)],layer_index=0)
        self.assertEqual(win.marker_inspector.display.green_count,1)
        self.assertFalse(win.marker_inspector.image_view.image.isNull())
        self.assertIs(crop_background(win.session.layers[0],15).observation,win.session.layers[0].observation)
        win._refresh(select=1)
        self.assertFalse(win.marker_inspector.display.rows)
        self.assertTrue(win.marker_inspector.image_view.image.isNull())
        win.set_frame_observation(2,image,[marker(1)],reference_id=1)
        self.assertEqual(win.marker_inspector.display.red_count,1)
        win.session.layers[0].visible=False
        win.session.layers[1].visible=False
        win._show_frame_observation()
        self.assertEqual(win.marker_inspector.display.red_count,1)
        self.assertFalse(win.marker_inspector.world_overlay.points)
        win._dirty=False;win.close();win.deleteLater();app.processEvents()


if __name__=='__main__':unittest.main(verbosity=2)
