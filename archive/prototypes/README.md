# MCC 原型归档

归档批次为 2026-11-13 和 2026-11-17。这里保留原型源码、测试和资料供追溯。子目录的历史命令可能引用归档前的路径或旧接口。当前入口见 [原型索引](../../prototypes/README.md)。

| 归档项目 | 现用入口或归档原因 |
|---|---|
| [offline_stitch](offline_stitch/) | 早期文件对拼接，现用主程序「离线拼接」 |
| [industrial_offline_stitch](industrial_offline_stitch/) | 工业风离线拼接过渡版，正式回归使用根目录的 `test_offline_stitch.py` 和 `test_offline_fpfh.py` |
| [industrial_scan_ui](industrial_scan_ui/) | 工业风布局原型，主体已迁入 `src/ui_v2/` |
| [postprocess_test](postprocess_test/) | 初版后处理，现用主程序「后处理」 |
| [quick_extrinsic](quick_extrinsic/) | 临时外参工具，现用主程序「多相机外参标定拼接」 |
| [task_workbench](task_workbench/) | 使用模拟数据的操作流程样机 |
| [turntable_360_stitch](turntable_360_stitch/) | 转台拼接已进入主程序转台工作区 |
| [cloudcompare_like](cloudcompare_like/) | CloudCompare 风格独立工作区。主程序「后处理」提供分割、合并、下采样和 ICP。标量场、形状拟合、独立法线计算和八叉树 LOD 保存在此实验中。 |
| [industrial_pointcloud_postprocess](industrial_pointcloud_postprocess/) | 主程序「后处理」，提供多边形分割、合并、下采样、ICP、撤销与导出 |
| [fixed_multi_camera](fixed_multi_camera/) | 主程序「多相机外参标定拼接」，可打开已保存的固定多相机会话 |
| [robot_handeye_transform](robot_handeye_transform/) | 主程序「机器人手眼拼接」，提供手眼矩阵、绝对位姿、基座系拼接和戳点验证 |
