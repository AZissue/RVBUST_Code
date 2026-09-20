#pragma once

#include <QObject>

// 第 11 回合任务 008（Codex 验收测试）：埃夫特（EFORT）机器人适配器里
// **不需要真机**的那部分——位姿归一化与 SDK 返回码映射。
//
// 现场没有埃夫特机器人可连，所以真机结论只能写 NEEDS_HUMAN；但"读到的 6 个数
// 有没有被正确换算成项目约定的 mm + 度、坏值会不会被放过去"这两件事必须钉死，
// 否则接上真机时错的是我们自己的换算而不是机器人。
class TestEfortPoseReader : public QObject {
    Q_OBJECT
private slots:
    void mmAndDegreePassThrough();
    void metersAndRadiansAreConverted();
    void nonFiniteInputIsRejectedAndOutputUntouched();
    void nullInputIsRejected();
    void sdkCodesMapToRobotPoseStatus();
    void errorTextIsReadableAndCarriesTheCode();
};
