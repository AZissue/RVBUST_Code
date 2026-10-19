# 面向客户部署的增量渲染

## 运行边界

使用现有 Qt/PyOpenGL 实现标准桌面 OpenGL 3.3 顶点缓冲，不新增 VTK，不使用 CUDA、显卡品牌判断、开发机 SDK 路径或专有运行时。支持情况取决于客户操作系统与显示驱动提供的 OpenGL 上下文；不能承诺所有工控机、远程桌面和虚拟机都有可用 GPU 加速。

OpenGL 无法初始化或渲染出错时，界面明确切换为兼容软件预览并展开错误日志；状态栏持续显示实际后端。兼容预览静止 18,000 点、拖动 3,000 点，不冒充大点云渲染能力。无界面测试自动使用兼容预览。

## 数据与显示分离

原始帧保持 float64 坐标与原颜色，不将显示采样结果回写到采集、拼接、裁切模型或导出接口。每个图层当前代表一帧/一个导入文件；后续接入正式流程时按采集帧添加，不应先把全部帧拼成一个大数组交给视图。

后台线程为每帧准备独立显示包：局部原点 + float32 XYZ + uint8 RGBA，每点 16 字节。先在 float64 中减去局部原点，再转 float32，避免大坐标平移吞掉局部细节；相机旋转、平移、缩放只更新矩阵。

采样使用无重复的渐进索引序列，低密度前缀分布在整帧采集序列中。它是显示抽稀，不进行体素均值，不承诺保留每个薄壁或微小缺陷；检测、测量和导出仍用原始数据。

## 显示档位（全场景总预算）

| 档位 | 静止 | 拖动/滚轮 | 单帧显示上限 |
|---|---:|---:|---:|
| 流畅 | 100 万 | 10 万 | 500 万 |
| 均衡（默认） | 500 万 | 50 万 | 500 万 |
| 细节 | 1000 万 | 100 万 | 500 万 |

松开鼠标/停止滚轮后约 220 ms 恢复静止预算；按住拖动时持续使用交互预算。两种密度使用相同顶点缓冲的渐进前缀，不重复采样或上传。点数预算不是帧率保证，需要按客户设备选择档位。

## 增量与内存

- 各帧按原始数组身份缓存；相同数据和显示质量不重新构建。新增帧优先只准备、上传新帧，保持原视角。
- 接入方须提交稳定帧快照，替换数组或增加 `revision` 来声明坐标/颜色改变；不得在后台准备期间原地修改源数组。
- 全局预算按帧点数分配。旧缓冲足够且不超过新份额的两倍时继续复用；超出时只重建相关帧，避免历史缓冲无限增长。因此不是所有追加场景都绝对只上传新帧。
- 稳态 CPU 显示包和 GPU 顶点缓冲各不超过约 `2 × 静止预算 × 16 字节`：均衡档各约 160 MB，细节档各约 320 MB。后台换包、旧场景、源数组及驱动开销会增加瞬时占用，此上限不代表进程总内存。
- 图层删除/隐藏后会回收其显示缓存和 GPU 缓冲。原始数据仍由会话/撤销记录保留，显示预算不能限制原始数据总内存。当前会话原始数据常驻内存；长期连续采集的磁盘分块、有限撤销和会话内存配额尚未实现。
- GPU 仍在 GUI/上下文线程上传数据；单帧至多 500 万点，上传约 80 MB。缓存准备放到后台，但首次上传、显存压力和驱动阻塞仍可能造成短暂停顿。

## 开发与交付

开发环境仅用来构建和验证，客户不使用开发机 Conda 或绝对路径。源码运行：

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r prototypes/industrial_scan_ui/requirements.txt
.venv/Scripts/python prototypes/industrial_scan_ui/run.py
```

Windows x64 原型打包（在构建环境安装 PyInstaller）：

```powershell
python -m PyInstaller --noconfirm prototypes/industrial_scan_ui/IndustrialScan.spec
```

交付整个 `dist/MCC-Scan-Prototype/`，客户启动其中 EXE，不需 Python。spec 从相对项目位置定位源码，不包含本机 Conda/RVC SDK 路径。运行仍需要操作系统和支持 OpenGL 3.3 的显示驱动。最终正式产品还需固定依赖版本、制作安装包并在客户代表性干净系统验收；原型包不等于正式产品交付完成。

## 可复用验收

```powershell
python prototypes/industrial_scan_ui/tests/test_render_cache.py
python prototypes/industrial_scan_ui/tests/test_prototype.py
# 以下测试需原生窗口环境，勿设置 QT_QPA_PLATFORM=offscreen。
python prototypes/industrial_scan_ui/tests/gpu_smoke.py --points-per-frame 5000000 --frames 2 --report gpu_report.json
```

最后一项逐帧追加两个 500 万点输入，检查 GPU 初始化、缓存/上传、鼠标交互与细节恢复、原始/显示点数及相机变化不重新上传。报告记录实际 OpenGL 后端；同步完成耗时不包含合成器和完整输入链路，不能直接宣称客户实测 FPS。
