"""Function entrance, mode separation, offline calibration and safe switching."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import numpy as np
HERE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(HERE.parents[1]/'src'),str(HERE.parent)]
from PySide6.QtWidgets import QApplication,QMessageBox,QDialog
from PySide6.QtGui import QImage,QFontDatabase
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from industrial_scan_ui.core.functions import default_registry
from industrial_scan_ui.app.studio import FunctionLauncher,StudioWindow
from industrial_scan_ui.app.workspaces import MultiCameraWorkbench,TurntableWorkbench,unique_markers


def markers(points):
    return [dict(code=i+1,x_2d=100+i*20,y_2d=100+i*10,x_3d=float(x),y_3d=float(y),z_3d=float(z),valid_3d=True)
            for i,(x,y,z) in enumerate(points)]


class StudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')

    def close_window(self, win):
        if hasattr(win,'workspace'):win.workspace._dirty=False
        else:win._dirty=False
        win.close();win.deleteLater();self.app.processEvents()

    def wait_job(self, win):
        deadline=time.monotonic()+15
        while win._busy:
            self.app.processEvents();time.sleep(.005)
            self.assertLess(time.monotonic(),deadline)

    def test_registry_extension_and_launcher_rules(self):
        registry=default_registry()
        custom=replace(registry.get('mobile_chain'),key='future',title='新增测试功能',
                       minimum_cameras=0,maximum_cameras=0,default_cameras=0)
        registry.register(custom)
        with self.assertRaises(ValueError):registry.register(custom)
        with self.assertRaises(ValueError):registry.create('multi_cam',camera_count=1)
        with self.assertRaises(ValueError):registry.get('missing')
        dialog=FunctionLauncher(registry)
        self.assertEqual(len(dialog.cards),4)
        self.assertEqual(dialog.camera_count.minimum(),2)
        dialog.select_function('turntable')
        self.assertEqual(dialog.camera_count.value(),1)
        self.assertFalse(dialog.camera_count.isEnabled())
        dialog.select_function('multi_cam')
        self.assertTrue(dialog.camera_count.isEnabled())
        dialog.camera_count.setValue(6)
        dialog.enter_button.click()
        self.assertEqual(dialog.result(),QDialog.Accepted)
        dialog.select_function('future')
        self.assertEqual(dialog.camera_count.value(),0)
        self.assertIn('无需相机',dialog.rule.text())
        workspace=registry.create('future',renderer='software',load_demo=False)
        self.assertEqual(workspace.camera_count,0)
        self.close_window(workspace)
        dialog.deleteLater()

    def test_switch_modes_cancel_busy_and_factory_failure_preserve_current(self):
        registry=default_registry()
        shell=StudioWindow(registry,'mobile_chain',renderer='software',load_demo=False)
        try:
            old=shell.workspace;old._dirty=True
            with patch('industrial_scan_ui.app.window.QMessageBox.question',return_value=QMessageBox.No):
                self.assertFalse(shell.switch_to('turntable'))
            self.assertIs(shell.workspace,old)
            old._dirty=False;old._busy=True
            self.assertFalse(shell.switch_to('turntable'));old._busy=False
            def broken(**kwargs):raise RuntimeError('fixture factory')
            registry.register(replace(registry.get('mobile_chain'),key='broken',factory=broken))
            with patch('industrial_scan_ui.app.studio.QMessageBox.warning'):
                self.assertFalse(shell.switch_to('broken'))
            self.assertIs(shell.workspace,old)
            self.assertTrue(shell.switch_to('turntable'))
            self.assertIsInstance(shell.workspace,TurntableWorkbench)
            self.assertTrue(shell.switch_to('multi_cam',camera_count=2))
            self.assertIsInstance(shell.workspace,MultiCameraWorkbench)
            self.assertEqual(len(shell.workspace.camera_grid.camera_ids()),2)
            self.assertFalse(shell.workspace.marker_inspector.isVisible())
        finally:self.close_window(shell)

    def test_multicam_2d_grid_and_real_offline_extrinsics(self):
        win=MultiCameraWorkbench(camera_count=2,renderer='software',load_demo=False)
        try:
            image=QImage(640,480,QImage.Format_RGB32);image.fill(0x808080)
            points=np.random.default_rng(42).normal(size=(8,3))*30+[0,0,500]
            shift=np.array([12.,-3.,2.])
            first,second=markers(points),markers(points-shift)
            win.set_camera_observation('cam1',image,first)
            self.assertEqual(win.steps.get_current(),0)
            win.set_camera_observation('cam2',image,second)
            self.assertEqual(win.steps.get_current(),1)
            self.assertTrue(win.solve_button.isEnabled())
            win.start_scan();self.wait_job(win)
            self.assertTrue(win.extrinsics['cam2']['success'])
            np.testing.assert_allclose(win.extrinsics['cam2']['T'][:3,3],shift,atol=1e-8)
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'外参.json';win.save_extrinsics(path)
                saved=json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(saved['direction'],'camera_to_reference')
                self.assertEqual(saved['units'],'mm')
            win.reference.setCurrentText('cam2')
            self.assertFalse(win.extrinsics)
            self.assertFalse(win.save_extrinsics_button.isEnabled())
            line=np.array([[i,0,500] for i in range(8)],dtype=float)
            win.set_camera_observation('cam1',image,markers(line))
            win.set_camera_observation('cam2',image,markers(line-shift))
            win.start_scan();self.wait_job(win)
            self.assertFalse(win.extrinsics['cam1']['success'])
            self.assertFalse(win.save_extrinsics_button.isEnabled())
            self.assertNotIn('core.camera_manager',sys.modules)
            self.assertNotIn('core.marker_detector',sys.modules)
        finally:self.close_window(win)

    def test_four_camera_overview_fits_two_rows(self):
        win=MultiCameraWorkbench(camera_count=4,renderer='software',load_demo=False)
        try:
            win.resize(1600,1000);win.show();self.app.processEvents()
            grid=win.camera_grid
            self.assertEqual(grid._last_cols,2)
            self.assertLessEqual(grid.card('cam4').geometry().bottom(),grid.viewport().height())
            self.assertFalse(grid.card('cam4')._btn_capture.isVisible())
        finally:self.close_window(win)

    def test_turntable_calibration_gate_result_and_invalidation(self):
        win=TurntableWorkbench(renderer='software',load_demo=False)
        try:
            self.assertFalse(win.scan_button.isEnabled())
            self.assertFalse(win.calibrate_button.isEnabled())
            angle=np.deg2rad(30);rotation=np.array([[np.cos(angle),-np.sin(angle),0],[np.sin(angle),np.cos(angle),0],[0,0,1]])
            points=np.array([[40,0,500],[0,30,500],[-40,0,500],[0,-30,500],[20,20,510]],dtype=float)
            win.set_calibration_frame(0,None,markers(points))
            win.set_calibration_frame(1,None,markers(points@rotation.T))
            self.assertTrue(win.calibrate_button.isEnabled())
            win.calibrate_turntable()
            self.assertAlmostEqual(win.calibration_result['angle_deg'],30,places=5)
            self.assertEqual(win.calibration_result['step_count'],12)
            self.assertTrue(win.scan_button.isEnabled())
            self.assertEqual(win.marker_inspector.display.red_count,5)
            win.set_calibration_frame(1,None,markers(points@rotation.T))
            self.assertIsNone(win.calibration)
            self.assertFalse(win.scan_button.isEnabled())
            invalid=markers(points);invalid[0]['valid_3d']=False;invalid.append(dict(invalid[1]))
            self.assertEqual(len(unique_markers(invalid)),3)
            win.clear_calibration();self.assertFalse(win.calibration_frames)
        finally:self.close_window(win)


if __name__=='__main__':unittest.main(verbosity=2)
