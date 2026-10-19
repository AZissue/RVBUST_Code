# 验证记录

日期：2026-10-19（Asia/Shanghai）。

- 使用现有 Conda rvc Python，`QT_QPA_PLATFORM=offscreen`，`PYTHONIOENCODING=utf-8`。
- `tests/test_prototype.py`：11 项 unittest 通过，退出码 0。包含真实临时 PLY 导入/导出及 m→mm 转换，文件失败路径不修改图层且线程回收；未执行相机或机器人操作。
- `run.py --screenshot D:/RVC_SRC/.verify_reports/industrial_scan_ui.png`：退出码 0；1440×900 截图已查看。顶部功能带、项目树、参数、3D 视图及状态栏正常显示；1000×660 紧凑尺寸的控件和绘制验证通过。
- 首次无界面截图发现 Windows offscreen 插件不枚举系统字体，已加入仅在字体缺失时从本机 Windows 字体目录注册微软雅黑的逻辑，重新截图后中文和英文显示正常。字体文件不复制、不上传。
- 截图、视频抽帧、演示导出和用户参考视频不纳入代码提交。

限制：模拟流程未接入正式业务，软件点预览无深度缓冲和点拾取。未做大型实拍点云帧率、真实相机、GPU 或第三方软件功能等价性验收。完整 A/B/C 并入另行验证。
