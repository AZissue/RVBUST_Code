#pragma once

// 主题系统（Foundation 设计系统，dark-first）。
// 所有设计 token 集中在此；全局 QSS、QPalette、QtNodes 风格全部由 token 生成，
// QSS 内禁止出现与 token 无关的裸 hex。后续换肤/亮色主题在此扩展。

#include <QString>

class QApplication;

namespace rvc::Theme {

// ---- 颜色 token ----
namespace Color {
// 表面层级（深度靠色差分层，不用阴影）
inline const QString Surface0 = "#0F0F13";  // 页面底
inline const QString Surface1 = "#1A1A20";  // 面板/卡片/输入框
inline const QString Surface2 = "#24242C";  // 悬浮/hover
inline const QString Surface3 = "#2E2E38";  // 按下/active

// 文字
inline const QString InkPrimary   = "#F0F0F5";
inline const QString InkSecondary = "#8B8D98";
inline const QString InkTertiary  = "#5C5E6A";
inline const QString InkInverse   = "#141419";  // accent 底上的文字

// 边框
inline const QString Border      = "#2A2A34";
inline const QString BorderHover = "#3E3E4C";

// 唯一点缀色（琥珀橙）：主按钮 / focus 环 / 选中态，不得用作装饰
inline const QString Accent      = "#EA580C";
inline const QString AccentHover = "#C2410C";
inline const QString AccentMuted = "#431407";  // tag/选中底
inline const QString AccentSoft  = "#7C2D12";  // accent 边框变体

// 语义色（仅状态/日志分级）
inline const QString Success      = "#16A34A";
inline const QString SuccessMuted = "#052E16";
inline const QString Warning      = "#D97706";
inline const QString WarningMuted = "#422006";
inline const QString Danger       = "#DC2626";
inline const QString DangerMuted  = "#450A0A";
inline const QString Info         = "#2563EB";
inline const QString InfoMuted    = "#172554";
} // namespace Color

// ---- 间距刻度（4/8/12/16/24/32/48/64，不用中间值）----
namespace Space {
inline constexpr int Xs = 4, Sm = 8, Md = 12, Lg = 16, Xl = 24, X2 = 32, X3 = 48, X4 = 64;
}

// ---- 圆角（按钮/输入/卡片 6px；表格/代码块 0）----
namespace Radius {
inline constexpr int Sm = 6;
}

// ---- 字体族（运行时探测：注册了用注册名，否则沿 fallback 链）----
// UI 字体链：Geist → Inter → Segoe UI → system-ui
QString uiFontFamily();
// 等宽字体链：JetBrains Mono → Fira Code → Consolas
QString monoFontFamily();

// ---- 主题模式（亮色主题预留，当前仅实现 Dark）----
enum class Mode { Dark /*, Light —— 预留 stub，未实现 */ };
void setMode(Mode m);
Mode mode();

// 从 exe 目录 fonts/ 注册应用字体（Geist / JetBrains Mono，OFL 许可）
void registerFonts();

// 用 token 拼出全局 QSS（无裸 hex，全部引用上方常量）
QString appStyleSheet();

// QtNodes 画布风格（NodeStyle/ConnectionStyle/GraphicsViewStyle，JSON 由 token 生成）
void applyQtNodesStyle();

// 一键应用：字体注册 + 应用字体 + QPalette + 全局 QSS + QtNodes 风格
void apply(QApplication& app);

} // namespace rvc::Theme
