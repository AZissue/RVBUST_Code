#include "test_calibration_service.h"

#include <QtTest>

#include "logic/CalibrationService.h"
#include "sdk/HandEyeSDKBridge.h"

void TestCalibrationService::normalizePoseLineAcceptsSpacesAndCommas()
{
    QCOMPARE(CalibrationService::normalizePoseLine(
                 QStringLiteral("1 2 3 4 5 6")),
             QStringLiteral("1,2,3,4,5,6"));
    QCOMPARE(CalibrationService::normalizePoseLine(
                 QStringLiteral("1, 2, 3, 4, 5, 6")),
             QStringLiteral("1,2,3,4,5,6"));
    QCOMPARE(CalibrationService::normalizePoseLine(
                 QStringLiteral("690.20,-63.13,424.72,137.91,11.32,173.11")),
             QStringLiteral("690.2,-63.13,424.72,137.91,11.32,173.11"));
}

void TestCalibrationService::normalizePoseLineRejectsBadInput()
{
    QVERIFY(CalibrationService::normalizePoseLine(
                QStringLiteral("1,2,3,4,5")).isEmpty());
    QVERIFY(CalibrationService::normalizePoseLine(
                QStringLiteral("1,2,3,4,5,abc")).isEmpty());
    QVERIFY(CalibrationService::normalizePoseLine(
                QStringLiteral("1，2，3，4，5，6")).isEmpty());
    QVERIFY(CalibrationService::normalizePoseLine(QString()).isEmpty());
}

void TestCalibrationService::errorTextMapping()
{
    QVERIFY(CalibrationService::errorText(0).contains(QStringLiteral("成功")));
    QVERIFY(CalibrationService::errorText(-2).contains(QStringLiteral("6 组")));
    QVERIFY(CalibrationService::errorText(-7).contains(QStringLiteral("旋转轴")));
    QVERIFY(CalibrationService::errorText(-999).contains(QStringLiteral("-999")));
}

// T-008 判据：桥接层的 `safeCall` 抓到 SEH/异常时，返回的码必须与"参数无效"(-1) 分开。
//
// 现状：`HandEyeSDKBridge::handEyeCalibrationMarker` 把 `ret` 预置成 -1，`safeCall`
// 捕获异常后 `ret` 不变 —— 于是 DLL 崩了、函数根本没执行，用户看到的是
// 「参数无效（文件夹/位姿文件/参数）」，现场会去反复检查文件夹和位姿格式。
void TestCalibrationService::sdkInternalErrorIsDistinctFromBadParameters()
{
    const QString bad = CalibrationService::errorText(-1);
    QVERIFY(bad.contains(QStringLiteral("参数无效")));

    const QString crashed =
        CalibrationService::errorText(HandEyeSDKBridge::kSdkInternalError);
    QVERIFY2(crashed != bad,
             "a caught SDK exception must not be reported as bad parameters");
    QVERIFY2(!crashed.contains(QStringLiteral("参数无效")),
             qPrintable(QStringLiteral("仍然在说参数无效：") + crashed));
    QVERIFY2(crashed.contains(QStringLiteral("SDK"))
                 || crashed.contains(QStringLiteral("异常"))
                 || crashed.contains(QStringLiteral("崩溃")),
             qPrintable(QStringLiteral("文案没说是 SDK 的事：") + crashed));
}

// T-008 r2 判据：标定结果正文由 `CalibrationService::formatResult()` 一处产出，
// 两个界面页（主界面「计算」与工具页「手眼标定」）都调它 —— 现在这段格式化
// 在 MainWindow.cpp:1077 与 ToolsPanel.cpp:860 各抄了一份。
//
// 这条用例钉住"正文不能因为重构而变形"：组数、总平均误差、4×4 矩阵（行主序、6 位小数）、
// 逐组误差、以及识别失败那一组的标注。
void TestCalibrationService::formatResultCarriesMatrixAndPerFrameErrors()
{
    CalibrationService::Result r;
    r.ok = true;
    r.usedCount = 2;
    r.totalMeanError = 0.123;
    for (int i = 0; i < 16; ++i)
        r.matrix[static_cast<std::size_t>(i)] = i + 1;      // 1..16
    r.errors = { 0.031, 0.215 };
    r.success2D = { 1, 0 };                                 // 第 2 组 2D 识别失败
    r.success3D = { 1, 1 };

    const QString text = CalibrationService::formatResult(r);
    QVERIFY2(text.contains(QStringLiteral("标定成功")), qPrintable(text));
    QVERIFY2(text.contains(QStringLiteral("2 组数据")), qPrintable(text));
    QVERIFY2(text.contains(QStringLiteral("0.123")), qPrintable(text));
    QVERIFY2(text.contains(QStringLiteral("4×4 矩阵")), qPrintable(text));
    QVERIFY2(text.contains(QStringLiteral("1.000000")), qPrintable(text));   // 第 1 行第 1 列
    QVERIFY2(text.contains(QStringLiteral("16.000000")), qPrintable(text));  // 第 4 行第 4 列
    QVERIFY2(text.contains(QStringLiteral("逐组误差")), qPrintable(text));
    QVERIFY2(text.contains(QStringLiteral("第 1 组")), qPrintable(text));
    QVERIFY2(text.contains(QStringLiteral("0.031")), qPrintable(text));
    QVERIFY2(text.contains(QStringLiteral("识别失败")), qPrintable(text));

    CalibrationService::Result bad;
    bad.ok = false;
    bad.error = QStringLiteral("位姿文件数据无效");
    const QString failText = CalibrationService::formatResult(bad);
    QVERIFY2(failText.contains(QStringLiteral("标定失败")), qPrintable(failText));
    QVERIFY2(failText.contains(bad.error), qPrintable(failText));
}
