# MCC 原型验证项目

从仓库根目录使用本机 rvc Python 运行。工业风原型加载已保存的 MCC 会话，实验结果默认手动保存到 `outputs/experiments/<项目名>/`。输入要求、启动示例和保存方式见 [离线实验项目说明](../docs/integrated_experiments.md)。

## 工业风离线验证

| 项目 | 启动脚本 | 验证范围 |
|---|---|---|
| [颜色后处理](color_postprocess/) | `color_postprocess/run.py` | 颜色统一、原色对比、2D 融合和框内颜色过滤 |
| [FPFH 几何匹配](fpfh_geometry_match/) | `fpfh_geometry_match/run.py` | 独立调参及多帧配准，正式离线拼接也提供 FPFH |
| [几何后处理](industrial_pointcloud_postprocess/) | `industrial_pointcloud_postprocess/offline.py` | 框选、下采样、ICP 和结果分支 |
| [普通圆点三角形匹配](circle_geometry_match/) | `circle_geometry_match/run.py` | 圆点检测、配对预览和拼接。主程序也复用本项目的识别与匹配核心 |
| [固定多相机](fixed_multi_camera/) | `fixed_multi_camera/run.py` | 固定多相机外参及拼接的离线复验 |
| [机器人手眼变换](robot_handeye_transform/) | `robot_handeye_transform/run.py` | 手眼矩阵、位姿变换和戳点门禁的离线复验 |

## 专项验证

| 项目 | 验证范围 |
|---|---|
| [高级点云后处理](cloudcompare_like/) | 标量场、形状检测、法线、LOD 和大点云交互 |
| [编码圆标定板](coded_circle_ui/) | 参数化生成、预览及导出标定板 |
| [双目离线重建](stereo_2d_to_pointcloud/) | 双目图像与内外参重建、帧率与标定实验 |
| [并发采集诊断](sync_capture_stress/) | 多相机并发污染复现，需要实体设备 |

离屏验证设置 `QT_QPA_PLATFORM=offscreen`。主程序正式离线拼接回归运行 `python -m unittest test_offline_stitch test_offline_fpfh`。早期版本及退役项目见 [原型归档](../archive/prototypes/README.md)。
