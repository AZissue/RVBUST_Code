#pragma once

#include <QObject>

// 使用说明的内容表（src/logic/HelpContent.h，header-only 纯数据）。
//
// 为什么帮助文本值得单测：它里面逐字写着界面上每一个按钮和卡片的名字。按钮改名
// 而说明没改，用户照着说明找不到东西 —— 这是"帮助"这种文档最典型的失效方式，而
// 它不会崩、不会报错，只会让人怀疑自己。所以这里钉住四件事：
//   1. 章节本身完整（数量、id 唯一且是稳定 ASCII、正文不能是占位符）；
//   2. 测量方法一章必须覆盖 MeasureMethods.h 里的每一个方法 —— 新加方法忘了写
//      说明会在这里断；
//   3. 说明里不许写死版本号（2026-10-08 的 V1.0 就是这么漏的），只能用占位符，
//      由界面拿 AppInfo::version() 替换；
//   4. 更新记录的第一条必须就是当前版本 —— 升版本而忘了写更新记录，也会在这里断。
class TestHelpContent : public QObject
{
    Q_OBJECT

private slots:
    void chaptersAreCompleteAndIdsAreStable();
    void chapterLookupRoundTripsAndRejectsUnknown();
    void measureChapterCoversEveryMethod();
    void bodiesDoNotHardcodeAVersion();
    void changelogHeadIsTheCurrentVersion();
    void changelogEntriesAppearInTheVersionChapter();
};
