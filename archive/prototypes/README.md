# MCC 原型归档

归档于 2026-11-13。这里保留原型源码、测试和资料供追溯。子目录的历史命令可能引用归档前的路径或旧接口。当前入口见 [原型索引](../../prototypes/README.md)。

| 归档项目 | 现用入口或归档原因 |
|---|---|
| [offline_stitch](offline_stitch/) | 早期文件对拼接，现用主程序「离线拼接」 |
| [industrial_offline_stitch](industrial_offline_stitch/) | 工业风离线拼接过渡版，正式回归使用根目录的 `test_offline_stitch.py` 和 `test_offline_fpfh.py` |
| [industrial_scan_ui](industrial_scan_ui/) | 工业风布局原型，主体已迁入 `src/ui_v2/` |
| [postprocess_test](postprocess_test/) | 初版后处理，现用正式后处理及 [几何后处理验证](../../prototypes/industrial_pointcloud_postprocess/) |
| [quick_extrinsic](quick_extrinsic/) | 临时外参工具，离线复验使用 [固定多相机原型](../../prototypes/fixed_multi_camera/) |
| [task_workbench](task_workbench/) | 使用模拟数据的操作流程样机 |
| [turntable_360_stitch](turntable_360_stitch/) | 转台拼接已进入主程序转台工作区 |
