# MultiCameraCalibration 代码审查 v3 — src/core/ 核心算法模块问题清单

> 审查日期: 2026-08-07
> 审查范围: `src/core/` 全部 16 个模块（camera_manager / calibration_engine / calib_board_detector / pose_graph / chain_stitcher / mobile_chain_workflow / fixed_multi_cam_workflow / station_manager / offline_session / frame_data / point_cloud_processor / marker_detector / stitch_engine / session_manager / workflow_base / utils）
> 方法: 逐行阅读 + 数值实验复现（conda rvc 环境，合成数据实测）
> 历史对照: v1（7/23）Bug1~5、v2（7/23）Bug1~6 均已修复，本报告不复述旧结论

---

## 一、真实 Bug（已用数值实验复现）

### Bug 1（严重）: `pose_graph.py:242-243` — PoseGraph.add_edge 邻接表方向存反，get_transform 返回真值的逆

**位置**: `src/core/pose_graph.py:242-243`（add_edge 内 `_adjacency` 更新）

```python
self._adjacency.setdefault(from_id, []).append((to_id, T_inv))   # 应为 T
self._adjacency.setdefault(to_id, []).append((from_id, T))       # 应为 T_inv
```

**问题描述**: `PoseEdge.T` 的语义是 from→to（`p_to = T @ p_from`），但邻接表里存反了：从 from 走一步到 to 应使用 from→to = T，代码却存了 `T_inv`（to→from）；反过来 to→from 应存 `T_inv`，代码却存了 `T`。

**为什么是问题**: 数值实验实锤：设真值 T_2to1 = rotz(10°)+平移[50,20,0]，`get_transform('station_2','station_1')` 返回 [-52.7,-11.0]（= 真值的逆），把 station_2 坐标的点变换到 station_1 系误差达 112.6mm。而模块级 `find_path_transform`（`_build_adjacency`）方向正确，两者结果不一致——同一变换在两套 API 下互为逆。现有测试只验证了自洽性（test_chain_stitcher.py [5] 只验复合关系）、test_chain_stitcher.py:121-127 的期望值 `inv(station_poses[idx])` 本身也是反的，所以测试全部通过却验不出方向错误。

**影响**: `ChainStitcher.add_frame:138` 的 `node.T_world` 全反（机位在 3D 预览/位姿显示中位置错误）；`optimize_global_ba` 失败回退的 `_bfs_spanning_tree` 输出全反；任何未来用 `pose_graph.get_transform` 变换点云的调用都会得到错误结果。当前端到端拼接点云走 `calibration_engine.find_path_transform`（正确），因此最终点云恰好没受影响——这是该 bug 一直没暴露的原因。

**改进建议**: 修正为 `adj[from_id] ← (to_id, T)`、`adj[to_id] ← (from_id, inv(T))`；并给 test_chain_stitcher.py 增加几何方向断言（用随机点验证 `p_to = T @ p_from`，参照 test_core.py:303-311 的做法）。

---

### Bug 2（严重）: `chain_stitcher.py:103,124-130` — 配准失败的机位残留 nodes，后续帧可触发未捕获 ValueError 崩溃

**位置**: `src/core/chain_stitcher.py:103`（`self.nodes[station_id] = node` 提前入 dict）、`:124-125` 与 `:129-130`（失败路径不清理）、`:138`（`get_transform` 调用）

**问题描述**: `add_frame` 第一步就把新机位写入 `self.nodes`，但配准失败（无足够共有标记 / 质量门限不过）时直接 `return False`，**不删除该节点**。这些失败节点没有 pose_graph 边。之后某帧与残留节点成功匹配 → `add_edge` 成功 → 第 138 行 `get_transform(new, ref)` 在 BFS 中走到死胡同 → `pose_graph.py:257` 抛出未捕获 `ValueError("位姿图中找不到终点")`。

**复现**: 实测复现——station_1 设为参考；station_2 无共有标记（配准失败，但 nodes 残留）；station_3 与 station_2 有 8 个共有标记 → `add_frame(station_3)` 直接抛 `ValueError` 崩溃。

**为什么是问题**: 单相机移动链式拼接的典型操作就是"拍了不合适的机位 → 重拍"，一旦出现一次失败帧，下一帧就可能崩溃；且 `detect_loop_closure` 的"最近 3 个机位"窗口也被残留节点污染。`MobileChainWorkflow.capture_station` 失败时只调了 `station_manager.remove_station`（mobile_chain_workflow.py:133），没有清理 ChainStitcher。

**改进建议**: `add_frame` 失败路径（两处 return False）前补 `self.nodes.pop(station_id, None)`；或改为"先配准成功再入 dict"。同时让 `MobileChainWorkflow.capture_station` 失败时调用一个统一的 `chain_stitcher.remove_node(station_id)`。

---

### Bug 3（严重）: `calib_board_detector.py:236` — blobColor=255 只认亮斑，黑圆白底标准标定板检测失败

**位置**: `src/core/calib_board_detector.py:236`（`params.blobColor = 255`）

**问题描述**: `SimpleBlobDetector` 配置了 `filterByColor=True, blobColor=255`，即只检测"比背景亮的斑点"。标准非对称圆标定板（OpenCV 官方 4x11 板及绝大多数市售板）是**黑圆白底**——圆是暗斑，会被 blobColor=255 直接过滤。

**为什么是问题**: 数值实验实锤：合成一张黑圆白底的 4x11 非对称网格图，用当前配置 `findCirclesGrid` 返回 `found=False`；同一张图反色（白圆黑底）即可检测。意味着用户按标准板印刷标定板时，标定板检测/位姿法标定整条链路在真实场景失效（除非板子是白圆黑底的特殊印刷）。

**改进建议**: 改为 `params.blobColor = 0`（暗斑）或 `filterByColor=False` 让 OpenCV 自适应；建议在文档/UI 中注明支持的板子配色，并在 README 标定板章节加一句"黑圆白底/白圆黑底均可"。

---

### Bug 4（中等）: `calib_board_detector.py:411-416` — 固定"从右到左逐列"排列在板子旋转 180° 时对应错位，且无 RMS 门限拦截

**位置**: `src/core/calib_board_detector.py:411-416`（`_build_object_points` 列循环 `range(cols-1, -1, -1)`）

**问题描述**: 实测（OpenCV 4.x + CLUSTERING）：板子正放时 `_build_object_points` 的"列从右到左、列内从上到下"顺序与 `findCirclesGrid` 输出**逐点一致（误差 0.000px）**——v2 报告说"应改行优先"其实不适用于当前 OpenCV 版本，现状是正确的。**但**：把板子旋转 180° 再检测，OpenCV 输出顺序整体翻转（k=0 从最右列变最左列，错位 400px=10 个列距），与固定 obj 排列完全失配。SVD Kabsch 在错误对应下解出的 `T_board_in_cam` 错误，而 `detect()` 对 `_solve_board_pose` 的 RMS 重投影误差**不做任何门限校验**（calib_board_detector.py:139-141 只判 None），错误位姿被直接当作成功结果返回，污染后续位姿法标定。

**为什么是问题**: 用户拿起板子换方向、旋转 180° 拍摄是极常见的操作。错位对应 + 无误差校验 = 静默产出错误外参，且 UI 只显示 RMS 数字不提示异常。

**改进建议**: (1) 对 `_solve_board_pose` 结果加 RMS 合理性门限（如 >0.5mm 视为失败）；(2) 检测到 RMS 超标时尝试 4 种排列（正常/转置/左右翻/上下翻）取最小 RMS 者；(3) 更稳的做法：用 3D 圆心的几何最近邻关系重建行列索引（不依赖 OpenCV 输出顺序），或至少把 `_detect_pattern`（`:260-261`，注释"行优先从左到右"）与 `_build_object_points`（`:400-404`，注释"从右到左逐列"）两处互相矛盾的注释统一改对。

---

## 二、残缺功能（未实现 / 半实现）

### F1（中等）: `mobile_chain_workflow.py:226-237` + `chain_stitcher.py:149-156` — 全局 BA 结果未真正用于拼接输出

`optimize_global` 调用 `optimize_global_ba` 后只把优化位姿写进 `node.T_world`，而 `get_merged_pointcloud` 仍走 `stitch_engine.stitch → calibration_engine.get_transform`（pair_results 链式 BFS），**完全忽略 BA 结果**。用户点"全局优化"后看到的点云没有任何变化——"消除累积漂移"的功能实际未生效（仅 3D 显示层可能变化）。建议：BA 后把优化位姿写回 `calibration_engine.pair_results` 的对应边（或让 stitch 支持位姿图直查），并实测验证优化前后拼接误差。

### F2（中等）: `chain_stitcher.py:215` — 边质量字段语义混淆：common_markers 实为 inlier_count

`_try_register` 里 `common_markers=result['inlier_count']`，即"内点数"而非"共有标记总数"。导致 `min_common_markers=6` 门限实际卡的是内点数；而 `detect_loop_closure`（`:194`）用的是原始 code 交集 ≥6——两处标准不一致，同一次拍摄可能配准被拒但闭环提示通过。建议 ChainEdge 同时携带 `total_common` 与 `inlier_count`，门限用 total_common、质量评级用 inlier_ratio。

### F3（中等）: `station_manager.py`（全文 188 行无 load 方法）+ `offline_session.py:91-98` — 站位会话不可重放

StationManager 只有 new_session/capture/remove，**没有 load_session**；OfflineSession._list_frame_dirs 只匹配 `frame_` 前缀目录，`station_*` 目录无法被加载。单相机移动链式拼接的会话落盘后无法重新载入复盘（与《两种拼接方式改进方案》的"可重放会话"承诺不符）。建议为 StationManager 增加 load_session（读取 stations 目录 + meta.json 重建站位），或在 OfflineSession 中兼容 station_ 前缀。

### F4（轻微）: `session_manager.py:118-133` — save_frame 目录格式与 StationManager 不一致

`save_frame` 在 `stations/` 下用 `frame.save(frame_dir)`（独立目录模式）生成 `frame_0001_cam/` 子目录，而 StationManager 生成的是 `station_1/station_1.png` 共享目录格式——同一份设计文档两种实现，且 SessionManager 没有对应的帧级 load 路径。建议统一为一种格式并补 load。

### F5（轻微）: `fixed_multi_cam_workflow.py:110-127` — detect_markers 不回写 board_pose / board_rms_mm

`FixedMultiCamWorkflow.detect_markers` 只写 `frame.markers`，不把 `marker_detector.last_board_result` 的 `T_board_in_cam`/`rms_mm` 写回 FrameData；而 `OfflineSession.detect_all`（offline_session.py:254-265）做了。同一检测逻辑两条路径行为不一致，工作流路径下位姿法标定数据缺失（`_on_calibrate_pair_board_pose` 拿不到 board_pose 会直接提示失败）。建议复用同一段回写逻辑。

---

## 三、健壮性缺陷

### R1（中等）: `pose_graph.py:330-342, 385-389` — BA 残差量纲不均衡 + _se3_log 在 θ→π 处数值奇异

1. 残差向量直接把旋转（弧度，量级 ~1e-3）和平移（mm，量级 ~1e2）拼接进同一最小二乘，平移项主导成本函数，旋转误差基本不被优化——需要按边/按分量加权（信息矩阵）或分开归一化；
2. `_se3_log` 在旋转接近 180° 时 `theta/(2*sin(theta))` 分母趋零 → 残差 NaN/inf → LM 失败 → 静默回退 BFS 生成树（用户无感知）。建议 θ→π 时改用矩阵对数（eigen 分解）或给 theta 接近 π 的残差加保护。

### R2（中等）: `camera_manager.py:585-596, 572-583` — capture()/capture_2d_preview() 不递增 _frame_counter，连续单拍 frame_id 重复

`capture_all` 每轮 +1 没问题，但单独 `capture(cid)`（单拍按钮、顺序拍摄 `_on_capture_sequential`）复用同一 `_frame_counter`：同一轮各相机同号（可接受），**不同轮次也同号**。后果：若把帧交给 `OfflineSession.add_frame`（同 camera_id+frame_id 去重替换，offline_session.py:128-134）会静默丢帧；`stitch_all` 按 frame_id 分组会把不同时刻的帧并成一组。UI 目前靠 main_window.py:1664-1667 手工重排 `_session_capture_seq` 掩盖（注释"在线各相机 frame_id 各自计数，无法直接对齐"正是此问题的痕迹）。建议 `capture()` 每次 +1、`capture_all` 拍完再 +1 并统一分配同号。

### R3（中等）: `calibration_engine.py:344-345` — calibrate_multi_frame 全帧失败时残留旧的 pair_results

多帧标定循环里每次 `calibrate_pair` 成功都会写 `pair_results[key]`；若本次全部帧失败，函数返回 success=False **但不清理** pair_results 中上一次标定的旧结果 → `is_calibrated` 仍返回 True，UI 显示旧外参并可能继续拼接。建议失败路径 `pair_results.pop(key, None)`。

### R4（中等）: `calibration_engine.py:90-92` — _match_markers 不过滤 NaN 3D 点（标定板模式下必现）

标定板检测把无效 3D 圆心以 NaN 留在 markers 里（`valid_3d=False`）。`_match_markers` 按 code 取点不做有限性过滤：≥6 对时 RANSAC 能把 NaN 点排到内点外（侥幸可用）；**<6 对时走非 RANSAC 分支，NaN 直接进 SVD → 返回"RANSAC 后内点不足"误报失败**。建议 `_match_markers` 或 `calibrate_pair` 入口先 `np.isfinite` 过滤，并同步过滤 common_codes。

### R5（中等）: `mobile_chain_workflow.py:169-184` — 删除/撤销机位不更新 pose_graph

`_remove_station_from_chain` 只删 `chain_stitcher.nodes/edges`，pose_graph 的 `_adjacency`/`edges`/`nodes` 残留已删机位：后续 BFS 可能绕道已删节点（路径/变换错误），BA 会把幻影节点纳入优化。建议删除时同步清理 pose_graph（或给 PoseGraph 加 remove_node/remove_edge）。

### R6（轻微）: `marker_detector.py:239-257` — 编码圆 3D 提取为单像素查表，无插值、int() 截断

中心像素在 PointMap 中为 NaN 时标记被直接丢弃（邻居像素有效也救不回），与标定板检测器的双线性插值（calib_board_detector.py:307-364）不一致；`int(m['x'])` 截断而非 round，有 1px 偏差。建议复用 `_extract_centers_3d` 的插值逻辑。

### R7（轻微）: `calibration_engine.py:435` — get_transform 求逆无 LinAlgError 保护

v1 Bug5 只修了 pose_graph._build_adjacency；`get_transform` 的 `np.linalg.inv`（:435）遇奇异矩阵（如载入的坏标定文件）仍会抛异常打断拼接。StitchEngine.stitch:67-72 已包 try/except 可兜底，但其他调用方没有。建议同样包 try 并返回 None/抛带上下文的错误。

### R8（轻微）: `pose_graph.py:237-243` — add_edge 遇不可逆矩阵时状态不一致

`self.edges.append(edge)` 在求逆之前执行；求逆失败 return 后 edge 已进列表但邻接表/节点未更新，后续 get_edge_quality 能查到一条"幽灵边"。建议先求逆再 append。

### R9（轻微）: `frame_data.py:106-120` — cv2.imwrite / SaveWithImage 返回值未检查

图像/点云落盘失败（磁盘满、权限）被静默吞掉，meta.json 却可能写"has_pointcloud: True"（has_pointcloud 在保存尝试之后求值，若 SaveWithImage 失败 offline_pointmap_path 为 None 则 False，但 imwrite 失败时 offline_image_path 仍会被赋路径——自相矛盾）。建议检查返回值并在失败时告警/抛错。

### R10（轻微）: `calibration_engine.py:473-489` — load_calibration 无 T 形状/数值校验

载入的 JSON 里 T 可能是错误形状/非数值/奇异矩阵，直接进 pair_results 后下游崩溃。建议校验 4x4 + 有限值 + 行列式非零。

### R11（轻微）: `offline_session.py:243-245` — detect_all 从磁盘读图后不释放，大会话内存持续增长

`frame.image_np = cv2.imread(...)` 后处理完不置 None，N 帧 × M 相机图像常驻内存。建议检测完释放（markers 已回写磁盘）。

### R12（轻微）: `point_cloud_processor.py:164-170` — auto_tune 单位判定在 10~100 区间靠猜

包围盒对角线 10~100 之间以 50 为界猜"米/毫米"：一个真实尺寸 30mm 的微缩场景会被判定为米单位，所有参数放大 1000 倍。建议增加更明确的判别（如点距量级、Z 范围）或让调用方显式传单位。

---

## 四、代码质量 / 潜在陷阱

| # | 位置 | 问题 |
|---|---|---|
| Q1 | `calibration_engine.py:103` | `calibrate_pair` 默认 `ransac_threshold=0.002`（米）与全项目 mm 数据不符，所有调用点都靠显式传 2.0 兜底——API 默认值是个坑，建议默认改 2.0 或按单位参数化 |
| Q2 | `calibration_engine.py:256-258` | `calibrate_pair_by_board_pose` 的 `min_mm=0.0`、`mean_mm=rms_mm` 是编造的统计量，质量评分会被误导（建议只保留 rms_mm 并注明统计口径） |
| Q3 | `calib_board_detector.py:260-261 vs 400-404` | 两处注释对输出顺序的描述互相矛盾（"行优先从左到右" vs "从右到左逐列"），实现是后者且实测正确——注释必须改，否则误导后续维护者"修正"成错误实现（v2 就是这么差点改坏的） |
| Q4 | `chain_stitcher.py:116-122` | 新帧与**全部**历史节点逐一跑 RANSAC（每帧 O(n)×100 次迭代），docstring 声称"最近 N 个+参考"未实现；链变长后每帧耗时线性增长，建议只匹配最近 3~5 个 + 参考 + 闭环候选 |
| Q5 | `pose_graph.py:324-327` | BA 初值用 self.nodes（默认全单位阵）而非 BFS 复合结果，大旋转/大平移场景易陷入局部最优；建议用 `_bfs_spanning_tree` 结果做 x0 |
| Q6 | `pose_graph.py:344-355` | optimize_global_ba 结果不写回 nodes/adjacency，调用方需手动同步；建议方法内部更新图状态或明确返回语义 |
| Q7 | `fixed_multi_cam_workflow.py:233-237` | `_check_calibration_quality` 直接 `res['rms_mm']`，载入不含该字段的旧 JSON 会 KeyError |
| Q8 | `marker_detector.py:135-140` | 浮点图像 >255 时 `astype(uint8)` 取模截断（300.0 → 44）；建议先 clip |
| Q9 | `calib_board_detector.py:203-210` | 浮点图像进 `_adjust_gamma` 时 `astype(np.uint8)` 直接截断（[0,1] 浮点全变 0 → 黑图检测失败），建议入口统一 dtype 归一化 |
| Q10 | `marker_detector.py:219-224` | 检测失败时每次在 CWD 写 `debug_detect_*.png`，磁盘垃圾累积，建议限频/可配置 |
| Q11 | `camera_manager.py:598-615` | capture_all 的 sync 参数无实际行为差异（文档已说明预留），建议要么实现硬件同步要么移除参数 |
| Q12 | `station_manager.py:66-85` | new_session 归档旧会话永不清理，长期运行磁盘膨胀，建议加保留策略 |
| Q13 | `utils.py:13` | LOG_FILE 是相对路径，从不同 CWD 启动程序日志落点不同，建议基于可执行文件目录 |
| Q14 | `fixed_multi_cam_workflow.py:219` | `o3d.io.write_point_cloud` 返回值未检查，保存失败无提示 |

---

## 五、已知架构问题（已在《两种拼接方式改进方案.md》覆盖，本报告不展开）

- StationManager 把"多相机标定"与"单相机链式拼接"伪装成同一流水线；
- `pose_graph.optimize_global`（模块级）仅是 BFS 生成树，非真全局 BA；
- 撤板重拍会覆盖 frames 字典（方案文档已设计标定/扫描帧分离状态机）。
- v1/v2 报告的全部问题（inlier_count 一致性、Tab 切换、拍摄计数、uint16 精度、pose_graph 吞异常、物点排列、board_rms_mm 丢失、FAST_CHECK 标志、Blob 面积硬编码、标记类型切换兼容性）均已确认修复。

---

## 六、优先级建议

### P0（必修，阻塞正确性）
1. **Bug 1** pose_graph.py:242-243 邻接表方向存反 → 修正并补几何方向测试
2. **Bug 2** chain_stitcher.py:103/124-130 失败机位残留 → 失败即清理 + 工作流侧同步
3. **Bug 3** calib_board_detector.py:236 blobColor=255 → 改 0 或关 filterByColor（先确认实际板子配色）

### P1（尽快，影响可用性/精度）
4. **Bug 4** 板子旋转 180° 顺序错位 → RMS 门限 + 多排列尝试（或 3D 几何重建索引）
5. **F1** BA 结果接入实际拼接输出（否则"全局优化"是摆设）
6. **R1** BA 残差旋转/平移加权 + _se3_log 近 π 保护
7. **R2** capture() 递增 _frame_counter，去掉 UI 手工重排 workaround
8. **F3/R5** 站位会话可重放 + 删除机位同步清理 pose_graph
9. **R4** _match_markers 过滤 NaN 点
10. **F2** ChainEdge 区分 total_common / inlier_count，统一门限语义

### P2（打磨）
11. **R3** 多帧标定失败清残留 pair_results；**R7** get_transform 求逆保护
12. **Q1** 默认阈值改 2.0；**Q3** 统一排列注释；**Q4** 最近 N 机位匹配
13. **F4/F5** 会话目录格式统一、工作流回写 board_pose
14. 其余轻微项（R6-R12、Q2、Q5-Q14）按需处理

---

*审查结论: 核心标定/拼接主链路（CalibrationEngine 单帧标定、find_path_transform、StitchEngine、PointCloudProcessor）经数值验证是正确的；问题集中在 2026-08 新增的 PoseGraph 类方向约定、ChainStitcher 状态管理、标定板检测器的配色/朝向假设三处。*
