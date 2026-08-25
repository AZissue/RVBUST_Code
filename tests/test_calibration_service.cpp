#include "test_calibration_service.h"

#include <QtTest>

#include "logic/CalibrationService.h"

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
