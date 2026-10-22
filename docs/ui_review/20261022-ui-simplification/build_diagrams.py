"""Render proposal diagrams only. Does not launch or modify production UI."""
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QApplication

OUT = Path(__file__).resolve().parent
PROJECT = OUT.parents[2]
sys.path.insert(0, str(PROJECT / 'src'))
from ui_v2 import icons
app = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
BG, PANEL, BORDER, TEXT, MUTED, RED = '#242424', '#292929', '#454545', '#e8eaed', '#9aa0a8', '#b93638'


def box(p, x, y, w, h, color=PANEL, border=BORDER, radius=6):
    p.setPen(QPen(QColor(border), 1) if border else Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(x, y, w, h), radius, radius)


def text(p, x, y, w, h, value, size=14, color=TEXT, bold=False, align=Qt.AlignVCenter | Qt.AlignLeft):
    p.setFont(QFont('Microsoft YaHei', size, QFont.Bold if bold else QFont.Normal))
    p.setPen(QColor(color))
    p.drawText(QRectF(x, y, w, h), align, value.replace('▾', 'v').replace('✓', ''))


def button(p, x, y, w, value, primary=False, selected=False, h=34):
    box(p, x, y, w, h, RED if primary else '#3c3033' if selected else '#34373c',
        '#dc6267' if primary else '#875055' if selected else BORDER, 5)
    text(p, x, y, w, h, value, 12, bold=primary, align=Qt.AlignCenter)


def badge(p, x, y, number):
    box(p, x, y, 25, 25, RED, None, 12)
    text(p, x, y, 25, 25, str(number), 12, bold=True, align=Qt.AlignCenter)


def cloud(p):
    area = QRectF(366, 145, 1208, 662)
    box(p, area.x(), area.y(), area.width(), area.height(), '#35383a', '#45484d', 0)
    p.save()
    p.setClipRect(area.adjusted(1, 1, -1, -1))
    p.setPen(QPen(QColor('#474c4b'), 1))
    for x in range(380, 1800, 85):
        p.drawLine(QPointF(x, 145), QPointF(x-270, 807))
    for y in range(200, 810, 65):
        p.drawLine(QPointF(366, y), QPointF(1574, y-90))
    path = PROJECT / 'offline_test_data/stool/.cache/1.ply'
    if path.exists():
        import open3d as o3d
        pointcloud = o3d.io.read_point_cloud(str(path))
        pts = np.asarray(pointcloud.points)
        keep = np.flatnonzero(np.isfinite(pts).all(axis=1) & (np.abs(pts).sum(axis=1)>0))
        keep = keep[np.linspace(0, len(keep)-1, min(65000, len(keep)), dtype=int)]
        pts = pts[keep]
        colors = np.asarray(pointcloud.colors)[keep] if pointcloud.has_colors() else np.tile([.7,.8,.8], (len(pts),1))
        display_xy = np.column_stack((-pts[:,1], pts[:,0]))
        low, high = np.percentile(display_xy, [1,99], axis=0)
        scale = min(860/max(high[0]-low[0],1), 525/max(high[1]-low[1],1))
        xy = (display_xy-(low+high)/2)*scale + [905,490]
        bins = np.clip((colors*7).astype(int),0,7)
        ids = bins[:,0]*64+bins[:,1]*8+bins[:,2]
        for value in np.unique(ids):
            mask = ids==value
            p.setPen(QPen(QColor.fromRgbF(*np.clip(colors[mask].mean(axis=0),0,1)),2))
            p.drawPoints(QPolygonF([QPointF(float(x),float(y)) for x,y in xy[mask]]))
    p.restore()
    text(p, 386, 158, 670, 25, '3D 工作视图  ·  正在查看原始帧 002', 12)
    text(p, 386, 774, 900, 24, '左键旋转   右键平移   滚轮缩放   F 适配   F11 专注视图', 11, '#cad0d3')


def ribbon_group(p, x, y, caption, entries):
    begin = x
    for label, glyph, width in entries:
        primary = label in ('执行拼接', '计算外参', '计算转轴')
        if primary:
            box(p, x, y, width-4, 55, '#633134', '#954447', 5)
        icon = icons.pixmap(glyph, '#d6d6d6', 23)
        p.drawPixmap(int(x+(width-23)/2), int(y+4), icon)
        text(p, x, y+30, width-4, 23, label, 11, align=Qt.AlignCenter)
        x += width
    text(p, begin, y+57, x-begin-4, 19, caption, 10, '#8f97a4', align=Qt.AlignCenter)
    p.setPen(QPen(QColor('#41444a'),1))
    p.drawLine(QPointF(x+7,y),QPointF(x+7,y+72))
    return x+24


def overview():
    image = QImage(1600, 1072, QImage.Format_ARGB32)
    image.fill(QColor('#17181b'))
    p=QPainter(image);p.setRenderHint(QPainter.Antialiasing)
    text(p, 24, 4, 1050, 34, 'MCC 工业风格保留与操作整合示意', 19, bold=True)
    text(p, 1070, 4, 505, 34, '布局示意 · 数据与状态为示例 · 2026-10-22', 11, MUTED, align=Qt.AlignRight|Qt.AlignVCenter)
    box(p, 14, 48, 1572, 858, BG, BORDER, 4)
    box(p, 15, 49, 1570, 48, '#202226', None, 0)
    badge(p, 27, 60, 1)
    box(p, 65, 57, 68, 32, '#b93638', None, 4)
    text(p, 65, 57, 68, 32, 'MCC', 17, bold=True, align=Qt.AlignCenter)
    text(p, 146, 56, 133, 34, 'SCAN STUDIO', 12, '#b8bec8', True)
    text(p, 297, 56, 180, 34, '单相机移动拼接', 14, bold=True)
    text(p, 500, 56, 405, 34, '支架扫描  ·  未保存', 12, MUTED)
    text(p, 1030, 56, 160, 34, '相机已连接  1 台', 11, '#b6c7bc')
    button(p, 1220, 56, 100, '切换工作区')
    button(p, 1332, 56, 110, '运行日志')
    button(p, 1454, 56, 110, '帮助')
    box(p, 15, 98, 1570, 86, '#292b2f', None, 0)
    badge(p,27,108,2)
    x=ribbon_group(p,65,102,'项目',[('项目 v','folder_open',78),('保存','save',72),('导出','layers',72)])
    x=ribbon_group(p,x,102,'设备',[('设备与参数','sliders',110)])
    x=ribbon_group(p,x,102,'采集',[('实时取景','video',90),('拍摄机位','camera',90)])
    x=ribbon_group(p,x,102,'拼接',[('范围: 全部(4)','layers',135),('执行拼接','stitch',95)])
    ribbon_group(p,x,102,'视图',[('等轴测','layers',94),('适配 F','reset_view',86),('显示设置','sliders',96),('2D预览','video',90),('视图工具','help',100)])
    p.save()
    p.translate(0,42)
    box(p, 24,153,326,652,PANEL,BORDER,5)
    badge(p,35,164,3)
    text(p,72,161,235,31,'项目数据',14,bold=True)
    text(p,39,204,281,26,'支架扫描  ·  4 帧 / 1 结果',12)
    button(p,38,244,92,'数据',selected=True)
    button(p,137,244,92,'任务参数')
    button(p,236,244,99,'属性')
    text(p,40,292,280,28,'▾ 原始数据（4）',12,bold=True)
    labels=['  帧 001    ·    2D + 3D','  帧 002    ·    2D + 3D','  帧 003    ·    2D + 3D','  帧 004    ·    2D + 3D']
    for index,label in enumerate(labels):
        y=328+index*42
        if index==1:box(p,34,y,306,37,'#493438','#735157',4)
        text(p,48,y,282,37,label,12)
    text(p,40,515,280,28,'▾ 拼接结果（1）',12,bold=True)
    text(p,51,551,275,32,'  拼接帧 001    ·    412 万点',12)
    text(p,40,607,282,28,'已选：原始帧 002',11,'#d3b0b2')
    button(p,38,645,128,'重拍帧 002')
    button(p,175,645,70,'删除')
    button(p,254,645,82,'更多 ▾')
    text(p,40,694,282,27,'仅作用于选中帧，不改变拼接范围',10,MUTED)
    box(p,36,742,301,49,'#242a27','#3e5546',5)
    text(p,48,746,278,37,'✓ 标记拟合通过   0.005 mm',11,'#a7d6b4')
    cloud(p)
    badge(p,377,199,4)
    # Preview content uses the existing offline fixture, never a live device.
    box(p,1263,177,287,239,'#25272b','#565b62',7)
    text(p,1278,185,221,28,'2D 预览 · 原始帧 002',11,bold=True)
    text(p,1502,185,30,28,'—',15,align=Qt.AlignCenter)
    source=QImage(str(PROJECT/'offline_test_data/stool/.cache/1.png'))
    if not source.isNull():p.drawImage(QRectF(1278,221,257,172),source)
    text(p,379,816,1080,30,'正在查看：原始帧 002   ·   2D / 3D 同步   ·   项目未保存',11,MUTED)
    box(p,24,873,1552,135,'#24262a',None,7)
    items=[(1,'项目与全局','新建、打开、会话管理归入项目菜单'),(2,'任务与视图','保留图标与组名，只合并重复操作'),(3,'数据与参数','选中帧操作只在左栏出现一次'),(4,'纯净画布','移走3D独立工具栏，预览只留折叠')]
    for index,(number,title,detail) in enumerate(items):
        x=40+index*385;badge(p,x,889,number)
        text(p,x+35,884,326,31,title,13,bold=True)
        text(p,x,931,365,47,detail,11,MUTED)
    p.restore()
    p.end();assert image.save(str(OUT/'layout-overview.png'))


def modes():
    image=QImage(1600,470,QImage.Format_ARGB32);image.fill(QColor('#1b1d20'))
    p=QPainter(image);p.setRenderHint(QPainter.Antialiasing)
    text(p,25,12,1500,38,'保留原工业功能区样式，只替换各模式任务组',19,bold=True)
    specs=[('多相机标定','拍摄标定帧','检测标记','计算外参','参考相机 / 标记类型 / 标定结果'),
           ('移动拼接','实时取景','拍摄机位','执行拼接','拼接范围 / 选中帧重拍与删除'),
           ('转台拼接','拍摄基准帧','拍摄旋转帧','计算转轴','转角 / 步长 / 步数 / 轴心参数')]
    for index,(name,a,b,c,detail) in enumerate(specs):
        y=75+index*118
        box(p,24,y,1550,102,PANEL,BORDER,6)
        text(p,43,y+12,180,37,name,14,bold=True)
        for j,label in enumerate((a,b,c)):
            ribbon_group(p,235+j*155,y+7,'',[(label,('video' if '取景' in label else 'stitch' if j==2 else 'camera'),142)])
        text(p,735,y+12,780,37,'共用视图区：视角 / 适配 / 显示设置 / 2D / 视图工具',12,MUTED)
        text(p,236,y+69,1240,24,'左栏任务参数：'+detail,11,MUTED)
    text(p,25,432,1540,25,'注：多相机与转台的工具条随“标定 / 扫描”阶段切换；未满足条件时给出禁用原因。',11,MUTED)
    p.end();assert image.save(str(OUT/'mode-task-bars.png'))


if __name__=='__main__':
    overview();modes()
