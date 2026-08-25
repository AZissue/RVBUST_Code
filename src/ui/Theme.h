#pragma once
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

// ── QSS factories ──
QString globalStylesheet();
QString primaryButtonStyle();
QString secondaryButtonStyle();
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

} // namespace Theme
