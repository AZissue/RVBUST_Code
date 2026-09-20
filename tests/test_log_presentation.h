#pragma once

#include <QObject>

// 第 10 回合 P4：操作日志的"落屏"规则（src/logic/LogPresentation.h）。
// 这里断言的是**用户在「操作日志」面板里直接读到的东西**：
//   1. LogManager 的四个级别各显示成哪个标签、用哪套配色角色；
//   2. 不认识的级别不能把日志丢掉（兜底成 [提示]）；
//   3. 测量日志的正文原样上屏：只带**一个** [测量-说明]/[测量-结果] 前缀、
//      关键数值不被截断（界面那一行 = "[标签] " + 正文，标签由本表决定）；
//   4. 只有测量日志上屏——相机/机器人那类会走 setTip() 的条目转发上去就重复了。
class TestLogPresentation : public QObject
{
    Q_OBJECT

private slots:
    void everyLevelHasItsOwnLabel();
    void levelColorsUseTheExistingPalette();
    void unknownLevelFallsBackToInfo();
    void explainLineKeepsExactlyOneTag();
    void resultLineKeepsValuesAndOneTag();
    void refusalBranchIsStillPanelWorthy();
    void onlyMeasurementLogsReachThePanel();
};
