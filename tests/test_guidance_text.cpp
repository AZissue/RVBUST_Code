#include "test_guidance_text.h"

#include <QtTest>

#include "logic/GuidanceText.h"

using GuidanceText::Message;

void TestGuidanceText::pendingReferenceWording()
{
    QCOMPARE(GuidanceText::pendingReference(QStringLiteral("机器人拍照位姿")),
             QStringLiteral("暂无机器人拍照位姿参考，可自由采集"));
    QCOMPARE(GuidanceText::noCollectedReference(QStringLiteral("机器人目标点")),
             QStringLiteral("暂无已采机器人目标点参考，可自由采集"));
}

void TestGuidanceText::invalidPoseTextMatchesTheFieldShape()
{
    // 6 值源要求位姿，3 值源只要求位置 —— 提示必须跟着源变。
    QCOMPARE(GuidanceText::invalidPoseText(true),
             QStringLiteral("机器人拍照位姿需为 6 个数值（x y z rx ry rz）"));
    QCOMPARE(GuidanceText::invalidPoseText(false),
             QStringLiteral("机器人目标点需为 3 个数值（x y z）"));
}

void TestGuidanceText::tooCloseWithOrientationShowsDistanceAndAngle()
{
    PoseGuide::Guide g;
    g.hasReference = true;
    g.distanceMm = 12.34;
    g.angleDeg = 5.67;
    g.refIndex = 2;  // 0-based -> 第 3 组
    g.tooClose = true;

    const Message m = GuidanceText::poseGuideMessage(
        g, true, QStringLiteral("机器人拍照位姿"));
    QCOMPARE(m.text,
             QStringLiteral("与第 3 组机器人拍照位姿过于接近（间距 12.3 mm / 角差 5.7°），"
                            "建议拉开位置或旋转角度"));
    QVERIFY(m.warn);
}

void TestGuidanceText::tooCloseWithoutOrientationOmitsAngle()
{
    PoseGuide::Guide g;
    g.hasReference = true;
    g.distanceMm = 7.0;
    g.angleDeg = 0.0;
    g.refIndex = 1;
    g.tooClose = true;

    const Message m = GuidanceText::poseGuideMessage(
        g, false, QStringLiteral("机器人目标点"));
    QCOMPARE(m.text,
             QStringLiteral("与第 2 组机器人目标点过于接近（间距 7.0 mm），建议拉开位置"));
    QVERIFY(m.warn);
    // 无姿态的源不该出现角差，哪怕是 0.0°。
    QVERIFY(!m.text.contains(QStringLiteral("角差")));
}

void TestGuidanceText::spreadWithOrientation()
{
    PoseGuide::Guide g;
    g.hasReference = true;
    g.distanceMm = 88.9;
    g.angleDeg = 21.24;
    g.refIndex = 0;

    const Message m = GuidanceText::poseGuideMessage(
        g, true, QStringLiteral("机器人拍照位姿"));
    QCOMPARE(m.text,
             QStringLiteral("最近第 1 组：间距 88.9 mm / 角差 21.2°，分散度良好"));
    QVERIFY(!m.warn);
}

void TestGuidanceText::spreadWithoutOrientationOmitsAngle()
{
    PoseGuide::Guide g;
    g.hasReference = true;
    g.distanceMm = 60.0;
    g.angleDeg = 0.0;
    g.refIndex = 4;

    const Message m = GuidanceText::poseGuideMessage(
        g, false, QStringLiteral("机器人目标点"));
    QCOMPARE(m.text, QStringLiteral("最近第 5 组：间距 60.0 mm，分散度良好"));
    QVERIFY(!m.warn);
}

void TestGuidanceText::reportHtmlEscapesAndKeepsCheckOrder()
{
    DataQualityCheck::Report rep;
    rep.overall = QStringLiteral("不足 <6 组>");
    rep.count.level = DataQualityCheck::Level::Fail;
    rep.count.summary = QStringLiteral("只有 3 组");

    const QString html = GuidanceText::qualityReportHtml(rep);

    // 总体与摘要都来自数据，必须转义后再进富文本。
    QVERIFY(html.contains(QStringLiteral("总体：不足 &lt;6 组&gt;")));
    QVERIFY(html.contains(QStringLiteral("只有 3 组")));
    QVERIFY(html.contains(QStringLiteral("color:#F5222D")));

    // 八项检查按固定顺序出现（逐项定位，确保不是碰巧同时存在）。
    const QStringList names = {
        QStringLiteral("数量"), QStringLiteral("数据源"), QStringLiteral("近重复"),
        QStringLiteral("离群"), QStringLiteral("相机目标点"),
        QStringLiteral("单帧误差"), QStringLiteral("标记点数"), QStringLiteral("分散度")};
    int last = -1;
    for (const QString& name : names) {
        const int at = html.indexOf(QStringLiteral("<b>%1</b>").arg(name));
        QVERIFY2(at > last, qPrintable(QStringLiteral("缺项或顺序错: %1").arg(name)));
        last = at;
    }
}

void TestGuidanceText::reportHtmlRendersDetailsAndEveryLevelTag()
{
    DataQualityCheck::Report rep;
    rep.count.level = DataQualityCheck::Level::Pass;
    rep.source.level = DataQualityCheck::Level::NotApplicable;
    rep.nearDup.level = DataQualityCheck::Level::Warn;
    rep.outlier.level = DataQualityCheck::Level::Fail;
    rep.nearDup.details = {QStringLiteral("第 1 组与第 2 组间距 < 50 mm"),
                            QStringLiteral("第 3 组与第 4 组间距 < 50 mm")};

    const QString html = GuidanceText::qualityReportHtml(rep);

    QVERIFY(html.contains(QStringLiteral("通过")));
    QVERIFY(html.contains(QStringLiteral("不适用")));
    QVERIFY(html.contains(QStringLiteral("提示")));
    QVERIFY(html.contains(QStringLiteral("不足")));
    QVERIFY(html.contains(QStringLiteral("#52C41A")));
    QVERIFY(html.contains(QStringLiteral("#8C8C8C")));
    QVERIFY(html.contains(QStringLiteral("#FAAD14")));
    QVERIFY(html.contains(QStringLiteral("#F5222D")));

    // 细节逐条缩进、同样转义。
    QVERIFY(html.contains(QStringLiteral("· 第 1 组与第 2 组间距 &lt; 50 mm")));
    QVERIFY(html.contains(QStringLiteral("· 第 3 组与第 4 组间距 &lt; 50 mm")));
    QCOMPARE(html.count(QStringLiteral("margin:1px 0 1px 12px")), 2);
}
