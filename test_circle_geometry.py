"""Production experiment entry, real image/organized PLY detection and DB transaction."""
import unittest
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
import open3d as o3d
import test_postprocess as fixture
from PySide6.QtCore import QTimer,QEvent
from core.frame_data import FrameData
from ui_v2.postprocess.circle_match_dialog import CircleMatchDialog
from prototypes.circle_geometry_match.core.pipeline import analyze_pair,merged_layer

class CircleIntegrationTests(unittest.TestCase):
    setUpClass=classmethod(fixture.PostprocessTests.setUpClass.__func__)
    wait=fixture.PostprocessTests.wait
    source=fixture.PostprocessTests.source
    finish=fixture.PostprocessTests.finish
    tearDown=fixture.PostprocessTests.tearDown

    def setUp(self):
        fixture.PostprocessTests.setUp(self)
        self.bridge.validation_root=Path(self.temp.name)/'validation'
        self.editor.close()
        self.editor=self.bridge.open_postprocess()
        self.app.processEvents()

    def inputs(self, *, rings=False):
        ids=[]
        rotation=cv2.Rodrigues(np.array([.1,-.15,.07]))[0];translation=np.array([11,-5,30])
        self.transform=np.eye(4);self.transform[:3,:3]=rotation;self.transform[:3,3]=translation
        for index,shift in enumerate(([0,0],[20,10])):
            image=np.full((180,240,3),255,np.uint8)
            for pixel in np.array([[35,35],[170,40],[65,130]])+shift:
                cv2.circle(image,tuple(pixel),9,(0,0,0),-1)
                if rings:
                    cv2.circle(image,tuple(pixel),7,(191,191,191),-1)
            yy,xx=np.mgrid[:180,:240]
            points=np.stack((xx-shift[0],yy-shift[1],np.full_like(xx,400)),axis=-1).reshape(-1,3).astype(float)
            if index:points=(points-translation)@rotation
            path=Path(self.temp.name)/f'original_{index}.ply'
            cloud=fixture.cloud(points,image.reshape(-1,3)[:,::-1]/255)
            self.assertTrue(o3d.io.write_point_cloud(str(path),cloud))
            frame=FrameData(index+1,f'cam{index}',image_np=image,is_offline=True,offline_pointmap_path=str(path))
            ids.append(self.db.ingest(frame))
        self.editor.source_browser.refresh()
        return ids

    def test_real_detection_confirm_publish_preserves_sources_and_transforms(self):
        ids=self.inputs(rings=True)
        originals={uid:(self.db.directory/'frames'/uid/'pointmap.ply').read_bytes() for uid in ids}
        dialog=CircleMatchDialog(self.editor);dialog.resize(800,600);dialog.show();self.app.processEvents()
        self.assertLessEqual(dialog.height(), 600)
        self.assertLess(dialog.execute_button.mapTo(dialog, dialog.execute_button.rect().bottomLeft()).y(), dialog.height())
        dialog.analyze()
        self.wait(lambda:not dialog._busy)
        self.assertIsNotNone(dialog.analysis['match'],dialog.report.toPlainText())
        scroll = dialog.scroll.verticalScrollBar()
        self.assertEqual(scroll.value(), scroll.maximum())
        self.assertFalse(dialog.execute_button.isEnabled())
        self.assertEqual(len(dialog.images[0].triangle),3)
        dialog.confirm.setChecked(True)
        self.assertTrue(dialog.execute_button.isEnabled())
        np.testing.assert_allclose(dialog.analysis['match']['transform'],self.transform,atol=1e-6)
        folder=Path('outputs/circle_geometry_preview');folder.mkdir(parents=True,exist_ok=True)
        dialog.grab().save(str(folder/'matching.png'))
        analysis,tokens=dialog.analysis,dialog.tokens
        dialog.accept();dialog.deleteLater()
        self.editor.publish_circle_match(analysis,tokens);self.finish()
        output=self.editor._display_ids[0]
        self.assertEqual(self.db.records[output].points,86400)
        published=self.editor._clouds[output]
        reference,moving=[frame['layer'] for frame in analysis['frames']]
        np.testing.assert_array_equal(published.colors,np.vstack([reference.colors,moving.colors]))
        np.testing.assert_array_equal(published.points[:len(reference.points)],reference.points)
        np.testing.assert_allclose(published.points[len(reference.points):],
            moving.points@self.transform[:3,:3].T+self.transform[:3,3],atol=1e-6)
        self.assertEqual(self.db.records[output].source_ids,ids)
        np.testing.assert_allclose(self.db.records[output].parent_transforms[ids[1]],self.transform,atol=1e-6)
        for uid in ids:self.assertEqual((self.db.directory/'frames'/uid/'pointmap.ply').read_bytes(),originals[uid])
        project=self.bridge.projects.projects[self.bridge._current_mode]
        project.save_root=Path(self.temp.name)/'saved'
        path=project.save({})
        from core.session_project import SessionProject
        loaded,_=SessionProject.load(path,self.bridge._current_mode)
        try:self.assertEqual(loaded.database.records[output].points,86400)
        finally:loaded.dispose()
        self.editor.undo();self.finish()
        self.assertIn(output,self.db.removed)

    def test_change_cancel_no_match_and_stale_publication(self):
        ids=self.inputs();before=set(self.db.records)
        dialog=CircleMatchDialog(self.editor)
        dialog.analyze();self.wait(lambda:not dialog._busy)
        analysis,tokens=dialog.analysis,dialog.tokens
        dialog.confirm.setChecked(True)
        dialog.point.setValue(3)
        self.assertIsNone(dialog.analysis)
        self.assertFalse(dialog.execute_button.isEnabled())
        dialog.reject();dialog.deleteLater()
        self.assertEqual(set(self.db.records),before)
        self.db.records[ids[0]].revision+=1
        self.editor.publish_circle_match(analysis,tokens)
        self.wait(lambda:self.editor._worker is None)
        self.assertEqual(set(self.db.records),before)
        self.assertIn('失败',self.editor.status.text())

    def test_atomic_write_failure_and_production_gate(self):
        ids=self.inputs()
        rows=[self.db.records[uid] for uid in ids]
        analysis=analyze_pair(self.db.directory,*rows)
        tokens=tuple((row.uid,row.revision) for row in rows)
        before=set(self.db.records)
        with patch('core.utils.write_point_cloud_atomic',return_value=False):
            self.editor.publish_circle_match(analysis,tokens)
            self.wait(lambda:self.editor._worker is None)
        self.assertEqual(set(self.db.records),before)
        self.assertFalse(self.editor._undo)
        self.bridge.validation_root=None
        self.editor.publish_circle_match(analysis,tokens)
        self.assertEqual(set(self.db.records),before)
        self.editor._refresh_controls()
        self.assertFalse(self.editor.actions['triangle'].isEnabled())

    def test_main_editor_dialog_entry_cancel_and_empty_inputs(self):
        self.assertFalse(self.editor.actions['triangle'].isEnabled())
        ids=self.inputs();self.editor._refresh_controls()
        self.assertTrue(self.editor.actions['triangle'].isEnabled())
        QTimer.singleShot(0,lambda:self.app.activeModalWidget().reject())
        self.editor.actions['triangle'].click()
        self.assertEqual(set(self.db.records),set(ids))
        self.app.sendPostedEvents(None,QEvent.DeferredDelete);self.app.processEvents()

if __name__=='__main__':unittest.main()
