#pragma once

#include <QString>

// 程序的名字与版本，只在这里写一次。
//
// 以前 "手眼标定数据收集助手 V1.0" 硬编码在三处（窗口标题、顶栏标题、帮助弹框），
// 版本升到 2.0 时三处都要改，漏一处就会同时显示两个版本号。现在所有面向用户的
// 地方都从这里取。
//
// CMakeLists 的 project(... VERSION ...) 是构建系统的版本，与本文件无关（它目前
// 没被任何地方读取）；改动本文件时顺手把那边也一起推进，防止两边对不上。
namespace AppInfo {

inline QString name() { return QStringLiteral("手眼标定数据收集助手"); }

inline QString version() { return QStringLiteral("2.0"); }

// 窗口标题 / 顶栏标题用的 "名字 V版本"。
inline QString title()
{
    return name() + QStringLiteral(" V") + version();
}

// 帮助窗口与「关于」用的一句话定位。
inline QString summary()
{
    return title()
        + QStringLiteral(" —— 面向 RVC X1/X2 相机的手眼标定数据采集工具");
}

} // namespace AppInfo
