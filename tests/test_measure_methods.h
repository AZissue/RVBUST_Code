#pragma once

#include <QObject>

// 第 7 回合 P3/P4：测量方法目录（src/logic/MeasureMethods.h）。
// 这里断言的是**用户会直接踩到**的两件事：
//   1. 每个方法声明的 ROI 需求必须与算法真正需要的数量一致，并且提示语要明确
//      说出"需要几个、哪个是哪个"；第 3 次拖框不能再悄悄清空重来；
//   2. 说明与结果日志的文案必须齐（用途/ROI/输出/可信度/常见错法/口径），
//      否则"测量方法怎么用不清楚"这条反馈等于没修。
class TestMeasureMethods : public QObject
{
    Q_OBJECT

private slots:
    void catalogueCoversEveryMethodOnce();
    void roiCountMatchesTheKernel();
    void roiRolesMatchTheDeclaredRequirement();
    void roiRequirementTextIsExplicit();
    void thirdDragTellsTheUserInsteadOfSilentRestart();
    void singleRoiMethodReplacesInsteadOfRestarting();
    void dragIsIgnoredByMethodsWithoutRoi();
    void roiStateTextDescribesProgress();
    void noteAfterDragMatchesTheState();
    void explainLineCarriesEverySection();
    void resultLineCarriesValuesAndConvention();
    void refusalLineNamesTheMethod();
    void logTagsSeparateExplainFromResult();
};
