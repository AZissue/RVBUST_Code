STYLESHEET = """
QMainWindow { background-color: #1e1e1e; }
QWidget { background-color: #2d2d2d; color: #ffffff; font-family: "Microsoft YaHei", "Segoe UI", Arial; font-size: 9pt; }

QGroupBox { 
    background-color: #363636; 
    border: 1px solid #4a4a4a; 
    border-radius: 4px; 
    margin-top: 4px; 
    font-weight: bold; 
    padding: 6px;
    font-size: 9pt;
}
QGroupBox::title { 
    subcontrol-origin: margin; 
    left: 8px; 
    padding: 0 4px; 
    color: #4fc3f7;
    font-size: 9pt;
}

QPushButton { 
    background-color: #424242; 
    border: 1px solid #4a4a4a; 
    border-radius: 4px; 
    padding: 6px 12px; 
    color: #ffffff; 
    font-weight: 500;
    font-size: 9pt;
    min-height: 28px;
}
QPushButton:hover { background-color: #4a4a4a; border-color: #5a5a5a; }
QPushButton:pressed { background-color: #555555; }
QPushButton:disabled { background-color: #333333; color: #666666; border-color: #3a3a3a; }
QPushButton#primaryButton { background-color: #1976d2; border-color: #1565c0; }
QPushButton#primaryButton:hover { background-color: #1e88e5; }
QPushButton#dangerButton { background-color: #d32f2f; border-color: #c62828; }
QPushButton#dangerButton:hover { background-color: #e53935; }
QPushButton#successButton { background-color: #388e3c; border-color: #2e7d32; }
QPushButton#successButton:hover { background-color: #43a047; }

QLineEdit { 
    background-color: #424242; 
    border: 1px solid #4a4a4a; 
    border-radius: 3px; 
    padding: 4px; 
    color: #ffffff;
    font-size: 9pt;
    min-height: 20px;
}
QTextEdit { 
    background-color: #252525; 
    border: 1px solid #3a3a3a; 
    border-radius: 3px; 
    padding: 6px; 
    color: #e0e0e0; 
    font-family: Consolas, Courier New, monospace; 
    font-size: 8pt;
}
QLabel { color: #e0e0e0; font-size: 9pt; }
QLabel#titleLabel { font-size: 14pt; font-weight: bold; color: #4fc3f7; padding: 4px; }
QLabel#statusLabel { 
    padding: 2px 8px; 
    border-radius: 10px; 
    font-weight: bold;
    font-size: 8pt;
}
QLabel#statusLabel[status="connected"] { background-color: #2e7d32; color: #ffffff; }
QLabel#statusLabel[status="disconnected"] { background-color: #c62828; color: #ffffff; }
QLabel#previewLabel { 
    background-color: #1a1a1a; 
    border: 1px dashed #4a4a4a; 
    border-radius: 3px;
}
QLabel#infoLabel { 
    font-size: 8pt; 
    color: #aaaaaa;
    padding: 2px 4px;
}
QLabel#sectionTitle {
    font-size: 10pt;
    font-weight: bold;
    color: #4fc3f7;
    padding: 4px 0px;
}

QStatusBar { background-color: #1e1e1e; color: #888888; font-size: 8pt; }

QTableWidget { 
    background-color: #252525; 
    border: 1px solid #3a3a3a; 
    border-radius: 3px; 
    gridline-color: #3a3a3a;
    font-size: 8pt;
}
QHeaderView::section { 
    background-color: #363636; 
    padding: 4px; 
    border: 1px solid #4a4a4a; 
    font-weight: bold;
    font-size: 8pt;
}
QTableWidget::item { padding: 2px 4px; }

QSpinBox, QDoubleSpinBox { 
    background-color: #424242; 
    border: 1px solid #4a4a4a; 
    border-radius: 3px; 
    padding: 2px 4px; 
    color: #ffffff;
    font-size: 9pt;
    min-height: 20px;
}

QComboBox { 
    background-color: #424242; 
    border: 1px solid #4a4a4a; 
    border-radius: 3px; 
    padding: 2px 4px; 
    color: #ffffff;
    font-size: 9pt;
    min-height: 20px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView { 
    background-color: #424242; 
    color: #ffffff; 
    selection-background-color: #1976d2;
}

QSplitter::handle { background-color: #4a4a4a; }
QSplitter::handle:horizontal { width: 4px; }
QSplitter::handle:vertical { height: 4px; }

QScrollArea { border: none; background-color: transparent; }
QScrollBar:vertical {
    background-color: #2d2d2d;
    width: 10px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background-color: #4a4a4a;
    border-radius: 5px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover { background-color: #5a5a5a; }
"""
