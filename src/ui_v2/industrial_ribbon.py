"""Prototype-style ribbon for the industrial presentation only.

Command buttons delegate to existing production controls. Their enabled/checked
states follow those controls, so layout changes cannot bypass workflow gates or
connect backend actions twice. No prototype or device runtime is instantiated.
"""
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget, QSizePolicy)

from . import icons
from .launcher_dialog import LauncherDialog


STYLE = '''
QWidget#industrialRibbon { background:#292b2f; border-bottom:1px solid #41444a; }
QWidget#studioHeader { background:#202226; border-bottom:1px solid #383b41; }
QLabel#studioLogo { color:#ffffff; background:#b93638; font-size:17px;
    font-weight:800; padding:4px 9px; border-radius:5px; }
QLabel#studioBrand { color:#b8bec8; font-size:13px; font-weight:600; background:transparent; }
QFrame#studioDivider { background:#454850; border:0; }
QLabel#studioMode { color:#f0f2f5; font-size:15px; font-weight:600;
    background:transparent; padding:3px 0; }
QLabel#studioBadge { color:#b6c7bc; background:#29322e; padding:5px 10px; border-radius:10px; }
QLabel#studioBadge[offline="true"] { color:#b5c2d6; background:#2c3340; }
QFrame#ribbonGroup { background:transparent; border:0; border-right:1px solid #41444a; }
QLabel#ribbonCaption { color:#8f97a4; font-size:11px; background:transparent; padding-top:2px; }
QWidget#industrialRibbon QToolButton { color:#dddddd; background:transparent;
    border:1px solid transparent; border-radius:5px; padding:2px; font-size:12px; }
QWidget#industrialRibbon QToolButton:hover { background:#3b3f46; border-color:#555b65; }
QWidget#industrialRibbon QToolButton:pressed { background:#4d3030; border-color:#d32f2f; }
QWidget#industrialRibbon QToolButton:checked { background:#573232; border-color:#d32f2f; color:#ffffff; }
QWidget#industrialRibbon QToolButton:disabled { color:#727272; background:transparent; border-color:transparent; }
QWidget#industrialRibbon QToolButton[headerAction="true"] { background:#353535;
    border-color:#4a4a4a; padding:4px 10px; }
QWidget#industrialRibbon QToolButton[headerAction="true"]:hover { background:#464646; }
QWidget#industrialRibbon QToolButton[headerAction="true"]:checked { background:#573232; border-color:#d32f2f; }
QWidget#industrialRibbon QToolButton#workspaceSwitch { background:#343941; border-color:#505866; }
QWidget#industrialRibbon QToolButton#workspaceSwitch:hover { background:#444c58; border-color:#7a8799; }
QWidget#industrialRibbon QToolButton[primaryAction="true"]:enabled { background:#633134; border-color:#954447; color:#ffffff; }
QWidget#industrialRibbon QToolButton[primaryAction="true"]:hover { background:#803b3f; border-color:#c45d62; }
'''


class RibbonButton(QToolButton):
    """Keep the complete title visible using Qt's current font/style metrics."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(55)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

    def sizeHint(self):
        return super().sizeHint().expandedTo(QSize(64, 55))

    def minimumSizeHint(self):
        return self.sizeHint()


class CommandButton(RibbonButton):
    """Mirror a production button, including asynchronous workflow state changes."""
    def __init__(self, source, title, glyph, parent=None, *, follow_text=False):
        super().__init__(parent)
        self.source = source
        self.follow_text = follow_text
        self.setText(title)
        self.setIcon(icons.icon(glyph, '#d6d6d6', 23))
        self.setIconSize(QSize(23, 23))
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
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
        if event.type() in (QEvent.EnabledChange, QEvent.ToolTipChange):
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
        header.setMinimumHeight(52)
        line = QHBoxLayout(header)
        line.setContentsMargins(14, 8, 14, 8)
        line.setSpacing(12)
        line.addWidget(QLabel('MCC', objectName='studioLogo'))
        line.addWidget(QLabel('SCAN STUDIO', objectName='studioBrand'))
        divider = QFrame(objectName='studioDivider')
        divider.setFixedSize(1, 22)
        line.addWidget(divider)
        self.mode_label = QLabel(objectName='studioMode')
        line.addWidget(self.mode_label)
        self.camera_status = QLabel()
        self.camera_status.setStyleSheet('color:#cccccc;background:#292929;padding:5px;border-radius:4px;font-size:11px;')
        self.camera_status.setMaximumWidth(330)
        self.camera_status.setMinimumWidth(180)
        self.camera_status.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        line.addWidget(self.camera_status)
        line.addStretch(1)
        self.workflow_status = QLabel()
        self.workflow_status.setStyleSheet('background:transparent;font-size:11px;')
        self.workflow_status.setMaximumWidth(420)
        self.workflow_status.setMinimumWidth(330)
        self.workflow_status.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        line.addWidget(self.workflow_status)
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
            row.setSpacing(2)
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
        col.setContentsMargins(1, 0, 3, 1)
        col.setSpacing(1)
        actions = QHBoxLayout()
        actions.setSpacing(1)
        for key, text, glyph, source in entries:
            button = CommandButton(source, text, glyph, follow_text=mode == 'multi_cam' and key == 'capture') if hasattr(source, 'click') else RibbonButton()
            if not isinstance(button, CommandButton):
                button.setText(text)
                button.setIcon(icons.icon(glyph, '#d6d6d6', 23))
                button.setIconSize(QSize(23, 23))
                button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                button.clicked.connect(lambda _checked=False, action=source: action())
            if key == 'select':
                button.setObjectName('workspaceSwitch')
                button.setToolTip('返回启动窗口，选择工作区或切换离线预览')
            elif key == 'restore':
                button.setToolTip('返回工作视图：退出DB历史帧预览，恢复当前工作区的2D / 3D显示')
            elif key == 'manage':
                button.setToolTip('会话占用 / 管理：查看磁盘占用、管理已保存会话与回收数据')
            elif key == 'disconnect':
                button.setToolTip('停止实时预览并断开当前所有已连接相机，保留DB、标定和采集结果')
            elif key == 'postprocess':
                button.setToolTip('打开点云后处理，直接使用当前项目DB数据')
            elif key == 'stitch':
                button.setProperty('primaryAction', True)
            self.commands[(mode, key)] = button
            actions.addWidget(button)
        col.addLayout(actions)
        col.addWidget(QLabel(title, alignment=Qt.AlignCenter, objectName='ribbonCaption'))
        row.addWidget(group)

    def _build_mode(self, mode, row):
        shell = self.shell
        multi, mobile, turn = shell.workspace_multi(), shell.workspace_mobile(), shell.workspace_turntable()
        robot = shell.workspace_robot()
        exports = dict(multi_cam=multi._btn_stitch_save, mobile_chain=mobile._btn_save,
            turntable=turn.btn_save, robot_stitch=robot.panel.btn_save_ply)
        self._group(row, '工作区', [
            ('select', '选择功能', 'layers', lambda: shell.open_device_manager()),
        ], mode)
        self._group(row, '项目', [
            ('new', '新建会话', 'folder_open', lambda: self._project_action('new_dialog')),
            ('open', '打开会话', 'folder_open', shell.open_session_requested.emit),
            ('save', '保存会话', 'save', turn.btn_save_session if mode == 'turntable' else shell.save_session_requested.emit),
            ('manage', '会话管理', 'folder_open', lambda: self._project_action('manage')),
            ('export', '导出点云', 'layers', lambda: self._stitch_action('export')),
        ], mode)
        self._group(row, '设备', [
            ('devices', '设备管理', 'camera_multi', shell.open_device_manager),
            ('disconnect', '断开连接', 'disconnect', lambda: shell._backend_bridge and shell._backend_bridge.disconnect_devices()),
            ('parameters', '参数调试', 'sliders', shell.open_param_debug),
        ], mode)
        if mode == 'multi_cam':
            groups = [('外参标定', [
                ('capture', '拍摄标定帧', 'camera', multi._btn_capture),
                ('detect', '检测标记', 'detect', multi._btn_detect),
                ('calibrate', '计算外参', 'calibrate', multi._btn_calibrate)]),
                ('扫描采集', [('scan_preview', '2D实时预览', 'video', multi._btn_scan_preview),
                             ('scan', '拍摄扫描帧', 'camera', multi._btn_scan_capture)])]
        elif mode == 'mobile_chain':
            groups = [('采集', [('preview', '实时取景', 'video', mobile._btn_preview),
                              ('capture', '拍摄机位', 'camera', mobile._btn_capture),
                              ('recapture', '重拍当前', 'refresh', mobile._btn_recapture)]),
                      ('机位编辑', [('undo', '撤销末帧', 'undo', mobile._btn_undo),
                                  ('delete', '删除机位', 'trash', mobile._btn_delete_node)])]
        elif mode == 'robot_stitch':
            groups = [('手眼矩阵', [
                ('import_he', '导入矩阵', 'folder_open', robot.panel.btn_import_he_file),
                ('export_he', '导出矩阵', 'save', robot.panel.btn_export_he_file)]),
                      ('位姿与采集', [('capture', '拍摄并变换', 'camera', robot.panel.btn_capture),
                                  ('clear', '清空采集', 'trash', robot.panel.btn_clear)]),
                      ('戳点验证', [('tip', '记录戳点', 'detect', robot.panel.btn_tip_record),
                                  ('verify', '运行门禁', 'calibrate', robot.panel.btn_tip_check)])]
        else:
            groups = [('转轴标定', [('frame0', '拍摄初始帧', 'camera', turn.btn_capture_frame0),
                                  ('frame1', '拍摄旋转帧', 'camera', turn.btn_capture_frame1),
                                  ('calibrate', '计算转轴', 'calibrate', turn.btn_online_calib)]),
                      ('步进采集', [('capture', '拍摄当前步', 'camera', turn.btn_capture_step),
                                  ('auto', '自动采集', 'loop', turn.btn_auto_capture)])]
        for caption, entries in groups:
            self._group(row, caption, entries, mode)
        stitch_source = robot.panel.btn_publish if mode == 'robot_stitch' else lambda: self._stitch_action('execute')
        self._group(row, '拼接', [('stitch', '执行拼接', 'stitch', stitch_source)], mode)
        self._group(row, '视图', [('restore', '返回视图', 'undo', self.restore_view),
                                 ('fit', '适配视图', 'reset_view', self.fit_view),
                                 ('screenshot', '视图截图', 'video', self.screenshot)], mode)
        self._group(row, '后处理', [('postprocess', '点云后处理', 'layers',
            lambda: shell._backend_bridge and shell._backend_bridge.open_postprocess())], mode)
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
                self._hide_section(multi._btn_batch.parentWidget())
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
        multi = shell.current_mode() == 'multi_cam'
        self.camera_status.setVisible(multi)
        self.workflow_status.setVisible(multi)
        self.badge.setVisible(not multi or getattr(shell, '_offline_preview', False))
        self.badge.setText('正在断开连接…' if getattr(shell._backend_bridge, '_disconnecting', False) else
                           '离线预览' if getattr(shell, '_offline_preview', False) else
                           f'已连接 {len(shell._devices)} 台设备' if shell._devices else '未连接相机')
        self.badge.setProperty('offline', bool(getattr(shell, '_offline_preview', False) or not shell._devices))
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        database = shell._frame_databases[shell.current_mode()]
        raw = sum(row.kind == 'raw' for row in database.records.values())
        robot = shell.current_mode() == 'robot_stitch'
        if not robot:
            self.commands[(shell.current_mode(), 'stitch')].setEnabled(raw >= 2)
        self.commands[(shell.current_mode(), 'stitch')].setToolTip(
            '将当前基座系合并点云发布为独立DB结果，保留原始帧及来源关系。' if robot else
            '优先拼接DB勾选的至少两帧原始点云；按当前模式使用标记配准或标定参数，生成独立拼接帧。未勾选时沿用当前工作流。')
        bridge = shell._backend_bridge
        ready = bool(bridge and bridge.can_change_workspace())
        for mode in self._pages:
            self.commands[(mode, 'postprocess')].setEnabled(ready)
            self.commands[(mode, 'disconnect')].setEnabled(
                bool(ready and bridge.camera_manager.get_connected_ids()))
            if getattr(bridge, '_disconnecting', False):
                self.commands[(mode, 'devices')].setEnabled(False)
                self.commands[(mode, 'parameters')].setEnabled(False)
            else:
                self.commands[(mode, 'devices')].setEnabled(True)
                self.commands[(mode, 'parameters')].setEnabled(True)
        presentation = getattr(shell._stack.currentWidget(), '_industrial', None)
        browser = presentation.frame_browser if presentation is not None else None
        self.commands[(shell.current_mode(), 'export')].setEnabled(
            browser is not None and browser.export_uid() is not None and (bridge is None or bridge.can_change_workspace()))
        self.commands[(shell.current_mode(), 'export')].setToolTip('导出选中或单独勾选的DB点云完整PLY；无选择时导出最新有效拼接结果')
        if bridge and hasattr(bridge, 'stitching'):
            bridge.stitching.update_mobile_actions()

    def _viewer(self):
        workspace = self.shell._stack.currentWidget()
        return workspace.viewer() if callable(workspace.viewer) else workspace.viewer

    def fit_view(self):
        self._viewer().reset_view()

    def restore_view(self):
        workspace = self.shell._stack.currentWidget()
        presentation = getattr(workspace, '_industrial', None)
        if presentation is not None:
            presentation.frame_browser.restore_requested.emit()

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
