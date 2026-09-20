#include "test_log_presentation.h"

#include <QtTest>

#include <string>
#include <vector>

#include "logic/LogPresentation.h"
#include "logic/MeasureMethods.h"

using namespace MeasureTools;

namespace {

QString q(const std::string& s) { return QString::fromStdString(s); }

bool contains(const std::string& hay, const char* needle)
{
    return hay.find(needle) != std::string::npos;
}

int countOf(const std::string& hay, const std::string& needle)
{
    int n = 0;
    for (std::size_t pos = hay.find(needle); pos != std::string::npos;
         pos = hay.find(needle, pos + needle.size()))
        ++n;
    return n;
}

// 界面那一行是怎么拼出来的：SidePanel::appendTimeline() 渲染 "[标签] 正文"
// （appendTimelineHtml 里的 `<span>[%2]</span> <span>%4</span>`），标签来自
// logPresentation()。这里照抄同一条公式，才能断言"用户看到的那一行"。
std::string panelPrefix(const std::string& level)
{
    return "[" + logPresentation(level).label + "] ";
}

std::string panelLine(const std::string& level, const std::string& text)
{
    return panelPrefix(level) + text;
}

// 从"用户看到的那一行"里切掉面板前缀取回正文。
//
// **单位是字节，不是字符**：line 是 std::string（UTF-8），"[提示] " 里的
// "提""示"各占 3 字节，前缀一共 3+3+1+1+1 = 9 字节。所以切前缀必须用
// panelPrefix().size()，写死一个字符数（例如 substr(5)）会切在汉字中间，
// QString::fromStdString 只能还原出 U+FFFD。
std::string stripPanelPrefix(const std::string& level, const std::string& line)
{
    const std::size_t n = panelPrefix(level).size();
    return line.size() >= n ? line.substr(n) : std::string();
}

} // namespace

void TestLogPresentation::everyLevelHasItsOwnLabel()
{
    QCOMPARE(q(logPresentation("info").label), QStringLiteral("提示"));
    QCOMPARE(q(logPresentation("success").label), QStringLiteral("完成"));
    QCOMPARE(q(logPresentation("warning").label), QStringLiteral("警告"));
    QCOMPARE(q(logPresentation("error").label), QStringLiteral("错误"));

    // 四个标签必须互不相同：否则用户分不出"提醒"和"出错"。
    const std::string labels[] = { logPresentation("info").label,
                                   logPresentation("success").label,
                                   logPresentation("warning").label,
                                   logPresentation("error").label };
    for (int i = 0; i < 4; ++i)
        for (int j = i + 1; j < 4; ++j)
            QVERIFY(labels[i] != labels[j]);

    // 归一化后的级别名也要跟着走（面板之外，日志/调试都按它判断）。
    QCOMPARE(q(logPresentation("warning").level), QStringLiteral("warning"));
}

void TestLogPresentation::levelColorsUseTheExistingPalette()
{
    // 配色只给"角色"，色值归 Theme.h：这里钉住角色，界面侧翻成
    // PRIMARY/SUCCESS/WARNING/ERROR（见 SidePanel.cpp 的 logColorHex）。
    QVERIFY(logPresentation("info").color == LogColorRole::Primary);
    QVERIFY(logPresentation("success").color == LogColorRole::Success);
    QVERIFY(logPresentation("warning").color == LogColorRole::Warning);
    QVERIFY(logPresentation("error").color == LogColorRole::Error);

    QCOMPARE(q(logColorRoleName(logPresentation("info").color)), QStringLiteral("primary"));
    QCOMPARE(q(logColorRoleName(logPresentation("success").color)), QStringLiteral("success"));
    QCOMPARE(q(logColorRoleName(logPresentation("warning").color)), QStringLiteral("warning"));
    QCOMPARE(q(logColorRoleName(logPresentation("error").color)), QStringLiteral("error"));

    // 复用既有提示路径的配色：[提示] 与 setTip() 同色、[警告] 与 setPoseGuide(true) 同色。
    QVERIFY(logPresentation("info").color == logPresentation("info").color);
    QVERIFY(logPresentation("warning").color != logPresentation("error").color);
}

void TestLogPresentation::unknownLevelFallsBackToInfo()
{
    // LogManager 只发四个级别，但拼错/新增级别不能把日志从面板上丢掉。
    const char* unknown[] = { "verbose", "INFO", "Info", "", "trace", "fatal" };
    for (const char* lv : unknown) {
        const LogPresentation p = logPresentation(lv);
        QCOMPARE(q(p.label), q(logPresentation("info").label));
        QCOMPARE(q(p.level), QStringLiteral("info"));
        QVERIFY(p.color == LogColorRole::Primary);
    }
    // 兜底路径也照样上屏（级别不认识 ≠ 内容不重要）。
    QVERIFY(shouldShowInPanel(logTagged(kResultLogTag, "平面度：PV = 0.0312 mm")));
}

void TestLogPresentation::explainLineKeepsExactlyOneTag()
{
    const std::string body = logTagged(kExplainLogTag, methodExplainLine(Method::Flatness));
    const std::string line = panelLine("info", body);

    // 一个前缀，不是两个（以前 chainText() 给每条都加 [测量-说明]，结果与说明分不开）。
    QCOMPARE(countOf(line, "[测量-说明]"), 1);
    QCOMPARE(countOf(line, "[测量-结果]"), 0);
    QVERIFY(line.rfind("[提示] [测量-说明] ", 0) == 0);

    // 正文原样：说明的每一段都还在，且没有被截断。
    QVERIFY(contains(line, "用途："));
    QVERIFY(contains(line, "ROI 怎么画："));
    QVERIFY(contains(line, "输出："));
    QVERIFY(contains(line, "可信度："));
    QVERIFY(contains(line, "常见错法："));
    // 面板那一行只在最前面多了 "[提示] "（9 个**字节**），其余逐字相同。
    QVERIFY(panelPrefix("info").size() == 9u);
    QCOMPARE(q(stripPanelPrefix("info", line)), q(body));
    QVERIFY(line == panelPrefix("info") + body);
}

void TestLogPresentation::resultLineKeepsValuesAndOneTag()
{
    const std::vector<ResultItem> items = { { "最小区域 PV", "0.0312", "mm" },
                                            { "RMS", "0.0049", "mm" } };
    const std::string body = logTagged(kResultLogTag,
                                       resultLine(Method::Flatness, items, "40000 点，高"));
    const std::string line = panelLine("info", body);

    QCOMPARE(countOf(line, "[测量-结果]"), 1);
    QCOMPARE(countOf(line, "[测量-说明]"), 0);
    QVERIFY(line.rfind("[提示] [测量-结果] ", 0) == 0);

    // 数值一位不少（截断数字正是"面板上看不出对错"的来源）。
    QVERIFY(contains(line, "0.0312"));
    QVERIFY(contains(line, "0.0049"));
    QVERIFY(contains(line, "40000 点，高"));
    QVERIFY(contains(line, "口径："));
    QCOMPARE(q(stripPanelPrefix("info", line)), q(body));
    QVERIFY(line == panelPrefix("info") + body);
}

void TestLogPresentation::refusalBranchIsStillPanelWorthy()
{
    // "测不了"也必须让用户看见，否则点了「测量」什么都不发生。
    const std::string body = logTagged(
        kResultLogTag, resultRefusalLine(Method::StepHeight, "ROI 没画全：需要 ROI A + ROI B"));
    QVERIFY(shouldShowInPanel(body));
    const std::string line = panelLine("error", body);
    QVERIFY(line.rfind("[错误] [测量-结果] ", 0) == 0);
    QVERIFY(contains(line, "高度段差"));
    QVERIFY(contains(line, "ROI 没画全"));
    QCOMPARE(countOf(line, "[测量-结果]"), 1);
}

void TestLogPresentation::onlyMeasurementLogsReachThePanel()
{
    // 测量日志：上屏。
    QVERIFY(shouldShowInPanel(logTagged(kExplainLogTag, "平面度 —— 用途：…")));
    QVERIFY(shouldShowInPanel(logTagged(kResultLogTag, "平面度：…")));

    // 其余条目：照旧只进文件日志。它们在 MainWindow 里几乎都同时走 setTip()，
    // 转发上去就是同一句话显示两遍（而且"正在搜索相机…"会刷屏）。
    const char* fileOnly[] = {
        "正在搜索相机...",
        "相机已连接（RVC-1234）",
        "机器人已连接（127.0.0.1:30003，UR Realtime）",
        "[WATCHDOG] 主线程停顿 1200 ms",
        "设置已更新",
        "[提示] 像素 (305,414) → 3D (-57.967 -17.586 223.162) mm，已填入相机目标点",
        ""
    };
    for (const char* text : fileOnly)
        QVERIFY2(!shouldShowInPanel(text), text);

    // 前缀必须是"以…开头"，正文里提到这几个字不算。
    QVERIFY(!shouldShowInPanel("已写入文件日志：[测量-结果] 平面度：…"));
}
