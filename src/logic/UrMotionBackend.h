#pragma once

// ── UR 真机运动后端（30003 反馈 + 30001 脚本 + 29999 Dashboard）──────────
//
// 接口与 SimulatedMotionBackend 完全一致，控制台不感知差别。真机后端把
// 所有网络操作放在自己的一条工作线程里（阻塞的 waitForConnected 只堵住
// 这条线程），UI 线程只收信号：
//
//   * 30003 realtime：控制器每 8 ms 推一个包。这里持续排空 socket、只保留
//     最新位姿（actual_TCP_pose 在包体 440，q_actual 在 248），每 50 ms
//     至多向界面发一次，避免 125 Hz 刷新拖住重绘。
//   * 30001 URScript：movel / movej。位置用米、姿态用弧度旋转向量，
//     由 UrMotionMath 换算；到位判据也用它（旋转矩阵夹角，不是欧拉角）。
//   * 29999 Dashboard：stop。只在"确实有运动在飞"时发送，避免误停 pendant
//     上正在运行的其他程序。
//
// 使能是软件层许可（与仿真后端一致）：UR 本身没有远程"伺服上电"命令，
// 控制器必须处于 RUNNING（连接后会查询 robotmode 并提示）。
#include <QByteArray>
#include <QElapsedTimer>
#include <QObject>
#include <QString>
#include <QThread>

#include <array>

#include "logic/RobotMotionBackend.h"
#include "logic/UrMotionMath.h"

class QTcpSocket;
class QTimer;

class UrMotionWorker : public QObject {
    Q_OBJECT
public:
    explicit UrMotionWorker(QObject* parent = nullptr);
    ~UrMotionWorker() override;

    // 以下方法只能在 worker 线程调用（UrMotionBackend 用队列连接投递）。
    void start(const QString& host, quint16 feedbackPort);
    void shutdown();
    void setEnabled(bool enabled);
    void moveCartesian(const RobotMotion::Pose& target, double speedPct,
                       double toleranceMm, double toleranceDeg, int timeoutMs);
    void moveJoint(const RobotMotion::Pose& target, double speedPct,
                   double toleranceDeg, int timeoutMs);
    void jogCartesian(int axis, double delta, double speedPct);
    void stopMotion();

signals:
    void connectedChanged(bool connected);
    void enabledChanged(bool enabled);
    void poseUpdated(const RobotMotion::State& state);
    void motionFinished(bool ok, const QString& error);
    void statusMessage(const QString& text, bool error);

private:
    struct PendingMove {
        bool active = false;
        bool joint = false;
        bool jog = false;
        RobotMotion::Pose target{};
        double toleranceMm = 2.0;
        double toleranceDeg = 1.0;
        int timeoutMs = 15000;
        QElapsedTimer elapsed;
    };

    void teardown(bool notify);
    bool ensureReady(const QString& action);
    void beginMove(const RobotMotion::Pose& target, double speedPct,
                   double toleranceMm, double toleranceDeg, int timeoutMs,
                   bool joint, bool jog);
    bool sendScript(const QString& statement);
    void sendDashboard(const QString& command);
    void onFeedbackReady();
    void onDisconnected();
    void onStatePacket(const RobotMotion::State& state);
    void checkReached();
    void finishPending(bool ok, const QString& error);
    void checkStream();
    void onDashboardReady();

    QTcpSocket* m_feedback = nullptr;
    QTcpSocket* m_script = nullptr;
    QTcpSocket* m_dashboard = nullptr;
    QTimer* m_watchdog = nullptr;
    QByteArray m_feedbackBuf;
    QByteArray m_dashboardBuf;

    RobotMotion::State m_state;
    bool m_connected = false;
    bool m_enabled = false;
    bool m_motionInFlight = false;
    bool m_streamWarned = false;
    QElapsedTimer m_lastPacketAt;
    QElapsedTimer m_lastPublishAt;
    PendingMove m_pending;
};

class UrMotionBackend : public RobotMotionBackend {
    Q_OBJECT
public:
    explicit UrMotionBackend(QObject* parent = nullptr);
    ~UrMotionBackend() override;

    QString name() const override { return QStringLiteral("UR"); }
    bool isSimulated() const override { return false; }
    bool isConnected() const override { return m_connected; }
    bool isEnabled() const override { return m_enabled; }
    RobotMotion::State state() const override { return m_state; }

public slots:
    void connectDevice(const QString& host, quint16 port) override;
    void disconnectDevice() override;
    void setEnabled(bool enabled) override;
    void moveCartesian(const RobotMotion::Pose& target, double speedPct,
                       double toleranceMm = 2.0, double toleranceDeg = 1.0,
                       int timeoutMs = 15000) override;
    void moveJoint(const RobotMotion::Pose& target, double speedPct,
                   double toleranceDeg = 1.0, int timeoutMs = 15000) override;
    void jogCartesian(int axis, double delta, double speedPct) override;
    void stopMotion() override;

private:
    QThread* m_thread = nullptr;
    UrMotionWorker* m_worker = nullptr;
    RobotMotion::State m_state;
    bool m_connected = false;
    bool m_enabled = false;
};
