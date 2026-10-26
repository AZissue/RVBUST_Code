#pragma once

// ── 运动后端接口 ────────────────────────────────────────────────────────
//
// 控制台只认这个接口：连接、使能、笛卡尔/关节移动、停止。第一版实现是
// SimulatedMotionBackend（不动真机，把整套交互跑通）；UR 真机后端按同样的
// 接口实现即可（30001/30002 发 URScript，30003 读反馈），控制台无需改动。
//
// 所有方法都在 UI 线程调用；后端自己负责把阻塞的网络操作挪到工作线程，
// 绝不能在 move*() 里等待连接/运动完成。
#include <QMetaType>
#include <QObject>
#include <QString>

#include <array>

#include "logic/RobotPose.h"

namespace RobotMotion {

using Pose = std::array<double, 6>;   // 笛卡尔 mm/度；关节 度

struct State {
    Pose cart{};          // x y z rx ry rz
    Pose joint{};         // j1..j6
    bool hasJoint = false;
};

} // namespace RobotMotion

Q_DECLARE_METATYPE(RobotMotion::State)

class RobotMotionBackend : public QObject {
    Q_OBJECT
public:
    explicit RobotMotionBackend(QObject* parent = nullptr)
        : QObject(parent)
    {
        qRegisterMetaType<RobotMotion::State>("RobotMotion::State");
    }

    virtual QString name() const = 0;
    virtual bool isSimulated() const = 0;

    virtual bool isConnected() const = 0;
    virtual bool isEnabled() const = 0;
    virtual RobotMotion::State state() const = 0;

    // ── 写入标定卡片的位姿（与通信工具同一约定）──────────────────────
    // state() 是"点动/程序"用的内部表示（mm + 度）。卡片必须沿用该协议
    // 历史上由通信工具写入的约定：UR 是轴角**弧度**，法奥是 mm + 度欧拉。
    // 默认实现直接透传 state()（法奥/仿真正确）；UR 后端覆盖为角度转弧度。
    virtual RobotPose::Pose cardPose() const
    {
        return RobotPose::fromStateCart(state().cart);
    }
    // 界面上显示的约定标签（日志/提示用），例如 "mm/弧度（轴角）"。
    virtual QString cardPoseUnit() const
    {
        return QStringLiteral("mm/度（欧拉角）");
    }

public slots:
    virtual void connectDevice(const QString& host, quint16 port) = 0;
    virtual void disconnectDevice() = 0;
    // 「使能」是软件层的运动许可（UR 真机还需要控制器处于 RUNNING）。禁用
    // 时必须立即停止正在执行的移动，不能只是把按钮变灰。
    virtual void setEnabled(bool enabled) = 0;
    // 到位判据由程序节点提供：位置 mm、姿态/关节 度、超时 ms。
    virtual void moveCartesian(const RobotMotion::Pose& target, double speedPct,
                               double toleranceMm = 2.0,
                               double toleranceDeg = 1.0,
                               int timeoutMs = 15000) = 0;
    virtual void moveJoint(const RobotMotion::Pose& target, double speedPct,
                           double toleranceDeg = 1.0,
                           int timeoutMs = 15000) = 0;
    // 单轴点动：真机后端按"绕基座轴旋转"正确合成姿态增量；仿真后端直接
    // 相加即可。界面不关心差异。
    virtual void jogCartesian(int axis, double delta, double speedPct) = 0;
    // 关节点动必须由后端按自己的最新反馈（而不是界面缓存的位姿）计算基准：
    // 界面缓存有 50 ms 节流，连续点按时会漏掉上一拍的增量。
    virtual void jogJoint(int axis, double delta, double speedPct) = 0;
    // 关节滑杆：把某一轴移动到绝对角度，其余轴保持后端的最新目标。
    virtual void moveJointAxisTo(int axis, double degrees,
                                 double speedPct) = 0;
    virtual void stopMotion() = 0;

signals:
    void connectedChanged(bool connected);
    void enabledChanged(bool enabled);
    void poseUpdated(const RobotMotion::State& state);
    // 一次移动结束。ok=true 表示到达目标；ok=false 时 error 可读。
    void motionFinished(bool ok, const QString& error);
    // 后端给操作员的提示（连接中、未使能、被拒绝……）。error=true 用红色。
    void statusMessage(const QString& text, bool error);
};
