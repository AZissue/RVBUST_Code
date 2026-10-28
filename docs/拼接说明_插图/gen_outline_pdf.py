# -*- coding: utf-8 -*-
"""生成《3D相机拼接方案通俗说明》的大纲 PDF（v2）。
卡片式排版 + TextWriter 写入真实字体（微软雅黑），Latin/数字间距正常；
章节标题与卡片联动分页，不会把标题孤留在页尾。
"""
import os

import fitz

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "..", "3D相机拼接方案_大纲.pdf")

_A4 = fitz.paper_rect("a4")
PAGE_W, PAGE_H = _A4.width, _A4.height
MARGIN = 52
CONTENT_W = PAGE_W - 2 * MARGIN

C_INK = (0.20, 0.25, 0.34)
C_SUB = (0.42, 0.47, 0.56)
C_BLUE = (0.15, 0.39, 0.92)
C_TEAL = (0.05, 0.58, 0.53)
C_AMBER = (0.85, 0.47, 0.03)
C_ROSE = (0.88, 0.11, 0.28)
C_SLATE = (0.36, 0.42, 0.51)
C_CARD = (0.973, 0.980, 0.988)

FONT = fitz.Font(fontfile=r"C:/Windows/Fonts/msyh.ttc")


def wrap_text(text, size, width):
    """用真实字体度量手动换行。"""
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if cur and FONT.text_length(cur + ch, fontsize=size) > width:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


class Layout:
    def __init__(self):
        self.doc = fitz.open()
        self.page = None
        self.page_no = 0
        self.y = 0
        self.new_page()

    def _text(self, x, y, s, size, color):
        tw = fitz.TextWriter(self.page.rect)
        tw.append((x, y), s, font=FONT, fontsize=size)
        tw.write_text(self.page, color=color)

    def _footer(self):
        s = f"— {self.page_no} —"
        w = FONT.text_length(s, fontsize=8)
        self._text(PAGE_W / 2 - w / 2, PAGE_H - 28, s, 8, C_SUB)

    def new_page(self):
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.page_no += 1
        self.y = MARGIN
        self._footer()

    def header(self, title, subtitle):
        self._text(MARGIN, self.y + 18, title, 18, C_INK)
        self.y += 40
        for line in wrap_text(subtitle, 9.5, CONTENT_W):
            self._text(MARGIN, self.y + 10, line, 9.5, C_SUB)
            self.y += 15
        self.y += 10
        self.page.draw_line((MARGIN, self.y), (PAGE_W - MARGIN, self.y),
                            color=C_BLUE, width=1.4)
        self.y += 18

    def chapter(self, text, color, lookahead=90):
        """章节标题；lookahead 保证标题不会孤留在页尾。"""
        h = 26
        if self.y + h + lookahead > PAGE_H - MARGIN - 16:
            self.new_page()
        self.page.draw_rect(fitz.Rect(MARGIN, self.y + 2, MARGIN + 3.5,
                                      self.y + 17), color=None, fill=color)
        self._text(MARGIN + 11, self.y + 15, text, 12.5, color)
        self.y += h + 4

    def card(self, heading, body, color=C_BLUE, indent=0):
        x = MARGIN + indent
        w = CONTENT_W - indent
        pad = 11
        hs, bs = 10.5, 9.3
        body_lines = wrap_text(body, bs, w - 2 * pad - 6) if body else []
        h = pad + 15 + (len(body_lines) * 14.5 + 7 if body_lines else 0) + pad
        if self.y + h > PAGE_H - MARGIN - 16:
            self.new_page()
        self.page.draw_rect(fitz.Rect(x, self.y, x + w, self.y + h),
                            color=None, fill=C_CARD, radius=0.06)
        self.page.draw_rect(fitz.Rect(x, self.y, x + 3.5, self.y + h),
                            color=None, fill=color)
        ty = self.y + pad + 10
        self._text(x + pad + 4, ty, heading, hs, C_INK)
        ty += 10
        for line in body_lines:
            ty += 14.5
            self._text(x + pad + 4, ty, line, bs, C_SUB)
        self.y += h + 9

    def close(self):
        tmp = OUT + ".tmp.pdf"
        try:
            self.doc.subset_fonts()
        except Exception as e:
            print("subset_fonts skipped:", e)
        self.doc.save(tmp, deflate=True, garbage=3)
        self.doc.close()
        try:
            os.replace(tmp, OUT)
            print("saved:", os.path.abspath(OUT), "pages:", self.page_no)
        except OSError:
            alt = OUT.replace(".pdf", "_v2.pdf")
            try:
                os.remove(alt)
            except OSError:
                pass
            os.replace(tmp, alt)
            print("TARGET LOCKED, saved as:", os.path.abspath(alt))


def main():
    L = Layout()
    L.header("3D 相机拼接方案通俗说明 · 内容大纲",
             "主线：拼接 = 求每片点云到公共坐标系的变换矩阵；线索要么来自工件上的标记，"
             "要么来自运动机构的读数，要么靠固定阵列一次标定。")

    L.chapter("一、什么是 3D 相机拼接", C_BLUE)
    L.card("核心概念",
           "单台 3D 相机一次只能拍一块。拼接 = 把多片点云合成到同一坐标系，"
           "关键就是求出每片点云的 4×4 变换矩阵（旋转 + 平移）。"
           "类比：认出两张风景照里的同一座塔，就能把照片对齐。")

    L.chapter("二、三类主流思路", C_TEAL)
    L.card("2.1 贴标记物（编码圆）—— 兜底方案",
           "工件上贴带唯一编号的编码圆；相邻两帧共有 ≥3 个（建议 ≥6）标记即可解矩阵。"
           "零工装、最灵活；但贴标拍帧人工成本高，链式误差会累积漂移"
           "（须扫回起点闭环 + 全局优化），且编码数量有限、大面积要防重码。",
           C_TEAL)
    L.card("2.2 已知运动拼接 —— 工业首选",
           "变换矩阵由机构读数直接给出：编码器线扫（长工件）/ 导轨走拍（高精度离线）/"
           "机器人手眼（柔性产线，一次标定随处换算）/ 转台托辊（回转体 360°）。"
           "精度 0.2~1 mm，前提是要有运动硬件。",
           C_TEAL)
    L.card("2.3 多相机固定阵列 + 一次标定 —— 量产最优",
           "相机环绕固定安装，标定一次长期复用，工件上不贴任何东西；精度最高 0.1~0.5 mm；"
           "代价是工装成本最高、柔性差，多机同拍要交替触发防结构光互扰。",
           C_TEAL)
    L.card("2.4 辅助手段：ICP 只能当精配准微调",
           "圆柱面上绕轴旋转 + 沿轴滑移两个自由度不可观测（简并），纯 ICP 必然漂移，"
           "不能独立使用，只作各方案的后处理 refine。",
           C_SLATE)

    L.chapter("三、特殊难题：顶底拼接", C_AMBER)
    L.card("顶、底相机互相看不到对方视野，常规手段失效",
           "双面标定物中转：两面标记、厚度已知，一次标定桥接两个坐标系（固定工位首选，"
           "0.1~0.5 mm）；物体侧面贴标链式传递（柔性场景）；"
           "夹具翻转或转台（需要完整 360° 模型时）。",
           C_AMBER)

    L.chapter("四、方案对比一览", C_BLUE)
    L.card("精度 / 柔性 / 成本 速查",
           "精度：固定阵列(0.1~0.5) > 线扫/导轨(0.2~1) > 机器人/转台(0.3~1) > "
           "纯标记(0.5~2) > 纯 ICP(不可控)；柔性大体相反；工装成本：阵列最高，"
           "标记法几乎为零。产线在线检测 → 阵列或已知运动；无机构兜底 → 标记法。",
           C_BLUE)

    L.chapter("五、怎么选：六个问题", C_ROSE)
    L.card("选型决策清单",
           "① 相机能否装上运动机构？ ② 工件能否转？ ③ 全表面还是局部检测？ "
           "④ 精度目标多少 mm？ ⑤ 表面允不允许贴标记？ ⑥ 离线建模还是产线在线？"
           "—— 前两个为“是”优先已知运动，在线检测排除标记法。",
           C_ROSE)

    L.chapter("六、局限性与常见坑", C_SLATE)
    L.card("所有方案共同的现实约束",
           "重叠区“双层皮”（去重/下采样/平滑）；链式漂移（闭环 + 全局优化）；"
           "结构光互扰（交替触发/异色波段）；标记质量（≥4 像素、无孔洞、不重码）；"
           "验收用标准球/量块 + 重叠区 RMS 说话；温漂需定期补偿；"
           "内存单位米 vs 落盘毫米，差 1000 倍最常见。",
           C_SLATE)

    L.chapter("七、一句话总结", C_INK)
    L.card("本质",
           "3D 拼接 = 求每片点云到公共坐标系的变换矩阵。线索来自标记（灵活但累）、"
           "来自运动机构读数（高精度省事但要硬件）、或一次标定永久复用（量产最优）；"
           "纯算法对齐（ICP）只能打下手，不能挑大梁。",
           C_INK)

    L.close()


if __name__ == "__main__":
    main()
