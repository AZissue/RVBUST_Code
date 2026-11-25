# ScanPort 调研与界面设计

## ZEISS ScanPort

ScanPort 是面向中小型零件的半自动光学三维测量工作站。传感器升降、俯仰与工件转台组成三条自动轴，从不同距离和角度采集零件。ZEISS INSPECT 支持扫描模板、运动重放、工作流助手和 Kiosk 操作模式，也支持网格处理与 CAD 比对。对于重复测量的同类工件，操作员可以复用扫描过程。 [ZEISS 官方发布说明](https://www.zeiss.com/metrology/en/about-us/newsroom/2025/zeiss-scanport.html) · [官方产品页](https://www.handsonmetrology.com/products/scanport/)

## RVC-3D-Metrix 外观框架

顶部按准备、采集、检测和报告安排入口。当前阶段在右侧显示操作提示、数据条件与设备状态。左侧对象树集中管理演示模型、扫描数据和测量结果。中央保留可调整大小的三维工作区，结构参考用户提供的测量软件截图。主题使用中性深灰和产品红，文字与网格采用相应灰阶。品牌标记、选中状态、主要操作及演示工件使用红色。

当前版本在离线模式下预览程序生成的法兰座。通过对象树或视窗工具栏切换模型显示，拖动旋转、滚轮缩放，双击或点击按钮复位。设备状态固定为未连接，扫描、CAD 对齐、偏差计算和报告生成尚未接入。

主窗口布局和流程状态在 `src/ui/main_window.py`，交互式几何预览在 `src/ui/viewport.py`，界面样式在 `resources/workbench.qss`。
