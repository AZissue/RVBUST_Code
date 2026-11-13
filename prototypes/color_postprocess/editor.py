"""Industrial postprocessor with experimental color operations."""
from dataclasses import asdict

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog

from core.frame_database import STALE_RESULT
from core.postprocess.session import CloudLayer
from ui_v2.postprocess.window import PostprocessWindow
from .core.color_correction import ColorParameters, NoColorCorrection, correct_color_layers
from .color_dialog import ColorDialog


class ColorValidationWindow(PostprocessWindow):
    def __init__(self, *args, **kwargs):
        self._color_state = dict(asdict(ColorParameters()), reference=None, aligned=False)
        self._last_color_report = []
        self._color_comparison = ((), ())
        super().__init__(*args, **kwargs)
        self.actions['compare'].setCheckable(True)

    def extra_actions(self):
        return (
            ('color', '颜色统一', 'color_palette', self.open_color_dialog),
            ('compare', '对比原色', 'color_compare', self.compare_color_source),
        )

    def extra_segment_action(self):
        return self.open_color_filter

    def refresh_extra_actions(self, ready):
        self.actions['color'].setEnabled(ready and not self._closed and bool(self._display_ids)
            and self.bridge.can_change_workspace()
            and self.database is self.bridge.frame_db.databases[self.mode]
            and self.database.directory == self.directory)
        sources, results = self._color_comparison
        comparable = bool(sources and results and tuple(self._display_ids) in (sources, results)
            and all(uid in self.database.records and self.database.records[uid].status != STALE_RESULT
                    for uid in (*sources, *results)))
        self.actions['compare'].setEnabled(ready and comparable)
        self.actions['compare'].setText('返回校正结果' if comparable and tuple(self._display_ids) == sources else '对比原色')
        self.actions['compare'].setChecked(comparable and tuple(self._display_ids) == sources)

    def create_color_dialog(self):
        inputs = [(uid, self._clouds[uid].name, len(self._clouds[uid].points)) for uid in self._display_ids]
        dialog = ColorDialog(inputs, self._active_uid, self._color_state, self)
        dialog.parameters_changed.connect(lambda state: setattr(self, '_color_state', dict(state)))
        return dialog

    def open_color_dialog(self):
        if not self._parameter_gate() or not self._display_ids:
            return
        snapshot = self._input_snapshot()
        dialog = self.create_color_dialog()
        accepted = []
        dialog.accepted.connect(lambda: accepted.append(dialog.parameters()))
        if dialog.exec() == QDialog.Accepted:
            state = accepted[0]
            params = ColorParameters(**{key: state[key] for key in asdict(ColorParameters()) if key in state})
            self.correct_colors(params, reference_uid=state['reference'], aligned=state['aligned'], snapshot=snapshot)

    def _color_params(self):
        return ColorParameters(**{key: value for key, value in self._color_state.items()
                                 if key in asdict(ColorParameters())})

    @staticmethod
    def _color_params_text(params):
        return (f'算法={params.algorithm}，预下采样={params.voxel_size:g}mm，尺度={params.scale:g}mm，强度={params.strength:.0%}，上限={params.max_gain:g}，'
                f'接缝融合={params.seam_strength:.0%}，样本上限={params.sample_limit}，重叠距离={params.overlap_distance:g}mm')

    def _show_color_diagnostic(self, params, reports, heading='颜色统一'):
        self._last_color_report = reports
        self._last_color_params = asdict(params)
        lines = [heading+'；'+self._color_params_text(params)]
        for row in reports:
            row.setdefault('params', asdict(params))
            text = (f"{row.get('name', '点云')}：{row.get('status', '拒绝')}，样本{row.get('samples', 0)}，"
                    f"格/支持{row.get('nodes', 0)}/{row.get('supported_nodes', 0)}，几何分区{row.get('components', 1)}，重叠内点{row.get('matches', 0)}")
            if 'output_points' in row:
                text += f"，点数{row['input_points']:,}→{row['output_points']:,}"
            if 'gain_min' in row:
                text += (f"，估计增益{np.round(row.get('estimated_gain_min', row.get('estimated_gain', [1]*3)), 3).tolist()}"
                         f"..{np.round(row.get('estimated_gain_max', row.get('estimated_gain', [1]*3)), 3).tolist()}"
                         f"，应用{np.round(row['gain_min'], 3).tolist()}..{np.round(row['gain_max'], 3).tolist()}"
                         f"，变化>5%/{row.get('changed_gt5_fraction', 0):.1%}、>10%/{row.get('changed_gt10_fraction', 0):.1%}"
                         f"，分布保留{row.get('distribution_retention', 1):.1%}，截断{row.get('clipped_fraction', 0):.2%}"
                         f"，实际强度{row.get('actual_strength', params.strength):.1%}")
                if row.get('adaptive_scale', 1) < 1:
                    text += f"，受高光限制，实际幅度k={row['adaptive_scale']:.1%}"
                if row.get('material_warning'):
                    text += '；可能抹平材质，建议降低强度'
            if row.get('reason'):
                text += '；'+row['reason']
            lines.append(text)
        message = '\n'.join(lines)
        self.bridge.shell.log(message, 'info')
        self.status.setToolTip(message)
        return message

    def compare_color_source(self):
        sources, results = self._color_comparison
        if (self._worker is not None or self._closed or not sources or not results
                or not self.bridge.can_change_workspace() or self.database.directory != self.directory
                or self.database is not self.bridge.frame_db.databases[self.mode]):
            return
        target = results if tuple(self._display_ids) == sources else sources
        if any(uid not in self.database.records or self.database.records[uid].status == STALE_RESULT for uid in target):
            self._set_status('对比来源或结果已变化，请重新生成颜色统一结果。')
            return
        # Only UID lists are retained. Reload on demand; never keep a second
        # permanent full-size colour cache just to compare the original.
        self.load_selected(list(target))

    def correct_colors(self, params=None, *, reference_uid=None, aligned=None, snapshot=None):
        if snapshot is not None and snapshot != self._input_snapshot():
            self._set_status('输入、来源修订或项目已变化，请重新打开参数。')
            return
        if (self._worker is not None or self._closed or not self.bridge.can_change_workspace()
                or self.database is not self.bridge.frame_db.databases[self.mode]
                or self.database.directory != self.directory):
            self._set_status('正在处理或项目已切换，不能执行颜色统一。')
            return
        identifiers = list(self._display_ids)
        if not identifiers:
            self._set_status('请先显示至少一项有色点云。')
            return
        with self.database._lock:
            if any(uid not in self.database.records or self.database.records[uid].status == STALE_RESULT
                    or self._clouds[uid].origins != ((uid, self.database.records[uid].revision),)
                    for uid in identifiers):
                self._set_status('来源数据已变化，请重新显示后执行颜色统一。')
                return
        if len(identifiers) > 1 and (not (self._color_state['aligned'] if aligned is None else aligned) or any(
                self.database.records[uid].kind == 'raw' for uid in identifiers)):
            self._set_status('多云需同一坐标系，重叠区用于估计；原始未配准帧请先拼接，并确认坐标系。')
            return
        layers = [self._clouds[uid] for uid in identifiers]
        if any(layer.colors is None for layer in layers):
            self._set_status('颜色统一拒绝无色或混合有色/无色输入，不会补造原始颜色。')
            return
        reference = reference_uid if reference_uid is not None else self._color_state.get('reference')
        if reference_uid is not None and reference_uid not in identifiers:
            self._set_status('参考点云已变化，请重新打开颜色参数。')
            return
        reference = identifiers.index(reference) if reference in identifiers else identifiers.index(
            self._active_uid) if self._active_uid in identifiers else 0
        params = params or self._color_params()
        try:
            params.validate()
        except ValueError as exc:
            self._set_status(self._show_color_diagnostic(params, [dict(status='参数拒绝', reason=str(exc))]))
            return
        reports = []
        def work():
            try:
                if params.algorithm == 'image_fusion':
                    from .core.image_color_fusion import source_poses, fuse_image_colors
                    pairs = [fuse_image_colors(self.database, layer, source_poses(self.database, uid), params)
                             for uid, layer in zip(identifiers, layers)]
                    outputs, details = [p[0] for p in pairs], [p[1] for p in pairs]
                else:
                    outputs, details = correct_color_layers(layers, reference=reference, params=params)
            except NoColorCorrection as exc:
                reports.extend(dict(row, name=layer.name) for layer, row in zip(layers, exc.reports))
                raise
            reports.extend(dict(row, name=layer.name) for layer, row in zip(layers, details))
            return outputs
        def diagnostic():
            self._color_comparison = (tuple(identifiers), tuple(self._display_ids))
            self._refresh_controls()
            return self._show_color_diagnostic(params, reports)
        def failed(error):
            details = reports or [dict(status='拒绝', reason=str(error))]
            self._set_status(self._show_color_diagnostic(params, details, '颜色统一未发布：'+str(error)))
        self._set_status('正在颜色统一；'+self._color_params_text(params))
        self._commit_operation(work, display_all=True, diagnostic=diagnostic, on_error=failed)


    def _color_filter_gate(self, segment):
        return (self._parameter_gate() and segment is not None and self._segment is segment
                and self._clouds.get(segment[0]) is segment[1]
                and segment[1].colors is not None
                and segment[0] in self.database.records
                and self.database.records[segment[0]].status != STALE_RESULT
                and segment[1].origins == ((segment[0], self.database.records[segment[0]].revision),)
                and all(np.allclose(self._view()[key], value) for key, value in segment[3].items()))

    def open_color_filter(self):
        segment = self._segment
        if not self._color_filter_gate(segment):
            self._set_status('请在实验副本中选中有原始RGB颜色的点云，完成多边形框选后再过滤。')
            return
        from .core.color_filter import preview_data
        from .color_filter_dialog import ColorFilterDialog
        uid, source, mask, view = segment
        def prepared(data):
            def show_dialog():
                if self._closed or self._segment is not segment:
                    return
                if self._worker is not None:
                    QTimer.singleShot(10, show_dialog)
                    return
                if not self._color_filter_gate(segment):
                    return
                dialog = ColorFilterDialog(data, getattr(self, '_color_filter_state', None), self)
                try:
                    accepted = dialog.exec() == QDialog.Accepted
                    if self._closed:
                        return
                    self._color_filter_state = dialog.parameters()
                    if accepted:
                        self.apply_color_filter(self._color_filter_state, segment)
                finally:
                    from shiboken6 import isValid
                    if isValid(dialog):
                        dialog.deleteLater()
            QTimer.singleShot(0, show_dialog)
        self._run(lambda: preview_data(source, mask, view), prepared,
                  kind='probe', preserve_selection=True)
        self._set_status('正在统计框内全部原始点的颜色；不会修改点云。')

    def apply_color_filter(self, parameters, segment=None):
        segment = segment if segment is not None else self._segment
        if not self._color_filter_gate(segment):
            self._set_status('框选、来源或视角已变化，请重新框选后再过滤。')
            return
        from .core.color_filter import threshold_rejection
        uid, source, mask, view = segment
        report = []
        def work():
            rejected = threshold_rejection(source.colors, mask, **parameters)
            keep = ~rejected
            if not rejected.any():
                raise ValueError('框内没有超出阈值的点，未生成结果')
            if not keep.any():
                raise ValueError('保留结果为空，请缩小框选或调整阈值')
            report.append(f'框内颜色过滤：剔除 {int(rejected.sum()):,} 点；'
                f'保留 {int(keep.sum()):,} 点；框外全部保留。'
                f'通道 {parameters["metric"]}，保留范围 [{parameters["low"]}, {parameters["high"]}]。')
            def build(selected, name, role):
                return CloudLayer(source.name + name, source.points[selected], source.colors[selected],
                    source=source.source, origins=source.origins, output_role=role,
                    source_transforms=source.source_transforms,
                    registration_transform=source.registration_transform,
                    parent_transforms=source.parent_transforms, intermediate_of=source.intermediate_of)
            return [build(keep, ' · 颜色过滤保留', 'color_kept'),
                    build(rejected, ' · 阈值剔除', 'color_rejected')]
        self._commit_operation(work, diagnostic=lambda: '\n'.join(report))
