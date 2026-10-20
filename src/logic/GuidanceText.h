#pragma once

#include <QString>

#include "logic/DataQualityCheck.h"
#include "logic/PoseGuide.h"

// 采集引导的全部文案与质检报告的 HTML 组装（header-only，纯函数）。
//
// 这些内容原来长在 MainWindow::updatePoseGuide() / refreshQualityReport() 里，
// 混着「取哪一列、解析失败、与已采位姿比较」的判定和一堆 QStringLiteral。
// 拆到这里以后，MainWindow 只负责读控件、调这里、把结果交给侧栏；
// 文案分支（有/无姿态、警告/正常、各级别配色）可以单测，不用起界面。
//
// 规则仍然来自 DataQualityCheck / PoseGuide —— 这里只做呈现，不改判定。
namespace GuidanceText {

// 「当前位姿卡片还是空的」：还没有可比较的参考。
inline QString pendingReference(const QString& what)
{
    return QStringLiteral("暂无%1参考，可自由采集").arg(what);
}

// 卡片有内容，但会话里还没有一组可用的已采位姿。
inline QString noCollectedReference(const QString& what)
{
    return QStringLiteral("暂无已采%1参考，可自由采集").arg(what);
}

// 卡片文本解析失败。
inline QString invalidPoseText(bool hasOrientation)
{
    return hasOrientation
        ? QStringLiteral("机器人拍照位姿需为 6 个数值（x y z rx ry rz）")
        : QStringLiteral("机器人目标点需为 3 个数值（x y z）");
}

struct Message {
    QString text;
    bool warn = false;
};

// 「当前 vs 最近已采」的引导语。
//
// 没有姿态的源只按位置判定：调用方传来的角差阈值是 0，于是 Guide 不会因为
// "姿态都是 0" 而永远报过于接近 —— 这里也就不显示角差。
inline Message poseGuideMessage(const PoseGuide::Guide& g, bool hasOrientation,
                                const QString& what)
{
    if (g.tooClose) {
        return {hasOrientation
                    ? QStringLiteral("与第 %1 组%2过于接近（间距 %3 mm / 角差 %4°），建议拉开位置或旋转角度")
                          .arg(g.refIndex + 1).arg(what)
                          .arg(g.distanceMm, 0, 'f', 1).arg(g.angleDeg, 0, 'f', 1)
                    : QStringLiteral("与第 %1 组%2过于接近（间距 %3 mm），建议拉开位置")
                          .arg(g.refIndex + 1).arg(what).arg(g.distanceMm, 0, 'f', 1),
                true};
    }
    return {hasOrientation
                ? QStringLiteral("最近第 %1 组：间距 %2 mm / 角差 %3°，分散度良好")
                      .arg(g.refIndex + 1)
                      .arg(g.distanceMm, 0, 'f', 1).arg(g.angleDeg, 0, 'f', 1)
                : QStringLiteral("最近第 %1 组：间距 %2 mm，分散度良好")
                      .arg(g.refIndex + 1).arg(g.distanceMm, 0, 'f', 1),
            false};
}

// 质检报告的 HTML（侧栏富文本）。八项检查按固定顺序，details 逐条缩进；
// 等级同时用颜色和文字标签表达，不单靠颜色区分（现场打印/色弱也能读）。
inline QString qualityReportHtml(const DataQualityCheck::Report& rep)
{
    auto levelColor = [](DataQualityCheck::Level lvl) -> QString {
        switch (lvl) {
        case DataQualityCheck::Level::Pass: return QStringLiteral("#52C41A");
        case DataQualityCheck::Level::Warn: return QStringLiteral("#FAAD14");
        case DataQualityCheck::Level::Fail: return QStringLiteral("#F5222D");
        case DataQualityCheck::Level::NotApplicable: return QStringLiteral("#8C8C8C");
        }
        return QStringLiteral("#8C8C8C");
    };
    auto levelTag = [](DataQualityCheck::Level lvl) -> QString {
        switch (lvl) {
        case DataQualityCheck::Level::Pass: return QStringLiteral("通过");
        case DataQualityCheck::Level::Warn: return QStringLiteral("提示");
        case DataQualityCheck::Level::Fail: return QStringLiteral("不足");
        case DataQualityCheck::Level::NotApplicable: return QStringLiteral("不适用");
        }
        return QStringLiteral("—");
    };

    QString html = QStringLiteral("<p style='margin:2px 0;'><b>总体：%1</b></p>")
                       .arg(rep.overall.toHtmlEscaped());

    auto appendCheck = [&](const QString& name, const DataQualityCheck::Check& c) {
        html += QStringLiteral("<p style='margin:3px 0; color:%1;'>%2 <b>%3</b>：%4</p>")
                    .arg(levelColor(c.level),
                         levelTag(c.level),
                         name,
                         c.summary.toHtmlEscaped());
        for (const auto& d : c.details)
            html += QStringLiteral("<p style='margin:1px 0 1px 12px; font-size:11px; color:#8C8C8C;'>· %1</p>")
                        .arg(d.toHtmlEscaped());
    };

    appendCheck(QStringLiteral("数量"), rep.count);
    appendCheck(QStringLiteral("数据源"), rep.source);
    appendCheck(QStringLiteral("近重复"), rep.nearDup);
    appendCheck(QStringLiteral("离群"), rep.outlier);
    appendCheck(QStringLiteral("相机目标点"), rep.cameraTarget);
    appendCheck(QStringLiteral("单帧误差"), rep.frameError);
    appendCheck(QStringLiteral("标记点数"), rep.detection);
    appendCheck(QStringLiteral("分散度"), rep.spread);

    return html;
}

} // namespace GuidanceText
