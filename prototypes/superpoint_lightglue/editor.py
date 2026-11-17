"""Connect the feature registration experiment to the industrial DB editor."""
from PySide6.QtWidgets import QDialog
from shiboken6 import isValid

from ui_v2.postprocess.window import PostprocessWindow

from .dialog import FeatureMatchDialog
from .pipeline import PretrainedMatcher, merge_pair, read_frame


class FeatureMatchEditor(PostprocessWindow):
    def extra_actions(self):
        return (('feature_match', '2D 特征拼接', 'cloud_register', self.open_feature_match),)

    def eligible_frames(self):
        return [row for row in self.database.records.values()
                if row.kind == 'raw' and row.pointcloud_aligned is not False]

    def refresh_extra_actions(self, ready):
        self.actions['feature_match'].setEnabled(
            self._parameter_gate() and len(self.eligible_frames()) >= 2)

    def open_feature_match(self):
        if not self._parameter_gate():
            return
        if not hasattr(self, '_feature_matcher'):
            self._feature_matcher = PretrainedMatcher()
        dialog = FeatureMatchDialog(self, self._feature_matcher)
        try:
            if dialog.exec() == QDialog.Accepted and not self._closed:
                self.publish_feature_match(dialog)
        finally:
            if isValid(dialog):
                dialog.deleteLater()

    def publish_feature_match(self, dialog):
        directory, tokens, boxes, pose = dialog.snapshot
        rms = dialog.rms

        def work():
            with self.database._lock:
                self._validate_source(directory, tokens)
                frames = [read_frame(directory, self.database.records[uid]) for uid, _ in tokens]
                return [merge_pair(frames, boxes, pose)]

        self._commit_operation(work, diagnostic=lambda: (
            f'SuperPoint + LightGlue · 移动 → 参考 · 内点 RMS {rms:.3f} mm · 合并两帧工件选区'))
