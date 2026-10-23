# 通用标定结果窗口

入口：`ui_common.calibration_result.CalibrationResultDialog`。默认 980×660，可缩放到 760×520，沿用深色工业风；窗口可以由不同业务流程传入数据使用，不初始化 SDK、不读文件、不重新计算标定、不改主视窗或原始数据。

## 显示能力

- 数据配对切换、参考 / 待对齐数据分别显示，点云叠加或匹配圆心叠加。
- 内点 RMS、全量 RMS、内点率；逐点 ΔX / ΔY / ΔZ 与欧氏误差（mm）。当前筛选样本的均值、最大误差及数量单独显示。
- 误差柱状图与表格联动：点击柱或表格行，突出当前误差及对应三维点；悬浮柱查看编号与误差。内点 / 离群点分类沿用求解器记录，不从误差大小推测。
- 4×4 变换矩阵及方向说明。质量门禁由调用者传入阈值；没有阈值或有效指标时显示“未评估”，缺失数值显示“—”。
- 文件缺失、历史明细缺失及矩阵无效均明确提示；矩阵无效时不伪造单位变换。点云与结果采用独立显示副本，每路点云最多显示 120,000 点。

## 输入约定

```python
from ui_common.calibration_result import CalibrationResultDialog

# T 把源帧坐标变换到参考帧：p_ref = R @ p_src + t，平移单位 mm。
# details 的 pt_cam_transformed 已经处于参考坐标系，窗口不会再次变换它。
pairs = {('参考帧', '源帧'): {
    'success': True,
    'T': transform_4x4,
    'rms_mm': rms_inliers,
    'rms_all_mm': rms_all,
    'inlier_ratio': inlier_ratio,
    'details': [{
        'code': marker_id,
        'pt_ref': reference_xyz,
        'pt_cam_transformed': transformed_xyz,
        'is_inlier': solver_inlier,
    }],
}}
dialog = CalibrationResultDialog(pairs, parent,
    rms_limit_mm=2.0, min_inlier_ratio=0.5)
# 可选：由业务层在后台加载后传入各帧的 Nx3 numpy 点云坐标。
dialog.set_clouds({'参考帧': reference_points, '源帧': source_points})
dialog.show()
# 调用方应持有窗口引用。关闭后 active=False，迟到的 set_clouds 不再更新。
```

通用窗口默认展示全部匹配点；`rms_mm` 是求解器的内点拟合指标，不用全量误差均值替代，也不等于点云表面间距。

## 正式业务接入

现有多相机入口继续使用 `ui_v2.calibration_inspector.CalibrationInspector`，现在是公共窗口的薄适配器；从 DB 树“标定参数”的标定结果区域点击“可视化”打开。异步文件读取、工作区门禁和窗口引用仍由 `BackendBridge` 负责，点云加载器保留在业务模块中。公共组件本身不依赖 `ui_v2`、SDK 或工作流。

转台通过 `ui_v2.turntable_calibration_inspector.TurntableCalibrationInspector` 接入：在 DB“标定参数”的数据属性页点击“标定结果可视化”。转台保存两帧 DB 来源、数据版本、转轴模型的旋转帧→初始帧矩阵及逐点误差快照；只读异步加载来源点云，各路至多显示 120,000 点。源帧已替换或缺失时不使用替代帧；历史会话缺少快照时仅显示轴心并提示缺失，误差分类及质量门禁保持未评估。

旋转方向从相机沿 +Z 看向场景判断（图像 X 向右、Y 向下），表示初始帧→旋转帧的运动；不是从转台上方俯视的方向。两帧求解按小于 180° 的单步解释，近侧视或接近 180° 时提示无法稳定判定。该显示不改变原有轴角及拼接变换。

转台窗口增加“播放变换 / 暂停”“重播”和可拖动进度：0% 是旋转帧原始位置，100% 是其绕标定轴反向回转后的初始帧坐标。每次约3秒，参考帧固定；按轴角生成中间刚体变换，不插值4×4矩阵，不改源点云。误差及矩阵始终表示最终结果，点击误差行会暂停并回到100%。仅两帧点云均已载入且快照矩阵与当前轴角一致时启用；匹配圆心模式、缺失源帧时禁用，关闭窗口停止计时器。转台窗口默认1040×740，最小760×620，为动画和误差区留出空间，公共窗口尺寸不变。
