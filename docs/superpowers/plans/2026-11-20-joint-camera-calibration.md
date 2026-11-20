# 多相机联合标定 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 只指定参考相机，使用所有合格共视约束统一优化外参。

**Architecture:** 保留 CalibrationEngine 的局部测量结果，在独立联合求解模块生成固定锚点的最终节点位姿。自动共视图负责初始化、连通性、全局求解与残差门禁，界面统一入口，旧会话只读兼容。

**Tech Stack:** Python, NumPy, SciPy least_squares, PySide6, unittest。

**Spec:** docs/multi_camera_joint_calibration.md

## Global Constraints

- 正式 UI 使用 ui_v2 / ui_common；不初始化相机、不改源点云、不自动保存用户会话。
- 项目测试放 tests，验证报告放 outputs，显式提交本批文件。
- 本次为现有标定流程渐进升级，使用 PATCH 1.14.50；同步 CHANGELOG。

## Review Focus

- 无直接参考共视、参考位于图中间与双向变换：保持锚点和方向正确。
- 闭环噪声和局部优质但全局矛盾的配对：使用冗余约束，不能假通过。
- 求解异常/非有限/不收敛：显式回退，仅一致的初始化可以通过。
- 序列化节点缺失或变换被篡改：拒绝载入，不污染旧状态。
- 旧会话、离线标定和拼接：载入保留原结果，重新计算采用统一策略。

## Tasks

### 1. 联合求解与外参模型

- [x] 在 tests/test_joint_camera_calibration.py 写连通图、闭环优化、固定锚点、冲突和保存载入测试，确认旧代码失败。
- [x] 新增 src/core/joint_camera_calibration.py；修改 multi_camera_topology.py 和 calibration_engine.py，维护测量边与最终节点位姿。
- [x] 覆盖求解失败回退、恶化拒绝、全局质量门禁及最终变换用于拼接。

### 2. 正式 UI 与会话兼容

- [x] 修改 fixed_multi_cam_workflow.py、session_projects.py、backend_bridge.py 的默认策略与旧结果恢复。
- [x] 修改 multi_cam_workspace.py、industrial_ribbon.py、calibration_inspector.py，统一设置并说明全局结果。
- [x] 更新旧拓扑回归预期，补参考相机设置、旧会话载入和优化报告回填验证。

### 3. 验证与交付

- [x] 定向算法/会话/UI 回归；用凳子四视角会话的私有临时副本验证正式计算；拼接变换使用合成数据验证，不写回原会话。
- [x] 核对全局残差、源数据散列、UI 显示；记录实机未验证项。
- [ ] 版本日志、diff 检查、提交并推送正式分支。
