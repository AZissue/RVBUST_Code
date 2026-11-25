from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout


class NewProjectDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("新建测量项目")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        title = QLabel("创建独立项目目录")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        description = QLabel("项目文件、原始数据、重建结果和报告将按类别保存。")
        description.setObjectName("muted")
        layout.addWidget(description)
        form = QFormLayout()
        self.name_edit = QLineEdit("PRJ-2026-NEW")
        self.part_edit = QLineEdit()
        self.part_edit.setPlaceholderText("例如 PART-A17")
        self.location_edit = QLineEdit(str(Path.home() / "MetrologyProjects"))
        location_row = QHBoxLayout()
        location_row.addWidget(self.location_edit)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        location_row.addWidget(browse)
        form.addRow("项目名称 *", self.name_edit)
        form.addRow("工件编号", self.part_edit)
        form.addRow("保存位置 *", location_row)
        layout.addLayout(form)
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color:#FCA5A5;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("创建项目")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primaryButton")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择项目保存位置", self.location_edit.text())
        if directory:
            self.location_edit.setText(directory)

    def _validate(self) -> None:
        name = self.name_edit.text().strip()
        location = self.location_edit.text().strip()
        if not name or not location:
            self.error_label.setText("请填写项目名称和保存位置。")
            return
        if any(character in name for character in '<>:"/\\|?*'):
            self.error_label.setText("项目名称包含 Windows 不允许的字符，请修改。")
            return
        self.accept()

    @property
    def project_name(self) -> str:
        return self.name_edit.text().strip()

    @property
    def project_directory(self) -> Path:
        return Path(self.location_edit.text().strip()) / self.project_name

    @property
    def part_number(self) -> str:
        return self.part_edit.text().strip()
