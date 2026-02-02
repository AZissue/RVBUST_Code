import os
from datetime import datetime

class Logger:
    def __init__(self):
        pass
    
    def get_log_file_path(self):
        """获取日志文件路径"""
        # 使用C盘用户文件夹作为存储位置
        user_dir = os.path.expanduser("~")
        data_dir = os.path.join(user_dir, "WorkLog Pro", "data")
        return os.path.join(data_dir, "app.log")
    
    def add_log(self, message, level="信息"):
        """添加日志"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        color_map = {
            "信息": "#3182ce",
            "操作": "#38a169", 
            "警告": "#d69e2e",
            "错误": "#e53e3e"
        }
        color = color_map.get(level, "#4a5568")
        log_entry = f'<span style="color:#718096">[{timestamp}]</span> <span style="color:{color};font-weight:bold">[{level}]</span> <span style="color:#2d3748">{message}</span>'
        
        # 保存到日志文件
        self._save_to_file(timestamp, level, message)
        
        return log_entry
    
    def _save_to_file(self, timestamp, level, message):
        """保存日志到文件"""
        try:
            log_file = self.get_log_file_path()
            # 确保data目录存在
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            # 写入日志文件
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] [{level}] {message}\n")
        except Exception as e:
            # 日志文件写入失败不影响程序运行
            pass
    
    def get_log_level_color(self, level):
        """获取日志级别的颜色"""
        color_map = {
            "信息": "#3182ce",
            "操作": "#38a169", 
            "警告": "#d69e2e",
            "错误": "#e53e3e"
        }
        return color_map.get(level, "#4a5568")
