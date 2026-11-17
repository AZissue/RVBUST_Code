# MCC 原型验证项目

从仓库根目录使用本机 rvc Python 运行。工业风原型加载已保存的 MCC 会话，实验结果默认手动保存到 `outputs/experiments/<项目名>/`。输入要求、启动示例和保存方式见 [离线实验项目说明](../docs/integrated_experiments.md)。

## 工业风离线验证

| 项目 | 启动脚本 | 验证范围 |
|---|---|---|
| [颜色后处理](color_postprocess/) | `color_postprocess/run.py` | 颜色统一、原色对比、2D 融合和框内颜色过滤 |
| [普通圆点三角形匹配](circle_geometry_match/) | `circle_geometry_match/run.py` | 圆点检测、配对预览和拼接。主程序也复用本项目的识别与匹配核心 |
| [SuperPoint + LightGlue 无标记拼接](superpoint_lightglue/) | `superpoint_lightglue/run.py` | 2D 特征匹配、3D 刚体配准及工件选区拼接 |

## 专项验证

| 项目 | 验证范围 |
|---|---|
| [编码圆标定板](coded_circle_ui/) | 参数化生成、预览及导出标定板 |
| [双目离线重建](stereo_2d_to_pointcloud/) | 双目图像与内外参重建、帧率与标定实验 |
| [并发采集诊断](sync_capture_stress/) | 多相机并发污染复现，需要实体设备 |

离屏验证设置 `QT_QPA_PLATFORM=offscreen`。主程序正式离线拼接回归运行 `python -m unittest test_offline_stitch test_offline_fpfh`。早期版本及退役项目见 [原型归档](../archive/prototypes/README.md)。
