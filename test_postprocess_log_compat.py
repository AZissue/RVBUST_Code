import unittest
from types import SimpleNamespace
import test_postprocess as fixture

class LogCompatibilityTests(unittest.TestCase):
    setUpClass = classmethod(fixture.PostprocessTests.setUpClass.__func__)
    setUp = fixture.PostprocessTests.setUp
    tearDown = fixture.PostprocessTests.tearDown
    wait = fixture.PostprocessTests.wait

    def test_older_log_without_signal_opens_syncs_and_reopens(self):
        self.editor.close()
        original = self.win._log_panel
        legacy = SimpleNamespace(records=original.records)
        try:
            self.win._log_panel = legacy
            for _ in range(2):
                self.editor = self.bridge.open_postprocess()
                self.app.processEvents()
                self.assertTrue(self.editor._log_sync_timer.isActive())
                row = ('now','info','','','legacy update')
                legacy.records.append(row)
                self.editor._sync_log_history()
                self.assertEqual(self.editor._log_panel.records[-1],row)
                self.editor._btn_log.click()
                self.assertTrue(self.editor._log_panel.isVisible())
                self.editor.close()
                self.assertFalse(self.editor._log_sync_timer.isActive())
        finally:
            self.win._log_panel = original

    def test_current_log_uses_signal_and_disconnects_when_closed(self):
        self.assertFalse(self.editor._log_sync_timer.isActive())
        self.win.log('live update','info')
        self.assertEqual(self.editor._log_panel.records[-1][-1],'live update')
        count=len(self.editor._log_panel.records)
        self.editor.close()
        self.win.log('after close','info')
        self.assertEqual(len(self.editor._log_panel.records),count)

if __name__=='__main__':unittest.main()
