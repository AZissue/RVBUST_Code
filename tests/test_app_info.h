#pragma once

#include <QObject>

// 程序名与版本号只有一个出处（src/AppInfo.h）。
//
// 背景：用户发现升到 2.0 之后界面还显示 V1.0 —— 因为 "…助手 V1.0" 当时硬编码在
// 窗口标题、顶栏标题、帮助弹框三处。这里钉住的不是那个字面量，而是"三处引用同一
// 个来源"这件事：标题必须由 name() + version() 拼出来，帮助那句必须由 title()
// 起头。以后升版本只改 AppInfo.h 的 version()，这些断言仍然成立。
class TestAppInfo : public QObject
{
    Q_OBJECT

private slots:
    void titleCarriesNameAndVersion();
    void summaryStartsWithTitle();
    void versionIsNotEmptyAndUniqueLooking();
};
