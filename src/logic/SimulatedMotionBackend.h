#pragma once

#include <QElapsedTimer>
#include <QTimer>

#include "logic/RobotMotionBackend.h"

// 仿真运动后端：不连接任何设备，用 20 ms 定时器把当前位置线性插值到目标。
// 目的不是模拟运动学，而是让"连接 → 使能 → 点动 → 添加节点 → 单步/整表运行"
// 这条完整交互在真机后端落地之前就能被验证（也能写进单测）。
class SimulatedMotionBackend : public RobotMotionBackend {
    Q_OBJECT
public:
    explicit SimulatedMotionBackend(QObject* parent = nullptr);

    QString name() const override { return QStringLiteral("仿真"); }
    bool isSimulated() const override { return true; }
    bool isConnected() const override { return m_connected; }
    bool isEnabled() const override { return m_enabled; }
    RobotMotion::State state() const override { return m_state; }

public slots:
    void connectDevice(const QString& host, quint16 port) override;
    void disconnectDevice() override;
    void setEnabled(bool enabled) override;
    void moveCartesian(const RobotMotion::Pose& target, double speedPct) override;
    void moveJoint(const RobotMotion::Pose& target, double speedPct) override;
    void stopMotion() override;

private:
    void startMove(const RobotMotion::Pose& cartTarget,
                   const RobotMotion::Pose& jointTarget, double speedPct,
                   bool angular);
    void onTick();
    void publishPose();

    RobotMotion::State m_state;
    bool m_connected = false;
    bool m_enabled = false;

    QTimer m_timer;
    QElapsedTimer m_elapsed;
    RobotMotion::Pose m_startCart{};
    RobotMotion::Pose m_startJoint{};
    RobotMotion::Pose m_targetCart{};
    RobotMotion::Pose m_targetJoint{};
    int m_durationMs = 0;
    bool m_moving = false;
    int m_connectGeneration = 0;
};
