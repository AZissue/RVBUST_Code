#pragma once
// 操作日志"落屏"规则（纯逻辑，无 Qt、无界面）——第 10 回合 P4 返工。
//
// 背景：LogManager 总是把条目写进文件日志，界面右侧的「操作日志」面板却只由
// SidePanel::setTip() / setPoseGuide() / setQualityReport() 追加，于是
// [测量-说明] / [测量-结果] 只落在文件里、用户看不见（P4 不通过的根因是
// MainWindow 里那条连接 `LogManager::logAdded` 的 lambda 是空的）。
//
// 这个头文件放两件"用户直接读到"的事，两件都可单测：
//   1) 级别 → 面板标签/配色角色的表（唯一来源，界面侧不再自己写 if-else）；
//   2) 哪些条目值得上屏（只有测量日志）。
//
// 颜色**刻意**不在这里：十六进制色值归 ui/Theme.h，这里只给"配色角色"，
// 界面侧按角色取色。这样逻辑层不必知道 UI 主题，单测也不必比对颜色字符串。
#include <string>

#include "MeasureMethods.h"

namespace MeasureTools {

// 面板标签的配色角色，与 Theme.h 的 PRIMARY / SUCCESS / WARNING / ERROR 一一对应。
enum class LogColorRole { Primary, Success, Warning, Error };

// 面板里一条日志的"外形"。text 不在这里——正文由调用方原样交给面板。
struct LogPresentation {
    std::string  level;  // 归一化后的级别名（未知级别 → "info"）
    std::string  label;  // 面板方括号里的字，如 [提示]
    LogColorRole color;
};

// 级别 → 标签/配色。LogManager 只发 info/success/warning/error（见
// LogManager.cpp 的四个便捷方法），但**任何不认识的级别都按 info 处理**：
// 面板只负责展示，宁可显示成一条普通提示，也不要因为拼错级别把日志丢掉。
// 标签沿用面板里已有的字（[提示] 来自 setTip，[警告] 来自 setPoseGuide），
// 所以老路径与新转发在视觉上是同一套。
inline LogPresentation logPresentation(const std::string& level)
{
    if (level == "success") return { "success", "完成", LogColorRole::Success };
    if (level == "warning") return { "warning", "警告", LogColorRole::Warning };
    if (level == "error")   return { "error",   "错误", LogColorRole::Error };
    return { "info", "提示", LogColorRole::Primary };
}

// 配色角色的名字。给"要不要换配色"这类调试与断言用；界面侧用的是角色本身。
inline const char* logColorRoleName(LogColorRole role)
{
    switch (role) {
    case LogColorRole::Success: return "success";
    case LogColorRole::Warning: return "warning";
    case LogColorRole::Error:   return "error";
    case LogColorRole::Primary: break;
    }
    return "primary";
}

// text 是否以 "[tag] " 的方括号前缀开头（标签本身，不是"含有"）。
inline bool taggedWith(const std::string& text, const char* tag)
{
    const std::string prefix = std::string("[") + tag + "]";
    return text.compare(0, prefix.size(), prefix) == 0;
}

// 该不该把这条日志转发给界面「操作日志」面板。
//
// **只放测量日志**（[测量-说明] / [测量-结果]，拒绝分支也带 [测量-结果]）：
// LogManager 里其余条目（相机扫描、机器人连接、看门狗、设置更新……）在文件日志里
// 一行不少，而其中相当一部分同时还走 setTip()——整表转发会**重复显示**（用户看到
// 同一句话两遍）并**刷屏**（"正在搜索相机..."之类把真正的提示顶上去）。
// 所以这里给出唯一的一条策略，而不是在 lambda 里写"看起来像日志就转发"。
inline bool shouldShowInPanel(const std::string& text)
{
    return taggedWith(text, kExplainLogTag) || taggedWith(text, kResultLogTag);
}

} // namespace MeasureTools
