#include "test_efort_pose_reader.h"

#include <QtTest>

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
