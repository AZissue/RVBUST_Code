"""One nonblocking, actionable failure surface for explicit user operations."""
from PySide6.QtCore import Qt
from .dialogs import ChineseMessageBox


def failure_advice(error, marker_type=None):
    text = str(error)
    if any(word in text for word in ('磁盘', '存储', '文件', 'disk', 'Permission', 'permission', '路径')):
        return '请检查磁盘剩余空间、目标路径和写入权限，确认文件未被占用；选择 DB 目录以外的位置后重试。原始帧可在 DB 中查看。'
    if any(word in text for word in ('断开', '连接', '设备离线', '相机离线')):
        return '请等待在飞拍摄结束，检查设备连接、电源和网络／USB；关闭占用相机的其他软件后重试连接或断开。已有 DB 数据保留，可继续离线查看。'
    if any(word in text for word in ('参数', '曝光', '增益', '亮度', 'SDK拒绝')):
        return '请重新读取目标相机参数，确认拍摄模式及该相机允许的范围；调整到有效范围后重试。切换相机或模式后应先读取当前设置。'
    if any(word in text for word in ('重叠', 'ICP', '配准', '对应点', '共有点')):
        return '请先检查两帧是否已粗略对齐及有足够重叠；必要时先手动选取至少三对分布开的共有点，再进行 ICP。检查单位、计算体素和最大对应距离，避免对大平面或重复结构误配准。'
    if marker_type is not None:
        names = dict(coded_circle='编码圆', unencoded_circle='普通圆点／圆环',
                     asymmetric_grid='非对称圆标定板', calib_board='非对称圆标定板',
                     feature='2D特征', feature_2d='2D特征', superpoint_lightglue='2D特征')
        name = names.get(marker_type, str(marker_type))
        return f'当前识别类型：{name}。请在“属性 → 识别参数”核对实际目标类型与参数，检查曝光、清晰度、遮挡及点云与2D对齐；等待后台重新识别后重试。'
    if any(word in text for word in ('点云', '深度', '3D', '有效点')):
        return '请在 DB 中逐帧检查有效深度、点云单位和输入选择，必要时调整曝光或重新拍摄；完成后重新执行操作。'
    if any(word in text for word in ('已变化', '来源', '已删除')):
        return '请重新选择当前有效 DB 数据；来源帧已重拍或删除时，需要重新生成依赖结果后再操作。'
    return '请检查当前选择及参数范围，确认输入数据完整后重试。详细原因见运行日志；原始数据可在 DB 中检查。'


def show_operation_failure(parent, title, error, *, advice=None, log=None,
                           automatic=False, action=None):
    """Log always when requested; show one window only for explicit operations.

    action is an optional (label, callback), e.g. opening recognition parameters.
    """
    if log is not None:
        log(f'{title}：{error}', 'error')
    if automatic:
        return None
    old = getattr(parent, '_operation_failure_dialog', None)
    if old is not None and old.isVisible():
        old.raise_()
        return old
    box = ChineseMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(ChineseMessageBox.Critical)
    box.setTextFormat(Qt.PlainText)
    box.setText(f'{title}。\n\n原因：{error}')
    box.setInformativeText(advice or failure_advice(error))
    if action is not None:
        button = box.addButton(action[0], ChineseMessageBox.ActionRole)
        def clicked(selected):
            if selected is button:
                action[1]()
                box.close()
        box.buttonClicked.connect(clicked)
    box.addButton('关闭', ChineseMessageBox.RejectRole)
    box.setWindowModality(Qt.WindowModal)
    box.setAttribute(Qt.WA_DeleteOnClose)
    def closed(_):
        if getattr(parent, '_operation_failure_dialog', None) is box:
            parent._operation_failure_dialog = None
    box.finished.connect(closed)
    parent._operation_failure_dialog = box
    box.open()
    return box
