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

// ── 戳点标定 ──────────────────────────────────────────────────────────

void TestCalibrationService::tcpErrorTextMapping()
{
    QVERIFY(CalibrationService::tcpErrorText(0).contains(QStringLiteral("成功")));
    QVERIFY(CalibrationService::tcpErrorText(-2).contains(QStringLiteral("相机")));
    QVERIFY(CalibrationService::tcpErrorText(-3).contains(QStringLiteral("机器人目标点")));
    QVERIFY(CalibrationService::tcpErrorText(-4).contains(QStringLiteral("不一致")));
    QVERIFY(CalibrationService::tcpErrorText(-999).contains(QStringLiteral("-999")));

    // 同一个返回码，两张表的说法必须不一样（共用一张表就会误报）。
    QVERIFY(CalibrationService::tcpErrorText(-2) != CalibrationService::errorText(-2));

    const QString crashed =
        CalibrationService::tcpErrorText(HandEyeSDKBridge::kSdkInternalError);
    QVERIFY2(!crashed.contains(QStringLiteral("参数无效")), qPrintable(crashed));
    QVERIFY(crashed.contains(QStringLiteral("SDK")) || crashed.contains(QStringLiteral("异常")));
}

void TestCalibrationService::normalizeXyzLineAcceptsSpacesAndCommas()
{
    QCOMPARE(CalibrationService::normalizeXyzLine(QStringLiteral("1 2 3")),
             QStringLiteral("1,2,3"));
    QCOMPARE(CalibrationService::normalizeXyzLine(QStringLiteral("1, 2, 3")),
             QStringLiteral("1,2,3"));
    // 6 个数值不是 3 值坐标；中文逗号也不是分隔符。
    QVERIFY(CalibrationService::normalizeXyzLine(
                QStringLiteral("1 2 3 4 5 6")).isEmpty());
    QVERIFY(CalibrationService::normalizeXyzLine(
                QStringLiteral("1，2，3")).isEmpty());
    QVERIFY(CalibrationService::normalizeXyzLine(QString()).isEmpty());
}

void TestCalibrationService::tcpTouchValidatesColumnsBeforeSdk()
{
    CalibrationService::Params p;
    p.calibType = CalibType::TcpTouch;
    p.eyeInHand = true;

    const std::vector<QString> cam { QStringLiteral("1 2 3"), QStringLiteral("4 5 6") };
    const std::vector<QString> pose { QStringLiteral("1 2 3 4 5 6"), QStringLiteral("1 2 3 4 5 6") };
    const std::vector<QString> tcp { QStringLiteral("7 8 9"), QStringLiteral("10 11 12") };

    // 任何一条校验失败都在进 SDK 之前返回（所以这些用例不需要真机/DLL）。
    auto err = [&](const std::vector<QString>& c, const std::vector<QString>& ps,
                   const std::vector<QString>& t) -> QString {
        const auto r = CalibrationService::calibrateTcpTouch(c, ps, t, p);
        // 没拦住就会真的去调 DLL —— 用一句显眼的文案代替断言（lambda 里
        // QVERIFY 的 return 在返回 QString 的 lambda 里不合法）。
        if (r.ok)
            return QStringLiteral("<校验没拦住，已经进 SDK 了>");
        return r.error;
    };

    QVERIFY(err({}, pose, tcp).contains(QStringLiteral("相机目标点")));
    QVERIFY(err(cam, pose, {}).contains(QStringLiteral("机器人目标点")));
    QVERIFY(err(cam, pose, { QStringLiteral("7 8 9") })
                .contains(QStringLiteral("不一致")));
    QVERIFY(err(cam, { QStringLiteral("1 2 3 4 5 6") }, tcp)
                .contains(QStringLiteral("拍照位姿数")));
    QVERIFY(err({ QStringLiteral("1 2 3"), QStringLiteral("bad") }, pose, tcp)
                .contains(QStringLiteral("第 2 组相机目标点")));
    QVERIFY(err(cam, pose, { QStringLiteral("7 8 9"), QStringLiteral("bad") })
                .contains(QStringLiteral("第 2 组机器人目标点")));
    QVERIFY(err(cam, { QStringLiteral("1 2 3 4 5 6"), QStringLiteral("bad") }, tcp)
                .contains(QStringLiteral("第 2 组机器人拍照位姿")));
}

void TestCalibrationService::tcpTouchRequiresPoseOnlyForEyeInHand()
{
    const std::vector<QString> cam { QStringLiteral("1 2 3") };
    const std::vector<QString> tcp { QStringLiteral("7 8 9") };

    // 眼在手上：没有拍照位姿就是缺列，要说出来。
    CalibrationService::Params hand;
    hand.calibType = CalibType::TcpTouch;
    hand.eyeInHand = true;
    const auto r1 = CalibrationService::calibrateTcpTouch(cam, {}, tcp, hand);
    QVERIFY(!r1.ok);
    QVERIFY2(r1.error.contains(QStringLiteral("机器人拍照位姿")), qPrintable(r1.error));

    // 眼在手外：拍照位姿这一列本来就不该有，校验不能拿它拦人。
    // 用一条坏掉的相机点位把流程停在逐行校验上（不碰 DLL），
    // 此时报的错只能是相机点位，不该提到拍照位姿。
    CalibrationService::Params fixed;
    fixed.calibType = CalibType::TcpTouch;
    fixed.eyeInHand = false;
    const std::vector<QString> camBad { QStringLiteral("bad"), QStringLiteral("4 5 6") };
    const std::vector<QString> tcp2 { QStringLiteral("7 8 9"), QStringLiteral("10 11 12") };
    const auto r2 = CalibrationService::calibrateTcpTouch(camBad, {}, tcp2, fixed);
    QVERIFY(!r2.ok);
    QVERIFY2(!r2.error.contains(QStringLiteral("机器人拍照位姿")), qPrintable(r2.error));
    QVERIFY2(r2.error.contains(QStringLiteral("第 1 组相机目标点")), qPrintable(r2.error));
}

void TestCalibrationService::calibrateDispatchesOnCalibType()
{
    // 戳点标定 + 空数据：入口必须走戳点那条路（报"相机目标点"），
    // 而不是标定板那条（报"没有可用的标定数据"/"数据文件夹不存在"）。
    CalibrationService::Params tcp;
    tcp.calibType = CalibType::TcpTouch;
    const auto r = CalibrationService::calibrate(
        QStringLiteral("Z:/definitely/not/here"), {}, {}, {}, tcp);
    QVERIFY(!r.ok);
    QVERIFY2(!r.error.contains(QStringLiteral("数据文件夹不存在")), qPrintable(r.error));
    QVERIFY2(r.error.contains(QStringLiteral("相机目标点")), qPrintable(r.error));

    // 标定板：空位姿行 -> 标定板那条路的提示。
    CalibrationService::Params marker;
    marker.calibType = CalibType::Marker;
    const auto m = CalibrationService::calibrate(
        QStringLiteral("Z:/definitely/not/here"), {}, {}, {}, marker);
    QVERIFY(!m.ok);
    QVERIFY2(m.error.contains(QStringLiteral("标定数据")), qPrintable(m.error));
}
