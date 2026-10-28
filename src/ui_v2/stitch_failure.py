"""Actionable, nonblocking UI errors for an explicitly requested stitch."""
from PySide6.QtCore import Qt
from .dialogs import ChineseMessageBox


def advice(error, marker_type):
    text = str(error)
    if any(word in text for word in ('写入DB', '存储', '磁盘', '文件', 'disk', 'Permission')):
        return '请检查项目路径、磁盘空间及写入权限，确认文件未被占用；恢复存储后在DB树右键重新识别，再执行拼接。'
    if any(word in text for word in ('标记', '识别', '圆', '内点', 'RMS', '配准')):
        current = '编码圆' if marker_type == 'coded_circle' else '非对称圆标定板'
        return (f'当前识别类型：{current}。\n'
                '1. 打开左侧“属性 → 识别参数”，核对实际拍摄的标记类型。若拍摄的是标定板，请选择“非对称圆标定板”，勾选正确的规格并核对圆心间距。\n'
                '2. 若拍摄的是编码圆，请核对编码参数；检查曝光、清晰度和遮挡。\n'
                '3. 参数修改后等待原始帧后台重新识别，查看各帧2D/有效3D标记，再执行拼接。\n'
                '若提示共有标记不足、内点率低或RMS过高，请增加相邻帧重叠、减小拍摄移动幅度，并检查点云与2D对应关系。')
    if '标定' in text or '转轴' in text:
        return '请在当前工作区完成并检查外参或转轴标定，确认质量门禁通过，再采集对应扫描帧并重新拼接。'
    if any(word in text for word in ('点云', '3D', '深度')):
        return '请逐帧查看DB点云是否包含有效深度，检查相机工作距离、曝光及点云与2D对应设置；重新拍摄无效帧后再拼接。'
    return '请检查DB输入是否为至少两帧有效原始数据及对应的标定结果；若为文件读写错误，请检查项目路径、磁盘空间和权限。详细原因可在运行日志中查看。'


def show_stitch_failure(bridge, mode, error):
    shell = bridge.shell
    shell.log('拼接失败：' + str(error), 'error')
    marker_type = bridge.recognition.config(mode).get('marker_type', 'coded_circle')
    old = getattr(shell, '_stitch_failure_dialog', None)
    if old is not None and old.isVisible():
        old.raise_()
        return
    box = ChineseMessageBox(shell)
    box.setWindowTitle('拼接失败')
    box.setIcon(ChineseMessageBox.Critical)
    box.setTextFormat(Qt.PlainText)
    box.setText('未生成拼接结果。\n\n原因：' + str(error))
    box.setInformativeText(advice(error, marker_type))
    settings = box.addButton('打开识别参数', ChineseMessageBox.ActionRole)
    box.addButton('关闭', ChineseMessageBox.RejectRole)
    def clicked(button):
        if button is settings:
            props = bridge.frame_db.browsers[mode].properties
            props.tabs.setCurrentWidget(props.recognition)
        box.close()
    box.buttonClicked.connect(clicked)
    box.setWindowModality(Qt.WindowModal)
    box.setAttribute(Qt.WA_DeleteOnClose)
    box.finished.connect(lambda _: setattr(shell, '_stitch_failure_dialog', None))
    shell._stitch_failure_dialog = box
    box.open()
