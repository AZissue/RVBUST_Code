#pragma once

#include <QObject>

// 机器人控制台的数据与执行规则（2026-10-21 第 17 阶段 P1）：
//   * 节点 JSON 往返、坏数据拒绝、数值收敛；
//   * 点动步长/速度/到位判据（角度走最短路径）；
//   * 程序执行器的顺序、失败即停、单步、停止；
//   * 仿真运动后端的连接/使能/到位。
// 这些都是纯逻辑或纯 Qt，不需要相机、真机或界面。
class TestRobotProgram : public QObject {
    Q_OBJECT
private slots:
    void jsonRoundTrip();
    void jsonRejectsUnknownType();
    void jsonRejectsBadPose();
    void invalidNumbersAreClamped();
    void displayTextIsReadable();
    void programSavesAndLoadsFile();

    void jogPolicyClampsAndWraps();
    void jogPolicyReachesTolerance();
    void runnerRunsAllInOrder();
    void runnerStopsOnFailure();
    void runnerRunOneAndStop();
    void runnerRejectsEmptyProgram();
    void simulatedBackendMovesOnlyWhenEnabled();
    void simulatedBackendCompletesMove();
};
