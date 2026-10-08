#include "test_help_content.h"

#include "AppInfo.h"
#include "logic/HelpContent.h"
#include "logic/MeasureMethods.h"

#include <QRegularExpression>
#include <QSet>
#include <QtTest>

#include <cstring>
#include <string>

namespace {

QString utf8(const char* s) { return QString::fromUtf8(s ? s : ""); }

} // namespace

void TestHelpContent::chaptersAreCompleteAndIdsAreStable()
{
    int n = 0;
    const HelpContent::Chapter* table = HelpContent::chapters(n);

    // 快速上手 / 安装方式与标定方法 / 主界面导览 / 采集流程 / 工具面板 /
    // 测量方法 / 输出文件 / 常见问题 / 版本与更新记录。
    QVERIFY2(n >= 9, qPrintable(QStringLiteral("章节只有 %1 章").arg(n)));

    // id 要能直接写进 [文字](#id) 链接里，所以限定小写 ASCII；重复 id 会让
    // showChapter() 跳到错误的一章。
    const QRegularExpression idRe(QStringLiteral("^[a-z][a-z0-9-]*$"));
    QSet<QString> seen;

    for (int i = 0; i < n; ++i) {
        const QString id = utf8(table[i].id);
        QVERIFY2(idRe.match(id).hasMatch(), qPrintable(id));
        QVERIFY2(!seen.contains(id), qPrintable(QStringLiteral("id 重复：") + id));
        seen.insert(id);

        QVERIFY2(!utf8(table[i].title).trimmed().isEmpty(), qPrintable(id));
        const QString body = utf8(table[i].body);
        // 正文不能是占位符 —— 100 字节是最小防线，真正写歪了测试会先断在上面几条。
        QVERIFY2(body.trimmed().size() >= 100,
                 qPrintable(QStringLiteral("章节 %1 的正文太短：%2 字节")
                                .arg(id).arg(body.size())));
    }
}

void TestHelpContent::chapterLookupRoundTripsAndRejectsUnknown()
{
    int n = 0;
    const HelpContent::Chapter* table = HelpContent::chapters(n);

    for (int i = 0; i < n; ++i) {
        QCOMPARE(HelpContent::chapterIndexOf(table[i].id), i);
        QVERIFY(HelpContent::chapterById(table[i].id) == &table[i]);
    }

    // 未知 id 必须能区分出来：界面据此忽略正文里的死链，而不是跳到第一章。
    QCOMPARE(HelpContent::chapterIndexOf("no-such-chapter"), -1);
    QVERIFY(HelpContent::chapterById("no-such-chapter") == nullptr);
    QCOMPARE(HelpContent::chapterIndexOf(nullptr), -1);
    QVERIFY(HelpContent::chapterById(nullptr) == nullptr);
}

void TestHelpContent::measureChapterCoversEveryMethod()
{
    const HelpContent::Chapter* c = HelpContent::chapterById("measure");
    QVERIFY(c != nullptr);
    const QString body = utf8(c->body);

    int n = 0;
    const MeasureTools::MethodSpec* specs = MeasureTools::methodSpecs(n);
    QVERIFY(n >= 8);

    // 方法名、用途、输出三项都取自 MeasureMethods.h —— 说明这一章是**生成**的，
    // 不是手抄的。新加一个测量方法而忘了写说明，会在这里断。
    for (int i = 0; i < n; ++i) {
        const QString name = utf8(specs[i].name);
        QVERIFY2(body.contains(name), qPrintable(QStringLiteral("测量方法一章缺了：") + name));
        QVERIFY2(body.contains(utf8(specs[i].purpose)), qPrintable(name));
        QVERIFY2(body.contains(utf8(specs[i].outputs)), qPrintable(name));
    }
}

void TestHelpContent::bodiesDoNotHardcodeAVersion()
{
    int n = 0;
    const HelpContent::Chapter* table = HelpContent::chapters(n);

    // 2026-10-08：界面升到 2.0 还显示 V1.0，因为版本号被写死在三处。帮助文本里
    // 一个都不许再写死 —— 当前版本只能来自 AppInfo，经占位符替换。
    for (int i = 0; i < n; ++i) {
        QVERIFY2(!utf8(table[i].body).contains(QStringLiteral("V1.0")),
                 qPrintable(utf8(table[i].id)));
        QVERIFY2(!utf8(table[i].title).contains(QStringLiteral("V1.0")),
                 qPrintable(utf8(table[i].id)));
    }

    const HelpContent::Chapter* v = HelpContent::chapterById("version");
    QVERIFY(v != nullptr);

    const std::string tok = HelpContent::kCurrentVersionToken;
    const std::string rendered = HelpContent::renderBody(v->body, "9.9.9");
    QVERIFY2(rendered.find("9.9.9") != std::string::npos,
             "版本一章没有用 AppInfo 传进来的版本号");
    QVERIFY2(rendered.find(tok) == std::string::npos,
             "版本一章的占位符没有被替换掉");

    // 其余章节不该出现占位符：留着没替换，用户会看到 %CURRENT_VERSION% 这串字。
    for (int i = 0; i < n; ++i) {
        if (std::strcmp(table[i].id, "version") == 0)
            continue;
        QVERIFY2(utf8(table[i].body).toStdString().find(tok) == std::string::npos,
                 qPrintable(utf8(table[i].id)));
    }

    // 没有占位符的正文要原样返回。
    QCOMPARE(QString::fromStdString(HelpContent::renderBody("no token here", "9.9.9")),
             QStringLiteral("no token here"));
}

void TestHelpContent::changelogHeadIsTheCurrentVersion()
{
    int n = 0;
    const HelpContent::ChangeEntry* log = HelpContent::changelog(n);
    QVERIFY(log != nullptr);
    QVERIFY2(n >= 1, "更新记录至少要有当前版本这一条");

    // 升版本时忘记录更新记录 → 这条会断（版本号的唯一出处仍是 AppInfo）。
    QCOMPARE(utf8(log[0].version), AppInfo::version());

    const QRegularExpression dateRe(QStringLiteral("^[0-9]{4}-[0-9]{2}-[0-9]{2}$"));
    for (int i = 0; i < n; ++i) {
        QVERIFY(!utf8(log[i].version).trimmed().isEmpty());
        QVERIFY2(dateRe.match(utf8(log[i].date)).hasMatch(),
                 qPrintable(QStringLiteral("%1 的日期不是 YYYY-MM-DD：%2")
                                .arg(utf8(log[i].version), utf8(log[i].date))));
        QVERIFY2(utf8(log[i].notes).trimmed().size() >= 4,
                 qPrintable(utf8(log[i].version)));
    }
}

void TestHelpContent::changelogEntriesAppearInTheVersionChapter()
{
    const HelpContent::Chapter* v = HelpContent::chapterById("version");
    QVERIFY(v != nullptr);
    const QString body = utf8(v->body);

    // 结构化的 changelog() 和章节正文是两份写法，必须逐条对得上 —— 否则
    // 界面看到的更新记录和测试盯着的更新记录会分叉。
    int n = 0;
    const HelpContent::ChangeEntry* log = HelpContent::changelog(n);
    for (int i = 0; i < n; ++i) {
        QVERIFY2(body.contains(utf8(log[i].version)), qPrintable(utf8(log[i].version)));
        QVERIFY2(body.contains(utf8(log[i].date)), qPrintable(utf8(log[i].date)));
    }
}
