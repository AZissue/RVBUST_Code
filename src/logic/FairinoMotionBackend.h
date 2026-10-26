#pragma once

// ── 法奥（FAIRINO）真机运动后端 ────────────────────────────────────────
//
// 接口与 SimulatedMotionBackend / UrMotionBackend 完全一致。网络操作全部在
// 自己的一条工作线程里，UI 线程只收信号。
//
// 证据（fairino Python SDK v2.1.7.1 + 官方通讯协议手册）：
//   * 20003：XML-RPC over HTTP。模式/使能/运动指令都发到这里；
//   * 20004：控制器主动推的二进制状态包（RobotStatePkg）。位姿、使能状态、
//     motion_done、故障码都以这条流为准 —— SDK 自己的 getter 也是读它；
//   * 位姿单位 mm + 度，姿态是 R = Rz·Ry·Rx（与卡片一致），无需换算；
//   * MoveL/MoveJ **立即返回错误码**，不阻塞到运动完成（协议手册：blendR=-1
//     只表示"到位停、不混合"）。到位必须看 20004 的 motion_done + 位置；
//   * MoveL 的参数里同时有目标关节和目标笛卡尔位姿；SDK 在关节全 0 时先
//     自己调 GetInverseKin，所以本后端也先解逆解再下发，绝不把 0 当目标。
//
// 使能：法奥有真正的上/下使能指令（RobotEnable 1/0），与 UR 的"纯软件许可"
// 不同。这里仍是两层：界面上的「开启使能」= 软件许可 + RobotEnable(1)；
// 只有软件许可和控制器反馈的 rbtEnableState 同时为真才算"已使能"。
//
// 没有真机时的边界：状态包格式、XML-RPC 返回码、自动/手动模式下的运动
// 行为都只能现场验证；代码里不猜字节偏移（偏移来自 ctypes 实测），不猜
// 错误码含义（只显示数字），模拟/单测只证明解析与策略正确。
#include <QByteArray>
#include <QElapsedTimer>
#include <QObject>
#include <QString>
#include <QThread>

#include <array>

#include "logic/FairinoRealtime.h"
#include "logic/FairinoXmlRpcClient.h"
#include "logic/RobotMotionBackend.h"

class QTcpSocket;
class QTimer;

class FairinoMotionWorker : public QObject {
    Q_OBJECT
public:
    explicit FairinoMotionWorker(QObject* parent = nullptr);
    ~FairinoMotionWorker() override;

    // 以下方法只能在 worker 线程调用（FairinoMotionBackend 用队列连接投递）。
    void start(const QString& host, quint16 rpcPort);
    void shutdown();
    void setEnabled(bool enabled);
    void moveCartesian(const RobotMotion::Pose& target, double speedPct,
                       double toleranceMm, double toleranceDeg, int timeoutMs);
    void moveJoint(const RobotMotion::Pose& target, double speedPct,
                   double toleranceDeg, int timeoutMs);
    void jogCartesian(int axis, double delta, double speedPct);
    void jogJoint(int axis, double delta, double speedPct);
    void moveJointAxisTo(int axis, double degrees, double speedPct);
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
        double speedPct = 50.0;
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
    void finishPending(bool ok, const QString& error, bool motionMayContinue,
                       bool announceArrival);
    RobotMotion::Pose latestJogBase(bool joint) const;

    bool callOk(const QString& method,
                const QList<FairinoXmlRpc::Value>& params,
                QList<FairinoXmlRpc::Value>& values, const QString& action);
    bool solveInverseKin(const RobotMotion::Pose& cart,
                         RobotMotion::Pose* joint, QString* error);
    bool solveForwardKin(const RobotMotion::Pose& joint,
                         RobotMotion::Pose* cart, QString* error);
    bool targetFrameIds(int* tool, int* user);

    void onStreamReady();
    void onStreamDisconnected();
    void onStreamState(const FairinoRealtime::State& state);
    void publishEnabled();
    void reportFaults(const FairinoRealtime::State& state);
    void checkReached();
    void checkStream();

    QTcpSocket* m_stream = nullptr;
    QTimer* m_watchdog = nullptr;
    FairinoRealtime::Parser m_parser;
    FairinoRealtime::State m_raw;
    FairinoXmlRpcClient m_rpc;
    QString m_host;
    quint16 m_rpcPort = 20003;

    RobotMotion::State m_state;
    bool m_haveState = false;
    bool m_connected = false;
    bool m_armed = false;      // 软件许可（界面按钮）
    bool m_hwEnabled = false;  // 控制器反馈 rbtEnableState
    bool m_enabledReported = false;
    bool m_motionInFlight = false;
    bool m_streamWarned = false;
    bool m_withinTolerance = false;
    QElapsedTimer m_withinToleranceAt;
    QElapsedTimer m_lastFrameAt;
    QElapsedTimer m_lastPublishAt;
    qint32 m_lastMainCode = 0;
    qint32 m_lastSubCode = 0;

    PendingMove m_pending;
    PendingMove m_queued;
    bool m_queuedActive = false;
};

class FairinoMotionBackend : public RobotMotionBackend {
    Q_OBJECT
public:
    explicit FairinoMotionBackend(QObject* parent = nullptr);
    ~FairinoMotionBackend() override;

    QString name() const override { return QStringLiteral("FAIRINO"); }
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
    void jogJoint(int axis, double delta, double speedPct) override;
    void moveJointAxisTo(int axis, double degrees, double speedPct) override;
    void stopMotion() override;

private:
    QThread* m_thread = nullptr;
    FairinoMotionWorker* m_worker = nullptr;
    RobotMotion::State m_state;
    bool m_connected = false;
    bool m_enabled = false;
};
