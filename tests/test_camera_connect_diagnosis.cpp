#include "test_camera_connect_diagnosis.h"

#include <QtTest>

#include <array>

#include "logic/CameraConnectDiagnosis.h"

using namespace CameraConnect;

namespace {

Evidence allGood()
{
    // 默认值就是"枚举到了、设备在、网络 OK，只是 Open 失败"。
    Evidence e;
    e.network = NetworkStatus::Ok;
    return e;
}

// std::array（不是 initializer_list）：initializer_list 的底层数组在函数返回时
// 就销毁了，按值返回会变成悬垂引用。
std::array<Cause, 11> allCauses()
{
    return {
        Cause::SdkInitFailed, Cause::NoDevice, Cause::EnumFailed,
        Cause::DeviceGone, Cause::DeviceInfoFailed, Cause::Unsupported,
        Cause::DeviceBusy, Cause::NetworkUnreachable, Cause::IpConflict,
        Cause::OpenFailed, Cause::Unknown,
    };
}

} // namespace

void TestCameraConnectDiagnosis::sdkInitFailureWinsOverEverything()
{
    // SDK 都没起来时，设备/网络字段没有意义 —— 不能报成"没插相机"。
    Evidence e;
    e.sdkReady = false;
    e.enumeratedAny = false;
    e.deviceFound = false;
    QCOMPARE(diagnose(e), Cause::SdkInitFailed);
}

void TestCameraConnectDiagnosis::noDeviceEnumerated()
{
    Evidence e;
    e.enumeratedAny = false;
    QCOMPARE(diagnose(e), Cause::NoDevice);
}

void TestCameraConnectDiagnosis::enumerationErrorIsItsOwnCause()
{
    Evidence e;
    e.enumerationOk = false;
    e.errorText = QStringLiteral("enum failed: -3");
    QCOMPARE(diagnose(e), Cause::EnumFailed);
    // 枚举报错不是"没有相机"：处理动作不同（看 SDK 报错 vs 查电源/网段）。
    QVERIFY(!retryCanHelp(Cause::EnumFailed));
}

void TestCameraConnectDiagnosis::deviceGoneAfterScan()
{
    Evidence e;
    e.deviceFound = false;
    QCOMPARE(diagnose(e), Cause::DeviceGone);
    QVERIFY(!retryCanHelp(diagnose(e)));
}

void TestCameraConnectDiagnosis::deviceInfoFailure()
{
    Evidence e;
    e.deviceInfoOk = false;
    QCOMPARE(diagnose(e), Cause::DeviceInfoFailed);
}

void TestCameraConnectDiagnosis::unsupportedModel()
{
    Evidence e;
    e.supportsX1X2 = false;
    QCOMPARE(diagnose(e), Cause::Unsupported);
}

void TestCameraConnectDiagnosis::busyFromGigeStatus()
{
    Evidence e = allGood();
    e.network = NetworkStatus::InUse;
    QCOMPARE(diagnose(e), Cause::DeviceBusy);
    // 占用是唯一"等一会儿可能自己好"的网络状态。
    QVERIFY(retryCanHelp(Cause::DeviceBusy));
}

void TestCameraConnectDiagnosis::unreachableFromGigeStatus()
{
    Evidence e = allGood();
    e.network = NetworkStatus::NotReachable;
    QCOMPARE(diagnose(e), Cause::NetworkUnreachable);
    QVERIFY(!retryCanHelp(Cause::NetworkUnreachable));
}

void TestCameraConnectDiagnosis::ipConflictFromGigeStatus()
{
    Evidence e = allGood();
    e.network = NetworkStatus::Conflict;
    QCOMPARE(diagnose(e), Cause::IpConflict);
    QVERIFY(!retryCanHelp(Cause::IpConflict));
}

void TestCameraConnectDiagnosis::fallsBackToSdkText()
{
    // 没有硬证据时沿用 3.3 的关键字规则，两套说法不能互相矛盾。
    Evidence e = allGood();
    e.errorText = QStringLiteral("device is in use");
    QCOMPARE(diagnose(e), Cause::DeviceBusy);

    e.errorText = QStringLiteral("该模式不支持");
    QCOMPARE(diagnose(e), Cause::Unsupported);

    e.errorText = QStringLiteral("open failed: -12");
    QCOMPARE(diagnose(e), Cause::OpenFailed);
    QVERIFY(retryCanHelp(Cause::OpenFailed));

    e.errorText.clear();
    QCOMPARE(diagnose(e), Cause::Unknown);
    QVERIFY(retryCanHelp(Cause::Unknown));
}

void TestCameraConnectDiagnosis::retryOnlyForTransientCauses()
{
    // 驱动/枚举/掉线/网段/IP 冲突/型号不支持：等 3 秒不会变好。
    for (Cause c : allCauses()) {
        const bool expected = (c == Cause::DeviceBusy || c == Cause::OpenFailed
                               || c == Cause::Unknown);
        QCOMPARE(retryCanHelp(c), expected);
    }
}

void TestCameraConnectDiagnosis::everyCauseHasHeadlineAndAdvice()
{
    Evidence e = allGood();
    e.errorText = QStringLiteral("raw sdk text");

    QStringList headlines;
    for (Cause c : allCauses()) {
        const QString h = headline(c);
        QVERIFY2(!h.isEmpty(), qPrintable(QStringLiteral("cause %1").arg(static_cast<int>(c))));
        QVERIFY2(!headlines.contains(h), "标题必须逐类可区分");
        headlines << h;

        const QString a = advice(e, c, 2);
        QVERIFY2(!a.isEmpty(), qPrintable(QStringLiteral("cause %1").arg(static_cast<int>(c))));
        // 漏掉 .arg() 会把这行原样显示给现场。
        QVERIFY2(!a.contains(QStringLiteral("%1")), qPrintable(a));
    }
}

void TestCameraConnectDiagnosis::noDeviceAdviceListsHostSubnets()
{
    Evidence e;
    e.enumeratedAny = false;
    e.hostSubnets = QStringList{ QStringLiteral("以太网=192.168.0.10/255.255.255.0"),
                      QStringLiteral("USB网卡=10.0.0.5/255.255.255.0") };
    const QString a = advice(e, diagnose(e), 0);
    QVERIFY(a.contains(QStringLiteral("没有枚举到任何相机")));
    QVERIFY(a.contains(QStringLiteral("以太网=192.168.0.10/255.255.255.0")));
    QVERIFY(a.contains(QStringLiteral("USB网卡=10.0.0.5/255.255.255.0")));
    QVERIFY(a.contains(QStringLiteral("网段")));
    // 没有副作用的下一步：去 RVCManager 核对/配置，而不是在本程序里猜。
    QVERIFY(a.contains(QStringLiteral("RVCManager")));
    QVERIFY(a.contains(QStringLiteral("一键配置")));
}

void TestCameraConnectDiagnosis::unreachableAdviceNamesCameraAndMismatch()
{
    Evidence e = allGood();
    e.network = NetworkStatus::NotReachable;
    e.cameraIp = QStringLiteral("192.168.0.38");
    e.cameraMask = QStringLiteral("255.255.255.0");
    e.hostSubnets = QStringList{ QStringLiteral("以太网=192.168.1.10/255.255.255.0") };

    const QString a = advice(e, diagnose(e), 0);
    QVERIFY(a.contains(QStringLiteral("192.168.0.38")));
    QVERIFY(a.contains(QStringLiteral("192.168.1.10")));
    // 主机没有同网段地址 —— 必须直接给出改法，而不是泛泛地"检查连接"。
    // 现场反馈：网段不匹配时先指到 RVCManager 的「一键配置」。
    QVERIFY(a.contains(QStringLiteral("RVCManager")));
    QVERIFY(a.contains(QStringLiteral("一键配置")));
    QVERIFY(!a.contains(QStringLiteral("同一网段仍不可达")));
}

void TestCameraConnectDiagnosis::unreachableAdviceRecognisesSameSubnet()
{
    Evidence e = allGood();
    e.network = NetworkStatus::NotReachable;
    e.cameraIp = QStringLiteral("192.168.0.38");
    e.cameraMask = QStringLiteral("255.255.255.0");
    e.hostSubnets = QStringList{ QStringLiteral("以太网=192.168.0.10/255.255.255.0") };

    const QString a = advice(e, diagnose(e), 0);
    QVERIFY(a.contains(QStringLiteral("同一网段仍不可达")));
    QVERIFY(!a.contains(QStringLiteral("没有与相机同网段的网卡")));
    // 同网段时不该再让人去改 IP —— 那是另一个问题的修法。
    QVERIFY(!a.contains(QStringLiteral("一键配置")));
}

void TestCameraConnectDiagnosis::unreachableAdviceWithoutCameraIp()
{
    Evidence e = allGood();
    e.network = NetworkStatus::NotReachable;
    e.hostSubnets = QStringList{ QStringLiteral("以太网=192.168.0.10/255.255.255.0") };

    const QString a = advice(e, diagnose(e), 0);
    // 没读到相机 IP 时不能断言"不同网段"，只能说先核对 IP。
    QVERIFY(a.contains(QStringLiteral("没能读到相机 IP")));
    QVERIFY(a.contains(QStringLiteral("192.168.0.10")));
    QVERIFY(!a.contains(QStringLiteral("不在同一网段")));
}

void TestCameraConnectDiagnosis::conflictAdviceNamesTheIp()
{
    Evidence e = allGood();
    e.network = NetworkStatus::Conflict;
    e.cameraIp = QStringLiteral("192.168.0.38");

    const QString a = advice(e, diagnose(e), 0);
    QVERIFY(a.contains(QStringLiteral("192.168.0.38")));
    QVERIFY(a.contains(QStringLiteral("冲突")));
    QVERIFY(a.contains(QStringLiteral("RVCManager")));
}

void TestCameraConnectDiagnosis::busyAdviceStillCarriesRetryCount()
{
    Evidence e = allGood();
    e.network = NetworkStatus::InUse;
    const QString a = advice(e, diagnose(e), 3);
    // 与 CameraRelease 的 3.3 文案保持一份，不另写一套。
    QVERIFY(a.contains(QStringLiteral("被占用")));
    QVERIFY(a.contains(QStringLiteral("3 次")));
}

void TestCameraConnectDiagnosis::hostSubnetMatching()
{
    const QStringList hosts = {
        QStringLiteral("以太网=192.168.0.10/255.255.255.0"),
        QStringLiteral("10.1.2.3/16"),                 // 名字省略 + 前缀写法
        QStringLiteral("坏数据"),                       // 无法解析，跳过
        QStringLiteral("USB=not-an-ip/24"),
    };

    QVERIFY(anyHostOnSubnet(QStringLiteral("192.168.0.38"),
                            QStringLiteral("255.255.255.0"), hosts));
    QVERIFY(anyHostOnSubnet(QStringLiteral("10.1.9.9"),
                            QStringLiteral("255.255.0.0"), hosts));
    QVERIFY(!anyHostOnSubnet(QStringLiteral("192.168.1.38"),
                             QStringLiteral("255.255.255.0"), hosts));
    // 相机自己的掩码决定比较范围：/24 下 10.1.9.9 与 10.1.2.3 同网段，
    // 换成 /16 仍同网段，换成 /30 就不同。
    QVERIFY(!anyHostOnSubnet(QStringLiteral("10.1.9.9"),
                             QStringLiteral("255.255.255.252"), hosts));

    // 无效输入不猜：返回 false，建议文案走"读不到相机 IP"那条分支。
    QVERIFY(!anyHostOnSubnet(QString(), QStringLiteral("255.255.255.0"), hosts));
    QVERIFY(!anyHostOnSubnet(QStringLiteral("192.168.0.38"),
                             QStringLiteral("0.0.0.0"), hosts));
    QVERIFY(!anyHostOnSubnet(QStringLiteral("192.168.0.38"),
                             QStringLiteral("255.255.255.0"), {}));
}
