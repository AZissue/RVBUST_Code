#pragma once

#include <QObject>

// 架构收敛第 3 批：采集引导的文案分支与质检报告 HTML。
// 这些字符串原来长在 MainWindow 里，判定逻辑（DataQualityCheck / PoseGuide）
// 已有单测；这里钉住"判定结果 → 操作员看到的字"这一段。
class TestGuidanceText : public QObject {
    Q_OBJECT
private slots:
    void pendingReferenceWording();
    void invalidPoseTextMatchesTheFieldShape();
    void tooCloseWithOrientationShowsDistanceAndAngle();
    void tooCloseWithoutOrientationOmitsAngle();
    void spreadWithOrientation();
    void spreadWithoutOrientationOmitsAngle();
    void reportHtmlEscapesAndKeepsCheckOrder();
    void reportHtmlRendersDetailsAndEveryLevelTag();
};
