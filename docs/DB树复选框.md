# DB 树组件勾选

三种新版工作区共用 `ui_v2.frame_database.FrameBrowser`。原始帧的点云、2D 图像和拼接结果的点云子项提供复选框，默认不勾选；分组、帧父项、标定参数没有复选框。

复选框表示待处理数据集合，与树高亮、多选删除和预览独立。点击复选框不会启动预览、读取几何数据、修改显示可见性或改写会话；点击名称沿用预览操作，当前子项也可使用空格键切换勾选。本次不提供后处理算子。

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

普通树刷新、重拍同一 UID、模式/呈现切换保留该浏览器的勾选；删除子项会清理对应勾选，恢复删除不会自动重新勾选。换成另一数据库对象时清空，即使新旧 UID 相同也不继承。勾选是临时 UI 状态，不写入项目文件；重启程序或重新载入会话后默认不勾选。它不改变现有拼接、导出和删除的输入来源，后续接入后处理时应显式调用上述接口。

离屏回归：`python -m unittest test_ui_db_checks`。
