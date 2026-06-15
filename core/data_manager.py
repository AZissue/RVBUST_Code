"""
采集数据管理模块。
负责：会话状态管理、采集记录的增删改查、HandEyeManager.exe 兼容格式的文件导出、JSON 备份/恢复。
"""

import json
import os
from datetime import datetime
from collections import namedtuple

from PyQt5.QtCore import QObject, pyqtSignal

# 命名元组：单次采集的完整数据记录
CaptureRecord = namedtuple(
    "CaptureRecord",
    [
        "index",               # 序号（1-based）
        "png_path",            # PNG 图像文件路径
        "ply_path",            # PLY 点云文件路径
        "camera_target_xyz",  # 相机坐标系下的目标点坐标（格式: "x y z"）
        "robot_capture_pose",  # 拍照时的机器人位姿（格式: "x y z rx ry rz"）
        "robot_target_xyz",   # TCP 戳点的机器人坐标（格式: "x y z"）
    ],
)


class DataManager(QObject):
    """采集数据管理器"""

    # 信号定义
    progress_updated = pyqtSignal(int, int)    # (当前数量, 目标数量)
    data_changed = pyqtSignal()                # 数据变更通知
    record_loaded = pyqtSignal(object)         # 加载了某条记录

    RECOMMENDED_COUNT = 15  # 推荐采集数据组数

    def __init__(self, parent=None):
        super().__init__(parent)
        self._records = []        # 所有采集记录列表
        self._save_dir = ""       # 当前会话数据保存目录
        self._backup_dir = ""     # 备份子目录
        self._current_index = -1  # 当前浏览的序号（-1 表示查看最新/未保存帧）
        self._eye_in_hand = False
        self._marker_type = True

    # ── 会话管理 ──────────────────────────────────────────

    def new_session(self, base_dir, eye_in_hand, marker_type):
        """
        创建新的采集会话。
        base_dir: 数据保存的基目录（如 ./data）
        实际在 base_dir 下创建带时间戳的子目录: calibration_data_YYYYMMDD_HHMMSS
        """
        # 生成时间戳目录名，避免不同会话数据混在一起
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._save_dir = os.path.join(base_dir, f"calibration_data_{ts}")
        self._backup_dir = os.path.join(self._save_dir, "backup")
        self._eye_in_hand = eye_in_hand
        self._marker_type = marker_type

        # 重置所有状态
        self._records = []
        self._current_index = -1

        # 创建输出目录和备份子目录
        os.makedirs(self._backup_dir, exist_ok=True)
        self.data_changed.emit()

    @property
    def save_dir(self):
        """返回当前会话的数据保存目录"""
        return self._save_dir

    @property
    def mode(self):
        """返回当前标定模式 (eye_in_hand, marker_type)"""
        return self._eye_in_hand, self._marker_type

    # ── 记录的增删改查 ──────────────────────────────────

    def add_record(self, png_path, ply_path, camera_target_xyz, robot_capture_pose,
                   robot_target_xyz):
        """
        添加一条新的采集记录。
        自动分配序号（当前记录数 + 1），保存备份 JSON。
        """
        idx = len(self._records) + 1
        rec = CaptureRecord(
            idx, png_path, ply_path, camera_target_xyz,
            robot_capture_pose, robot_target_xyz,
        )
        self._records.append(rec)
        self._current_index = idx - 1
        self.progress_updated.emit(len(self._records), -1)
        self.data_changed.emit()
        self._save_backup()
        return rec

    def update_record(self, index, field, value):
        """
        更新某条记录的字段值。
        index: 1-based 序号
        field: 字段名（如 "camera_target_xyz"）
        value: 新值
        """
        if index < 1 or index > len(self._records):
            return
        rec = self._records[index - 1]
        # 将 namedtuple 转为 dict → 修改字段 → 重建 namedtuple
        fields = rec._asdict()
        fields[field] = value
        self._records[index - 1] = CaptureRecord(**fields)
        self.data_changed.emit()

    def remove_last(self):
        """
        删除最后一条记录（撤销功能）。
        同时删除对应的 PNG 和 PLY 文件。
        """
        if not self._records:
            return False
        rec = self._records.pop()
        # 清理关联的图像和点云文件
        if rec.png_path and os.path.exists(rec.png_path):
            os.remove(rec.png_path)
        if rec.ply_path and os.path.exists(rec.ply_path):
            os.remove(rec.ply_path)
        self._current_index = len(self._records) - 1
        self.progress_updated.emit(len(self._records), -1)
        self.data_changed.emit()
        self._save_backup()
        return True

    def clear_all(self):
        """
        清空所有记录。
        删除所有关联的 PNG 和 PLY 文件。
        """
        for rec in self._records:
            if rec.png_path and os.path.exists(rec.png_path):
                os.remove(rec.png_path)
            if rec.ply_path and os.path.exists(rec.ply_path):
                os.remove(rec.ply_path)
        self._records = []
        self._current_index = -1
        self.progress_updated.emit(0, -1)
        self.data_changed.emit()
        self._save_backup()

    def get_record(self, index):
        """按 1-based 序号获取记录，不存在返回 None"""
        if index < 1 or index > len(self._records):
            return None
        return self._records[index - 1]

    def get_count(self):
        """返回当前记录总数"""
        return len(self._records)

    def get_current_index(self):
        """返回当前浏览的序号（1-based），无记录时返回 0"""
        return self._current_index + 1

    def all_records(self):
        """返回所有记录的列表（只读副本）"""
        return list(self._records)

    # ── 数据文件导出（HandEyeManager.exe 兼容格式）────

    def write_handeye_output(self):
        """
        按 HandEyeManager.exe 期望的格式写出数据文件。
        标记物模式: 文件已存在 (N.png, N.ply)，只需写 pose.txt。
        戳点模式: 写 cameraCapturePointXyz.txt, [cameraCaptureRobotPose.txt], tcp.txt。
        """
        if not self._records:
            return False

        if self._marker_type:
            self._write_marker_output()
        else:
            self._write_tcp_output()
        return True

    def _write_marker_output(self):
        """
        标记物标定模式输出:
        pose.txt — 每行一个机器人位姿，格式: x y z rx ry rz
        PNG/PLY 文件已经以序号命名保存在目录中。
        """
        pose_path = os.path.join(self._save_dir, "pose.txt")
        with open(pose_path, "w", encoding="utf-8") as f:
            for rec in self._records:
                f.write(f"{rec.robot_capture_pose}\n")

    def _write_tcp_output(self):
        """
        TCP 戳点标定模式输出:
        - cameraCapturePointXyz.txt: 每行 "x y z"，相机坐标系下的目标点
        - tcp.txt: 每行 "x y z"，TCP 戳点在机器人坐标系下的坐标
        - cameraCaptureRobotPose.txt (仅眼在手上): 每行拍照时的机器人位姿
        """
        camera_xyz_path = os.path.join(self._save_dir, "cameraCapturePointXyz.txt")
        tcp_path = os.path.join(self._save_dir, "tcp.txt")

        with open(camera_xyz_path, "w", encoding="utf-8") as f_cam:
            for rec in self._records:
                f_cam.write(f"{rec.camera_target_xyz}\n")

        with open(tcp_path, "w", encoding="utf-8") as f_tcp:
            for rec in self._records:
                f_tcp.write(f"{rec.robot_target_xyz}\n")

        # 眼在手上模式还需要机器人拍照位姿文件
        if self._eye_in_hand:
            robot_pose_path = os.path.join(
                self._save_dir, "cameraCaptureRobotPose.txt"
            )
            with open(robot_pose_path, "w", encoding="utf-8") as f_pose:
                for rec in self._records:
                    f_pose.write(f"{rec.robot_capture_pose}\n")

    # ── JSON 备份与恢复 ─────────────────────────────────

    def _save_backup(self):
        """
        自动保存 JSON 备份。
        每采集一组数据后自动调用，确保意外退出时数据不丢失。
        备份文件保存在 <save_dir>/backup/ 下，按时间戳命名。
        """
        if not self._backup_dir:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(self._backup_dir, f"calibration_data_{ts}.json")
        data = {
            "eye_in_hand": self._eye_in_hand,
            "marker_type": self._marker_type,
            "records": [r._asdict() for r in self._records],  # namedtuple → dict 序列化
        }
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # 清理旧备份：只保留最近 10 份
        self._cleanup_backups()

    def _cleanup_backups(self):
        """
        清理旧备份文件，只保留最近 10 份。
        按文件名倒序排列（最新的在前），删除第 11 个及之后的所有文件。
        """
        if not self._backup_dir or not os.path.isdir(self._backup_dir):
            return
        files = sorted(
            [f for f in os.listdir(self._backup_dir) if f.endswith(".json")],
            reverse=True,
        )
        for f in files[10:]:
            os.remove(os.path.join(self._backup_dir, f))

    def load_backup(self, backup_path):
        """
        从 JSON 备份文件恢复会话状态。
        返回 True 表示恢复成功，False 表示文件格式错误。
        """
        try:
            with open(backup_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._eye_in_hand = data["eye_in_hand"]
            self._marker_type = data["marker_type"]
            self._records = [CaptureRecord(**r) for r in data["records"]]
            self._current_index = len(self._records) - 1
            self.data_changed.emit()
            self.progress_updated.emit(len(self._records), -1)
            return True
        except Exception:
            return False

    def find_latest_backup(self, base_dir):
        """
        在 base_dir 下搜索最新的备份文件。
        用于程序启动时检测是否有未完成的会话。
        """
        candidates = []
        for root, dirs, files in os.walk(base_dir):
            for f in files:
                if f.startswith("calibration_data_") and f.endswith(".json"):
                    candidates.append(os.path.join(root, f))
        if not candidates:
            return None
        # 按文件修改时间排序，取最新的
        return max(candidates, key=os.path.getmtime)
