COLORS = {
    "window": "#172333",
    "workspace": "#111C2B",
    "panel": "#202E3E",
    "secondary": "#26374A",
    "border": "#34475C",
    "primary": "#3B82F6",
    "success": "#22C55E",
    "warning": "#F59E0B",
    "error": "#EF4444",
    "text": "#E2E8F0",
    "muted": "#94A3B8",
}


def stylesheet() -> str:
    return f"""
    * {{ font-family: "Segoe UI", "Microsoft YaHei", sans-serif; font-size: 12px; color: {COLORS['text']}; }}
    QMainWindow, QDialog {{ background: {COLORS['window']}; }}
    QMenuBar {{ background: #14202F; border-bottom: 1px solid {COLORS['border']}; padding: 2px 6px; }}
    QMenuBar::item {{ padding: 5px 10px; background: transparent; }}
    QMenuBar::item:selected {{ background: {COLORS['secondary']}; border-radius: 3px; }}
    QMenu {{ background: {COLORS['panel']}; border: 1px solid {COLORS['border']}; padding: 5px; }}
    QMenu::item {{ padding: 7px 28px 7px 12px; border-radius: 3px; }}
    QMenu::item:selected {{ background: {COLORS['primary']}; color: white; }}
    QMenu::separator {{ height: 1px; background: {COLORS['border']}; margin: 5px 8px; }}
    QToolBar {{ background: #182635; border: none; spacing: 4px; padding: 0px; }}
    QToolButton {{ min-height: 30px; padding: 0 8px; border: 1px solid transparent; border-radius: 4px; background: transparent; }}
    QToolButton:hover {{ background: {COLORS['secondary']}; border-color: {COLORS['border']}; }}
    QToolButton:pressed {{ background: #172333; }}
    QToolButton:checked {{ background: #1D4E89; border-color: {COLORS['primary']}; color: #FFFFFF; }}
    QToolButton:disabled {{ color: #64748B; background: #1B2938; }}
    QPushButton {{ min-height: 32px; padding: 0 13px; border: 1px solid {COLORS['border']}; border-radius: 4px; background: {COLORS['secondary']}; }}
    QPushButton:hover {{ background: #30465E; border-color: #526A83; }}
    QPushButton:pressed {{ background: #182635; }}
    QPushButton:focus, QToolButton:focus {{ border: 2px solid #7CB3FF; }}
    QPushButton#primaryButton {{ background: {COLORS['primary']}; color: white; border-color: #60A5FA; font-weight: 600; }}
    QPushButton#primaryButton:hover {{ background: #2570E8; }}
    QPushButton#navButton {{ border: none; border-radius: 3px; padding: 0 11px; color: {COLORS['muted']}; }}
    QPushButton#navButton:hover {{ color: white; background: {COLORS['secondary']}; }}
    QPushButton#navButton:checked {{ color: white; background: #244E78; border-bottom: 2px solid #60A5FA; }}
    QDockWidget {{ color: {COLORS['text']}; font-weight: 600; titlebar-close-icon: none; titlebar-normal-icon: none; }}
    QDockWidget::title {{ background: #1B2939; text-align: left; padding: 8px 10px; border-bottom: 1px solid {COLORS['border']}; }}
    QDockWidget > QWidget {{ background: {COLORS['panel']}; }}
    QScrollArea {{ background: {COLORS['panel']}; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: {COLORS['panel']}; }}
    QTreeView, QTableView, QListView, QPlainTextEdit {{ background: #172534; alternate-background-color: #1B2B3B; border: 1px solid {COLORS['border']}; border-radius: 3px; selection-background-color: #24578C; selection-color: white; outline: none; }}
    QTreeView::item {{ min-height: 28px; padding: 2px 3px; border: none; }}
    QTreeView::item:hover {{ background: #263B50; }}
    QTreeView::item:selected {{ background: #24578C; border-left: 2px solid #72AFFF; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ min-height: 30px; background: #152231; border: 1px solid {COLORS['border']}; border-radius: 4px; padding: 0 8px; selection-background-color: {COLORS['primary']}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 2px solid #6BA8F8; }}
    QLineEdit[readOnly="true"] {{ background: transparent; border: none; color: {COLORS['muted']}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{ background: {COLORS['panel']}; border: 1px solid {COLORS['border']}; selection-background-color: {COLORS['primary']}; }}
    QTabWidget::pane {{ border: 1px solid {COLORS['border']}; background: {COLORS['panel']}; }}
    QTabBar::tab {{ background: #182635; color: {COLORS['muted']}; min-height: 30px; padding: 0 16px; border: none; border-right: 1px solid {COLORS['border']}; }}
    QTabBar::tab:selected {{ background: {COLORS['panel']}; color: white; border-top: 2px solid {COLORS['primary']}; }}
    QHeaderView::section {{ background: #26374A; color: #CBD5E1; border: none; border-right: 1px solid {COLORS['border']}; border-bottom: 1px solid {COLORS['border']}; padding: 6px 8px; font-weight: 600; }}
    QGroupBox {{ border: 1px solid {COLORS['border']}; border-radius: 4px; margin-top: 12px; padding-top: 10px; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #B7C8D9; }}
    QLabel#muted {{ color: {COLORS['muted']}; }}
    QLabel#sectionTitle {{ font-size: 16px; font-weight: 600; color: white; }}
    QLabel#brand {{ font-size: 16px; font-weight: 700; color: white; }}
    QLabel#brandAccent {{ color: #70ACFA; font-size: 11px; font-weight: 600; }}
    QLabel#statusOk {{ color: #6EE7A0; }}
    QLabel#badge {{ background: #263F56; color: #A9D2FF; border: 1px solid #3D6487; border-radius: 3px; padding: 3px 6px; }}
    QStatusBar {{ background: #14202F; border-top: 1px solid {COLORS['border']}; color: {COLORS['muted']}; }}
    QStatusBar::item {{ border: none; }}
    QScrollBar:vertical {{ background: #172534; width: 11px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: #40566E; min-height: 28px; border-radius: 4px; margin: 2px; }}
    QScrollBar:horizontal {{ background: #172534; height: 11px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: #40566E; min-width: 28px; border-radius: 4px; margin: 2px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QProgressBar {{ background: #14202F; border: 1px solid {COLORS['border']}; border-radius: 3px; text-align: center; max-height: 14px; }}
    QProgressBar::chunk {{ background: {COLORS['primary']}; }}
    QToolTip {{ background: #26374A; color: white; border: 1px solid #526A83; padding: 5px; }}
    """
