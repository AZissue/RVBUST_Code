#pragma once

#include <QObject>

// 3.0 E-05：相机连接失败的原因分类与提示文案
// （src/logic/CameraConnectDiagnosis.h，header-only 纯函数）。
//
// 这里钉住三件事：
//   1. 判定顺序 —— 越硬的事实越优先（SDK → 枚举 → 设备 → 网络状态 → 文本）；
//   2. 重试只发生在"等一会儿真能好"的原因上；
//   3. 每种原因都有短标题和可执行建议，且网段相关建议会带出相机 IP 与本机网卡。
class TestCameraConnectDiagnosis : public QObject {
    Q_OBJECT
private slots:
    void sdkInitFailureWinsOverEverything();
    void noDeviceEnumerated();
    void enumerationErrorIsItsOwnCause();
    void deviceGoneAfterScan();
    void deviceInfoFailure();
    void unsupportedModel();
    void busyFromGigeStatus();
    void unreachableFromGigeStatus();
    void ipConflictFromGigeStatus();
    void fallsBackToSdkText();
    void retryOnlyForTransientCauses();
    void everyCauseHasHeadlineAndAdvice();
    void noDeviceAdviceListsHostSubnets();
    void unreachableAdviceNamesCameraAndMismatch();
    void unreachableAdviceRecognisesSameSubnet();
    void unreachableAdviceWithoutCameraIp();
    void conflictAdviceNamesTheIp();
    void busyAdviceStillCarriesRetryCount();
    void hostSubnetMatching();
};
