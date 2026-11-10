"""Production editor adapter; no camera or separate rendering implementation."""
import json
import re
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QComboBox,QCheckBox,QSpinBox,QDoubleSpinBox,QScrollArea,QWidget,QPushButton,QPlainTextEdit,QLabel,QFileDialog,QListWidget,QListWidgetItem,QHBoxLayout)
from core.postprocess.fpfh_registration import SPECS,DEFAULTS,validate,solve,merge,solve_chain,merge_chain
from core.frame_database import STALE_RESULT

class FPFHDialog(QDialog):
    def __init__(self,editor):
        super().__init__(editor); self.editor=editor; self.busy=False; self.result=None
        self.setFont(QFont('Microsoft YaHei',9))
        self.setWindowTitle('FPFH + 几何约束 · 参数调试（mm）'); self.resize(860,760)
        layout=QVBoxLayout(self)
        note=QLabel('默认多帧链式：按勾选列表从上到下，当前帧配准到前一帧，统一到首帧坐标系。单位mm。可切换两帧配准。\n相邻帧需有足够重叠；可关闭此面板导入更多点云。任一步失败整批不发布，未做闭环优化。')
        note.setWordWrap(True); layout.addWidget(note)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); body=QWidget(); form=QFormLayout(body); scroll.setWidget(body); layout.addWidget(scroll,1)
        self.reference=QComboBox(); self.moving=QComboBox()
        for combo in (self.reference,self.moving):
            for row in editor.database.records.values():
                if row.status != STALE_RESULT: combo.addItem(row.logical_name+' · '+row.uid[:6],row.uid)
        if self.moving.count()>1:self.moving.setCurrentIndex(1)
        self.mode=QComboBox();self.mode.addItem('两帧配准','pair');self.mode.addItem('多帧链式配准','chain');self.mode.setCurrentIndex(1)
        form.addRow('配准方式',self.mode)
        form.addRow('固定参考',self.reference);form.addRow('移动点云',self.moving)
        self.chain_list=QListWidget();self.chain_list.setMinimumHeight(130);self.chain_list.setMaximumHeight(180)
        rows=[row for row in editor.database.records.values() if row.status != STALE_RESULT]
        rows.sort(key=lambda row:tuple((0,int(part)) if part.isdigit() else (1,part.lower()) for part in re.split(r'(\d+)',row.logical_name)))
        selected=set(getattr(editor,'_display_ids',[]))
        raw={row.uid for row in rows if row.kind=='raw'}
        defaults=selected if len(selected)>=2 else raw or {row.uid for row in rows}
        for row in rows:
            item=QListWidgetItem(row.logical_name+' · '+row.uid[:6]);item.setData(Qt.UserRole,row.uid)
            item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(Qt.Checked if row.uid in defaults else Qt.Unchecked)
            self.chain_list.addItem(item)
        form.addRow('链式顺序（首项为参考）',self.chain_list)
        order=QHBoxLayout();self.order_buttons=[]
        for title,action in [('上移',lambda:self.move_item(-1)),('下移',lambda:self.move_item(1)),('全选',lambda:self.check_all(True)),('全不选',lambda:self.check_all(False))]:
            button=QPushButton(title);button.clicked.connect(action);order.addWidget(button);self.order_buttons.append(button)
        form.addRow('调整参与帧及顺序',order)
        self.chain_list.itemChanged.connect(self.invalidate)
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
        for w in [self.mode,self.reference,self.moving,*self.controls.values()]:
            signal=w.currentIndexChanged if isinstance(w,QComboBox) else w.toggled if isinstance(w,QCheckBox) else w.valueChanged
            signal.connect(self.invalidate)
        self.confirm.toggled.connect(self.refresh);self.refresh()
    def chain_ids(self):
        return [self.chain_list.item(i).data(Qt.UserRole) for i in range(self.chain_list.count())
                if self.chain_list.item(i).checkState()==Qt.Checked]
    def move_item(self,offset):
        if self.busy:return
        row=self.chain_list.currentRow();target=row+offset
        if row<0 or not 0<=target<self.chain_list.count():return
        item=self.chain_list.takeItem(row);self.chain_list.insertItem(target,item);self.chain_list.setCurrentRow(target);self.invalidate()
    def check_all(self,checked):
        if self.busy:return
        for i in range(self.chain_list.count()):self.chain_list.item(i).setCheckState(Qt.Checked if checked else Qt.Unchecked)
    def parameters(self):
        return {k:w.isChecked() if isinstance(w,QCheckBox) else w.currentText() if isinstance(w,QComboBox) else w.value() for k,w in self.controls.items()}
    def invalidate(self,*_):
        self.result=None;self.confirm.setChecked(False);self.report.setPlainText('输入或参数变化，请重新计算。');self.refresh()
    def refresh(self,*_):
        chain=self.mode.currentData()=='chain'
        self.chain_list.setEnabled(chain and not self.busy)
        for button in self.order_buttons:button.setEnabled(chain and not self.busy)
        self.reference.setEnabled(not chain and not self.busy);self.moving.setEnabled(not chain and not self.busy)
        valid=len(self.chain_ids())>=2 if chain else self.reference.currentData() is not None and self.reference.currentData()!=self.moving.currentData()
        self.calculate.setEnabled(not self.busy and valid)
        self.publish.setEnabled(not self.busy and self.result is not None and self.confirm.isChecked())
        self.export.setEnabled(not self.busy)
    def analyze(self):
        e=self.editor
        if self.busy or not e._parameter_gate():return
        try:
            p=self.parameters();validate(p)
            e._fpfh_parameters=p.copy()
            chain=self.mode.currentData()=='chain'
            ids=self.chain_ids() if chain else [self.reference.currentData(),self.moving.currentData()]
            if len(ids)<2 or len(set(ids))!=len(ids):raise ValueError('请选择至少两项互不重复的点云')
            self.tokens=tuple((uid,e.database.records[uid].revision) for uid in ids)
        except (ValueError,KeyError) as exc:self.report.setPlainText(str(exc));return
        self.invalidate();self.busy=True;self.refresh()
        for w in [self.mode,self.reference,self.moving,*self.controls.values()]:w.setEnabled(False)
        directory=e.directory;tokens=self.tokens
        progress={'stage':'准备FPFH配准'};e._progress_state=progress
        def work():
            e._validate_source(directory,tokens)
            layers=e._read_records(directory,tokens)
            result=solve_chain(layers,p,progress=lambda text:progress.update(stage=text)) if chain else solve(layers[0].points,layers[1].points,p)
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
                for w in [self.mode,self.reference,self.moving,*self.controls.values()]:w.setEnabled(True)
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
            output=merge_chain(layers,result) if result.get('mode')=='chain' else merge(*layers,result)
            e._validate_source(directory,tokens)
            return [output]
        e._commit_operation(work,diagnostic=lambda:json.dumps(result,ensure_ascii=False),on_error=lambda error:e._set_status('FPFH发布失败：'+str(error)))
        self.accept()
    def export_report(self):
        path,_=QFileDialog.getSaveFileName(self,'导出FPFH调试报告','','JSON (*.json)')
        if path:
            from pathlib import Path
            try:Path(path).write_text(json.dumps(self.result or {'parameters':self.parameters(),'mode':self.mode.currentData(),'chain_ids':self.chain_ids()},ensure_ascii=False,indent=2),encoding='utf-8')
            except OSError as exc:self.report.setPlainText('导出失败：'+str(exc))
    def reject(self):
        if not self.busy:super().reject()
    def closeEvent(self,event):
        if self.busy:event.ignore()
        else:super().closeEvent(event)
