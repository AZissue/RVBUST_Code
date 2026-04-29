"""
Overlay Loading Widget - 遮罩层加载动画
提供更明显的全屏 loading 指示
"""
import math

from PySide6.QtCore import Qt, QTimer, QSize, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QGraphicsDropShadowEffect
)


class OverlayLoadingWidget(QWidget):
    """
    全屏遮罩层加载控件
    
    特性：
    - 半透明黑色背景覆盖父窗口
    - 中央显示旋转的圆环动画
    - 支持进度条和状态文字
    - 带有阴影效果增强视觉层次
    """
    
    def __init__(self, parent=None, message="处理中...", show_progress=False):
        super().__init__(parent)
        self._message = message
        self._show_progress = show_progress
        self._progress = 0
        self._rotation = 0
        self._spinner_timer = None
        self._is_finished = False
        
        self._setup_ui()
        self._setup_spinner()
        
    def _setup_ui(self):
        """设置UI布局"""
        # 设置透明背景，但捕获鼠标事件
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 创建中央内容容器
        self.content = QWidget(self)
        self.content.setObjectName("loadingContent")
        self.content.setStyleSheet("""
            #loadingContent {
                background-color: #2d2d2d;
                border-radius: 16px;
                border: 2px solid #2196F3;
            }
        """)
        
        # 添加阴影效果
        shadow = QGraphicsDropShadowEffect(self.content)
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 8)
        self.content.setGraphicsEffect(shadow)
        
        # 布局
        layout = QVBoxLayout(self.content)
        layout.setSpacing(16)
        layout.setContentsMargins(32, 32, 32, 32)
        
        # Spinner 区域
        self.spinner_container = QWidget()
        self.spinner_container.setFixedSize(80, 80)
        layout.addWidget(self.spinner_container, alignment=Qt.AlignCenter)
        
        # 状态文字
        self.lbl_message = QLabel(self._message)
        self.lbl_message.setAlignment(Qt.AlignCenter)
        self.lbl_message.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 16px;
                font-weight: 500;
            }
        """)
        layout.addWidget(self.lbl_message)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedWidth(280)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #444;
                border-radius: 6px;
                background-color: #1a1a1a;
                color: #fff;
                font-size: 12px;
                font-weight: bold;
                text-align: center;
                height: 24px;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(
                    spread:pad, x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2196F3, stop:1 #21CBF3
                );
                border-radius: 4px;
            }
        """)
        self.progress_bar.setVisible(self._show_progress)
        layout.addWidget(self.progress_bar, alignment=Qt.AlignCenter)
        
        # 详情文字（用于显示额外信息）
        self.lbl_detail = QLabel("")
        self.lbl_detail.setAlignment(Qt.AlignCenter)
        self.lbl_detail.setStyleSheet("""
            QLabel {
                color: #aaa;
                font-size: 13px;
            }
        """)
        layout.addWidget(self.lbl_detail)
        
        # 初始隐藏内容，等显示时再定位
        self.content.adjustSize()
        
    def _setup_spinner(self):
        """设置旋转动画定时器"""
        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._rotate_spinner)
        self._spinner_timer.start(30)  # 约33fps，流畅动画
        
    def _rotate_spinner(self):
        """旋转 spinner - 每30ms转10度，约每秒333度"""
        self._rotation = (self._rotation + 10) % 360
        self.spinner_container.update()
        
    def paintEvent(self, event):
        """绘制遮罩背景和 spinner"""
        painter = QPainter(self)
        
        # 绘制半透明黑色背景
        painter.fillRect(self.rect(), QColor(0, 0, 0, 180))
        
        # 绘制 spinner
        self._draw_spinner(painter)
        
        super().paintEvent(event)
        
    def _draw_spinner(self, painter: QPainter):
        """绘制旋转的圆环 spinner"""
        painter.save()
        
        # 获取 spinner 在窗口中的位置
        spinner_pos = self.spinner_container.mapTo(self, self.spinner_container.rect().topLeft())
        center_x = spinner_pos.x() + self.spinner_container.width() // 2
        center_y = spinner_pos.y() + self.spinner_container.height() // 2
        
        painter.translate(center_x, center_y)
        painter.rotate(self._rotation)
        
        # 根据容器大小计算半径
        container_size = min(self.spinner_container.width(), self.spinner_container.height())
        radius = int(container_size * 0.35)  # 留出边距
        pen_width = max(4, container_size // 15)
        
        # 绘制渐变圆环
        pen = QPen()
        pen.setWidth(pen_width)
        pen.setCapStyle(Qt.RoundCap)
        
        # 背景圆环（灰色）
        pen.setColor(QColor(80, 80, 80))
        painter.setPen(pen)
        painter.drawEllipse(QPointF(0, 0), radius, radius)
        
        # 渐变圆环（蓝色到青色）- 12段弧线
        segments = 12
        for i in range(segments):
            angle = i * (360 // segments)
            alpha = int(255 * (1 - i / segments) * 0.8 + 50)
            
            # 蓝色渐变
            blue_intensity = int(200 + 55 * (1 - i / segments))
            pen.setColor(QColor(33, blue_intensity, 243, alpha))
            pen.setWidth(pen_width)
            painter.setPen(pen)
            
            # 绘制弧线片段
            start_angle = angle * 16
            span_angle = 25 * 16
            painter.drawArc(int(-radius), int(-radius), int(radius * 2), int(radius * 2), 
                          start_angle, span_angle)
        
        painter.restore()
        
    def resizeEvent(self, event):
        """窗口大小改变时重新定位内容"""
        super().resizeEvent(event)
        if self.parent():
            self.setGeometry(self.parent().rect())
        self._center_content()
        
    def _center_content(self):
        """将内容居中"""
        if self.content:
            x = (self.width() - self.content.width()) // 2
            y = (self.height() - self.content.height()) // 2
            self.content.move(x, y)
            # 内容位置改变后，重绘 spinner
            self.spinner_container.update()
            
    def showEvent(self, event):
        """显示时重新定位并启动spinner"""
        super().showEvent(event)
        self._center_content()
        self.raise_()
        # 强制启动spinner动画
        if self._spinner_timer and not self._spinner_timer.isActive():
            self._spinner_timer.start(30)
        # 强制刷新spinner区域
        self.spinner_container.update()
        
    def set_progress(self, value: int):
        """设置进度"""
        self._progress = max(0, min(100, value))
        if self.progress_bar:
            self.progress_bar.setValue(self._progress)
            
    def resize_spinner(self, size: int):
        """调整 spinner 尺寸（需要在 show 后调用）"""
        self.spinner_container.setFixedSize(size, size)
        self.content.adjustSize()
        self._center_content()
        self.update()  # 强制整个遮罩重绘
            
    def set_message(self, message: str):
        """设置主消息"""
        self._message = message
        if self.lbl_message:
            self.lbl_message.setText(message)
            
    def set_detail(self, detail: str):
        """设置详情文字"""
        if self.lbl_detail:
            self.lbl_detail.setText(detail)
            
    def finish(self, message: str = None):
        """完成动画"""
        self._is_finished = True
        if self._spinner_timer:
            self._spinner_timer.stop()
            
        if message:
            self.lbl_message.setText(message)
            self.lbl_message.setStyleSheet("""
                QLabel {
                    color: #4CAF50;
                    font-size: 16px;
                    font-weight: 500;
                }
            """)
            # 显示对勾图标
            self.lbl_detail.setText("✓ 完成")
            self.lbl_detail.setStyleSheet("""
                QLabel {
                    color: #4CAF50;
                    font-size: 24px;
                    font-weight: bold;
                }
            """)
            
        self.hide()
        self.deleteLater()
        
    def error(self, message: str, auto_close: bool = True):
        """显示错误"""
        self._is_finished = True
        if self._spinner_timer:
            self._spinner_timer.stop()
            
        self.lbl_message.setText(message)
        self.lbl_message.setStyleSheet("""
            QLabel {
                color: #f44336;
                font-size: 16px;
                font-weight: 500;
            }
        """)
        self.lbl_detail.setText("✗ 失败")
        self.lbl_detail.setStyleSheet("""
            QLabel {
                color: #f44336;
                font-size: 24px;
                font-weight: bold;
            }
        """)
        
        # 自动关闭遮罩
        if auto_close:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1500, self.finish)


class LoadingOverlayManager:
    """
    Loading 遮罩管理器 - 简化使用
    
    用法：
        with LoadingOverlayManager(self, "拍摄中...") as loader:
            # 执行耗时操作
            loader.set_progress(50)
            # 更多操作
    """
    
    def __init__(self, parent, message="处理中...", show_progress=False):
        self.parent = parent
        self.message = message
        self.show_progress = show_progress
        self.overlay = None
        
    def __enter__(self):
        self.overlay = OverlayLoadingWidget(
            self.parent, 
            self.message, 
            self.show_progress
        )
        self.overlay.show()
        # 强制刷新确保显示
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        return self.overlay
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.overlay:
            self.overlay.finish()
        return False  # 不吞掉异常
