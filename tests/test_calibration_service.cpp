#include "test_calibration_service.h"

#include <QtTest>

#include <QSet>
#include <array>
#include <cmath>

#include "logic/CalibrationService.h"
#include "logic/RobotDataFormats.h"
#include "logic/TransformTools.h"
#include "sdk/HandEyeSDKBridge.h"

namespace {

// toSdkPoseLine 的输出是逗号分隔的数值行；这里拆回 double 好逐项比对。
std::vector<double> splitNumbers(const QString& line)
{
    std::vector<double> out;
    const QStringList parts = line.split(QLatin1Char(','), Qt::SkipEmptyParts);
    for (const QString& p : parts)
        out.push_back(p.toDouble());
    return out;
}

} // namespace

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

// ── 位姿格式 ────────────────────────────────────────────────────────

// 既有机器人（FANUC 等）走的是 poseType=0 + 6 数欧拉这条路。加"位姿格式"参数
// 以后这条路必须一个字节都没变 —— 否则已核定的"助手 = 官方 SDK"一致性就断了。
void TestCalibrationService::eulerRpyStaysOnTheOldPoseTypeZeroPath()
{
    const QString raw = QStringLiteral("690.20,-63.13,424.72,137.91,11.32,173.11");
    const QString old = CalibrationService::normalizePoseLine(raw);

    for (const auto unit : { TransformTools::AngleUnit::Degree,
                             TransformTools::AngleUnit::Radian }) {
        int poseType = -99;
        const QString line = CalibrationService::toSdkPoseLine(
            raw, RobotDataFormats::Id::EulerSxyz, unit, poseType);
        QCOMPARE(poseType, 0);
        QCOMPARE(line, old);          // 逐字节相同，不是"数值接近"
    }
}

// UR 的 rx/ry/rz 是轴角旋转矢量（示教器数值：|v| = 2.53 rad = 145°），
// 不是欧拉角。当欧拉读 SDK 会"成功但算错"，所以必须转成矩阵。
void TestCalibrationService::rotationVectorBecomesMatrix16()
{
    const QString raw = QStringLiteral(
        "-208.7141,-232.9,880.1776,0.798727,1.697482,-1.697482");
    int poseType = -99;
    const QString line = CalibrationService::toSdkPoseLine(
        raw, RobotDataFormats::Id::RotationVector,
        TransformTools::AngleUnit::Radian, poseType);
    QVERIFY2(!line.isEmpty(), qPrintable(line));
    QCOMPARE(poseType, 3);

    const auto v = splitNumbers(line);
    QCOMPARE(static_cast<int>(v.size()), 16);

    // 平移三个数原样落在第 4 列；最后一行是 0 0 0 1。
    QVERIFY(std::abs(v[3] - (-208.7141)) < 1e-6);
    QVERIFY(std::abs(v[7] - (-232.9)) < 1e-6);
    QVERIFY(std::abs(v[11] - 880.1776) < 1e-6);
    for (const int i : { 12, 13, 14 })
        QVERIFY(std::abs(v[static_cast<std::size_t>(i)]) < 1e-12);
    QVERIFY(std::abs(v[15] - 1.0) < 1e-12);

    // 3x3 就是 TransformTools 的旋转矢量转换（行主序）。
    const auto rot = TransformTools::rotationVectorToRot(
        0.798727, 1.697482, -1.697482, TransformTools::AngleUnit::Radian);
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 3; ++c) {
            const double got = v[static_cast<std::size_t>(r * 4 + c)];
            const double want = rot[static_cast<std::size_t>(r * 3 + c)];
            QVERIFY2(std::abs(got - want) < 1e-8,
                     qPrintable(QStringLiteral("row %1 col %2: %3 vs %4")
                                    .arg(r).arg(c).arg(got, 0, 'g', 12).arg(want, 0, 'g', 12)));
        }
    }
    // 不是单位阵（空旋转会掩盖"没转"这类错误）。
    QVERIFY(std::abs(v[0] - 1.0) > 1e-3 || std::abs(v[1]) > 1e-3);
}

// 欧拉 RPY 不在这里测：它走 poseType=0 原样透传，"SDK 怎么解释这 6 个数"
// 不由我们决定（见 eulerRpyStaysOnTheOldPoseTypeZeroPath）。
void TestCalibrationService::everyThreeValueFormatMatchesCatalog()
{
    const QString raw = QStringLiteral("10 20 30 0.5 -0.25 0.125");
    const std::array<RobotDataFormats::Id, 3> formats {
        RobotDataFormats::Id::EulerRzyx,
        RobotDataFormats::Id::EulerRxyz,
        RobotDataFormats::Id::RotationVector,
    };

    for (const auto fmt : formats) {
        for (const auto unit : { TransformTools::AngleUnit::Degree,
                                 TransformTools::AngleUnit::Radian }) {
            int poseType = -99;
            const QString line = CalibrationService::toSdkPoseLine(raw, fmt, unit, poseType);
            QVERIFY2(!line.isEmpty(), qPrintable(line));
            QCOMPARE(poseType, 3);

            const auto v = splitNumbers(line);
            QCOMPARE(static_cast<int>(v.size()), 16);

            const auto rot = RobotDataFormats::buildRotation(
                fmt, unit, { 0.5, -0.25, 0.125 });
            for (int r = 0; r < 3; ++r) {
                for (int c = 0; c < 3; ++c) {
                    const double got = v[static_cast<std::size_t>(r * 4 + c)];
                    const double want = rot[static_cast<std::size_t>(r * 3 + c)];
                    QVERIFY2(std::abs(got - want) < 1e-8,
                             qPrintable(QStringLiteral("fmt %1 unit %2 row %3 col %4")
                                            .arg(static_cast<int>(fmt))
                                            .arg(static_cast<int>(unit))
                                            .arg(r).arg(c)));
                }
            }
        }
    }
}

// 界面提示行与实际的 SDK 调用必须说同一件事。标定页下拉框选的是“卡片这 3 个
// 旋转数怎么读”，不是 SDK 的 poseType：sXYZ 正好等于 SDK 的欧拉（0），其它 3 数
// 约定由本工具转成 4x4 矩阵（3）；四元数/矩阵约定卡片装不下，返回 -1。
void TestCalibrationService::sdkPoseTypeMatchesTheCalibrationPath()
{
    QCOMPARE(CalibrationService::sdkPoseType(RobotDataFormats::Id::EulerSxyz), 0);
    QCOMPARE(CalibrationService::sdkPoseType(RobotDataFormats::Id::EulerRzyx), 3);
    QCOMPARE(CalibrationService::sdkPoseType(RobotDataFormats::Id::RotationVector), 3);
    QCOMPARE(CalibrationService::sdkPoseType(RobotDataFormats::Id::EulerSxyx), 3);

    for (const auto fmt : { RobotDataFormats::Id::QuatWxyz,
                            RobotDataFormats::Id::QuatXyzw,
                            RobotDataFormats::Id::Matrix3x3Row,
                            RobotDataFormats::Id::Matrix3x3Col,
                            RobotDataFormats::Id::Matrix4x4Row }) {
        QCOMPARE(CalibrationService::sdkPoseType(fmt), -1);
    }

    // 每个能进卡片的约定，toSdkPoseLine 报出来的 poseType 都要和提示行一致。
    const QString raw = QStringLiteral("10 20 30 0.5 -0.25 0.125");
    for (const auto tier : { RobotDataFormats::Tier::Common,
                             RobotDataFormats::Tier::Advanced }) {
        for (const auto fmt : RobotDataFormats::ids(tier)) {
            if (!RobotDataFormats::cardUsable(fmt))
                continue;
            int poseType = -99;
            const QString line = CalibrationService::toSdkPoseLine(
                raw, fmt, TransformTools::AngleUnit::Degree, poseType);
            QVERIFY2(!line.isEmpty(), qPrintable(QStringLiteral("fmt %1")
                                                     .arg(static_cast<int>(fmt))));
            QCOMPARE(poseType, CalibrationService::sdkPoseType(fmt));
        }
    }
}

// 卡片永远是 6 个数（CaptureRecord::robotCapturePose），四元数要 4 个旋转数、
// 3x3 矩阵要 9 个、4x4 姿态矩阵要 16 个 —— 在卡片里表达不了。必须干净地拒绝，
// 不能抛异常穿到 QtConcurrent 的工作线程里去（那会直接崩进程）。
void TestCalibrationService::formatsTheCardCannotCarryAreRejected()
{
    const QString raw = QStringLiteral("10 20 30 0.5 -0.25 0.125");
    for (const auto fmt : { RobotDataFormats::Id::QuatWxyz,
                            RobotDataFormats::Id::QuatXyzw,
                            RobotDataFormats::Id::Matrix3x3Row,
                            RobotDataFormats::Id::Matrix4x4Row }) {
        int poseType = -99;
        const QString line = CalibrationService::toSdkPoseLine(
            raw, fmt, TransformTools::AngleUnit::Degree, poseType);
        QVERIFY2(line.isEmpty(), qPrintable(line));
        QCOMPARE(poseType, -99);      // 没转换就不许改调用方的变量
    }
}

void TestCalibrationService::toSdkPoseLineRejectsBadInput()
{
    int poseType = -99;
    const auto fmt = RobotDataFormats::Id::RotationVector;

    QVERIFY(CalibrationService::toSdkPoseLine(
                QStringLiteral("1,2,3,4,5"), fmt,
                TransformTools::AngleUnit::Radian, poseType).isEmpty());
    QVERIFY(CalibrationService::toSdkPoseLine(
                QStringLiteral("1,2,3,4,5,abc"), fmt,
                TransformTools::AngleUnit::Radian, poseType).isEmpty());
    // 中文逗号按卡片校验的规矩就是非法输入。
    QVERIFY(CalibrationService::toSdkPoseLine(
                QStringLiteral("1，2，3，4，5，6"), fmt,
                TransformTools::AngleUnit::Radian, poseType).isEmpty());
    QVERIFY(CalibrationService::toSdkPoseLine(
                QString(), fmt, TransformTools::AngleUnit::Radian, poseType).isEmpty());
}

void TestCalibrationService::poseFormatNamesAreDistinctAndComplete()
{
    const std::array<RobotDataFormats::Id, 7> all {
        RobotDataFormats::Id::EulerSxyz,
        RobotDataFormats::Id::EulerRzyx,
        RobotDataFormats::Id::EulerRxyz,
        RobotDataFormats::Id::QuatWxyz,
        RobotDataFormats::Id::QuatXyzw,
        RobotDataFormats::Id::Matrix3x3Row,
        RobotDataFormats::Id::RotationVector,
    };
    QSet<QString> seen;
    for (const auto fmt : all) {
        const QString name = CalibrationService::poseFormatName(fmt);
        QVERIFY2(!name.isEmpty(), "格式名不能为空");
        QVERIFY2(!seen.contains(name), qPrintable(QStringLiteral("格式名重复：") + name));
        seen.insert(name);
        QVERIFY2(!CalibrationService::poseFormatDescription(fmt).isEmpty(),
                 qPrintable(QStringLiteral("格式说明不能为空：") + name));
    }
    QCOMPARE(seen.size(), 7);
    // UR 的轴角必须说清楚是"旋转矢量"，否则界面上没人认得出该选哪个。
    QVERIFY(CalibrationService::poseFormatName(
                RobotDataFormats::Id::RotationVector)
                .contains(QStringLiteral("旋转矢量")));
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

void TestCalibrationService::columnBuilderKeepsEmptyRowsAligned()
{
    // 第 2 组什么都没填，第 3 组只有戳点和相机点：三列仍必须各 3 行，
    // 且同一行的值来自同一条记录。
    CaptureRecord a;
    a.cameraTargetXyz = QStringLiteral("1 2 3");
    a.robotCapturePose = QStringLiteral("1 2 3 0 0 0");
    a.robotTargetXyz = QStringLiteral("4 5 6");
    CaptureRecord empty;
    CaptureRecord c;
    c.cameraTargetXyz = QStringLiteral("7 8 9");
    c.robotTargetXyz = QStringLiteral("10 11 12");

    const auto cols = CalibrationService::columnsFromRecords({a, empty, c});
    QCOMPARE(int(cols.camera.size()), 3);
    QCOMPARE(int(cols.pose.size()), 3);
    QCOMPARE(int(cols.tcp.size()), 3);

    QCOMPARE(cols.camera[0], QStringLiteral("1 2 3"));
    QCOMPARE(cols.camera[1], QString());
    QCOMPARE(cols.camera[2], QStringLiteral("7 8 9"));
    QCOMPARE(cols.pose[0], QStringLiteral("1 2 3 0 0 0"));
    QCOMPARE(cols.pose[1], QString());
    QCOMPARE(cols.pose[2], QString());
    QCOMPARE(cols.tcp[0], QStringLiteral("4 5 6"));
    QCOMPARE(cols.tcp[1], QString());
    QCOMPARE(cols.tcp[2], QStringLiteral("10 11 12"));

    const auto none = CalibrationService::columnsFromRecords({});
    QVERIFY(none.camera.empty());
    QVERIFY(none.pose.empty());
    QVERIFY(none.tcp.empty());
}
