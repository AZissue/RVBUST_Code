#include "logic/PoseOnlyMotionBackend.h"

#include "logic/EfortPoseReader.h"
#include "logic/NrcJsonReader.h"

#include <QTimer>

#include <cmath>
#include <utility>

namespace {

constexpr int kPollMs = 50;
constexpr int kReadTimeoutMs = 1500;

RobotMotion::State stateFromPose(const RobotPose::Pose& pose)
{
    RobotMotion::State state;
    for (int i = 0; i < 3; ++i) {
        state.cart[static_cast<std::size_t>(i)] = pose.xyz[static_cast<std::size_t>(i)];
        state.cart[static_cast<std::size_t>(i + 3)] =
            pose.rpy[static_cast<std::size_t>(i)];
    }
    // 这些品牌只给 TCP 位姿，没有关节角；点动/关节区对它们是隐藏的。
    state.hasJoint = false;
    return state;
}

} // namespace

PoseOnlyWorker::PoseOnlyWorker(std::unique_ptr<RobotPose::Reader> reader,
                               QString protocol, Configure configure,
                               bool usePort, QObject* parent)
    : QObject(parent)
    , m_reader(std::move(reader))
    , m_protocol(std::move(protocol))
    , m_configure(std::move(configure))
    , m_usePort(usePort)
{
}

void PoseOnlyWorker::start(const RobotMotion::ConnectOptions& options)
{
    m_reportedReadError = false;
    m_reader->disconnect();
    m_connected = false;

    if (m_configure)
        m_configure(options);

    m_label = m_usePort
        ? QStringLiteral("%1:%2，%3").arg(options.host).arg(options.port).arg(m_protocol)
        : QStringLiteral("%1，%2").arg(options.host).arg(m_protocol);

    const quint16 port = m_usePort ? options.port : 0;
    if (!m_reader->connect(options.host, port)) {
        const QString error = m_reader->lastError();
        emit connectedChanged(false);
        emit statusMessage(QStringLiteral("%1 连接失败：%2").arg(m_label, error), true);
        return;
    }

    m_connected = true;
    emit connectedChanged(true);
    emit statusMessage(QStringLiteral("已连接（%1）").arg(m_label), false);

    if (!m_timer) {
        m_timer = new QTimer(this);
        m_timer->setInterval(kPollMs);
        connect(m_timer, &QTimer::timeout, this, &PoseOnlyWorker::poll);
    }
    m_timer->start();
    poll();
}

void PoseOnlyWorker::shutdown()
{
    if (m_timer)
        m_timer->stop();
    m_reader->disconnect();
    const bool was = m_connected;
    m_connected = false;
    if (was)
        emit connectedChanged(false);
}

void PoseOnlyWorker::poll()
{
    if (!m_connected || !m_reader)
        return;
    RobotPose::Pose pose;
    if (m_reader->readPose(pose) != RobotPose::Status::Ok) {
        // 每 50 ms 报一次会把操作日志刷满；只在"从好变坏"时报一次。
        if (!m_reportedReadError) {
            m_reportedReadError = true;
            emit statusMessage(QStringLiteral("%1 读取位姿失败：%2")
                                   .arg(m_label, m_reader->lastError()), true);
        }
        return;
    }
    m_reportedReadError = false;
    emit poseUpdated(stateFromPose(pose));
}

// ── PoseOnlyMotionBackend ──────────────────────────────────────────────

PoseOnlyMotionBackend::PoseOnlyMotionBackend(Kind kind, QObject* parent)
    : RobotMotionBackend(parent)
    , m_kind(kind)
{
    std::unique_ptr<RobotPose::Reader> reader;
    QString protocol;
    PoseOnlyWorker::Configure configure;
    bool usePort = true;

    switch (kind) {
    case Kind::Modbus: {
        auto modbus = std::make_unique<RobotPose::ModbusTcpReader>();
        RobotPose::ModbusTcpReader* raw = modbus.get();
        configure = [raw](const RobotMotion::ConnectOptions& options) {
            RobotPose::ModbusConfig cfg;
            switch (options.registerFormat) {
            case 1:  cfg.format = RobotPose::RegisterFormat::Int32Scaled; break;
            case 2:  cfg.format = RobotPose::RegisterFormat::Int16Scaled; break;
            default: cfg.format = RobotPose::RegisterFormat::Float32; break;
            }
            cfg.scale = options.scale;
            cfg.unitId = options.unitId;
            cfg.startAddress = options.startAddress;
            cfg.timeoutMs = kReadTimeoutMs;
            raw->setConfig(cfg);
        };
        reader = std::move(modbus);
        protocol = QStringLiteral("Modbus TCP");
        break;
    }
    case Kind::NrcJson: {
        auto nrc = std::make_unique<RobotPose::NrcJsonReader>();
        nrc->setTimeoutMs(kReadTimeoutMs);
        reader = std::move(nrc);
        protocol = QStringLiteral("博纳斯 JSON/TCP");
        break;
    }
    case Kind::Efort:
        // 端口被 SDK 忽略（固定 8100），传 0 即可；地址里的 ":端口" 由
        // EfortReader 自己切掉。
        reader = std::make_unique<EfortPoseReader::EfortReader>();
        protocol = QStringLiteral("埃夫特 EfortSDK");
        usePort = false;
        break;
    }

    m_thread = new QThread(this);
    m_worker = new PoseOnlyWorker(std::move(reader), protocol,
                                  std::move(configure), usePort);
    m_worker->moveToThread(m_thread);

    connect(m_worker, &PoseOnlyWorker::connectedChanged, this,
            [this](bool connected) {
                m_connected = connected;
                emit connectedChanged(connected);
            });
    connect(m_worker, &PoseOnlyWorker::poseUpdated, this,
            [this](const RobotMotion::State& state) {
                m_state = state;
                emit poseUpdated(state);
            });
    connect(m_worker, &PoseOnlyWorker::statusMessage, this,
            &PoseOnlyMotionBackend::statusMessage);
    m_thread->start();
}

PoseOnlyMotionBackend::~PoseOnlyMotionBackend()
{
    if (m_thread && m_thread->isRunning()) {
        QMetaObject::invokeMethod(
            m_worker, [worker = m_worker]() { worker->shutdown(); },
            Qt::BlockingQueuedConnection);
        m_thread->quit();
        m_thread->wait();
    }
}

QString PoseOnlyMotionBackend::name() const
{
    switch (m_kind) {
    case Kind::Modbus:  return QStringLiteral("Modbus TCP");
    case Kind::NrcJson: return QStringLiteral("博纳斯 JSON/TCP");
    case Kind::Efort:   return QStringLiteral("埃夫特");
    }
    return QStringLiteral("只读位姿");
}

void PoseOnlyMotionBackend::connectDevice(const QString& host, quint16 port)
{
    RobotMotion::ConnectOptions options;
    options.host = host;
    options.port = port;
    connectDevice(options);
}

void PoseOnlyMotionBackend::connectDevice(
    const RobotMotion::ConnectOptions& options)
{
    QMetaObject::invokeMethod(
        m_worker, [worker = m_worker, options]() { worker->start(options); },
        Qt::QueuedConnection);
}

void PoseOnlyMotionBackend::disconnectDevice()
{
    QMetaObject::invokeMethod(
        m_worker, [worker = m_worker]() { worker->shutdown(); },
        Qt::QueuedConnection);
}

void PoseOnlyMotionBackend::setEnabled(bool enabled)
{
    Q_UNUSED(enabled);
    // 只读品牌没有运动许可；使能按钮已隐藏，这里不制造额外状态。
}

void PoseOnlyMotionBackend::refuseMotion()
{
    const QString error =
        QStringLiteral("%1 只支持读取位姿，不支持运动控制").arg(name());
    emit statusMessage(error, true);
    emit motionFinished(false, error);
}

void PoseOnlyMotionBackend::moveCartesian(const RobotMotion::Pose&, double,
                                          double, double, int)
{
    refuseMotion();
}

void PoseOnlyMotionBackend::moveJoint(const RobotMotion::Pose&, double, double,
                                      int)
{
    refuseMotion();
}

void PoseOnlyMotionBackend::jogCartesian(int, double, double) { refuseMotion(); }
void PoseOnlyMotionBackend::jogJoint(int, double, double) { refuseMotion(); }
void PoseOnlyMotionBackend::moveJointAxisTo(int, double, double) { refuseMotion(); }
void PoseOnlyMotionBackend::stopMotion() {}
