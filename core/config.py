"""
应用配置管理模块。
负责持久化设置的读写：保存路径、窗口状态、上次模式、相机参数等。
配置文件位于项目根目录 config/settings.json。
"""

import json
import os


# 项目根目录（core/ 的父目录）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_DIR = os.path.join(_PROJECT_ROOT, "config")
_CONFIG_PATH = os.path.join(_CONFIG_DIR, "settings.json")


# 默认配置值
_DEFAULTS = {
    "save_base_dir": os.path.join(_PROJECT_ROOT, "data"),
    "eye_in_hand": True,
    "marker_type": True,
    "window_geometry": {"x": -1, "y": -1, "width": 1920, "height": 1080},
    "camera_params": {},
}


class SettingsManager:
    """应用配置管理器，单例模式读取/写入 JSON 配置文件"""

    def __init__(self):
        self._data = {}

    def load(self):
        """从 config/settings.json 加载配置，文件不存在或格式错误时使用默认值"""
        try:
            if os.path.exists(_CONFIG_PATH):
                with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            else:
                self._data = dict(_DEFAULTS)
        except Exception:
            self._data = dict(_DEFAULTS)
        # 合并默认值（确保新版本新增的键有默认值）
        for key, val in _DEFAULTS.items():
            if key not in self._data:
                self._data[key] = val
        return self

    def save(self):
        """将当前配置写入 config/settings.json，目录不存在时自动创建"""
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    # ── 各配置项的 getter / setter ──

    def get_save_base_dir(self):
        """返回数据保存基目录"""
        return self._data.get("save_base_dir", _DEFAULTS["save_base_dir"])

    def set_save_base_dir(self, path):
        """设置数据保存基目录"""
        self._data["save_base_dir"] = path
        self.save()

    def get_eye_in_hand(self):
        """返回上次标定模式是否为眼在手上"""
        return self._data.get("eye_in_hand", _DEFAULTS["eye_in_hand"])

    def get_marker_type(self):
        """返回上次标定类型是否为标记物标定"""
        return self._data.get("marker_type", _DEFAULTS["marker_type"])

    def set_last_mode(self, eye_in_hand, marker_type):
        """保存当前标定模式和类型"""
        self._data["eye_in_hand"] = eye_in_hand
        self._data["marker_type"] = marker_type
        self.save()

    def get_window_geometry(self):
        """返回上次窗口位置和尺寸 {x, y, width, height}"""
        return self._data.get("window_geometry", _DEFAULTS["window_geometry"])

    def set_window_geometry(self, x, y, width, height):
        """保存当前窗口位置和尺寸"""
        self._data["window_geometry"] = {"x": x, "y": y, "width": width, "height": height}
        # 窗口几何信息不立即保存（由 closeEvent 统一保存以减IO）

    def get_camera_params(self):
        """返回上次保存的相机参数"""
        return self._data.get("camera_params", {})

    def set_camera_params(self, params):
        """保存相机参数"""
        self._data["camera_params"] = params
        self.save()
