#pragma once

#include <QObject>
#include <QString>
#include <QStringList>

#include "logic/EfortPoseReader.h"
#include "logic/NrcJsonReader.h"
#include "logic/RobotPose.h"
#include "logic/URRealtimeReader.h"
#include "logic/URRtdeReader.h"

class QThread;

// kind values for RobotWorker::readPose / its poseReady() signal: which UI
// request asked for the pose decides where the answer goes.
enum RobotReadKind {
    RobotReadCapturePose       = 0,   // 「拍照位姿」 → robot_capture_pose 卡片
    RobotReadTouchPose         = 1,   // 「戳点位姿」 → robot_target_xyz 卡片
    RobotReadAutoBeforeCapture = 2    // 拍照前自动读取 → robot_capture_pose 卡片
};

// ── Robot channel worker ──
// Every robot operation is a *blocking* network call (waitForConnected /
// waitForReadyRead, up to 1.5 s).  QTcpSocket is thread-affine, so the whole
// channel — the four readers and every call on them — lives on one dedicated
// thread (moveToThread); the UI thread only talks to it through queued
// signals/slots.  That is what keeps a connect / read / capture-time read from
// freezing the window (and the UI stall watchdog from firing).
//
// This class is an implementation detail of RobotController; nothing outside
// RobotController.cpp constructs it.
class RobotWorker : public QObject {
    Q_OBJECT
public:
    explicit RobotWorker(QObject* parent = nullptr);
    ~RobotWorker() override;

public slots:
    // All of these run on the worker thread.
    void connectRobot(const QString& host, quint16 port, int protocol, int format,
                      double scale, quint8 unitId, quint16 startAddress);
    void disconnectRobot();
    void simulateConnect();
    void readPose(int kind);

signals:
    // ok=false → error carries the adapter's lastError() text.
    void connectFinished(bool ok, const QString& label, const QString& error);
    // fields = the six pose numbers already formatted "%.3f" (x y z rx ry rz),
    // so the cross-thread hop needs no custom metatype.
    void poseReady(int kind, bool ok, const QStringList& fields, const QString& error);

private:
    RobotPose::Reader* readerFor(int protocol);

    // The four readers live here, not in MainWindow: they own the QTcpSocket and
    // must only ever be touched from this worker's thread.
    RobotPose::ModbusTcpReader   m_robotReader;
    RobotPose::URRealtimeReader  m_urReader;
    RobotPose::URRtdeReader      m_rtdeReader;
    RobotPose::NrcJsonReader     m_nrcReader;
    EfortPoseReader::EfortReader m_eftReader;
    int  m_protocol    = 0;
    bool m_simulated   = false;
    int  m_simCounter  = 0;   // 模拟位姿每次 +10
};

// RobotController owns the robot thread and the single copy of the logical
// connection state.  MainWindow keeps only the widgets: it calls connect/
// disconnect/read and reacts to the two signals below.
//
// Threading contract (unchanged from T-009):
//   • connect/disconnect/read are queued onto the worker thread; the UI thread
//     never blocks on a network call;
//   • the logical state (connected / simulated / autoRead) is written on the UI
//     thread, so every getter is safe to call from MainWindow;
//   • shutdown() is bounded and idempotent, called from closeEvent() and
//     ~MainWindow().
class RobotController : public QObject {
    Q_OBJECT
public:
    explicit RobotController(QObject* parent = nullptr);
    ~RobotController() override;

    void connectToRobot(const QString& host, quint16 port, int protocol, int format,
                        double scale, quint8 unitId, quint16 startAddress);
    void disconnectRobot();
    void simulateConnect();
    // No-op when not connected (the UI guards this too; kept here so a stray
    // call cannot queue a pointless blocking read).
    void readPose(int kind);

    bool isConnected() const { return m_connected; }
    bool isSimulated() const { return m_simulated; }
    void setAutoRead(bool on) { m_autoRead = on; }
    bool autoRead() const { return m_autoRead; }

    // Bounded teardown; safe to call more than once and from the destructor.
    void shutdown();

signals:
    void connectFinished(bool ok, const QString& label, const QString& error);
    void poseReady(int kind, bool ok, const QStringList& fields, const QString& error);

private:
    void onConnectFinished(bool ok, const QString& label, const QString& error);

    QThread*     m_thread = nullptr;
    RobotWorker* m_worker = nullptr;

    bool m_connected = false;   // logical connection (real or simulated)
    bool m_simulated = false;   // "模拟连接成功" — no real socket
    bool m_autoRead  = false;   // pre-capture automatic pose read
};
