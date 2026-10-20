"""Prototype-style ribbon for the industrial presentation only.

Command buttons delegate to existing production controls. Their enabled/checked
states follow those controls, so layout changes cannot bypass workflow gates or
connect backend actions twice. No prototype or device runtime is instantiated.
"""
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from . import icons
from .launcher_dialog import LauncherDialog


STYLE = '''
QWidget#industrialRibbon { background:#2e2e2e; border-bottom:1px solid #444444; }
QWidget#studioHeader { background:#222222; }
QLabel#studioBrand { color:#eeeeee; font-size:18px; font-weight:700; }
QLabel#studioMode { background:#303030; color:#dddddd; border:1px solid #484848;
    border-radius:3px; padding:5px 10px; }
QLabel#studioBadge { color:#bbbbbb; background:#303030; padding:6px 10px; border-radius:3px; }
QFrame#ribbonGroup { background:#2b2b2b; border:0; border-right:1px solid #454545; }
QLabel#ribbonCaption { color:#aaaaaa; font-size:11px; background:transparent; }
QWidget#industrialRibbon QToolButton { color:#dddddd; background:transparent;
    border:1px solid transparent; border-radius:3px; padding:3px; font-size:12px; }
QWidget#industrialRibbon QToolButton:hover { background:#414141; border-color:#565656; }
QWidget#industrialRibbon QToolButton:pressed { background:#4d3030; border-color:#d32f2f; }
QWidget#industrialRibbon QToolButton:checked { background:#573232; border-color:#d32f2f; color:#ffffff; }
QWidget#industrialRibbon QToolButton:disabled { color:#727272; background:transparent; border-color:transparent; }
QWidget#industrialRibbon QToolButton[headerAction="true"] { background:#353535;
    border-color:#4a4a4a; padding:4px 10px; }
QWidget#industrialRibbon QToolButton[headerAction="true"]:hover { background:#464646; }
QWidget#industrialRibbon QToolButton[headerAction="true"]:checked { background:#573232; border-color:#d32f2f; }
'''


class CommandButton(QToolButton):
    """Mirror a production button, including asynchronous workflow state changes."""
    def __init__(self, source, title, glyph, parent=None, *, follow_text=False):
        super().__init__(parent)
        self.source = source
        self.follow_text = follow_text
        self.setText(title)
        self.setIcon(icons.icon(glyph, '#d6d6d6', 23))
        self.setIconSize(QSize(23, 23))
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setFixedSize(78, 55)
        self.setToolTip(source.toolTip() or source.text().strip())
        self.setCheckable(source.isCheckable())
        self.clicked.connect(lambda _checked=False: source.click())
        source.installEventFilter(self)
        source.toggled.connect(self.sync)
        source.objectNameChanged.connect(self.sync)
        self.sync()

    def sync(self, *_):
        self.setEnabled(self.source.isEnabled())
        if self.follow_text:
            self.setText(self.source.text().strip())
        self.setToolTip(self.source.toolTip() or self.source.text().strip())
        self.blockSignals(True)
        self.setChecked(self.source.isChecked())
        self.blockSignals(False)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.EnabledChange:
            self.sync()
        return super().eventFilter(watched, event)


class IndustrialRibbon(QWidget):
    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self.setObjectName('industrialRibbon')
        self.setStyleSheet(STYLE)
        self.commands = {}
        self._sources = []
        self._hidden_before = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        header = QWidget(objectName='studioHeader')
        line = QHBoxLayout(header)
        line.setContentsMargins(18, 8, 14, 8)
        line.setSpacing(10)
        line.addWidget(QLabel('MCC   /   SCAN STUDIO', objectName='studioBrand'))
        line.addSpacing(18)
        self.mode_label = QLabel(objectName='studioMode')
        line.addWidget(self.mode_label)
        select = self._header_button('选择功能', 'layers', shell.open_device_manager)
        select.setToolTip('返回启动窗口，选择工作区或切换离线预览')
        line.addWidget(select)
        line.addStretch(1)
        self.badge = QLabel(objectName='studioBadge')
        line.addWidget(self.badge)
        self.log_button = self._header_button('运行日志', 'terminal', shell._btn_log.click)
        self.log_button.setCheckable(True)
        shell._btn_log.toggled.connect(self.log_button.setChecked)
        line.addWidget(self.log_button)
        line.addWidget(self._header_button('帮助', 'help', shell._show_help))
        root.addWidget(header)
        self.pages = QStackedWidget()
        root.addWidget(self.pages)
        self._pages = {}
        for mode in LauncherDialog.MODE_NAMES:
            page = QWidget()
            row = QHBoxLayout(page)
            row.setContentsMargins(10, 5, 10, 4)
            row.setSpacing(10)
            self._pages[mode] = page
            self.pages.addWidget(page)
            self._build_mode(mode, row)
            row.addStretch(1)
        self.hide()

    def _header_button(self, title, glyph, callback):
        button = QToolButton()
        button.setProperty('headerAction', True)
        button.setText(title)
        button.setIcon(icons.icon(glyph, '#cccccc', 15))
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.clicked.connect(lambda _checked=False: callback())
        return button

    def _group(self, row, title, entries, mode):
        group = QFrame(objectName='ribbonGroup')
        col = QVBoxLayout(group)
        col.setContentsMargins(3, 0, 8, 1)
        col.setSpacing(1)
        actions = QHBoxLayout()
        actions.setSpacing(2)
        for key, text, glyph, source in entries:
            button = CommandButton(source, text, glyph, follow_text=mode == 'multi_cam' and key == 'capture') if hasattr(source, 'click') else QToolButton()
            if not isinstance(button, CommandButton):
                button.setText(text)
                button.setIcon(icons.icon(glyph, '#d6d6d6', 23))
                button.setIconSize(QSize(23, 23))
                button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                button.setFixedSize(78, 55)
                button.clicked.connect(lambda _checked=False, action=source: action())
            self.commands[(mode, key)] = button
            actions.addWidget(button)
        col.addLayout(actions)
        col.addWidget(QLabel(title, alignment=Qt.AlignCenter, objectName='ribbonCaption'))
        row.addWidget(group)

    def _build_mode(self, mode, row):
        shell = self.shell
        multi, mobile, turn = shell.workspace_multi(), shell.workspace_mobile(), shell.workspace_turntable()
        exports = dict(multi_cam=multi._btn_stitch_save, mobile_chain=mobile._btn_save, turntable=turn.btn_save)
        self._group(row, '项目', [
            ('new', '新建会话', 'folder_open', lambda: self._project_action('new_dialog')),
            ('open', '打开会话', 'folder_open', shell.open_session_requested.emit),
            ('save', '保存会话', 'save', turn.btn_save_session if mode == 'turntable' else shell.save_session_requested.emit),
            ('export', '导出点云', 'layers', lambda: self._stitch_action('export')),
        ], mode)
        self._group(row, '设备', [
            ('devices', '设备管理', 'camera_multi', shell.open_device_manager),
            ('parameters', '参数调试', 'sliders', shell.open_param_debug),
        ], mode)
        if mode == 'multi_cam':
            groups = [('外参标定', [
                ('capture', '拍摄标定帧', 'camera', multi._btn_capture),
                ('detect', '检测标记', 'detect', multi._btn_detect),
                ('calibrate', '计算外参', 'calibrate', multi._btn_calibrate)]),
                ('扫描拼接', [('scan', '拍摄扫描帧', 'camera', multi._btn_scan_capture),
                           ('batch', '批量拼接', 'stitch', multi._btn_batch)])]
        elif mode == 'mobile_chain':
            groups = [('采集', [('preview', '实时取景', 'video', mobile._btn_preview),
                              ('capture', '拍摄机位', 'camera', mobile._btn_capture),
                              ('recapture', '重拍当前', 'refresh', mobile._btn_recapture)]),
                      ('机位编辑', [('undo', '撤销末帧', 'undo', mobile._btn_undo),
                                  ('delete', '删除机位', 'trash', mobile._btn_delete_node)])]
        else:
            groups = [('转台标定', [('frame0', '拍摄 frame0', 'camera', turn.btn_capture_frame0),
                                  ('frame1', '拍摄 frame1', 'camera', turn.btn_capture_frame1),
                                  ('calibrate', '计算转台', 'calibrate', turn.btn_online_calib)]),
                      ('步进采集', [('capture', '采集下一帧', 'camera', turn.btn_capture_step),
                                  ('auto', '自动采集', 'loop', turn.btn_auto_capture)])]
        for caption, entries in groups:
            self._group(row, caption, entries, mode)
        self._group(row, '拼接', [('stitch', '执行拼接', 'stitch', lambda: self._stitch_action('execute'))], mode)
        self._group(row, '视图', [('fit', '适配视图', 'reset_view', self.fit_view),
                                 ('screenshot', '视图截图', 'video', self.screenshot)], mode)
        # Keep existing controls for business logic; hide only their duplicates
        # in the new presentation. Classic visibility is restored on exit.
        self._sources.append(exports[mode])
        if mode == 'mobile_chain':
            self._sources.append(mobile._btn_offline_load)
        if mode == 'turntable':
            self._sources.append(turn.btn_save_session)
        for _, entries in groups:
            self._sources.extend(entry[3] for entry in entries)

    def _project_action(self, name):
        bridge = self.shell._backend_bridge
        if bridge and hasattr(bridge, 'projects'):
            getattr(bridge.projects, name)()

    def _stitch_action(self, name):
        bridge = self.shell._backend_bridge
        if bridge and hasattr(bridge, 'stitching'):
            getattr(bridge.stitching, name)()

    def activate(self, enabled, mode):
        self.setVisible(enabled)
        if enabled:
            if self._hidden_before is None:
                self._hidden_before = {source: source.isHidden() for source in self._sources}
            for source in self._sources:
                source.hide()
            # The existing mobile presentation groups these commands together;
            # hide the empty section after their ribbon equivalents are shown.
            mobile = self.shell.workspace_mobile()
            if getattr(getattr(mobile, '_industrial', None), 'active', False):
                self._hide_section(mobile._btn_capture.parentWidget())
            multi = self.shell.workspace_multi()
            if getattr(getattr(multi, '_industrial', None), 'active', False):
                self._hide_section(multi._btn_calibrate.parentWidget())
                self._hide_section(multi._btn_scan_capture.parentWidget())
            self.pages.setCurrentWidget(self._pages[mode])
            for button in self.commands.values():
                if isinstance(button, CommandButton):
                    button.sync()
        elif self._hidden_before is not None:
            for source, hidden in self._hidden_before.items():
                source.setVisible(not hidden)
            self._hidden_before = None
        self.update_status()

    def _hide_section(self, section):
        if section not in self._hidden_before:
            self._hidden_before[section] = section.isHidden()
        section.hide()

    def update_status(self):
        shell = self.shell
        self.mode_label.setText(LauncherDialog.MODE_NAMES[shell.current_mode()])
        self.badge.setText('离线预览' if getattr(shell, '_offline_preview', False) else
                           f'已连接 {len(shell._devices)} 台设备' if shell._devices else '未连接相机')
        database = shell._frame_databases[shell.current_mode()]
        raw = sum(row.kind == 'raw' for row in database.records.values())
        results = any(row.kind == 'result' for row in database.records.values())
        self.commands[(shell.current_mode(), 'stitch')].setEnabled(raw >= 2)
        self.commands[(shell.current_mode(), 'stitch')].setToolTip('至少两帧原始数据；多角度选择两帧以上时拼接选中帧，否则使用全部原始帧')
        self.commands[(shell.current_mode(), 'export')].setEnabled(results)

    def _viewer(self):
        workspace = self.shell._stack.currentWidget()
        return workspace.viewer() if callable(workspace.viewer) else workspace.viewer

    def fit_view(self):
        self._viewer().reset_view()

    def screenshot(self):
        canvas = getattr(self._viewer().viewer(), 'canvas', None)
        if canvas is None or canvas.is_busy:
            self.shell.log('点云视图仍在准备，请稍后截图。', 'warn')
            return
        path, _ = QFileDialog.getSaveFileName(self.shell, '保存3D视图截图', 'MCC_view.png', 'PNG 图片 (*.png)')
        if not path:
            return
        path = str(Path(path).with_suffix('.png'))
        if canvas.grab().save(path):
            self.shell.log('视图截图已保存：' + path, 'success')
        else:
            self.shell.log('视图截图保存失败：' + path, 'error')
