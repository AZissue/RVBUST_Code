"""Actionable, nonblocking UI errors for an explicitly requested stitch."""
from PySide6.QtCore import Qt
from .dialogs import ChineseMessageBox


def advice(error, marker_type):
    text = str(error)
    if any(word in text for word in ('标记物平面', '标记物在平面', '圆心近似共线', '圆心未形成可靠的共面分布')):
        return '请确认各帧有至少四个分布开且共面的有效三维圆心，相机从工件侧拍摄。若工件贴近平台，请降低“拼接 → 平面过滤”的最小高度，也可关闭过滤后重试。'
    if '未与2D对齐' in text:
        return '请在“属性 → 拍摄参数”开启“点云对应2D”，在DB树中选中黄色原始帧后点击顶部“重拍当前”。修改相机设置不会修复旧帧；请完成重拍后再执行拼接。'
    if any(word in text for word in ('写入DB', '存储', '磁盘', '文件', 'disk', 'Permission')):
        return '请检查项目路径、磁盘空间及写入权限，确认文件未被占用；恢复存储后在DB树右键重新识别，再执行拼接。'
    if marker_type == 'superpoint_lightglue':
        return ('当前识别类型：2D特征。请检查相邻帧的工件 ROI、纹理和重叠，'
                '检查图像清晰度及匹配点处有效深度、点云与2D对齐；'
                '大转角时补拍中间帧，重新匹配后再拼接。')
    if marker_type == 'unencoded_circle':
        return ('当前识别类型：普通圆点／圆环。请检查圆点极性、灰度阈值、半径范围及圆度，'
                '确保各帧检测到足够且分布开的有效三维圆心；'
                '检查点云与2D对齐，并增加相邻帧重叠后重试。')
    if any(word in text for word in ('标记', '识别', '圆', '内点', 'RMS', '配准')):
        current = {'coded_circle': '编码圆', 'unencoded_circle': '普通圆点／圆环',
                   'superpoint_lightglue': '2D特征', 'asymmetric_grid': '非对称圆标定板',
                   'calib_board': '非对称圆标定板'}.get(marker_type, str(marker_type))
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
    from .operation_failure import show_operation_failure
    shell = bridge.shell
    marker_type = bridge.recognition.config(mode).get('marker_type', 'coded_circle')
    def settings():
        props = bridge.frame_db.browsers[mode].properties
        props.tabs.setCurrentWidget(props.recognition)
    box = show_operation_failure(shell, '拼接失败', error,
        advice=advice(error, marker_type), log=shell.log,
        action=('打开识别参数', settings))
    if getattr(shell, '_stitch_failure_dialog', None) is not box:
        shell._stitch_failure_dialog = box
        box.finished.connect(lambda _: setattr(shell, '_stitch_failure_dialog', None))
    return box
