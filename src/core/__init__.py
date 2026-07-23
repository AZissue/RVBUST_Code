# -*- coding: utf-8 -*-
"""
core 包：与 UI 无关的核心算法层。

模块：
  - frame_data           帧数据封装（在线/离线双模式）
  - camera_manager       N 相机管理（软触发同步/异步拍摄）
  - marker_detector      编码圆 2D 检测 + 3D 提取
  - calibration_engine   N 相机外参标定（星型拓扑）
  - point_cloud_processor 点云裁切/下采样/滤波
  - pose_graph           链式拓扑 BFS 复合 + 全局优化预留（Phase 2）
  - stitch_engine        N 相机点云拼接引擎（Phase 2）
  - offline_session      N 相机离线会话：保存/加载/批量检测/标定/拼接（Phase 4）
  - utils                日志 + 安全资源释放
"""
