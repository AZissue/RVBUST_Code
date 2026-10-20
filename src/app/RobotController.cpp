#include "app/RobotController.h"

#include "logic/RuntimeLog.h"

#include <QThread>

namespace {
// Bounded wait for an in-flight blocking robot call (<= 1.5 s) on shutdown.
constexpr int kShutdownWaitMs = 3000;

// Format a robot pose for the UI exactly the way the old synchronous path did
// (".arg(v, 0, 'f', 3)" == QString::number(v, 'f', 3)), so the values shown in
// the cards / logs / 探针 regex are byte-for-byte unchanged.  Carried across the
// worker->UI signal hop as plain strings (no custom metatype needed).
QStringList robotPoseFields(const RobotPose::Pose& pose)
{
    QStringList f;
    for (int i = 0; i < 3; ++i)
        f << QString::number(pose.xyz[i], 'f', 3);
    for (int i = 0; i < 3; ++i)
        f << QString::number(pose.rpy[i], 'f', 3);
    return f;
}
} // namespace

// ── RobotWorker ───────────────────────────────────────────────────────
// 所有 connect() / disconnect() / readPose() 只在本 worker 的线程被调用，
// socket 的亲和性因此一致。

RobotWorker::RobotWorker(QObject* parent) : QObject(parent) {}

RobotWorker::~RobotWorker() = default;

RobotPose::Reader* RobotWorker::readerFor(int protocol)
{
    switch (protocol) {
    case 4:  return &m_rtdeReader;
    case 3:  return &m_eftReader;
    case 2:  return &m_nrcReader;
    case 1:  return &m_urReader;
    default: return &m_robotReader;   // 0 = Modbus TCP，其它协议号也按 Modbus
    }
}

void RobotWorker::connectRobot(const QString& host, quint16 port, int protocol,
                               int format, double scale, quint8 unitId,
                               quint16 startAddress)
{
    m_protocol = protocol;
    m_simulated = false;   // 一次真实连接尝试离开「模拟」态

    // 协议特有的「连接前设置」+ 已连接文案里的协议标签，集中在这里一处。
    QString label;
    if (protocol == 3) {
        // 埃夫特：走厂商 EfortSDK（EftSdk.dll）。地址串与端口由适配器决定，
        // 与 UR/NRC 一样没有寄存器格式/系数要配。
        label = QStringLiteral("%1，埃夫特 EfortSDK").arg(host);
    } else if (protocol == 2) {
        // 博纳斯/纳博特 JSON over TCP: like UR, no register format/scale to
        // configure — the adapter owns the framing and the JSON payload.
        m_nrcReader.setTimeoutMs(1500);
        label = QStringLiteral("%1:%2，博纳斯 JSON/TCP").arg(host).arg(port);
    } else if (protocol == 4) {
        // UR RTDE (30004): like the 30003 port there is no register
        // format/scale to configure -- the adapter owns the handshake and the
        // recipe. The timeout also bounds each handshake step.
        m_rtdeReader.setTimeoutMs(1500);
        label = QStringLiteral("%1:%2，UR RTDE").arg(host).arg(port);
    } else if (protocol == 1) {
        // UR Realtime interface: no register format/scale to configure.
        m_urReader.setTimeoutMs(1500);
        label = QStringLiteral("%1:%2，UR Realtime").arg(host).arg(port);
    } else {
        RobotPose::ModbusConfig cfg;
        switch (format) {
        case 1:  cfg.format = RobotPose::RegisterFormat::Int32Scaled; break;
        case 2:  cfg.format = RobotPose::RegisterFormat::Int16Scaled; break;
        default: cfg.format = RobotPose::RegisterFormat::Float32; break;
        }
        cfg.scale = scale;
        cfg.unitId = unitId;
        cfg.startAddress = startAddress;
        cfg.timeoutMs = 1500;
        m_robotReader.setConfig(cfg);
        label = QStringLiteral("%1:%2").arg(host).arg(port);
    }

    RobotPose::Reader* reader = readerFor(protocol);
    // 重复点「连接」：先把目标 reader 上的旧 socket 收掉再重连，免得残留；
    // 第一次连接时它是空操作。都在同一线程，没有并发。
    reader->disconnect();
    if (!reader->connect(host, port)) {
        emit connectFinished(false, label, reader->lastError());
        return;
    }
    emit connectFinished(true, label, QString());
}

void RobotWorker::disconnectRobot()
{
    for (int p = 0; p <= 4; ++p)
        readerFor(p)->disconnect();
    m_simulated = false;
}

void RobotWorker::simulateConnect()
{
    // "模拟连接成功" — no real Modbus socket; only sets the logical connected
    // state so the read buttons / cards can be exercised in the UI.
    for (int p = 0; p <= 4; ++p)
        readerFor(p)->disconnect();
    m_simulated = true;
}

void RobotWorker::readPose(int kind)
{
    if (m_simulated) {
        // Deterministic dummy pose so the read buttons / cards can be verified
        // without real Modbus hardware.
        const double base = 100.0 + (m_simCounter++ % 50) * 10.0;
        RobotPose::Pose pose;
        pose.xyz = { base, base + 1.0, base + 2.0 };
        pose.rpy = { 0.0, 0.0, 0.0 };
        emit poseReady(kind, true, robotPoseFields(pose), QString());
        return;
    }
    RobotPose::Pose pose;
    RobotPose::Reader* reader = readerFor(m_protocol);
    if (reader->readPose(pose) != RobotPose::Status::Ok) {
        emit poseReady(kind, false, QStringList(), reader->lastError());
        return;
    }
    emit poseReady(kind, true, robotPoseFields(pose), QString());
}

// ── RobotController ───────────────────────────────────────────────────

RobotController::RobotController(QObject* parent) : QObject(parent)
{
    // The worker has no parent because moveToThread() requires it; it deletes
    // itself when the thread finishes.
    m_thread = new QThread(this);
    m_worker = new RobotWorker;
    m_worker->moveToThread(m_thread);
    connect(m_thread, &QThread::finished, m_worker, &QObject::deleteLater);
    connect(m_worker, &RobotWorker::connectFinished,
            this, &RobotController::onConnectFinished);
    connect(m_worker, &RobotWorker::poseReady,
            this, &RobotController::poseReady);
    m_thread->start();
}

RobotController::~RobotController()
{
    shutdown();
}

void RobotController::connectToRobot(const QString& host, quint16 port,
                                     int protocol, int format, double scale,
                                     quint8 unitId, quint16 startAddress)
{
    if (!m_worker)
        return;
    // connect() 是阻塞调用——交给 worker 线程，UI 立刻返回。  The functor
    // overload is used (instead of Q_ARG by name) so the arguments need no
    // metatype registration and the compiler checks the call.
    RobotWorker* worker = m_worker;
    QMetaObject::invokeMethod(worker,
        [worker, host, port, protocol, format, scale, unitId, startAddress]() {
            worker->connectRobot(host, port, protocol, format, scale, unitId,
                                 startAddress);
        }, Qt::QueuedConnection);
}

void RobotController::disconnectRobot()
{
    m_connected = false;
    m_simulated = false;
    if (RobotWorker* worker = m_worker) {
        QMetaObject::invokeMethod(worker, [worker]() { worker->disconnectRobot(); },
                                  Qt::QueuedConnection);
    }
}

void RobotController::simulateConnect()
{
    // Logical state changes immediately, exactly as the old UI slot did; the
    // worker call itself only drops stale sockets.
    m_connected = true;
    m_simulated = true;
    if (RobotWorker* worker = m_worker) {
        QMetaObject::invokeMethod(worker, [worker]() { worker->simulateConnect(); },
                                  Qt::QueuedConnection);
    }
}

void RobotController::readPose(int kind)
{
    if (!m_connected)
        return;
    if (RobotWorker* worker = m_worker) {
        QMetaObject::invokeMethod(worker, [worker, kind]() { worker->readPose(kind); },
                                  Qt::QueuedConnection);
    }
}

void RobotController::onConnectFinished(bool ok, const QString& label,
                                        const QString& error)
{
    m_simulated = false;
    m_connected = ok;
    emit connectFinished(ok, label, error);
}

void RobotController::shutdown()
{
    //   1. cut the worker<->controller signals both ways, so no late pose/connect
    //      result can be delivered once the window is closing;
    //   2. quit() the worker's event loop and wait (bounded) — the loop returns
    //      as soon as the current blocking call (<= 1.5 s) finishes; a queued
    //      request then never runs at all;
    //   3. the worker deletes itself in its own thread (QThread::finished ->
    //      deleteLater), so we drop the pointer and never touch it again.
    if (!m_thread)
        return;
    if (m_worker) {
        QObject::disconnect(m_worker, nullptr, this, nullptr);
        QObject::disconnect(this, nullptr, m_worker, nullptr);
    }
    m_thread->quit();
    if (!m_thread->wait(kShutdownWaitMs)) {
        RuntimeLog::log("[ROBOT] worker thread still busy after %d ms at shutdown",
                        kShutdownWaitMs);
        // Do not let ~QObject delete a still-running QThread: detach it and let
        // the process exit reclaim it.
        m_thread->setParent(nullptr);
    }
    m_worker = nullptr;
    m_thread = nullptr;

    m_connected = false;
    m_simulated = false;
}
