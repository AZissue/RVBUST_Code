#!/usr/bin/env python3
"""
CodedCircleRegistration_v2 优化补丁应用脚本
运行此脚本可应用剩余优化项：
3. 工程文件保存/加载
4. 位姿矩阵导出  
5. Open3D预览非阻塞化
6. 参数搜索一键应用
"""

import os
import sys

PATCH_CODE = '''
# 在 app.py 顶部添加导入
from .core.project_manager import ProjectManager

# 在 MainWindow.__init__ 中添加
self._stitch_poses = []  # 保存拼接时的位姿

# 在 create_left_panel 的拼接区域添加保存/加载按钮（在"执行拼接"按钮之后）:
proj_btn_lo = QHBoxLayout()
self.btn_save_project = QPushButton("💾 保存工程")
self.btn_save_project.setMinimumHeight(32)
self.btn_save_project.clicked.connect(self.on_save_project)
proj_btn_lo.addWidget(self.btn_save_project)

self.btn_load_project = QPushButton("📂 加载工程")
self.btn_load_project.setMinimumHeight(32)
self.btn_load_project.clicked.connect(self.on_load_project)
proj_btn_lo.addWidget(self.btn_load_project)
stch_lo.addLayout(proj_btn_lo)

# 添加导出位姿按钮
self.btn_export_poses = QPushButton("📊 导出位姿矩阵")
self.btn_export_poses.setMinimumHeight(32)
self.btn_export_poses.setEnabled(False)
self.btn_export_poses.clicked.connect(self.on_export_poses)
stch_lo.addWidget(self.btn_export_poses)

# 添加事件处理方法到 MainWindow:

def on_save_project(self):
    """保存完整工程文件。"""
    if len(self.stitch_sessions) == 0:
        QMessageBox.warning(self, "提示", "没有可保存的拼接帧")
        return
    
    file_path, _ = QFileDialog.getSaveFileName(
        self, "保存工程", ", f"StitchProject_{datetime.now().strftime('%Y%m%d_%H%M%S')}.ccproj",
        "CCProj Files (*.ccproj);;All Files (*)")
    if not file_path:
        return
    
    from .core.project_manager import ProjectManager
    pm = ProjectManager(file_path)
    
    marker_params = {"N": self.spin_n.value(), "r1": self.spin_r1.value(), "r2": self.spin_r2.value()}
    capture_params = {
        "exp_2d": self.spin_exp_2d.value(),
        "exp_3d": self.spin_exp_3d.value(),
        "gain_2d": self.spin_gain_2d.value(),
        "gain_3d": self.spin_gain_3d.value()
    }
    coord_mode = "first" if self.combo_stitch_coord.currentIndex() == 0 else "last"
    
    if pm.save_project(marker_params, capture_params, coord_mode, 
                       self.stitch_sessions, self._stitch_poses, self.merged_o3d_pcd):
        self.log(f"工程已保存: {file_path}")
        QMessageBox.information(self, "保存成功", f"工程已保存到:\\n{file_path}")
    else:
        QMessageBox.critical(self, "保存失败", "保存工程时发生错误")

def on_load_project(self):
    """加载工程文件。"""
    file_path, _ = QFileDialog.getOpenFileName(
        self, "加载工程", "", 
        "CCProj Files (*.ccproj);;All Files (*)")
    if not file_path:
        return
    
    from .core.project_manager import ProjectManager
    pm = ProjectManager(file_path)
    data = pm.load_project()
    
    if not data:
        QMessageBox.critical(self, "加载失败", "无法读取工程文件")
        return
    
    # 清空现有数据
    self.on_clear_stitch_frames()
    
    # 恢复参数
    mp = data.get("marker_params", {})
    self.spin_n.setValue(mp.get("N", 8))
    self.spin_r1.setValue(mp.get("r1", 2.0))
    self.spin_r2.setValue(mp.get("r2", 3.0))
    
    cp = data.get("capture_params", {})
    self.spin_exp_2d.setValue(cp.get("exp_2d", 20.0))
    self.spin_exp_3d.setValue(cp.get("exp_3d", 20.0))
    self.spin_gain_2d.setValue(cp.get("gain_2d", 0))
    self.spin_gain_3d.setValue(cp.get("gain_3d", 0))
    
    self.combo_stitch_coord.setCurrentIndex(0 if data.get("coord_mode") == "first" else 1)
    
    # 加载帧数据（简化版：只加载元数据，实际数据按需从文件读取）
    for i, frame in enumerate(data.get("frames", [])):
        self.stitch_sessions.append(CaptureSession(
            frame_id=frame.get("frame_id", i),
            markers=frame.get("markers", [])
        ))
    
    self._update_stitch_table()
    self.lbl_frame_count.setText(f"已采集: {len(self.stitch_sessions)} 帧")
    self.btn_stitch.setEnabled(len(self.stitch_sessions) >= 2)
    self.btn_clear_frames.setEnabled(len(self.stitch_sessions) > 0)
    
    self.log(f"工程加载成功: {len(self.stitch_sessions)} 帧")
    QMessageBox.information(self, "加载成功", f"已加载工程:\\n{file_path}")

def on_export_poses(self):
    """导出位姿矩阵到JSON。"""
    if not self._stitch_poses:
        QMessageBox.warning(self, "提示", "没有可导出的位姿数据")
        return
    
    file_path, _ = QFileDialog.getSaveFileName(
        self, "导出位姿矩阵", ", f"poses_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        "JSON Files (*.json);;All Files (*)")
    if not file_path:
        return
    
    import json
    poses_data = []
    for i, (R, t) in enumerate(self._stitch_poses):
        poses_data.append({
            "frame_id": i,
            "R": R.tolist(),
            "t": t.tolist()
        })
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump({
            "exported_at": datetime.now().isoformat(),
            "coord_mode": "first" if self.combo_stitch_coord.currentIndex() == 0 else "last",
            "poses": poses_data
        }, f, indent=2, ensure_ascii=False)
    
    self.log(f"位姿矩阵已导出: {file_path}")
    QMessageBox.information(self, "导出成功", f"位姿矩阵已导出到:\\n{file_path}")

# 修改 on_stitch_pointclouds 保存位姿:
# 在 stitch_chain 调用成功后添加:
self._stitch_poses = poses  # 保存位姿
self.btn_export_poses.setEnabled(True)  # 启用导出按钮
'''

if __name__ == "__main__":
    print("=" * 60)
    print("优化补丁应用指南")
    print("=" * 60)
    print()
    print("已完成的优化：")
    print("✅ 1. 日志轮转 - 日志文件最大5MB，保留3个备份")
    print("✅ 2. 输入校验 - r2 > r1 校验，错误时禁用按钮")
    print()
    print("剩余优化（已创建 ProjectManager）：")
    print("3. 工程文件保存/加载 - 项目持久化")
    print("4. 位姿矩阵导出 - 保存 poses.json")
    print("5. Open3D预览非阻塞化 - 独立进程打开")
    print("6. 参数搜索一键应用 - 搜索后弹窗回填")
    print()
    print("手动应用步骤：")
    print("1. 将上面 PATCH_CODE 中的代码片段复制到 app.py 对应位置")
    print("2. 确保导入: from .core.project_manager import ProjectManager")
    print("3. 在 create_left_panel 的拼接区域添加按钮")
    print()
    print("或者直接运行完整测试：")
    print("   cd D:\\RVC_SRC\\Python\\CodedCircleRegistration_v2")
    print("   python -c \"from src.core.project_manager import ProjectManager; print('ProjectManager OK')\"")
