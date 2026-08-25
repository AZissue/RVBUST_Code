# STATUS.md — 进度状态（每次会话结束必须更新）

> 最后更新：2026-08-25
> 只保留“当前快照”，不积累历史；旧条目删除即可，git 历史里仍可追溯。

## ⏭ 交接块（新会话先读这里）
- 当前状态：阶段 2「节点逐个完善」进行中；**当前主线：ROI BOX 节点完善**。
  基准流程「点云加载 → Box ROI → 保存点云」已跑通；ROI 交互（拖移 / 缩放 /
  旋转）、重置包围盒、显示降采样、保存“文件夹 + 文件名”均已完成。
- 本轮：ROI 交互升级——①单面缩放启用（MoveFaces，抓面沿法向放大缩小），去掉
  右键整体缩放（原“往哪滑都缩”）；②选中 box_roi 自动进入编辑（免再点 ROI 按钮）；
  ③关闭米字线（OutlineFaceWires/CursorWires），外框线宽 2.0→1.2px、面透明度
  0.15→0.06（去遮挡）。已构建 + `ctest` 6/6 全绿 + smoke + demo 冒烟通过。
- 下一步：ROI 包围盒样式自定义——三色边框（X红/Y绿/Z蓝）+ 只留 XYZ 三轴
  （vtkBoxWidget2 无法原生按轴分色，需叠加自定义线框/轴，待确认编辑态手柄方案）。
- 正在进行的文件：`app/src/roi_selector.cpp`、`app/src/main_window.cpp/.h`
- 卡点 / 风险：ROI 交互/样式为 VTK 行为，QtTest 无法断言，只能手动验证；
  核显 / 远程桌面场景必须保持显示降采样。
- 远程协作：项目已上传 `github.com/AZissue/RVBUST_Code` 的 `pointcloud-search`
  分支（main 总览 README 已登记）；本地 master 跟踪 `origin/pointcloud-search`，
  提交后直接 `git push`。本机 GitHub 直连超时，需走代理：
  http `127.0.0.1:10809` / socks5 `127.0.0.1:10808`。
- 上次会话结束已提交：是（已 push 到 `origin/pointcloud-search`；本轮双盒修复已提交）

## ✅ 已完成（近期；更早历史见 git）
- [x] 2026-08-25 修复本地一键构建：CMake 复用 RvcVisionStudio 自编译 VTK（带 GUISupportQt）解决 PCL 1.13.0 捆绑 VTK 缺 Qt 支持问题；start.bat 自动探测本机 Qt/PCL 路径；ctest 6/6 + autoquit 冒烟通过
- [x] 2026-08-25 ROI 交互升级：单面缩放(MoveFaces)、去掉右键整体缩放、选中
  box_roi 自动进入编辑、关闭米字线、外框细化(线宽 1.2px/面 0.06)；构建/ctest/smoke/demo 通过
- [x] 2026-08-25 修复 ROI 操控“双包围盒”：box_roi 编辑态只显示 vtkBoxWidget2
  交互框，隐藏静态预览框，退出编辑恢复预览；构建 / ctest / smoke / demo 通过
- [x] 2026-08-25 补齐 random_downsample / euclidean_cluster / plane_detect 节点级
  E2E 单测（走 Graph 全链路 + source_indices 溯源）；`ctest` 6/6 全绿
- [x] 2026-08-25 项目文档按新模板迁移（AGENTS / PROJECT / PLAN / STATUS +
  docs/SESSION_PROMPTS.md）；git 初始化基线提交
- [x] 2026-08-24 Box ROI 全套：OBB 旋转、8 角点位姿读取、重置包围盒（AABB，
  跳过 NaN/Inf）、拖动松手才刷新（不卡顿不刷屏）
- [x] 2026-08-24 显示降采样 ≤150 万点 + 单精度顶点；QThread 取消机制；
  File 参数类型闪退修复
- [x] 2026-08-24 保存节点改为“输出文件夹 + 文件名”，auto → PLY、自动建目录
- [x] 2026-08-20 画布交互（连线跟随 / 右键删除断开 / 背景风格）、默认中文 +
  Dark、方案 JSON、多视窗

## 🚧 进行中
- 阶段 2（主线 ROI BOX）：节点级 E2E 已补齐；本轮完成 ROI 交互升级（单面缩放 /
  自动进入编辑 / 去米字 / 细化）；剩「三色边框 + XYZ 三轴」样式自定义 + 手动验证。

## 🐛 已知 BUG / 问题
| 问题 | 状态 | 备注 |
|---|---|---|
| 本机 ctest 直启 QtTest 卡死（PCL DLL ALPC 等待） | 已绕开 | `cmake -P` 包装 + 显式 PATH；换机器需复查 |
| 端口圆心贴节点边缘，精确点击可能不命中 | 已缓解 | boundingRect +4px；点圆内部即可 |
| 右键断开菜单 `menu.exec` 阻塞，QtTest 未覆盖 | 搁置 | 仅直接调用 removeEdge 的用例 |
| 切换语言后部分控件不即时重刷 | 搁置 | 低优先级 |
| 参数枚举值保持英文 | 设计取舍 | 非 BUG |
| `rot_y=±90°` 欧拉角万向锁（角度跳变，裁剪正确） | 已定位 | 后续可换四元数 |
| ROI 交互回归只能手动验证 | 已知 | 手动测试清单：加载 → 框选 → 拖 / 缩 / 旋转 → 重置 → 保存 |
| 关窗时单节点执行 >30s 会阻塞等待 | 已定位 | 取消在节点间生效，单节点内不可中断 |

## ❌ 已尝试但失败的方案（附原因，防止重复踩坑）
| 方案 | 失败原因 | 当时条件（版本 / 环境） | 结论是否仍有效 |
|---|---|---|---|
| ctest 直启 QtTest exe | 进程卡死（ALPC） | 本机 PCL 加载 | 是（换机器复查） |
| `cmd /c` 作为 ctest 命令 | 引号拼接语法错 | ctest CreateProcess | 是 |
| `windeployqt --no-compiler-runtime` | 仍带旧 MSVC 运行库 | Qt 6.8.3 | 是（POST_BUILD 清理） |
| Qt6_DIR 两级路径找 bin | 指向 lib/bin | Qt 6.8.3 | 是（三级） |
| 拖拽连线 `scene->items()` 命中 | 边界不稳定 | 画布 v1 | 是（改端口距离吸附） |
| `GetTransform` 读取盒子中心 | GetPosition = R·c 偏 | VTK 9.4 原点居中放置 | 是（改 8 角点） |
| std::min/max 全量算包围盒 | NaN/Inf 污染 | RVC 点云空洞 | 是（改 allFinite） |
| 参数默认只写 description | 实际默认 0 / 类型错 | Params v1 | 是（加 default_value） |
| 直接销毁运行中 QThread | Qt6 fail-fast 0xC0000409 | 5M 流程中退出 | 是（加取消 + wait） |
| 保存单“输出路径”框 | 文件夹被当文件名 | 保存节点 v1 | 是（拆文件夹 + 文件名） |

## 🧭 近期技术决策（永久记录在 PROJECT.md 第 7 节）
- 2026-08-18 ~ 2026-08-25 的决策已全部归档到 PROJECT.md §7 ADR 表，此处不重复。

## ▶️ 下一步任务
- [ ] 平面检测节点 E2E（加载 → 平面检测 → 保存 / 3D），补单测
- [ ] DBSCAN / 欧几里得聚类节点 E2E，补单测
- [ ] Z 过滤 / 体素 / 随机下采样节点 E2E，补单测
- [ ] ROI Crop 节点 E2E（消费 region 端口）
- [ ] 每完成一个节点：更新交接块并本地提交

## 📦 清理规则
- 已完成且不再需要关注的条目，从本文件删除（git 历史可追溯）；只保留交接块、
  近期已完成、进行中、问题 / 失败表、下一步任务。
