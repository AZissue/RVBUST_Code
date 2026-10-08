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
