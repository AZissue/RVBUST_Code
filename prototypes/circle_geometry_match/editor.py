"""Industrial DB editor for experimental triangle matching."""
from PySide6.QtWidgets import QDialog

from ui_v2.postprocess.window import PostprocessWindow
from .core.pipeline import merged_layer


class CircleMatchEditor(PostprocessWindow):
    def extra_actions(self):
        return (('triangle', '圆点匹配', 'cloud_register', self.open_circle_match),)

    def refresh_extra_actions(self, ready):
        self.actions['triangle'].setEnabled(
            self._parameter_gate()
            and sum(row.kind == 'raw' for row in self.database.records.values()) >= 2)

    def open_circle_match(self):
        if not self._parameter_gate():
            return
        from .circle_match_dialog import CircleMatchDialog
        dialog = CircleMatchDialog(self)
        try:
            if dialog.exec() == QDialog.Accepted and not self._closed:
                self.publish_circle_match(dialog.analysis, dialog.tokens)
        finally:
            from shiboken6 import isValid
            if isValid(dialog):
                dialog.deleteLater()

    def publish_circle_match(self, analysis, tokens):
        if (not self._parameter_gate()
                or not analysis or analysis.get('match') is None):
            self._set_status('请在实验副本中重新识别并确认圆点匹配。')
            return
        tokens = tuple(tokens)
        if tokens != tuple(token for frame in analysis['frames'] for token in frame['layer'].origins):
            self._set_status('匹配来源已变化，请重新识别。')
            return
        directory = self.directory
        def work():
            self._validate_source(directory, tokens)
            layer = merged_layer(analysis)
            self._validate_source(directory, tokens)
            return [layer]
        match = analysis['match']
        self._commit_operation(work, diagnostic=lambda:
            f'普通圆点三角形匹配：{len(match["pairs"])}对；圆心RMS {match["rms"]:.4f} mm；'
            '移动帧变换到参考帧；保留全部有效点和原始颜色，未执行ICP。')
