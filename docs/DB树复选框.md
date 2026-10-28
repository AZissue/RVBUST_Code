# DB 树组件勾选

三种新版工作区共用 `ui_v2.frame_database.FrameBrowser`。原始帧的点云、2D 图像和拼接结果的点云子项提供复选框，默认不勾选；分组、帧父项、标定参数没有复选框。

复选框与树高亮、多选删除独立，当前子项也可使用空格键切换勾选。正式工作区中，点云复选框控制 3D 叠加预览：后台读取所勾选的各帧，保持独立显示层；原始帧按各自相机坐标显示，不应用标定外参，不合并或修改原始文件。拼接结果按文件中已有坐标显示。

取消勾选移除对应显示层，全部取消或点击“返回视图”恢复工作视图。存在勾选点云时，点击点云名称仅选择属性，点击原始帧名称或图像名称可查看 2D，并保留叠加点云。图像复选框仍作为待处理图像集合，不触发预览或几何读取。新版后处理窗口复用同一棵树，勾选点云作为后处理输入。

## 层级与后处理

树固定为“会话/项目根 → 数据分类 → 帧节点 → 数据叶子”。扫描与标定分类按各自业务用途保留；“拼接结果”同时包含拼接帧和后处理帧。同一次操作产生的框内、框外点云共用一个后处理帧，仅叶子带真实 UID 与复选框。后处理帧为无 UID 的显示分组，选择它递归去重得到真实结果，不触发单个叶子的预览。勾选仍按每个结果 UID 保存，不按分组或来源联动；刷新保留勾选，删除清理、恢复不自动重新勾选。

## 后续功能接入

```python
browser = workspace._industrial.frame_browser

# 返回按树内帧顺序排列的 (frame_uid, component) 列表。
all_inputs = browser.checked_components()
cloud_inputs = browser.checked_components('cloud')
image_inputs = browser.checked_components('image')

browser.set_component_checked(frame_uid, 'cloud', True)
browser.checked_components_changed.connect(on_inputs_changed)
```

变化信号参数与 `checked_components()` 一致，为完整引用列表，不含点云、图像或 SDK 句柄。`component` 为 `cloud` 或 `image`，查询可省略以获取全部；未知查询类型抛出 `ValueError`，设置不存在的组件抛出 `KeyError`。使用者通过所在工作区数据库和帧 UID 自行解析输入，并在执行时验证数据版本和可用性。

普通树刷新保留勾选；已勾选点云的数据版本改变后重新读取。点云勾选在返回工作视图、切换模式或呈现、开始业务处理及更换会话时清理，取消勾选及读取失败不会被迟到的后台结果重新显示。图像勾选保留为独立处理输入。删除子项会清理对应勾选，恢复删除不会自动重新勾选。换成另一数据库对象时清空，即使新旧 UID 相同也不继承。勾选是临时 UI 状态，不写入项目文件；重启程序或重新载入会话后默认不勾选。它不改变现有拼接、导出和删除的输入来源，后续接入后处理时应显式调用上述接口。

离屏回归：`python -m unittest test_ui_db_checks test_ui_db_overlay`。
