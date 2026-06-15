"""
手眼标定数据收集助手 - 程序入口。
负责：添加 SDK 路径到 Python 搜索路径 → 创建 QApplication → 设置全局样式 → 启动主窗口。
"""

import sys
import os

# ── 将 PyRVC（RVC 3D 相机 Python SDK）所在目录添加到 Python 模块搜索路径 ──
# 这样 import PyRVC 就能找到 PyRVC.pyd（pybind11 编译的 C++ 扩展模块）
_PYRVC_PATH = r"D:\Program Files\RVBUST\RVC\RVCSDK\PyRVC"
if os.path.isdir(_PYRVC_PATH) and _PYRVC_PATH not in sys.path:
    sys.path.insert(0, _PYRVC_PATH)

# ── 将项目根目录添加到模块搜索路径 ──
# 确保 widgets/ 和 core/ 等子包能被正确导入
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PyQt5.QtWidgets import QApplication
import resources as res  # 全局配色和样式定义


def main():
    """
    应用程序主入口函数。
    1. 创建 QApplication（Qt 事件循环）
    2. 应用全局 QSS 样式表
    3. 注册未捕获异常处理（防止崩溃时无提示）
    4. 创建并显示主窗口
    5. 进入事件循环
    """
    # 创建 Qt 应用程序实例，sys.argv 允许传递命令行参数给 Qt
    app = QApplication(sys.argv)
    # 应用全局样式表（定义在 resources.py 中，颜色/字体/控件样式）
    app.setStyleSheet(res.global_stylesheet())

    # 全局异常钩子：捕获所有未被 try-except 处理的异常
    # 防止 GUI 程序因异常直接崩溃退出，至少打印堆栈信息到控制台
    def _excepthook(exc_type, exc_value, exc_tb):
        import traceback
        traceback.print_exception(exc_type, exc_value, exc_tb)
    sys.excepthook = _excepthook

    # 延迟导入 MainWindow（避免在模块加载时就加载 PyQt 依赖）
    from app import MainWindow
    window = MainWindow()
    window.show()

    # app.exec_() 进入 Qt 事件循环，阻塞直到窗口关闭
    # 返回值是程序的退出码（0=正常退出）
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
