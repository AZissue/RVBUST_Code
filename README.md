# PointCloudSearch

模块化点云查找 / 分析工具：桌面程序（节点式图形化流程）+ C++ SDK。

## 技术栈
- C++20, CMake, VS2026
- PCL 1.13.0（算法：平面/球/圆柱 RANSAC、聚类、下采样、滤波、IO）
- Qt 6.8 LTS（界面、中英切换、明暗主题）
- VTK（3D 渲染，嵌入 Qt）
- OpenCV 4.7（2D 功能，P1）

## 模块结构
见各 `modules/*/README.md`。核心约定：
- 内部坐标单位统一为 **mm**；单位换算只在 IO 层做。
- 所有结果保留原始点索引（Region.indices）。
- 节点输入输出统一为 `ObjectList`（PointCloudObject 列表）。

## 构建
```powershell
cmake -S . -B build -G "Visual Studio 18 2026" -A x64 -DPCL_ROOT="D:/Program Files/PCL 1.13.0"
cmake --build build --config Release
ctest --test-dir build -C Release
```

## 运行桌面程序
构建会自动把 Qt（windeployqt）、VTK 9.4、PCL 运行库部署到
`build/app/Release/` 下（测试程序 `build/tests/app/Release/` 同样部署），
直接双击或 VS 调试（F5）即可，无需手工配 PATH。VS 调试环境已自动包含
Qt/VTK/PCL 路径；部署时会剔除 PCL/Qt 自带的旧版 MSVC 运行库，避免
`MSVCP140.dll` 崩溃。

界面要点：
- 左侧工具箱按分类树展示算法节点，`Ctrl+F` 聚焦搜索框，双击节点即添加到画布中心，也可拖拽；
- 画布节点端口带类型颜色（蓝=cloud、绿=region、灰=any），类型不符会拒绝连线并在日志说明原因；
- 连线：从输出端口按住拖拽到输入端口松手即可连接（也兼容点击-点击）；
- 连线随节点拖动实时跟随；右键连线可「断开连接」；
- 删除：右键节点 → Delete Node，或选中后按 Delete 键；
- 画布背景：View → Canvas Background 可选网格/点阵/纯色/自定义图片（png/jpg/bmp 等）；
- 拖拽节点时全视口刷新，不会残留旧边线；
- 点云加载/保存节点的路径参数带「…」浏览按钮，直接选文件；
- 程序默认中文界面 + Dark 主题（View → Language/Theme 可切换）；
- 选中画布节点会同步把该节点输出切到 3D 视窗显示；双击节点聚焦其参数；
- `F5` / 工具栏 Run 按钮异步执行流程：运行中禁止编辑，日志逐节点输出耗时（毫秒），大点云不卡界面。

## 功能清单
- 过滤器：移除无效点、体素/随机下采样、Z 范围过滤
- 分割/聚类：多平面检测、DBSCAN、欧几里得聚类
- ROI：`Box ROI`（输出裁剪点云 + region 端口）、`ROI Crop`；3D 视窗工具栏
  “ROI”按钮用 vtkBoxWidget2 交互框选，范围实时写回选中 Box ROI 节点参数
- 多视窗：`Display 3D` 节点按 `viewport` 参数把输出路由到命名视窗（自动创建
  dock），View 菜单可手动添加 3D 视窗
- 方案管理：File → Save/Open Solution，`*.pcsearch.json` 保存节点、参数、
  连线与画布位置
- 端口类型：cloud / region / any，类型不符禁止连线（SDK 层同样生效）

## 命令行（自动化/冒烟）
```powershell
pcsearch_app.exe --smoke <ply>                 # 无头链路测试，退出码 0/1
pcsearch_app.exe --demo <ply> [--autoquit N]   # 演示链路 + N 秒后自动退出
pcsearch_app.exe --autoquit N                  # 普通启动 N 秒后退出
```
