"""ROI threshold boundary, UI preview, immutable DB and transactional regression."""
import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
import test_postprocess as fixture
from core.postprocess.color_filter import color_values, threshold_rejection, preview_data
from core.postprocess.session import CloudLayer
from ui_v2.postprocess.color_filter_dialog import ColorFilterDialog

class ThresholdTests(unittest.TestCase):
    def test_threshold_inclusive_and_outside_untouched(self):
        rgb=np.repeat((np.array([0,39,40,200,201,255])/255)[:,None],3,axis=1)
        roi=np.array([False,True,True,True,True,False])
        np.testing.assert_array_equal(threshold_rejection(rgb,roi,40,200),[False,True,False,False,True,False])
        np.testing.assert_array_equal(color_values([[1,1,0],[.1,.1,.1]]),[255,26])
        np.testing.assert_array_equal(color_values([[1,0,0]],'green'),[0])
        self.assertEqual(color_values([[1,0,0]],'gray')[0],76)
        for params in (dict(low=256),dict(low=80,high=20),dict(low=1.5),dict(metric='bad')):
            with self.assertRaises(ValueError): threshold_rejection(rgb,roi,**params)
        with self.assertRaises(ValueError): threshold_rejection(rgb,roi[:2])
        with self.assertRaises(ValueError): threshold_rejection([[np.nan,0,0]],np.array([True]))

    def test_full_roi_empty_result_and_bounded_preview(self):
        points=np.column_stack((np.arange(20000),np.ones(20000),np.ones(20000)))
        colors=np.zeros((20000,3));colors[10000:]=[1,1,0]
        layer=CloudLayer('test',points,colors)
        view=dict(center=np.zeros(3),rotation_matrix=np.eye(3))
        data=preview_data(layer,np.ones(20000,bool),view)
        self.assertEqual(len(data['points']),12000)
        self.assertEqual(data['histograms']['value'][0],10000)
        self.assertEqual(data['histograms']['value'][255],10000)
        self.assertEqual(int(threshold_rejection(colors,np.ones(20000,bool),40).sum()),10000)
        with self.assertRaises(ValueError): preview_data(layer,np.zeros(20000,bool),view)
        with self.assertRaises(ValueError): preview_data(CloudLayer('no rgb',points),np.ones(20000,bool),view)

class FilterUiTests(unittest.TestCase):
    setUpClass=classmethod(fixture.PostprocessTests.setUpClass.__func__)
    wait=fixture.PostprocessTests.wait
    source=fixture.PostprocessTests.source
    finish=fixture.PostprocessTests.finish
    tearDown=fixture.PostprocessTests.tearDown

    def setUp(self):
        fixture.PostprocessTests.setUp(self)
        self.editor.close()
        from prototypes.industrial_pointcloud_postprocess.color_validation import ColorValidationWindow
        self.editor=ColorValidationWindow(self.bridge,self.bridge._current_mode)
        self.editor.show()
        self.app.processEvents()

    def inputs(self, colored=True):
        raw=self.db.ingest(self.source())
        points=np.array([[x,y,1] for x in range(10) for y in range(10)],float)
        colors=np.tile([.8,.7,.1],(100,1))
        colors[:20]=0
        colors[80:]=0
        result=self.db.publish_result(fixture.cloud(points,colors if colored else None),[raw])
        self.editor.source_browser.refresh()
        self.editor.load_selected([result]);self.finish()
        layer=self.editor._clouds[result]
        mask=np.arange(100)<50
        self.editor._segment=(result,layer,mask,self.editor._view())
        self.editor._refresh_controls()
        return raw,result,layer,mask

    def test_filter_preserves_outside_xyz_rgb_undo_and_save(self):
        raw,source,layer,mask=self.inputs()
        original=(self.db.directory/'frames'/source/'pointmap.ply').read_bytes()
        self.editor.apply_color_filter(dict(low=40,high=255,metric='value'));self.finish()
        outputs=[uid for uid,_ in self.editor._undo[-1][0]]
        kept,removed=[self.editor._clouds[outputs[0]],self.db.records[outputs[1]]]
        self.assertEqual(len(kept.points),80)
        np.testing.assert_array_equal(kept.points,layer.points[20:])
        np.testing.assert_array_equal(kept.colors,layer.colors[20:])
        self.assertEqual(removed.points,20)
        self.assertEqual(self.editor._display_ids,[outputs[0]])
        self.assertEqual(self.db.records[outputs[0]].source_ids,[source])
        self.assertEqual((self.db.directory/'frames'/source/'pointmap.ply').read_bytes(),original)
        self.assertEqual(self.editor.source_browser._items[outputs[1]].text(0),'阈值剔除 · PLY')
        from core.session_project import SessionProject
        project=self.bridge.projects.projects[self.bridge._current_mode]
        project.save_root=Path(self.temp.name)/'saved'
        saved=project.save({})
        loaded,_=SessionProject.load(saved,self.bridge._current_mode)
        try:
            self.assertEqual(loaded.database.records[outputs[1]].output_role,'color_rejected')
        finally: loaded.dispose()
        self.editor.undo();self.finish()
        self.assertEqual(self.editor._display_ids,[source])
        self.assertTrue(set(outputs).issubset(self.db.removed))

    def test_empty_no_color_view_change_and_production_gates(self):
        _,source,layer,mask=self.inputs()
        before=set(self.db.records)
        self.editor.apply_color_filter(dict(low=0,high=255,metric='value'))
        self.wait(lambda:self.editor._worker is None)
        self.assertEqual(set(self.db.records),before)
        self.assertIn('没有超出阈值',self.editor.status.text())
        self.editor._segment=(source,layer,mask,self.editor._view())
        self.editor.viewer.canvas.zoom*=2
        self.editor.apply_color_filter(dict(low=40,high=255,metric='value'))
        self.assertEqual(set(self.db.records),before)
        self.assertIn('重新框选',self.editor.status.text())
        self.editor.COLOR_VALIDATION=False
        self.editor._refresh_controls()
        self.assertTrue(self.editor.segment_tools.buttons['color_filter'].isHidden())
        self.editor._segment=(source,layer,mask,self.editor._view())
        self.editor.apply_color_filter(dict(low=40,high=255,metric='value'))
        self.assertEqual(set(self.db.records),before)
        _,_,_,_=self.inputs(colored=False)
        self.assertFalse(self.editor.segment_tools.buttons['color_filter'].isEnabled())

    def test_atomic_failure_publishes_neither_branch(self):
        _,source,layer,mask=self.inputs()
        before=set(self.db.records)
        with patch('core.utils.write_point_cloud_atomic',return_value=False):
            self.editor.apply_color_filter(dict(low=40,high=255,metric='value'))
            self.wait(lambda:self.editor._worker is None)
        self.assertEqual(set(self.db.records),before)
        self.assertIs(self.editor._clouds[source],layer)
        self.assertFalse(self.editor._undo)

    def test_dialog_preview_validation_cancel_then_apply_from_toolbar(self):
        _,source,layer,mask=self.inputs()
        data=preview_data(layer,mask,self.editor._view())
        dialog=ColorFilterDialog(data,parent=self.editor)
        self.assertIn('20',dialog.summary.text())
        dialog.low.setValue(256);dialog.high.setValue(10)
        self.assertFalse(dialog.execute_button.isEnabled())
        dialog.low.setValue(0);dialog.high.setValue(255)
        self.assertFalse(dialog.execute_button.isEnabled())
        dialog.low.setValue(40)
        self.assertTrue(dialog.execute_button.isEnabled())
        folder=Path('outputs/color_filter_preview');folder.mkdir(parents=True,exist_ok=True)
        dialog.show();self.app.processEvents()
        dialog.grab().save(str(folder/'dialog.png'))
        dialog.reject();dialog.deleteLater()
        before=set(self.db.records)
        cancellations=[]
        def cancel(instance):
            cancellations.append(True)
            return ColorFilterDialog.Rejected
        with patch.object(ColorFilterDialog,'exec',cancel):
            self.editor.open_color_filter()
            self.wait(lambda:bool(cancellations))
            self.finish()
        self.assertEqual(set(self.db.records),before)
        calls=[]
        def accept(instance):
            calls.append(True)
            instance.low.setValue(40)
            return ColorFilterDialog.Accepted
        with patch.object(ColorFilterDialog,'exec',accept):
            self.editor.segment_tools.buttons['color_filter'].click()
            self.wait(lambda:bool(calls))
            self.finish()
        self.assertEqual(len(self.editor._clouds[self.editor._display_ids[0]].points),80)

if __name__=='__main__':unittest.main()
