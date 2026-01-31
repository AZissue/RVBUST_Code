import sys
import os
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QTextEdit, QComboBox, 
                             QPushButton, QDateEdit, QTableWidget, QTableWidgetItem,
                             QHeaderView, QSplitter, QFrame, QMessageBox, QFileDialog,
                             QAbstractItemView)
from PyQt5.QtCore import Qt, QDate, pyqtSignal, QTimer
from PyQt5.QtGui import QColor, QPalette, QFont, QIcon

# 导入核心功能模块
from core.data_manager import DataManager
from core.business_logic import BusinessLogic
from core.logger import Logger

# 尝试导入pandas，如果没有安装则提示用户
try:
    import pandas as pd
except ImportError:
    QMessageBox.critical(None, "错误", "请安装pandas库：pip install pandas openpyxl")
    sys.exit(1)

class ModernGroupBox(QFrame):
    """现代化的卡片容器，替代传统 GroupBox"""
    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFrameShape(QFrame.StyledPanel)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(16, 16, 16, 16)
        self.layout.setSpacing(12)
        
        if title:
            title_label = QLabel(title)
            title_label.setObjectName("cardTitle")
            title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
            self.layout.addWidget(title_label)

class WorkLogPro(QMainWindow):
    # 定义信号供外部连接
    save_requested = pyqtSignal(dict)      # 保存请求，传递表单数据
    delete_requested = pyqtSignal(int)     # 删除请求，传递记录ID
    clear_requested = pyqtSignal()         # 清空表单请求
    search_requested = pyqtSignal(str)     # 搜索请求，传递关键词
    import_excel_requested = pyqtSignal()  # 导入Excel
    export_excel_requested = pyqtSignal()  # 导出Excel
    table_row_selected = pyqtSignal(int)   # 表格选中行变更
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WorkLog Pro - 工作日志管理系统")
        self.setMinimumSize(1400, 900)
        # 初始化核心功能模块
        self.data_manager = DataManager()
        self.business_logic = BusinessLogic()
        self.logger = Logger()
        # 添加状态变量
        self.is_table_selection = False  # 标记是否从表格选择填充的表单
        self.current_selected_row = -1  # 当前选中的表格行索引
        self.original_status = ""  # 原始问题进度
        # 排序状态变量
        self.sort_columns = []  # 当前排序的列索引列表，按优先级排序
        self.sort_orders = {}  # 当前排序顺序，键为列索引，值为排序顺序
        self.setup_ui()
        self.apply_styles()
        self.load_data_from_excel()
        
    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)
        
        # 上部分分割器（左表单 + 右表格）
        top_splitter = QSplitter(Qt.Horizontal)
        
        # 左侧工作记录表单
        self.form_panel = self.create_form_panel()
        top_splitter.addWidget(self.form_panel)
        
        # 右侧历史记录
        self.history_panel = self.create_history_panel()
        top_splitter.addWidget(self.history_panel)
        
        # 设置分割比例（左:右 = 1:1.5）
        top_splitter.setSizes([500, 750])
        top_splitter.setHandleWidth(2)
        
        main_layout.addWidget(top_splitter, stretch=4)
        
        # 底部操作日志
        self.log_panel = self.create_log_panel()
        main_layout.addWidget(self.log_panel, stretch=1)
        
    def create_form_panel(self):
        panel = ModernGroupBox("📝 工作记录")
        layout = panel.layout
        
        # 表单网格布局
        form_layout = QVBoxLayout()
        form_layout.setSpacing(12)
        
        # 1. 日期行（带今天按钮）
        date_layout = QHBoxLayout()
        date_label = QLabel("日期:")
        date_label.setFixedWidth(70)
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.today_btn = QPushButton("今天")
        self.today_btn.setObjectName("secondaryBtn")
        self.today_btn.setFixedWidth(60)
        self.today_btn.clicked.connect(self.set_today)
        
        date_layout.addWidget(date_label)
        date_layout.addWidget(self.date_edit)
        date_layout.addWidget(self.today_btn)
        date_layout.addStretch()
        form_layout.addLayout(date_layout)
        
        # 2. 客户名称
        self.customer_input = self.create_labeled_input("客户名称:", form_layout)
        
        # 3. 相机型号
        self.camera_input = self.create_labeled_input("相机型号:", form_layout)
        
        # 4. 客户问题（多行）
        problem_label = QLabel("客户问题:")
        self.problem_text = QTextEdit()
        self.problem_text.setPlaceholderText("请详细描述客户遇到的问题...")
        self.problem_text.setFixedHeight(100)
        form_layout.addWidget(problem_label)
        form_layout.addWidget(self.problem_text)
        
        # 5. 解决方法（多行）
        solution_label = QLabel("解决方法:")
        self.solution_text = QTextEdit()
        self.solution_text.setPlaceholderText("记录问题的解决步骤和方法...")
        self.solution_text.setFixedHeight(100)
        form_layout.addWidget(solution_label)
        form_layout.addWidget(self.solution_text)
        
        # 6. 下拉选择行
        combo_layout = QHBoxLayout()
        
        # 问题类型
        type_layout = QVBoxLayout()
        type_label = QLabel("问题类型:")
        self.type_combo = QComboBox()
        self.type_combo.addItems(["账户问题", "硬件故障", "软件设置", "网络连接", "其他"])
        type_layout.addWidget(type_label)
        type_layout.addWidget(self.type_combo)
        combo_layout.addLayout(type_layout)
        
        # 问题进度
        status_layout = QVBoxLayout()
        status_label = QLabel("问题进度:")
        self.status_combo = QComboBox()
        self.status_combo.addItems(["待处理", "处理中", "已解决", "已关闭"])
        status_layout.addWidget(status_label)
        status_layout.addWidget(self.status_combo)
        combo_layout.addLayout(status_layout)
        
        form_layout.addLayout(combo_layout)
        
        # 7. 操作按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        self.save_btn = QPushButton("✅ 保存")
        self.save_btn.setObjectName("saveBtn")
        self.save_btn.clicked.connect(self.on_save_click)
        
        self.delete_btn = QPushButton("🗑️ 删除")
        self.delete_btn.setObjectName("deleteBtn")
        self.delete_btn.clicked.connect(self.on_delete_click)
        
        self.clear_btn = QPushButton("🔄 清除")
        self.clear_btn.setObjectName("secondaryBtn")
        self.clear_btn.clicked.connect(self.on_clear_click)
        
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addWidget(self.clear_btn)
        btn_layout.addStretch()
        
        form_layout.addLayout(btn_layout)
        form_layout.addStretch()
        
        layout.addLayout(form_layout)
        return panel
        
    def create_history_panel(self):
        panel = ModernGroupBox("📚 历史记录")
        layout = panel.layout
        
        # 搜索工具栏
        toolbar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索客户名称、问题内容...")
        self.search_input.returnPressed.connect(self.on_search_click)
        
        self.clear_search_btn = QPushButton("清除")
        self.clear_search_btn.setObjectName("secondaryBtn")
        self.clear_search_btn.clicked.connect(self.on_clear_search)
        
        self.search_btn = QPushButton("搜索")
        self.search_btn.setObjectName("primaryBtn")
        self.search_btn.clicked.connect(self.on_search_click)
        
        self.import_btn = QPushButton("📥 导入 Excel")
        self.import_btn.setObjectName("secondaryBtn")
        self.import_btn.clicked.connect(self.on_import_click)
        
        self.export_btn = QPushButton("📤 导出 Excel")
        self.export_btn.setObjectName("secondaryBtn")
        self.export_btn.clicked.connect(self.on_export_click)
        
        toolbar.addWidget(self.search_input)
        toolbar.addWidget(self.clear_search_btn)
        toolbar.addWidget(self.search_btn)
        toolbar.addSpacing(20)
        toolbar.addWidget(self.import_btn)
        toolbar.addWidget(self.export_btn)
        
        layout.addLayout(toolbar)
        
        # 数据表格
        self.table = QTableWidget()
        self.table.setColumnCount(9)  # 增加一列用于复选框
        headers = ["选择", "ID", "日期", "客户名称", "相机型号", "客户问题", "解决方法", "问题类型", "问题进度"]
        self.table.setHorizontalHeaderLabels(headers)
        
        # 表格设置
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        # 设置固定宽度的列
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)  # 选择列固定
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)  # ID列固定
        # 设置自适应宽度的列
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)  # 日期自适应
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)  # 客户名称自适应
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)  # 相机型号自适应
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)  # 问题类型自适应
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeToContents)  # 问题进度自适应
        
        # 设置列宽度
        self.table.setColumnWidth(0, 50)  # 选择列宽度
        self.table.setColumnWidth(1, 50)  # ID列宽度
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self.on_table_selection_changed)
        # 添加双击事件处理
        self.table.cellDoubleClicked.connect(self.on_table_cell_double_clicked)
        # 添加表头点击事件处理（用于排序）
        self.table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        
        layout.addWidget(self.table)
        return panel
        
    def create_log_panel(self):
        panel = ModernGroupBox("📋 操作日志")
        layout = panel.layout
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 10))
        self.log_text.setPlaceholderText("系统操作日志将显示在这里...")
        
        # 设置日志颜色（可选深色主题）
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #e9ecef;
                border-radius: 6px;
                padding: 8px;
                color: #495057;
            }
        """)
        
        layout.addWidget(self.log_text)
        return panel
        
    def create_labeled_input(self, label_text, parent_layout):
        """辅助方法：创建标签+输入框组合"""
        layout = QHBoxLayout()
        label = QLabel(label_text)
        label.setFixedWidth(70)
        line_edit = QLineEdit()
        layout.addWidget(label)
        layout.addWidget(line_edit)
        parent_layout.addLayout(layout)
        return line_edit
        
    def apply_styles(self):
        """应用现代化样式表"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f0f2f5;
            }
            
            /* 卡片样式 */
            #card {
                background-color: white;
                border-radius: 12px;
                border: 1px solid #e1e4e8;
            }
            
            #cardTitle {
                color: #2d3748;
                margin-bottom: 4px;
                padding-bottom: 8px;
                border-bottom: 2px solid #e2e8f0;
            }
            
            /* 输入框样式 */
            QLineEdit, QTextEdit, QComboBox, QDateEdit {
                border: 1px solid #cbd5e0;
                border-radius: 6px;
                padding: 8px 12px;
                background-color: #fff;
                font-size: 13px;
                color: #2d3748;
            }
            
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
                border: 2px solid #4299e1;
                background-color: #fff;
            }
            
            QLineEdit:hover, QTextEdit:hover, QComboBox:hover {
                border-color: #a0aec0;
            }
            
            /* 按钮样式 */
            QPushButton {
                padding: 8px 16px;
                border-radius: 6px;
                border: none;
                font-weight: 500;
                font-size: 13px;
                min-height: 32px;
            }
            
            #primaryBtn {
                background-color: #4299e1;
                color: white;
            }
            #primaryBtn:hover { background-color: #3182ce; }
            #primaryBtn:pressed { background-color: #2c5282; }
            
            #secondaryBtn {
                background-color: #edf2f7;
                color: #4a5568;
                border: 1px solid #cbd5e0;
            }
            #secondaryBtn:hover { background-color: #e2e8f0; }
            #secondaryBtn:pressed { background-color: #cbd5e0; }
            
            #saveBtn {
                background-color: #48bb78;
                color: white;
                font-weight: bold;
            }
            #saveBtn:hover { background-color: #38a169; }
            #saveBtn:pressed { background-color: #2f855a; }
            
            #deleteBtn {
                background-color: #f56565;
                color: white;
            }
            #deleteBtn:hover { background-color: #e53e3e; }
            #deleteBtn:pressed { background-color: #c53030; }
            
            /* 表格样式 */
            QTableWidget {
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                background-color: white;
                gridline-color: #e2e8f0;
            }
            
            QHeaderView::section {
                background-color: #f7fafc;
                color: #4a5568;
                padding: 10px;
                border: none;
                border-bottom: 2px solid #e2e8f0;
                font-weight: 600;
            }
            
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #edf2f7;
            }
            
            QTableWidget::item:selected {
                background-color: #ebf8ff;
                color: #2b6cb0;
                outline: none;
            }
            
            QTableWidget {
                outline: none;
            }
            
            QTableWidget:focus {
                outline: none;
            }
            
            QTableWidget::item:alternate {
                background-color: #f7fafc;
            }
            
            /* 标签样式 */
            QLabel {
                color: #4a5568;
                font-size: 13px;
                font-weight: 500;
            }
            
            /* 下拉框特殊处理 */
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            
            QComboBox QAbstractItemView {
                border: 1px solid #cbd5e0;
                border-radius: 6px;
                background-color: white;
                selection-background-color: #ebf8ff;
            }
            
            /* 日历组件样式 */
            QCalendarWidget {
                background-color: white;
                border: 1px solid #cbd5e0;
                border-radius: 8px;
                font-family: "Microsoft YaHei";
                font-size: 13px;
            }
            
            /* 日历头部导航栏 */
            QCalendarWidget QWidget {
                alternate-background-color: #f7fafc;
            }
            
            /* 月份和年份显示 */
            QCalendarWidget QAbstractItemView:enabled {
                color: #2d3748;
                background-color: white;
                selection-background-color: #4299e1;
                selection-color: white;
            }
            
            /* 星期标题 */
            QCalendarWidget QHeaderView::section {
                background-color: #f7fafc;
                color: #4a5568;
                padding: 8px;
                border: none;
                border-bottom: 1px solid #e2e8f0;
                font-weight: 600;
            }
            
            /* 日期单元格 */
            QCalendarWidget QTableView QAbstractItemView::item {
                padding: 4px;
                border-radius: 4px;
                color: #2d3748;
            }
            
            /* 选中日期 */
            QCalendarWidget QTableView QAbstractItemView::item:selected {
                background-color: #4299e1;
                color: white;
                border-radius: 4px;
            }
            
            /* 今天日期 */
            QCalendarWidget QTableView QAbstractItemView::item:today {
                background-color: #ebf8ff;
                color: #2b6cb0;
                border: 1px solid #90cdf4;
                border-radius: 4px;
            }
            
            /* 今天日期且被选中 */
            QCalendarWidget QTableView QAbstractItemView::item:today:selected {
                background-color: #4299e1;
                color: white;
                border: 1px solid #4299e1;
            }
            
            /* 其他月份日期 */
            QCalendarWidget QTableView QAbstractItemView::item:other-month {
                color: #a0aec0;
                background-color: #f7fafc;
            }
            
            /* 导航按钮 */
            QCalendarWidget QToolButton {
                background-color: transparent;
                color: #4a5568;
                border: none;
                padding: 6px;
                border-radius: 4px;
            }
            
            QCalendarWidget QToolButton:hover {
                background-color: #ebf8ff;
            }
            
            QCalendarWidget QToolButton:pressed {
                background-color: #90cdf4;
            }
        """)
        
    def get_default_excel_path(self):
        """获取默认Excel文件路径"""
        # 默认保存到 data 目录
        data_dir = "d:\\WorkLog Pro\\data"
        return os.path.join(data_dir, "worklog.xlsx")
        
    def get_excel_file_path(self):
        """获取Excel文件路径"""
        return self.current_excel_path
        
    def load_data_from_excel(self):
        """从Excel文件加载数据"""
        try:
            df = self.data_manager.load_data_from_excel()
            
            if df is not None:
                # 清空表格
                self.table.setRowCount(0)
                
                # 填充表格
                for index, row in df.iterrows():
                    table_row = self.table.rowCount()
                    self.table.insertRow(table_row)
                    
                    # 复选框
                    checkbox_item = QTableWidgetItem()
                    checkbox_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                    checkbox_item.setCheckState(Qt.Unchecked)
                    self.table.setItem(table_row, 0, checkbox_item)
                    
                    # ID
                    id_item = QTableWidgetItem(str(int(row.get('ID', index + 1))))
                    id_item.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(table_row, 1, id_item)
                    
                    # 日期
                    date_item = QTableWidgetItem(str(row.get('日期', '')))
                    self.table.setItem(table_row, 2, date_item)
                    
                    # 客户名称
                    customer_item = QTableWidgetItem(str(row.get('客户名称', '')))
                    self.table.setItem(table_row, 3, customer_item)
                    
                    # 相机型号
                    camera_item = QTableWidgetItem(str(row.get('相机型号', '')))
                    self.table.setItem(table_row, 4, camera_item)
                    
                    # 客户问题
                    problem = str(row.get('客户问题', ''))[:50] + '...' if len(str(row.get('客户问题', ''))) > 50 else str(row.get('客户问题', ''))
                    problem_item = QTableWidgetItem(problem)
                    self.table.setItem(table_row, 5, problem_item)
                    
                    # 解决方法
                    solution = str(row.get('解决方法', ''))[:50] + '...' if len(str(row.get('解决方法', ''))) > 50 else str(row.get('解决方法', ''))
                    solution_item = QTableWidgetItem(solution)
                    self.table.setItem(table_row, 6, solution_item)
                    
                    # 问题类型
                    type_item = QTableWidgetItem(str(row.get('问题类型', '')))
                    self.table.setItem(table_row, 7, type_item)
                    
                    # 问题进度
                    status_item = QTableWidgetItem(str(row.get('问题进度', '')))
                    self.table.setItem(table_row, 8, status_item)
                
                self.add_log(f"成功从Excel文件加载 {len(df)} 条记录", "信息")
            else:
                self.add_log("Excel文件不存在，将创建新文件", "信息")
        except Exception as e:
            self.add_log(f"加载Excel文件失败: {str(e)}", "错误")
        
        self.add_log("应用程序启动成功", "信息")
        
    def save_data_to_excel(self):
        """保存数据到Excel文件"""
        try:
            # 准备数据
            data = []
            for row in range(self.table.rowCount()):
                record = {
                    'ID': self.table.item(row, 1).text(),  # 调整为第1列
                    '日期': self.table.item(row, 2).text(),  # 调整为第2列
                    '客户名称': self.table.item(row, 3).text(),  # 调整为第3列
                    '相机型号': self.table.item(row, 4).text(),  # 调整为第4列
                    '客户问题': self.table.item(row, 5).text(),  # 调整为第5列
                    '解决方法': self.table.item(row, 6).text(),  # 调整为第6列
                    '问题类型': self.table.item(row, 7).text(),  # 调整为第7列
                    '问题进度': self.table.item(row, 8).text()  # 调整为第8列
                }
                data.append(record)
            
            # 使用data_manager保存数据
            self.data_manager.save_data_to_excel(data)
            
            self.add_log(f"成功保存 {len(data)} 条记录到Excel文件", "信息")
            return True
        except Exception as e:
            self.add_log(f"保存Excel文件失败: {str(e)}", "错误")
            return False
        
    # ========== 功能接口方法（预留，供子类或外部连接实现）==========
    
    def on_save_click(self):
        """保存按钮点击"""
        data = self.get_form_data()
        
        try:
            # 验证必填字段
            self.business_logic.validate_record(data)
            
            self.add_log(f"请求保存记录: {data.get('customer', '')}", "操作")
            self.save_requested.emit(data)
            
            # 检查是否从表格选择填充的表单
            if self.is_table_selection and self.current_selected_row >= 0:
                # 检查是否是编辑模式（所有字段都已启用）
                is_edit_mode = self.date_edit.isEnabled() and self.customer_input.isEnabled() and self.problem_text.isEnabled()
                
                if is_edit_mode:
                    # 编辑模式，覆盖当前记录
                    self.update_table_row(self.current_selected_row, data)
                    
                    # 保存到Excel
                    if self.save_data_to_excel():
                        QMessageBox.information(self, "成功", "记录编辑成功！已覆盖原记录。")
                        # 重置状态并清空表单
                        self.clear_form()
                    else:
                        QMessageBox.error(self, "错误", "记录编辑失败，请检查日志！")
                else:
                    # 非编辑模式，检查问题进度是否有更新
                    current_status = data.get('status', '')
                    status_changed = current_status != self.original_status
                    
                    if status_changed:
                        # 问题进度有更新，创建新记录
                        # 生成新ID
                        new_id = 1
                        if self.table.rowCount() > 0:
                            last_id = int(self.table.item(self.table.rowCount() - 1, 1).text())  # 调整为第1列
                            new_id = last_id + 1
                        
                        # 准备表格数据
                        record = self.business_logic.format_record_from_form(data, new_id)
                        table_record = self.business_logic.prepare_record_for_table(record)
                        table_data = [
                            new_id,
                            table_record.get('日期'),
                            table_record.get('客户名称'),
                            table_record.get('相机型号'),
                            table_record.get('客户问题'),
                            table_record.get('解决方法'),
                            table_record.get('问题类型'),
                            table_record.get('问题进度')
                        ]
                        
                        # 添加到表格
                        self.add_table_row(table_data)
                        
                        # 保存到Excel
                        if self.save_data_to_excel():
                            QMessageBox.information(self, "成功", "记录保存成功！问题进度已更新并另存为新记录。")
                            # 重置状态并清空表单
                            self.clear_form()
                        else:
                            QMessageBox.error(self, "错误", "记录保存失败，请检查日志！")
                    else:
                        # 问题进度无更新，提示用户
                        QMessageBox.information(self, "提示", "问题进度未发生变化，无需保存。")
                        # 重置状态并清空表单
                        self.clear_form()
            else:
                # 生成新ID
                new_id = 1
                if self.table.rowCount() > 0:
                    last_id = int(self.table.item(self.table.rowCount() - 1, 1).text())  # 调整为第1列
                    new_id = last_id + 1
                
                # 准备表格数据
                record = self.business_logic.format_record_from_form(data, new_id)
                table_record = self.business_logic.prepare_record_for_table(record)
                table_data = [
                    new_id,
                    table_record.get('日期'),
                    table_record.get('客户名称'),
                    table_record.get('相机型号'),
                    table_record.get('客户问题'),
                    table_record.get('解决方法'),
                    table_record.get('问题类型'),
                    table_record.get('问题进度')
                ]
                
                # 添加到表格
                self.add_table_row(table_data)
                
                # 保存到Excel
                if self.save_data_to_excel():
                    QMessageBox.information(self, "成功", "记录保存成功！")
                    self.clear_form()
                else:
                    QMessageBox.error(self, "错误", "记录保存失败，请检查日志！")
        except ValueError as e:
            QMessageBox.warning(self, "警告", str(e))
        except Exception as e:
            QMessageBox.error(self, "错误", f"保存失败: {str(e)}")
            self.add_log(f"保存失败: {str(e)}", "错误")
        
    def on_delete_click(self):
        """删除按钮点击"""
        # 首先检查是否有通过复选框选中的行
        selected_rows = self.get_selected_rows()
        
        if not selected_rows:
            # 没有通过复选框选中的行，使用原来的单行删除逻辑
            row = self.table.currentRow()
            if row < 0:
                QMessageBox.warning(self, "警告", "请先选择要删除的记录！")
                return
            selected_rows = [row]
        
        # 确认删除
        if len(selected_rows) == 1:
            reply = QMessageBox.question(self, "确认", "确定要删除选中的记录吗？", 
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        else:
            reply = QMessageBox.question(self, "确认", f"确定要删除选中的 {len(selected_rows)} 条记录吗？", 
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            # 按行号从大到小删除，避免删除时行号变化
            selected_rows.sort(reverse=True)
            deleted_ids = []
            
            for row in selected_rows:
                item_id = self.table.item(row, 1).text()  # 调整为第1列
                deleted_ids.append(item_id)
                self.add_log(f"请求删除记录 ID: {item_id}", "操作")
                self.delete_requested.emit(int(item_id))
                
                # 从表格中删除
                self.table.removeRow(row)
            
            # 重新编号
            for i in range(self.table.rowCount()):
                id_item = QTableWidgetItem(str(i + 1))
                id_item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, 1, id_item)  # 调整为第1列
            
            # 保存到Excel
            if self.save_data_to_excel():
                if len(deleted_ids) == 1:
                    QMessageBox.information(self, "成功", "记录删除成功！")
                else:
                    QMessageBox.information(self, "成功", f"成功删除 {len(deleted_ids)} 条记录！")
            else:
                QMessageBox.error(self, "错误", "记录删除失败，请检查日志！")
        
    def on_clear_click(self):
        """清除按钮点击"""
        self.clear_form()
        self.add_log("清空表单", "操作")
        self.clear_requested.emit()
        
    def on_search_click(self):
        """搜索按钮点击"""
        keyword = self.search_input.text().strip()
        self.add_log(f"搜索关键词: {keyword}", "操作")
        self.search_requested.emit(keyword)
        
        if not keyword:
            # 关键词为空，显示所有行
            for row in range(self.table.rowCount()):
                self.table.setRowHidden(row, False)
                # 恢复默认样式
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item:
                        item.setBackground(QColor(255, 255, 255))
                        item.setForeground(QColor(45, 55, 72))
            return
        
        # 搜索范围：客户名称(3)、相机型号(4)、客户问题(5)、解决方法(6)
        search_columns = [3, 4, 5, 6]
        matched_rows = []
        unmatched_rows = []
        
        # 收集匹配和不匹配的行
        for row in range(self.table.rowCount()):
            match = False
            for col in search_columns:
                item = self.table.item(row, col)
                if item and keyword.lower() in item.text().lower():
                    match = True
                    break
            if match:
                matched_rows.append(row)
            else:
                unmatched_rows.append(row)
        
        # 保存所有行的数据
        all_rows_data = []
        for row in range(self.table.rowCount()):
            row_data = []
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                row_data.append(item.text() if item else "")
            all_rows_data.append(row_data)
        
        # 清空表格
        self.table.setRowCount(0)
        
        # 先添加匹配的行（置顶）
        for row_idx in matched_rows:
            row_data = all_rows_data[row_idx]
            new_row = self.table.rowCount()
            self.table.insertRow(new_row)
            for col, value in enumerate(row_data):
                item = QTableWidgetItem(value)
                if col == 0:
                    # 复选框列
                    item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                    item.setCheckState(Qt.Unchecked)
                elif col == 1:
                    # ID列
                    item.setTextAlignment(Qt.AlignCenter)
                # 高亮匹配的行
                item.setBackground(QColor(235, 248, 255))  # 浅蓝色背景
                item.setForeground(QColor(43, 108, 176))  # 深蓝色文字
                self.table.setItem(new_row, col, item)
        
        # 再添加不匹配的行
        for row_idx in unmatched_rows:
            row_data = all_rows_data[row_idx]
            new_row = self.table.rowCount()
            self.table.insertRow(new_row)
            for col, value in enumerate(row_data):
                item = QTableWidgetItem(value)
                if col == 0:
                    # 复选框列
                    item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                    item.setCheckState(Qt.Unchecked)
                elif col == 1:
                    # ID列
                    item.setTextAlignment(Qt.AlignCenter)
                # 变暗不匹配的行
                item.setBackground(QColor(247, 250, 252))  # 浅灰色背景
                item.setForeground(QColor(160, 174, 192))  # 灰色文字
                self.table.setItem(new_row, col, item)
        
    def on_clear_search(self):
        """清除搜索"""
        self.search_input.clear()
        self.add_log("清除搜索条件", "操作")
        
        # 重置排序并重新加载数据
        self.reset_sort()
        
    def on_import_click(self):
        """导入Excel"""
        file_path, _ = QFileDialog.getOpenFileName(self, "选择Excel文件", "", "Excel Files (*.xlsx *.xls)")
        if file_path:
            self.add_log(f"请求导入: {file_path}", "操作")
            self.import_excel_requested.emit()
            
            try:
                df = self.data_manager.import_data_from_excel(file_path)
                
                # 清空表格
                self.table.setRowCount(0)
                
                # 填充表格
                for index, row in df.iterrows():
                    table_row = self.table.rowCount()
                    self.table.insertRow(table_row)
                    
                    # 复选框
                    checkbox_item = QTableWidgetItem()
                    checkbox_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                    checkbox_item.setCheckState(Qt.Unchecked)
                    self.table.setItem(table_row, 0, checkbox_item)
                    
                    # ID
                    id_item = QTableWidgetItem(str(int(row.get('ID', index + 1))))
                    id_item.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(table_row, 1, id_item)
                    
                    # 日期
                    date_item = QTableWidgetItem(str(row.get('日期', '')))
                    self.table.setItem(table_row, 2, date_item)
                    
                    # 客户名称
                    customer_item = QTableWidgetItem(str(row.get('客户名称', '')))
                    self.table.setItem(table_row, 3, customer_item)
                    
                    # 相机型号
                    camera_item = QTableWidgetItem(str(row.get('相机型号', '')))
                    self.table.setItem(table_row, 4, camera_item)
                    
                    # 客户问题
                    problem = str(row.get('客户问题', ''))[:50] + '...' if len(str(row.get('客户问题', ''))) > 50 else str(row.get('客户问题', ''))
                    problem_item = QTableWidgetItem(problem)
                    self.table.setItem(table_row, 5, problem_item)
                    
                    # 解决方法
                    solution = str(row.get('解决方法', ''))[:50] + '...' if len(str(row.get('解决方法', ''))) > 50 else str(row.get('解决方法', ''))
                    solution_item = QTableWidgetItem(solution)
                    self.table.setItem(table_row, 6, solution_item)
                    
                    # 问题类型
                    type_item = QTableWidgetItem(str(row.get('问题类型', '')))
                    self.table.setItem(table_row, 7, type_item)
                    
                    # 问题进度
                    status_item = QTableWidgetItem(str(row.get('问题进度', '')))
                    self.table.setItem(table_row, 8, status_item)
                
                # 保存到导入的Excel文件
                self.save_data_to_excel()
                
                self.add_log(f"成功导入 {len(df)} 条记录", "信息")
                QMessageBox.information(self, "成功", f"成功导入 {len(df)} 条记录！\n默认保存路径已更新为：{file_path}")
            except Exception as e:
                self.add_log(f"导入Excel文件失败: {str(e)}", "错误")
                QMessageBox.error(self, "错误", f"导入失败: {str(e)}")
            
    def on_export_click(self):
        """导出Excel"""
        file_path, _ = QFileDialog.getSaveFileName(self, "保存Excel文件", "worklog.xlsx", "Excel Files (*.xlsx)")
        if file_path:
            self.add_log(f"请求导出到: {file_path}", "操作")
            self.export_excel_requested.emit()
            
            try:
                # 准备数据
                data = []
                for row in range(self.table.rowCount()):
                    record = {
                        'ID': self.table.item(row, 1).text(),  # 调整为第1列
                        '日期': self.table.item(row, 2).text(),  # 调整为第2列
                        '客户名称': self.table.item(row, 3).text(),  # 调整为第3列
                        '相机型号': self.table.item(row, 4).text(),  # 调整为第4列
                        '客户问题': self.table.item(row, 5).text(),  # 调整为第5列
                        '解决方法': self.table.item(row, 6).text(),  # 调整为第6列
                        '问题类型': self.table.item(row, 7).text(),  # 调整为第7列
                        '问题进度': self.table.item(row, 8).text()  # 调整为第8列
                    }
                    data.append(record)
                
                # 使用data_manager导出数据
                self.data_manager.export_data_to_excel(data, file_path)
                
                self.add_log(f"成功导出 {len(data)} 条记录到Excel文件", "信息")
                QMessageBox.information(self, "成功", "导出成功！")
            except Exception as e:
                self.add_log(f"导出Excel文件失败: {str(e)}", "错误")
                QMessageBox.error(self, "错误", f"导出失败: {str(e)}")
            
    def on_table_selection_changed(self):
        """表格选择变更"""
        row = self.table.currentRow()
        if row >= 0:
            self.add_log(f"选中记录行: {row}", "调试")
            self.table_row_selected.emit(row)
            # 自动填充表单
            self.fill_form_from_table(row)
            # 设置状态变量
            self.is_table_selection = True
            self.current_selected_row = row
            # 禁用主要输入字段，只允许修改问题类型和问题进度
            self.enable_only_type_and_status()
            
    def set_today(self):
        """设置日期为今天"""
        self.date_edit.setDate(QDate.currentDate())
        
    def on_table_cell_double_clicked(self, row, column):
        """表格单元格双击事件处理，进入编辑模式"""
        # 从表格行填充表单
        self.fill_form_from_table(row)
        # 设置状态变量，标记为编辑模式
        self.is_table_selection = True
        self.current_selected_row = row
        # 启用所有输入字段，允许修改
        self.enable_all_fields()
        # 添加日志
        self.add_log(f"双击记录行 {row} 进入编辑模式", "操作")
        
    def on_header_clicked(self, logical_index):
        """表头点击事件处理，实现组合排序功能"""
        # 只对客户名称(3)、相机型号(4)、问题类型(7)和问题进度(8)列进行排序
        if logical_index not in [3, 4, 7, 8]:
            return
        
        # 获取列名称
        if logical_index == 3:
            column_name = "客户名称"
        elif logical_index == 4:
            column_name = "相机型号"
        elif logical_index == 7:
            column_name = "问题类型"
        else:  # logical_index == 8
            column_name = "问题进度"
        
        # 检查是否按下了Ctrl键（这里简化处理，实际应用中需要通过QMouseEvent获取）
        # 注意：在PyQt中，需要重写header的mousePressEvent来获取按键状态
        # 这里我们使用一种简化的方式，通过检查当前列是否已经在排序列表中来模拟
        is_ctrl_pressed = logical_index in self.sort_columns
        
        if not is_ctrl_pressed:
            # 没有按Ctrl键，重置排序，只按当前列排序
            self.sort_columns = [logical_index]
            self.sort_orders = {logical_index: Qt.AscendingOrder}
            self.add_log(f"按 {column_name} 升序排序", "操作")
        else:
            # 按了Ctrl键，添加到排序列表
            if logical_index in self.sort_columns:
                # 如果当前列已经在排序列表中，切换排序顺序
                current_order = self.sort_orders.get(logical_index, Qt.AscendingOrder)
                new_order = Qt.DescendingOrder if current_order == Qt.AscendingOrder else Qt.AscendingOrder
                self.sort_orders[logical_index] = new_order
                order_text = "降序" if new_order == Qt.DescendingOrder else "升序"
                self.add_log(f"按 {column_name} {order_text} 排序", "操作")
            else:
                # 添加到排序列表
                self.sort_columns.append(logical_index)
                self.sort_orders[logical_index] = Qt.AscendingOrder
                self.add_log(f"添加 {column_name} 升序排序", "操作")
        
        # 执行排序
        self.perform_sort()
        
        # 更新表头显示，指示排序状态
        self.update_header_sort_indicators()
    
    def perform_sort(self):
        """执行组合排序"""
        # 保存所有行的数据
        rows_data = []
        for row in range(self.table.rowCount()):
            row_data = {}
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                row_data[col] = item.text() if item else ""
            rows_data.append(row_data)
        
        # 按多列排序
        def sort_key(row):
            keys = []
            for col in self.sort_columns:
                value = row[col]
                # 根据排序顺序调整键值
                if self.sort_orders.get(col, Qt.AscendingOrder) == Qt.DescendingOrder:
                    # 对于降序，我们需要反转字符串的比较
                    # 注意：这只是一个简化的实现，对于数字等类型可能需要特殊处理
                    if isinstance(value, str):
                        value = ''.join(chr(255 - ord(c)) for c in value)
                keys.append(value)
            return keys
        
        rows_data.sort(key=sort_key)
        
        # 清空表格
        self.table.setRowCount(0)
        
        # 重新填充表格
        for row_data in rows_data:
            new_row = self.table.rowCount()
            self.table.insertRow(new_row)
            for col, value in row_data.items():
                item = QTableWidgetItem(value)
                if col == 0:
                    # 复选框列
                    item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                    item.setCheckState(Qt.Unchecked)
                elif col == 1:
                    # ID列
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(new_row, col, item)
    
    def update_header_sort_indicators(self):
        """更新表头排序指示器"""
        # 重置所有表头的排序指示器
        for i in range(self.table.columnCount()):
            self.table.horizontalHeader().setSortIndicatorShown(False)
        
        # 设置当前排序列的指示器
        if self.sort_columns:
            primary_col = self.sort_columns[0]
            primary_order = self.sort_orders.get(primary_col, Qt.AscendingOrder)
            self.table.horizontalHeader().setSortIndicator(primary_col, primary_order)
            self.table.horizontalHeader().setSortIndicatorShown(True)
    
    def reset_sort(self):
        """重置排序状态"""
        self.sort_columns = []
        self.sort_orders = {}
        self.table.horizontalHeader().setSortIndicatorShown(False)
        
    def get_form_data(self) -> dict:
        """获取表单数据"""
        return {
            "date": self.date_edit.date().toString("yyyy-MM-dd"),
            "customer": self.customer_input.text(),
            "camera": self.camera_input.text(),
            "problem": self.problem_text.toPlainText(),
            "solution": self.solution_text.toPlainText(),
            "type": self.type_combo.currentText(),
            "status": self.status_combo.currentText()
        }
        
    def set_form_data(self, data: dict):
        """设置表单数据"""
        if "date" in data:
            self.date_edit.setDate(QDate.fromString(data["date"], "yyyy-MM-dd"))
        self.customer_input.setText(data.get("customer", ""))
        self.camera_input.setText(data.get("camera", ""))
        self.problem_text.setPlainText(data.get("problem", ""))
        self.solution_text.setPlainText(data.get("solution", ""))
        self.type_combo.setCurrentText(data.get("type", ""))
        self.status_combo.setCurrentText(data.get("status", ""))
        
    def clear_form(self):
        """清空表单"""
        self.date_edit.setDate(QDate.currentDate())
        self.customer_input.clear()
        self.camera_input.clear()
        self.problem_text.clear()
        self.solution_text.clear()
        self.type_combo.setCurrentIndex(0)
        self.status_combo.setCurrentIndex(0)
        # 重置状态变量
        self.is_table_selection = False
        self.current_selected_row = -1
        self.original_status = ""
        # 启用所有字段
        self.enable_all_fields()
        
    def enable_all_fields(self):
        """启用所有表单字段"""
        self.date_edit.setEnabled(True)
        self.customer_input.setEnabled(True)
        self.camera_input.setEnabled(True)
        self.problem_text.setEnabled(True)
        self.solution_text.setEnabled(True)
        self.type_combo.setEnabled(True)
        self.status_combo.setEnabled(True)
        
    def enable_only_type_and_status(self):
        """只启用问题类型和问题进度字段"""
        self.date_edit.setEnabled(False)
        self.customer_input.setEnabled(False)
        self.camera_input.setEnabled(False)
        self.problem_text.setEnabled(False)
        self.solution_text.setEnabled(False)
        self.type_combo.setEnabled(True)
        self.status_combo.setEnabled(True)
        
    def fill_form_from_table(self, row: int):
        """从表格行填充表单（快速编辑）"""
        try:
            data = {
                "date": self.table.item(row, 2).text(),  # 调整为第2列
                "customer": self.table.item(row, 3).text(),  # 调整为第3列
                "camera": self.table.item(row, 4).text(),  # 调整为第4列
                "problem": self.table.item(row, 5).text(),  # 调整为第5列
                "solution": self.table.item(row, 6).text(),  # 调整为第6列
                "type": self.table.item(row, 7).text(),  # 调整为第7列
                "status": self.table.item(row, 8).text(),  # 调整为第8列
            }
            # 保存原始问题进度
            self.original_status = data.get("status", "")
            self.set_form_data(data)
        except:
            pass
            
    def get_log_file_path(self):
        """获取日志文件路径"""
        # 修改为保存到 src/data 目录
        data_dir = "d:\\WorkLog Pro\\src\\data"
        return os.path.join(data_dir, "app.log")
        
    def add_log(self, message: str, level: str = "信息"):
        """添加日志"""
        log_entry = self.logger.add_log(message, level)
        self.log_text.append(log_entry)
        
    def add_table_row(self, row_data: list):
        """向表格添加一行数据"""
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        # 添加复选框
        checkbox_item = QTableWidgetItem()
        checkbox_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        checkbox_item.setCheckState(Qt.Unchecked)
        self.table.setItem(row, 0, checkbox_item)
        
        # 添加其他数据
        for col, value in enumerate(row_data):
            item = QTableWidgetItem(str(value))
            if col == 0:
                item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, col + 1, item)
            
    def clear_table(self):
        """清空表格"""
        self.table.setRowCount(0)
        
    def get_selected_rows(self):
        """获取所有选中的行（通过复选框）"""
        selected_rows = []
        for row in range(self.table.rowCount()):
            checkbox_item = self.table.item(row, 0)
            if checkbox_item and checkbox_item.checkState() == Qt.Checked:
                selected_rows.append(row)
        return selected_rows
        
    def update_table_row(self, row: int, data: dict):
        """更新指定行数据"""
        if "date" in data:
            self.table.setItem(row, 2, QTableWidgetItem(data["date"]))  # 调整为第2列
        if "customer" in data:
            self.table.setItem(row, 3, QTableWidgetItem(data["customer"]))  # 调整为第3列
        if "camera" in data:
            self.table.setItem(row, 4, QTableWidgetItem(data["camera"]))  # 调整为第4列
        if "problem" in data:
            problem = data["problem"][:50] + '...' if len(data["problem"]) > 50 else data["problem"]
            self.table.setItem(row, 5, QTableWidgetItem(problem))  # 调整为第5列
        if "solution" in data:
            solution = data["solution"][:50] + '...' if len(data["solution"]) > 50 else data["solution"]
            self.table.setItem(row, 6, QTableWidgetItem(solution))  # 调整为第6列
        if "type" in data:
            self.table.setItem(row, 7, QTableWidgetItem(data["type"]))  # 调整为第7列
        if "status" in data:
            self.table.setItem(row, 8, QTableWidgetItem(data["status"]))  # 调整为第8列
