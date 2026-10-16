#include "test_efort_pose_reader.h"

#include <QtTest>

#include <QDir>
#include <QFile>
#include <QTemporaryDir>

#include <cmath>
#include <limits>

// 只要 SDK 的返回码定义（纯宏，不带 dllexport 声明），避免污染这个编译单元。
#include "SdkConstDef.h"

#include "logic/EfortPoseReader.h"
#include "logic/RobotPose.h"

namespace {

constexpr double kPi = 3.14159265358979323846;

RobotPose::Pose sentinel()
{
    RobotPose::Pose pose;
    pose.xyz = { 1.0, 2.0, 3.0 };
    pose.rpy = { 4.0, 5.0, 6.0 };
    return pose;
}

} // namespace

void TestEfortPoseReader::mmAndDegreePassThrough()
{
    const double raw[6] = { 100.0, -20.5, 400.25, 180.0, 0.0, -45.5 };
    RobotPose::Pose pose;
    QVERIFY(EfortPoseReader::normalizePose(raw, true, true, pose));
    QCOMPARE(pose.xyz[0], 100.0);
    QCOMPARE(pose.xyz[1], -20.5);
    QCOMPARE(pose.xyz[2], 400.25);
    QCOMPARE(pose.rpy[0], 180.0);
    QCOMPARE(pose.rpy[1], 0.0);
    QCOMPARE(pose.rpy[2], -45.5);
}

void TestEfortPoseReader::metersAndRadiansAreConverted()
{
    // 项目约定是 mm + 度；SDK 若给 m + 弧度，必须换算，不能只换个标签。
    const double raw[6] = { 0.1, 0.2, 0.3, 0.0, kPi / 2.0, -kPi / 2.0 };
    RobotPose::Pose pose;
    QVERIFY(EfortPoseReader::normalizePose(raw, false, false, pose));
    QCOMPARE(pose.xyz[0], 100.0);
    QCOMPARE(pose.xyz[1], 200.0);
    QCOMPARE(pose.xyz[2], 300.0);
    QVERIFY(std::abs(pose.rpy[0]) < 1e-9);
    QVERIFY(std::abs(pose.rpy[1] - 90.0) < 1e-9);
    QVERIFY(std::abs(pose.rpy[2] + 90.0) < 1e-9);
}

void TestEfortPoseReader::nonFiniteInputIsRejectedAndOutputUntouched()
{
    double raw[6] = { 1.0, 2.0, std::numeric_limits<double>::quiet_NaN(),
                      0.0, 0.0, 0.0 };
    RobotPose::Pose pose = sentinel();
    QVERIFY(!EfortPoseReader::normalizePose(raw, true, true, pose));
    QCOMPARE(pose.xyz[0], 1.0);      // 失败时绝不半写
    QCOMPARE(pose.rpy[2], 6.0);
}

void TestEfortPoseReader::nullInputIsRejected()
{
    RobotPose::Pose pose = sentinel();
    QVERIFY(!EfortPoseReader::normalizePose(nullptr, true, true, pose));
    QCOMPARE(pose.xyz[2], 3.0);
}

void TestEfortPoseReader::sdkCodesMapToRobotPoseStatus()
{
    using RobotPose::Status;
    QCOMPARE(EfortPoseReader::statusFromSdkCode(ERROR_OK), Status::Ok);
    QCOMPARE(EfortPoseReader::statusFromSdkCode(ERROR_CONNECT_FAILED),
             Status::NotConnected);
    QCOMPARE(EfortPoseReader::statusFromSdkCode(ERROR_NO_CONNECTION),
             Status::NotConnected);
    QCOMPARE(EfortPoseReader::statusFromSdkCode(ERROR_CONNECTION_BROKEN),
             Status::NotConnected);
    QCOMPARE(EfortPoseReader::statusFromSdkCode(ERROR_THIRD_OPERATION_TIME_OUT),
             Status::Timeout);
    // 认不出来的码也要有归属，不能返回 Ok 把错误吞掉。
    QCOMPARE(EfortPoseReader::statusFromSdkCode(999999), Status::ProtocolError);
}

void TestEfortPoseReader::errorTextIsReadableAndCarriesTheCode()

{
    const QString ok = EfortPoseReader::sdkErrorText(ERROR_OK);
    QVERIFY(!ok.isEmpty());
    const QString bad = EfortPoseReader::sdkErrorText(ERROR_CONNECT_FAILED);
    QVERIFY(!bad.isEmpty());
    QVERIFY2(bad.contains(QString::number(ERROR_CONNECT_FAILED)), qPrintable(bad));
    QVERIFY2(RobotPose::statusText(RobotPose::Status::NotConnected) != bad,
             "错误文案应当把 SDK 码一起交代清楚");
}

void TestEfortPoseReader::addressSuffixIsSplitOffTheIp()
{
    // 客户给的地址就是写着端口的：只把 IP 交给 SDK。
    // （整串喂给 SDK 的 str2IpAddr，"192.168.0.1:8003" 会变成 192.171.44.131。）
    const EfortPoseReader::AddressSplit withPort =
        EfortPoseReader::splitAddress(QStringLiteral("192.168.0.1:8003"));
    QCOMPARE(withPort.ip, QStringLiteral("192.168.0.1"));
    QCOMPARE(withPort.portSuffix, QStringLiteral("8003"));

    // 客户把 8003 写成 80003 也一样对待（本链路不用这两个数）。
    const EfortPoseReader::AddressSplit fiveDigit =
        EfortPoseReader::splitAddress(QStringLiteral("192.168.0.1:80003"));
    QCOMPARE(fiveDigit.ip, QStringLiteral("192.168.0.1"));
    QCOMPARE(fiveDigit.portSuffix, QStringLiteral("80003"));

    // 只有 IP：原样透传，portSuffix 为空（UI 据此决定要不要提示）。
    const EfortPoseReader::AddressSplit bare =
        EfortPoseReader::splitAddress(QStringLiteral("  192.168.0.37  "));
    QCOMPARE(bare.ip, QStringLiteral("192.168.0.37"));
    QVERIFY(bare.portSuffix.isEmpty());

    // 冒号在开头 / 结尾 / 多个：都不许把 IP 弄丢。
    QCOMPARE(EfortPoseReader::splitAddress(QStringLiteral(":8003")).ip, QString());
    QCOMPARE(EfortPoseReader::splitAddress(QStringLiteral("192.168.0.1:")).ip,
             QStringLiteral("192.168.0.1"));
    QCOMPARE(EfortPoseReader::splitAddress(QStringLiteral("192.168.0.1:8003:9")).ip,
             QStringLiteral("192.168.0.1"));

    // 空输入：ip 为空（connect() 靠这个报"IP 不能为空"）。
    QVERIFY(EfortPoseReader::splitAddress(QString()).ip.isEmpty());
    QVERIFY(EfortPoseReader::splitAddress(QStringLiteral("   ")).ip.isEmpty());
}

void TestEfortPoseReader::missingLogConfigIsDetectableAndExplained()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());

    // 目录里没有文件 → 判为缺失（test2.4 绿色包就是这个状态）。
    QVERIFY(!EfortPoseReader::logConfigPresent(dir.path()));

    // 建出文件 → 判为存在（能走到真正连机器那一步）。
    QFile conf(dir.path() + QStringLiteral("/log4cpp.conf"));
    QVERIFY(conf.open(QIODevice::WriteOnly));
    conf.write("log4j.rootCategory=DEBUG\n");
    conf.close();
    QVERIFY(EfortPoseReader::logConfigPresent(dir.path()));

    // 空目录串不做"当前目录"猜测：宁可报缺失，也不要在别处悄悄读了。
    QVERIFY(!EfortPoseReader::logConfigPresent(QString()));

    // 文案要自己说得清：点名文件、给出期望路径、并说明这不是网络问题。
    const QString text = EfortPoseReader::logConfigMissingText(dir.path());
    QVERIFY2(text.contains(QStringLiteral("log4cpp.conf")), qPrintable(text));
    QVERIFY2(text.contains(dir.path()) || text.contains(QDir::toNativeSeparators(dir.path())),
             qPrintable(text));
    QVERIFY2(text.contains(QStringLiteral("连接")) || text.contains(QStringLiteral("网络")),
             qPrintable(text));
}
