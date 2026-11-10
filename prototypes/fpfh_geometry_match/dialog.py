"""Production editor adapter; no camera or separate rendering implementation."""
import json
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QComboBox,QCheckBox,QSpinBox,QDoubleSpinBox,QScrollArea,QWidget,QPushButton,QPlainTextEdit,QLabel,QFileDialog)
from .algorithm import SPECS,DEFAULTS,validate,solve,merge
from core.frame_database import STALE_RESULT

class FPFHDialog(QDialog):
    def __init__(self,editor):
        super().__init__(editor); self.editor=editor; self.busy=False; self.result=None
        self.setFont(QFont('Microsoft YaHei',9))
        self.setWindowTitle('FPFH + 几何约束 · 参数调试（mm）'); self.resize(860,760)
        layout=QVBoxLayout(self)
        note=QLabel('从实验副本DB选择两项点云。移动 → 参考；参数和矩阵单位均为mm。\n先计算候选并核对报告，再生成DB结果；原始颜色及完整有效点保留。对称物体需人工检查。')
        note.setWordWrap(True); layout.addWidget(note)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); body=QWidget(); form=QFormLayout(body); scroll.setWidget(body); layout.addWidget(scroll,1)
        self.reference=QComboBox(); self.moving=QComboBox()
        for combo in (self.reference,self.moving):
            for row in editor.database.records.values():
                if row.status != STALE_RESULT: combo.addItem(row.logical_name+' · '+row.uid[:6],row.uid)
        if self.moving.count()>1:self.moving.setCurrentIndex(1)
        form.addRow('固定参考',self.reference);form.addRow('移动点云',self.moving)
        self.controls={}
        for key,value,low,high,help_text in SPECS:
            if isinstance(value,bool):
                widget=QCheckBox();widget.setChecked(value)
            elif isinstance(value,str):
                widget=QComboBox();widget.addItems(['exact_kdtree','open3d'])
            elif isinstance(value,int):
                widget=QSpinBox();widget.setRange(low,high);widget.setValue(value)
            else:
                widget=QDoubleSpinBox();widget.setDecimals(9 if low < .000001 else 6 if key == 'confidence' else 3);widget.setRange(low,high);widget.setValue(value)
            widget.setToolTip(help_text);self.controls[key]=widget
            saved=getattr(editor,'_fpfh_parameters',{}).get(key,value)
            if isinstance(value,bool):widget.setChecked(saved)
            elif isinstance(value,str):widget.setCurrentText(saved)
            else:widget.setValue(saved)
            label=QLabel(key+'\n'+help_text);label.setWordWrap(True);form.addRow(label,widget)
        self.calculate=QPushButton('计算候选 / 重新计算');layout.addWidget(self.calculate);self.calculate.clicked.connect(self.analyze)
        self.report=QPlainTextEdit();self.report.setReadOnly(True);self.report.setMaximumHeight(190);layout.addWidget(self.report)
        self.confirm=QCheckBox('已核对毫米单位及候选变换，生成结果后在3D视图检查物理对应关系');layout.addWidget(self.confirm)
        self.publish=QPushButton('生成完整拼接DB结果');layout.addWidget(self.publish);self.publish.clicked.connect(self.publish_result)
        self.export=QPushButton('导出参数与诊断JSON');layout.addWidget(self.export);self.export.clicked.connect(self.export_report)
        for w in [self.reference,self.moving,*self.controls.values()]:
            signal=w.currentIndexChanged if isinstance(w,QComboBox) else w.toggled if isinstance(w,QCheckBox) else w.valueChanged
            signal.connect(self.invalidate)
        self.confirm.toggled.connect(self.refresh);self.refresh()
    def parameters(self):
        return {k:w.isChecked() if isinstance(w,QCheckBox) else w.currentText() if isinstance(w,QComboBox) else w.value() for k,w in self.controls.items()}
    def invalidate(self,*_):
        self.result=None;self.confirm.setChecked(False);self.report.setPlainText('输入或参数变化，请重新计算。');self.refresh()
    def refresh(self,*_):
        self.calculate.setEnabled(not self.busy and self.reference.currentData() is not None and self.reference.currentData()!=self.moving.currentData())
        self.publish.setEnabled(not self.busy and self.result is not None and self.confirm.isChecked())
        self.export.setEnabled(not self.busy)
    def analyze(self):
        e=self.editor
        if self.busy or not e._parameter_gate():return
        try:
            p=self.parameters();validate(p)
            e._fpfh_parameters=p.copy()
            self.tokens=tuple((uid,e.database.records[uid].revision) for uid in (self.reference.currentData(),self.moving.currentData()))
        except (ValueError,KeyError) as exc:self.report.setPlainText(str(exc));return
        self.invalidate();self.busy=True;self.refresh()
        for w in [self.reference,self.moving,*self.controls.values()]:w.setEnabled(False)
        directory=e.directory;tokens=self.tokens
        def work():
            e._validate_source(directory,tokens)
            layers=e._read_records(directory,tokens)
            result=solve(layers[0].points,layers[1].points,p)
            e._validate_source(directory,tokens)
            return layers,result
        def finished(value=None,error=None):
            if error:self.report.setPlainText('计算失败：'+str(error))
            else:
                self.layers,self.result=value
                self.result['inputs']=[list(t) for t in tokens]
                self.report.setPlainText(json.dumps(self.result,ensure_ascii=False,indent=2))
            def release():
                if e._worker is not None:QTimer.singleShot(20,release);return
                self.busy=False
                for w in [self.reference,self.moving,*self.controls.values()]:w.setEnabled(True)
                self.refresh()
            QTimer.singleShot(0,release)
        e._run(work,lambda value:finished(value),kind='probe',on_error=lambda error:finished(error=error))
        self.report.setPlainText('后台计算中；FPFH/RANSAC耗时随点数及参数变化，请等待。')
    def publish_result(self):
        e=self.editor
        if self.busy or self.result is None or not self.confirm.isChecked() or not e._parameter_gate():return
        tokens=self.tokens;directory=e.directory;layers=self.layers;result=self.result
        def work():
            e._validate_source(directory,tokens)
            output=merge(*layers,result)
            e._validate_source(directory,tokens)
            return [output]
        e._commit_operation(work,diagnostic=lambda:json.dumps(result,ensure_ascii=False),on_error=lambda error:e._set_status('FPFH发布失败：'+str(error)))
        self.accept()
    def export_report(self):
        path,_=QFileDialog.getSaveFileName(self,'导出FPFH调试报告','','JSON (*.json)')
        if path:
            from pathlib import Path
            try:Path(path).write_text(json.dumps(self.result or {'parameters':self.parameters()},ensure_ascii=False,indent=2),encoding='utf-8')
            except OSError as exc:self.report.setPlainText('导出失败：'+str(exc))
    def reject(self):
        if not self.busy:super().reject()
    def closeEvent(self,event):
        if self.busy:event.ignore()
        else:super().closeEvent(event)
