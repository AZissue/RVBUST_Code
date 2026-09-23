# -*- coding: utf-8 -*-
"""
MultiCameraCalibration UI 包（Phase 3）。

三栏布局（参考 DualCameraFusion，泛化为 N 相机）：
  - 左：CameraPanel      —— 相机管理 + 采集控制
  - 中：相机预览卡片网格 + 嵌入式 3D 查看器（可折叠）
  - 右：QTabWidget       —— CalibrationPanel / StitchPanel
  - 底：可折叠日志面板

⚠️ Phase 0（原型 UI 复用主程序拆分批）：
本文件**不再 eager 重导出子模块符号**。历史写法在 `import ui` 时即连带导入
`viewer_3d`（open3d）/ `panels.*` / `main_window` 整条链，使得 `ui_v2.theme`
这类轻量入口付出 2057 模块 / ~2.1s 的导入代价。

消费者一律直接导入子模块（全仓已无 `from ui import <符号>`）：
    from ui.camera_card import AspectRatioLabel
    from ui.viewer_3d import EmbeddedPointCloudViewer
"""

__all__ = []
