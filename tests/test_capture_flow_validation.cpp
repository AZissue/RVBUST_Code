#include "test_capture_flow_validation.h"

#include "logic/CaptureFlow.h"

#include <QtTest>

void TestCaptureFlowValidation::acceptsCleanValues()
{
    QVERIFY(!CaptureFlow::containsBadValue(QString()));
    QVERIFY(!CaptureFlow::containsBadValue(QStringLiteral("1.5 2.0 3.0")));
    QVERIFY(!CaptureFlow::containsBadValue(QStringLiteral("-10.5 20 30.25 0.5")));
    QVERIFY(!CaptureFlow::containsBadValue(QStringLiteral("1e+10 2e-5")));
}

void TestCaptureFlowValidation::rejectsNanInfVariants()
{
    QVERIFY(CaptureFlow::containsBadValue(QStringLiteral("1 nan 3")));
    QVERIFY(CaptureFlow::containsBadValue(QStringLiteral("NaN")));
    QVERIFY(CaptureFlow::containsBadValue(QStringLiteral("nAn")));
    QVERIFY(CaptureFlow::containsBadValue(QStringLiteral("inf")));
    QVERIFY(CaptureFlow::containsBadValue(QStringLiteral("-Infinity")));
    // Documented limitation of the substring check:
    QVERIFY(CaptureFlow::containsBadValue(QStringLiteral("infinite")));
    QVERIFY(CaptureFlow::containsBadValue(QStringLiteral("nanometer")));
}

void TestCaptureFlowValidation::validatesRequiredFieldsByMode()
{
    CalibrationMode marker;  // defaults: Marker + EyeInHand

    auto r1 = CaptureFlow::validateSaveInputs(
        QString(), QStringLiteral("1 2 3 4 5 6"), QString(), marker);
    QVERIFY(!r1.ok);
    QCOMPARE(r1.field, QStringLiteral("camera_target_xyz"));

    auto r2 = CaptureFlow::validateSaveInputs(
        QStringLiteral("1 2 3"), QString(), QString(), marker);
    QVERIFY(!r2.ok);
    QCOMPARE(r2.field, QStringLiteral("robot_capture_pose"));

    CalibrationMode tcpInHand;
    tcpInHand.calibType = CalibType::TcpTouch;
    tcpInHand.eyeHand = EyeHandMode::EyeInHand;

    auto r3 = CaptureFlow::validateSaveInputs(
        QStringLiteral("1 2 3"), QString(), QString(), tcpInHand);
    QVERIFY(!r3.ok);
    QCOMPARE(r3.field, QStringLiteral("robot_target_xyz"));

    auto r4 = CaptureFlow::validateSaveInputs(
        QStringLiteral("1 2 3"), QString(), QStringLiteral("4 5 6"), tcpInHand);
    QVERIFY(!r4.ok);
    QCOMPARE(r4.field, QStringLiteral("robot_capture_pose"));

    CalibrationMode tcpOutHand;
    tcpOutHand.calibType = CalibType::TcpTouch;
    tcpOutHand.eyeHand = EyeHandMode::EyeToHand;

    auto r5 = CaptureFlow::validateSaveInputs(
        QStringLiteral("1 2 3"), QString(), QStringLiteral("4 5 6"), tcpOutHand);
    QVERIFY(r5.ok);  // pose card is hidden for eye-to-hand TCP
}

void TestCaptureFlowValidation::rejectsNonNumericValues()
{
    CalibrationMode marker;

    auto r1 = CaptureFlow::validateSaveInputs(
        QStringLiteral("1 2 abc"), QStringLiteral("1 2 3 4 5 6"), QString(), marker);
    QVERIFY(!r1.ok);
    QCOMPARE(r1.field, QStringLiteral("camera_target_xyz"));

    // Pose must have exactly 6 numeric tokens
    auto r2 = CaptureFlow::validateSaveInputs(
        QStringLiteral("1 2 3"), QStringLiteral("1 2 3 4 5"), QString(), marker);
    QVERIFY(!r2.ok);
    QCOMPARE(r2.field, QStringLiteral("robot_capture_pose"));
}

void TestCaptureFlowValidation::rejectsNanInfViaSaveValidation()
{
    CalibrationMode marker;
    auto r = CaptureFlow::validateSaveInputs(
        QStringLiteral("1 nan 3"), QStringLiteral("1 2 3 4 5 6"), QString(), marker);
    QVERIFY(!r.ok);
    QVERIFY(r.field.isEmpty());  // NaN rejection has no specific card
    QVERIFY(r.message.contains(QStringLiteral("NaN")));
}

void TestCaptureFlowValidation::acceptsValidInputs()
{
    CalibrationMode marker;
    auto r = CaptureFlow::validateSaveInputs(
        QStringLiteral("10.5 -2.25 3"), QStringLiteral("1 2 3 4 5 6"), QString(), marker);
    QVERIFY(r.ok);
    QVERIFY(r.message.isEmpty());
    QVERIFY(r.field.isEmpty());
}

void TestCaptureFlowValidation::caliboardQualityGates()
{
    QVERIFY(CaptureFlow::caliboardQualityMessage(44, 44, 0.5f).isEmpty());
    QVERIFY(CaptureFlow::caliboardQualityMessage(44, 44, 4.9f).isEmpty());

    const auto tooFew = CaptureFlow::caliboardQualityMessage(20, 44, 0.0f);
    QVERIFY(!tooFew.isEmpty());
    QVERIFY(tooFew.contains(QStringLiteral("20/44")));

    const auto poor = CaptureFlow::caliboardQualityMessage(44, 44, 5.1f);
    QVERIFY(!poor.isEmpty());
    QVERIFY(poor.contains(QStringLiteral("5.10")));
}

void TestCaptureFlowValidation::caliboardQualityThresholdConfigurable()
{
    // With a higher operator-set threshold, the same error no longer warns.
    QVERIFY(CaptureFlow::caliboardQualityMessage(44, 44, 5.1f, 10.0f).isEmpty());
    QVERIFY(CaptureFlow::caliboardQualityMessage(44, 44, 10.0f, 10.0f).isEmpty());

    const auto poor = CaptureFlow::caliboardQualityMessage(44, 44, 10.1f, 10.0f);
    QVERIFY(!poor.isEmpty());
    QVERIFY(poor.contains(QStringLiteral("10.10")));

    // Point-count advisory is independent of the threshold.
    const auto tooFew = CaptureFlow::caliboardQualityMessage(20, 44, 0.0f, 50.0f);
    QVERIFY(!tooFew.isEmpty());
    QVERIFY(tooFew.contains(QStringLiteral("20/44")));
}

void TestCaptureFlowValidation::detectsCjkFormatChars()
{
    // Full-width comma ，(U+FF0C), ideographic comma 、, CJK brackets, and
    // full-width digits must all be flagged.
    QVERIFY(CaptureFlow::containsCjkFormatChars(QStringLiteral("1，2，3")));
    QVERIFY(CaptureFlow::containsCjkFormatChars(QStringLiteral("1、2")));
    QVERIFY(CaptureFlow::containsCjkFormatChars(QStringLiteral("（1，2）")));
    QVERIFY(CaptureFlow::containsCjkFormatChars(QStringLiteral("1 2 ３")));

    // ASCII separators and numbers are fine.
    QVERIFY(!CaptureFlow::containsCjkFormatChars(QString()));
    QVERIFY(!CaptureFlow::containsCjkFormatChars(QStringLiteral("(1,2)")));
    QVERIFY(!CaptureFlow::containsCjkFormatChars(QStringLiteral("1, 2, 3")));
    QVERIFY(!CaptureFlow::containsCjkFormatChars(QStringLiteral("1 2 3")));
    QVERIFY(!CaptureFlow::containsCjkFormatChars(QStringLiteral("-1.5 2e-3 4.0")));
}

void TestCaptureFlowValidation::acceptsEnglishCommaSeparatedValues()
{
    CalibrationMode marker;
    // Spaces, English commas, or a mix are all accepted separators.
    auto r1 = CaptureFlow::validateSaveInputs(
        QStringLiteral("1, 2, 3"), QStringLiteral("1 2 3 4 5 6"), QString(), marker);
    QVERIFY(r1.ok);
    QVERIFY(r1.message.isEmpty());

    auto r2 = CaptureFlow::validateSaveInputs(
        QStringLiteral("1,2,3"), QStringLiteral("1,2,3,4,5,6"), QString(), marker);
    QVERIFY(r2.ok);
}

void TestCaptureFlowValidation::rejectsChineseFormatOnSave()
{
    CalibrationMode marker;
    auto r = CaptureFlow::validateSaveInputs(
        QStringLiteral("1，2，3"), QStringLiteral("1 2 3 4 5 6"), QString(), marker);
    QVERIFY(!r.ok);
    QVERIFY(r.message.contains(QStringLiteral("中文")));
}
