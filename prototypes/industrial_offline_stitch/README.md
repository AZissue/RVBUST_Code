# 工业风离线拼接原型

独立离线验证工具：复用主程序工业风、2D/3D 组件与 `ChainStitcher`，不连接相机，不并入主程序，也不修改主程序版本号或更新日志。

## 功能

- 扫描同名图像与 PLY 文件对，支持递归子目录及 `_color` / `_depth` 等常见后缀。
- 左侧帧树显示检测与入链状态；选择帧查看原始 2D 标记和 3D 点云。
- 后台执行检测、配准和拼接，显示合并结果、节点/边统计与失败原因。
- 至少两个机位成功入链后，才可原子导出合并 PLY。
- 内置凳子第 1、2 帧示例，直接回放已有标记，不初始化相机 SDK。

## 运行

在仓库根目录执行：

```bash
"D:/Program Files/Anaconda/envs/rvc/python.exe" prototypes/industrial_offline_stitch/app/main.py
```

启动后自动加载凳子示例：

```bash
"D:/Program Files/Anaconda/envs/rvc/python.exe" prototypes/industrial_offline_stitch/app/main.py --stool
```

无显示器时：

```bash
export QT_QPA_PLATFORM=offscreen
export PYTHONUTF8=1
"D:/Program Files/Anaconda/envs/rvc/python.exe" prototypes/industrial_offline_stitch/app/main.py --stool
```

## 输入格式

目录中图像和点云按文件名配对：

```text
data/
├── 1.png
├── 1.ply
├── 2_color.png
├── 2_depth.ply
└── nested/
    ├── 3.jpg
    └── 3.ply
```

支持 `.png`、`.jpg`、`.jpeg`、`.bmp` 与 `.ply`。图像与 PLY 必须位于同一目录；递归模式下同名帧也按各自子目录独立配对，歧义候选会明确拒绝。

点云必须与图像同分辨率，按 row-major 像素顺序组织，单位为 mm。检测前会校验 `点数 = 图像宽 × 图像高`；普通非有组织 PLY 或点序未知的文件不能直接用于当前像素索引映射。图像与点云必须来自同一采集坐标体系，能够获得有效的 2D/3D 标记。原始文件只读，不会在数据目录生成配置或会话文件，导出也禁止覆盖任一输入 PLY。

## 验证

```bash
export PYTHONUTF8=1
export QT_QPA_PLATFORM=offscreen
PY="D:/Program Files/Anaconda/envs/rvc/python.exe"
"$PY" prototypes/industrial_offline_stitch/tests/test_offline_workflow.py
"$PY" prototypes/industrial_offline_stitch/tests/test_ui_smoke.py
```

测试覆盖文件配对、真实链式拼接、失败门禁、PLY 导出、凳子标记回放、目录到拼接的 UI 端到端，以及 1440×900 / 1050×650 布局截图。UI 截图输出到 `tmp_skill_logs/industrial_offline_stitch/`，不作为原型源码提交。

## 边界

- 只做独立原型验证，不注册到主程序模式栈，不修改 `src/`、`src/version.py` 或根目录 `CHANGELOG.md`。
- 配准使用真实 `ChainStitcher`，但合成测试只验证接口和数学链路；凳子示例不作为现场拼接精度验收。
- 当前不包含闭环优化、手动参考帧、真实相机采集或客户机打包。硬件 GPU 性能需另行实测。
