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
