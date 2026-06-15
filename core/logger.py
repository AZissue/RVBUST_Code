"""
操作日志管理模块。
在内存中维护日志条目列表，通过 Qt 信号通知 UI 更新，
同时将日志持久化写入项目 logs/ 目录下的日志文件。
支持四种日志级别：info（信息）、success（成功）、warning（警告）、error（错误）。
"""

import os
from datetime import datetime
from PyQt5.QtCore import QObject, pyqtSignal


# 项目根目录（core/ 的父目录）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOGS_DIR = os.path.join(_PROJECT_ROOT, "logs")

# 级别中文标签映射
_LEVEL_LABELS = {"info": "INFO", "success": " OK ", "warning": "WARN", "error": "ERR "}


class LogManager(QObject):
    """
    日志管理器。
    所有操作（相机连接、采集成功/失败、模式切换等）都通过此类记录。
    通过 log_added 信号通知 UI 侧边栏更新日志显示，
    同时将日志写入 logs/ 目录下的文件中。
    """

    # 信号：新日志条目 (时间戳, 消息, 级别)
    log_added = pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries = []  # [(timestamp, message, level), ...]
        self._log_file = None  # 当前日志文件路径

    def _ensure_log_file(self):
        """确保日志目录和当天的日志文件存在，惰性创建"""
        if self._log_file is None:
            os.makedirs(_LOGS_DIR, exist_ok=True)
            # 按日期命名，避免单个日志文件过大
            date_str = datetime.now().strftime("%Y%m%d")
            self._log_file = os.path.join(_LOGS_DIR, f"app_{date_str}.log")

    def _add(self, message, level):
        """
        内部方法：添加一条日志。
        自动生成时间戳（HHMMSS 格式），存入内存列表，发射信号，写入文件。
        """
        ts = datetime.now().strftime("%H:%M:%S")
        self._entries.append((ts, message, level))
        self.log_added.emit(ts, message, level)
        # 持久化写入日志文件
        self._write_to_file(ts, message, level)

    def _write_to_file(self, ts, message, level):
        """将日志行追加写入文件"""
        try:
            self._ensure_log_file()
            label = _LEVEL_LABELS.get(level, "----")
            line = f"[{ts}] [{label}] {message}\n"
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass  # 文件写入失败不影响 UI 日志显示

    def info(self, message):
        """
        信息级别日志。
        用于一般操作记录（如模式切换、重拍等）。
        """
        self._add(message, "info")

    def success(self, message):
        """
        成功级别日志。
        用于操作成功的确认（如采集完成、检测到标记物等）。
        UI 中显示为绿色 ✅ 前缀。
        """
        self._add(message, "success")

    def warning(self, message):
        """
        警告级别日志。
        用于非致命问题提示（如未检测到标记物、数据可能不合格等）。
        UI 中显示为橙色 ⚠️ 前缀。
        """
        self._add(message, "warning")

    def error(self, message):
        """
        错误级别日志。
        用于操作失败的记录（如相机错误、采集失败等）。
        UI 中显示为红色 ❌ 前缀。
        """
        self._add(message, "error")

    def all_entries(self):
        """返回所有日志条目的副本"""
        return list(self._entries)

    def clear(self):
        """清空所有日志"""
        self._entries.clear()
