"""Publish independently claimable MCC tasks with explicit acceptance gates."""
from store import TaskStore

PYTHON = 'D:/Program Files/Anaconda/envs/rvc/python.exe'

TASKS = [
    dict(id='MCC-ROBOT-001', title='将机器人重合度计算移出 UI 线程', priority='P1',
        evidence='robot_workspace.on_overlap_check 在 UI 线程构建两帧点云并执行 KDTree 查询，大点云会冻结界面。',
        scope=['src/ui_v2/workspaces/robot_workspace.py', 'test_robot_workspace.py'],
        requirements=['复用统一后台 runner；忙碌时禁止重复操作和过期回填；重合度仍仅作参考，不改变 VERIFIED。'],
        acceptance=[f'"{PYTHON}" test_robot_workspace.py']),
    dict(id='MCC-ROBOT-002', title='修正米制旧键与毫米矩阵的直接比较', priority='P1',
        evidence='handeye_file._check_legacy_keys 将旧键数值直接与 matrix_mm 比较；v1 文件 unit=m 时合法兼容键可能被误拒。',
        scope=['src/core/robot_handeye/handeye_file.py', 'test_robot_handeye_file.py'],
        requirements=['先按文件 unit 将旧键归一到 mm 再比较；保持反装键拒绝和数值不一致拒绝；补 mm/m 双域往返。'],
        acceptance=[f'"{PYTHON}" test_robot_handeye_file.py']),
    dict(id='MCC-ROBOT-003', title='机器人 DB 标定参数显示手眼信息', priority='P2',
        evidence='frame_database 在 has_calibration=True 时统一显示“转台轴心”，机器人项目的标定节点语义错误。',
        scope=['src/ui_v2/frame_database.py', 'src/ui_v2/widgets/db_properties.py', 'test_ui_db_properties.py'],
        requirements=['机器人模式显示手眼矩阵/验证状态，不冒充转台参数；其他三种模式文案和属性页不变。'],
        acceptance=[f'"{PYTHON}" test_ui_db_properties.py']),
    dict(id='MCC-ROBOT-004', title='戳点失败原因在验证区持续可见', priority='P2',
        evidence='on_tip_check 的 reasons/warnings 仅写日志，用户离开日志后无法在当前验证区看到失败原因。',
        scope=['src/ui_v2/workspaces/robot_workspace.py', 'src/ui_v2/widgets/robot_control_panel.py', 'test_robot_workspace.py'],
        requirements=['在验证区显示最近报告的摘要和原因，保留详细日志；新矩阵、重跑和清空时同步状态，不改变门禁。'],
        acceptance=[f'"{PYTHON}" test_robot_workspace.py']),
    dict(id='MCC-PROTO-001', title='离线原型递归选项改为 GUI 线程捕获', priority='P2',
        evidence='industrial_offline_stitch 在 worker 内调用 self.recursive.isChecked()，跨线程访问 QWidget。',
        scope=['prototypes/industrial_offline_stitch/app/window.py', 'prototypes/industrial_offline_stitch/tests/test_ui_smoke.py'],
        requirements=['启动任务前在 GUI 线程读取布尔值并传入闭包；保持后台加载与忙碌门禁。'],
        acceptance=[f'"{PYTHON}" prototypes/industrial_offline_stitch/tests/test_ui_smoke.py']),
    dict(id='MCC-PROTO-002', title='离线检测调试图像写入独立目录', priority='P2',
        evidence='MarkerDetector.save_debug_images 默认开启，失败检测可能在当前工作目录写 debug_detect_*.png，污染输入目录。',
        scope=['prototypes/industrial_offline_stitch/core/offline_workflow.py', 'prototypes/industrial_offline_stitch/README.md', 'prototypes/industrial_offline_stitch/tests/test_offline_workflow.py'],
        requirements=['默认不向输入目录写调试文件；需要调试时显式指定独立输出目录，并验证原始目录无新增文件。'],
        acceptance=[f'"{PYTHON}" prototypes/industrial_offline_stitch/tests/test_offline_workflow.py']),
    dict(id='MCC-TEST-001', title='消除拍摄参数模拟设备 device_info 噪声', priority='P2',
        evidence='test_ui_frame_database 运行时 capture_parameter_labels 对 SimpleNamespace 模拟设备读取 device_info 产生 Qt  traceback，虽不影响退出码但污染验收输出。',
        scope=['test_ui_frame_database.py', 'src/ui_v2/widgets/capture_parameters.py'],
        requirements=['优先修正测试夹具的设备信息完整性；不得为通过测试吞掉真实设备异常；定向输出无该 traceback。'],
        acceptance=[f'"{PYTHON}" test_ui_frame_database.py']),
    dict(id='MCC-TEST-002', title='补充原型超时关闭和原子写失败回归', priority='P3',
        evidence='离线原型当前覆盖活跃任务关闭和输入覆盖保护，但缺少关闭等待超时与已有导出目标写失败的明确回归。',
        scope=['prototypes/industrial_offline_stitch/tests/test_ui_smoke.py', 'prototypes/industrial_offline_stitch/tests/test_offline_workflow.py'],
        requirements=['验证超时关闭被忽略、回调不失效；写失败保留旧目标文件且无临时文件残留。'],
        acceptance=[f'"{PYTHON}" prototypes/industrial_offline_stitch/tests/test_ui_smoke.py',
                    f'"{PYTHON}" prototypes/industrial_offline_stitch/tests/test_offline_workflow.py']),
]


def seed_tasks(store):
    existing = {task['id'] for task in store.all_tasks()}
    created = []
    for data in TASKS:
        if data['id'] not in existing:
            created.append(store.create_task(data))
    return created


if __name__ == '__main__':
    from pathlib import Path
    created = seed_tasks(TaskStore(Path(__file__).resolve().parent / 'data'))
    print(f'已发布 {len(created)} 项正式任务；总任务定义 {len(TASKS)} 项。')
