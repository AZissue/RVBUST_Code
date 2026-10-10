#include "test_app_info.h"

#include "AppInfo.h"

#include <QRegularExpression>
#include <QtTest>

void TestAppInfo::titleCarriesNameAndVersion()
{
    const QString t = AppInfo::title();
    QVERIFY2(t.contains(AppInfo::name()), qPrintable(t));
    QVERIFY2(t.contains(AppInfo::version()), qPrintable(t));
    // 形如 "… V2.0"：版本前面有个 V，否则用户看到的只是一串数字。
    QVERIFY2(t.contains(QStringLiteral("V") + AppInfo::version()), qPrintable(t));
}

void TestAppInfo::summaryStartsWithTitle()
{
    const QString s = AppInfo::summary();
    QVERIFY2(s.startsWith(AppInfo::title()), qPrintable(s));
    // 帮助弹框拿它当第一行，后面还要接"支持…"那几句，所以不能以换行结尾。
    QVERIFY(!s.endsWith(QLatin1Char('\n')));
}

void TestAppInfo::versionIsNotEmptyAndUniqueLooking()
{
    const QString v = AppInfo::version();
    QVERIFY(!v.trimmed().isEmpty());
    // 版本号里必须有数字，防止有人把 "dev" 之类的写进来当正式版本。
    QVERIFY2(v.contains(QRegularExpression(QStringLiteral("[0-9]"))), qPrintable(v));
}

// runtime 日志的第一行是现场回传日志里唯一的版本标记，认错版本就等于认错包。
// 曾经这里硬编码 "v1.0.0"：2.0 的包在日志里仍自称 1.0.0（2026-10-10 收到的
// test2.1 现场日志就是这样，排障时得先排除"这是 1.0 的老包"这个误判）。
void TestAppInfo::runtimeLogHeaderCarriesTheCurrentVersion()
{
    const QString h = AppInfo::runtimeLogHeader();
    QVERIFY2(h.contains(QStringLiteral("HandEyeCalibrationTool")), qPrintable(h));
    QVERIFY2(h.contains(QStringLiteral("v") + AppInfo::version()), qPrintable(h));

    // 这一行里出现的**每一个**版本样式的串都必须是当前版本：不允许留任何旧版本号。
    const QRegularExpression versionish(
        QStringLiteral("([0-9]+\\.[0-9]+(\\.[0-9]+)?)"));
    auto it = versionish.globalMatch(h);
    int found = 0;
    while (it.hasNext()) {
        ++found;
        const QString token = it.next().captured(1);
        QVERIFY2(token == AppInfo::version(), qPrintable(h));
    }
    QVERIFY2(found > 0, qPrintable(h));   // 版本号本身必须真的写在这一行里
}
