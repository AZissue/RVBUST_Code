#pragma once
#include <QColor>
#include <QIcon>
#include <QString>

namespace Theme {

// ── Color palette ──
inline constexpr const char* PRIMARY       = "#1677FF";
inline constexpr const char* PRIMARY_HOVER = "#4096FF";
inline constexpr const char* PRIMARY_CLICK = "#0958D9";
inline constexpr const char* PRIMARY_LIGHT = "#E6F7FF";
inline constexpr const char* BG_MAIN       = "#FFFFFF";
inline constexpr const char* BG_CARD       = "#F5F5F5";
inline constexpr const char* BG_DARK_2D    = "#000000";
inline constexpr const char* BG_DARK_3D    = "#1A1A1A";
inline constexpr const char* BORDER_DEFAULT = "#D9D9D9";
inline constexpr const char* BORDER_FOCUS  = "#1677FF";
inline constexpr const char* TEXT_TITLE    = "#262626";
inline constexpr const char* TEXT_BODY     = "#434343";
inline constexpr const char* TEXT_HINT     = "#8C8C8C";
inline constexpr const char* SUCCESS       = "#52C41A";
inline constexpr const char* WARNING       = "#FAAD14";
inline constexpr const char* ERROR         = "#F5222D";
inline constexpr const char* ERROR_BG      = "#FFF2F0";
// 3D 视窗容器的底衬色（T-008 r3：从 VisSceneView.cpp 的字面量收敛到这里，
// 取值逐位不变——原来写的是 rgb(26, 31, 46)）。
inline constexpr const char* BG_SCENE_3D   = "#1A1F2E";

// ── Fonts ──
inline constexpr const char* FONT_FAMILY   = "Microsoft YaHei";
inline constexpr int FONT_H1  = 18;
inline constexpr int FONT_H2  = 16;
inline constexpr int FONT_BODY = 14;
inline constexpr int FONT_HINT = 12;

// ── Dimensions & effects ──
inline constexpr int RECOMMENDED_COUNT = 15;
inline constexpr int BORDER_RADIUS = 8;
inline constexpr const char* CARD_SHADOW   = "0 2px 8px rgba(0, 0, 0, 0.08)";
inline constexpr const char* BTN_SHADOW    = "0 2px 4px rgba(22, 119, 255, 0.2)";
inline constexpr const char* ACTIVE_SHADOW = "0 4px 12px rgba(22, 119, 255, 0.15)";

// ── 12 栅格设计系统 ───────────────────────────────────────────────
// 全界面共用一套尺寸语言：12 列、页边距 24、列间距 16、行基线 8。
// 主窗口设计宽 1280：内容宽 1232，列宽 88；右栏 4 列 = 400，2D/3D 各 4 列。
// 工具窗口设计宽 1040：内容宽 992，列宽 64；左列表 2 列 = 144，内容 10 列 = 784。
// 新布局一律用 Grid 的常量，不要再写 4/6/10/14/15/20 这类散值。
namespace Grid {
inline constexpr int Columns = 12;
inline constexpr int Margin = 24;
inline constexpr int Gutter = 16;
inline constexpr int Row = 8;

inline constexpr int MainWidth = 1280;
inline constexpr int MainHeight = 720;
inline constexpr int ToolsWidth = 1040;
inline constexpr int ToolsHeight = 720;

inline constexpr int IconSm = 16;
inline constexpr int IconMd = 18;
inline constexpr int IconLg = 20;
inline constexpr int LogoSize = 24;
inline constexpr int ControlH = 32;   // 4 行
inline constexpr int ActionH = 40;    // 5 行

// 最接近 8 的倍数（用于从视觉尺寸反推栅格值）。
inline constexpr int snap(int px)
{
    return ((px + Row / 2) / Row) * Row;
}

// 12 列栅格在给定内容宽度下的单列宽度（最小 0，避免窄窗口出现负值）。
inline constexpr int columnWidth(int contentWidth)
{
    const int usable = contentWidth - (Columns - 1) * Gutter;
    return usable > 0 ? usable / Columns : 0;
}

// 跨 n 列的总宽度（含列间距）。n 会被夹到 [0, 12]。
inline constexpr int spanWidth(int contentWidth, int n)
{
    if (n <= 0)
        return 0;
    if (n > Columns)
        n = Columns;
    const int col = columnWidth(contentWidth);
    return n * col + (n - 1) * Gutter;
}
} // namespace Grid

// 单色线性 SVG 图标（resources/icons/*.svg）。运行时用 QSvgRenderer 渲染并着色，
// 同一份 SVG 可同时用于深色文字、浅色文字与主色按钮；按 name/color/size/dpr 缓存。
QIcon icon(const QString& name,
           const QColor& color = QColor(QString::fromLatin1(TEXT_BODY)),
           int size = Grid::IconMd);

// ── QSS factories ──
// 把 Theme 的颜色常量包成 "rgba(r, g, b, a)"（alpha ∈ [0,1]）。品牌蓝这类
// "同一个色、不同 alpha" 的写法都经这里取值，改主题色只需改上面的常量。
QString withAlpha(const char* color, double alpha);
QString globalStylesheet();
QString primaryButtonStyle();
QString secondaryButtonStyle();
// secondary style with reduced horizontal padding — for longer labels (e.g.
// the robot read buttons) so they stay compact when the window is narrow.
QString secondaryButtonCompactStyle();
QString secondaryEmphasisButtonStyle();
QString dangerButtonStyle();
// In-progress state: translucent sky-blue gradient that stays visible even
// when the button is disabled (no grey-out).
QString busyButtonStyle();
// Short highlight for quick actions (save/undo flash).
QString flashButtonStyle();
QString inputStyle(int fontSize = FONT_BODY);
QString inputErrorStyle();
QString toggleSelectedStyle();
QString toggleUnselectedStyle();
QString comboBoxStyle();
QString spinBoxStyle();

// ── 2D/3D 视窗的浮层（用户反馈 4：无边框、无底色、半透明背景）──
// 只给这两个视窗用：标签与工具栏按钮统一成同一种"看得见底下图像"的浮层样式。
// 2D/3D 视窗上的文字标签：无边框、无实心底色，只有一层很淡的半透明底。
QString viewOverlayLabelStyle();
// 2D/3D 视窗底部工具栏的按钮：同上，悬停/按下时略亮一点。
QString viewOverlayButtonStyle();

} // namespace Theme
