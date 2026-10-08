#pragma once

#include <QObject>

class TestDataQualityCheck : public QObject {
    Q_OBJECT
private slots:
    void parsePoseText();
    void countEmpty();
    void countTooFew();
    void countAdvisory();
    void countEnough();
    void nearDuplicate();
    void noNearDuplicate();
    void outlierPosition();
    void frameErrorHigh();
    void spreadInsufficient();
    void overallOk();

    // ── 按标定方式选数据源（"眼在手外 + 戳点标定"质检假报告的根因）──
    // 这四组判据必须和 DataInputArea::updateVisibility() 的卡片可见性一致：
    // 眼在手外 + 戳点不采机器人拍照位姿，质检就不能拿它当数据源。
    void sourceForFollowsCalibrationMode();
    // 用户报告的场景：眼在手外 + 戳点，连续 15 组一模一样的数据。
    // 以前每一项都显示"正常"；现在必须按机器人目标点报出近重复与分散度不足。
    void eyeToHandTouchFlagsIdenticalTargetPoints();
    // 数据源整列为空必须是"不足/有问题"，不能因为"没数据可判"就报通过。
    void emptySourceIsFailNotPass();
    // 部分帧缺数据源：报出具体组号。
    void sourceReportsMissingFrames();
    // 3 值的数据源没有姿态：不许冒出"姿态分散不足"这种无意义的结论。
    void positionOnlySourceSkipsAngleChecks();
    // 相机目标点单独查：只有那一帧的目标点跑偏 = 那一帧多半录错了。
    void cameraTargetOutlierDetected();
    // 同心圆识别点数各帧应一致，掉点要报出来。
    void markerCountMismatchIsWarned();
    // 同心圆/戳点没有单帧识别误差 —— 必须报"不适用"，不能报"正常"。
    void frameErrorNotApplicableWithoutErrorValues();
    // 按方式组装记录时，选中的那一列才进 xyz。
    void makeRecordSelectsTheModeColumn();
};
