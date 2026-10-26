#include "logic/FairinoPoseReader.h"

#include <QNetworkProxy>
#include <QTcpSocket>

namespace {
constexpr int kFreshnessMs = 1000;
}

FairinoPoseReader::~FairinoPoseReader()
{
    disconnect();
}

bool FairinoPoseReader::connect(const QString& host, quint16 port)
{
    disconnect();
    m_error.clear();
    const quint16 realtimePort = port == 0 ? m_realtimePort : port;

    m_socket = new QTcpSocket;
    // 与其它机器人适配器一致：VM/办公网常被系统代理干扰，原始 TCP 必须直连。
    m_socket->setProxy(QNetworkProxy::NoProxy);
    m_socket->connectToHost(host, realtimePort);
    if (!m_socket->waitForConnected(m_timeoutMs)) {
        m_error = QStringLiteral("连接法奥实时口 %1:%2 失败：%3")
                      .arg(host).arg(realtimePort)
                      .arg(m_socket->errorString());
        disconnect();
        return false;
    }

    // 控制器主动推流；持续读掉，只留最新帧（见头文件里 stage-10 的教训）。
    QObject::connect(m_socket, &QTcpSocket::readyRead, m_socket,
                     [this]() { drain(); });

    QElapsedTimer timer;
    timer.start();
    while (!m_hasState && timer.elapsed() < m_timeoutMs) {
        const int remaining = m_timeoutMs - static_cast<int>(timer.elapsed());
        if (remaining <= 0)
            break;
        if (m_socket->bytesAvailable() <= 0)
            m_socket->waitForReadyRead(remaining);
        drain();
    }
    if (!m_hasState) {
        m_error = QStringLiteral(
                      "已连接法奥实时口 %1:%2，但 %3 ms 内没有收到有效状态包"
                      "（校验失败 %4 帧、丢弃 %5 字节）。请确认控制器固件版本"
                      "与该 20004 状态包格式一致。")
                      .arg(host).arg(realtimePort).arg(m_timeoutMs)
                      .arg(m_parser.rejectedChecksums())
                      .arg(m_parser.skippedBytes());
        disconnect();
        return false;
    }
    return true;
}

void FairinoPoseReader::disconnect()
{
    if (m_socket) {
        QObject::disconnect(m_socket, nullptr, nullptr, nullptr);
        if (m_socket->state() != QAbstractSocket::UnconnectedState)
            m_socket->disconnectFromHost();
        m_socket->deleteLater();
        m_socket = nullptr;
    }
    m_parser.clear();
    m_latest = FairinoRealtime::State{};
    m_hasState = false;
    m_lastFrameAt.invalidate();
}

void FairinoPoseReader::drain()
{
    if (!m_socket)
        return;
    FairinoRealtime::State state;
    const int accepted = m_parser.feed(m_socket->readAll(), &state);
    if (accepted > 0) {
        m_latest = state;
        m_hasState = true;
        m_lastFrameAt.start();
    }
}

RobotPose::Status FairinoPoseReader::currentPose(RobotPose::Pose& out)
{
    if (!m_hasState || !m_lastFrameAt.isValid())
        return RobotPose::Status::Timeout;
    if (m_lastFrameAt.elapsed() > kFreshnessMs)
        return RobotPose::Status::Timeout;
    if (!FairinoRealtime::stateHasFinitePose(m_latest)) {
        m_error = QStringLiteral("法奥实时包里的位姿出现 NaN/Inf，"
                                 "字段偏移或状态包版本可能不一致");
        return RobotPose::Status::ProtocolError;
    }

    std::array<double, 6> raw{};
    for (std::size_t i = 0; i < 6; ++i)
        raw[i] = m_latest.tcp[i];
    const RobotPose::PoseSanity sanity = RobotPose::checkPoseSanity(raw);
    if (sanity != RobotPose::PoseSanity::Ok) {
        m_error = RobotPose::poseSanityText(sanity)
            + QStringLiteral("（法奥 20004 的 tl_cur_pos）");
        return RobotPose::Status::ProtocolError;
    }

    for (int i = 0; i < 3; ++i) {
        out.xyz[static_cast<std::size_t>(i)] = m_latest.tcp[static_cast<std::size_t>(i)];
        out.rpy[static_cast<std::size_t>(i)] = m_latest.tcp[static_cast<std::size_t>(i + 3)];
    }
    return RobotPose::Status::Ok;
}

RobotPose::Status FairinoPoseReader::readPose(RobotPose::Pose& out)
{
    m_error.clear();
    if (!m_socket || m_socket->state() != QAbstractSocket::ConnectedState) {
        m_error = QStringLiteral("法奥实时口未连接");
        return RobotPose::Status::NotConnected;
    }

    drain();
    if (m_hasState && m_lastFrameAt.isValid()
        && m_lastFrameAt.elapsed() <= kFreshnessMs) {
        return currentPose(out);
    }

    QElapsedTimer timer;
    timer.start();
    while (timer.elapsed() < m_timeoutMs) {
        if (m_socket->state() != QAbstractSocket::ConnectedState) {
            m_error = QStringLiteral("法奥实时口连接已断开");
            return RobotPose::Status::NotConnected;
        }
        if (m_socket->bytesAvailable() <= 0) {
            const int remaining = m_timeoutMs - static_cast<int>(timer.elapsed());
            if (remaining <= 0)
                break;
            if (!m_socket->waitForReadyRead(remaining))
                break;
        }
        drain();
        if (m_hasState && m_lastFrameAt.isValid()
            && m_lastFrameAt.elapsed() <= kFreshnessMs) {
            return currentPose(out);
        }
    }

    m_error = QStringLiteral(
                  "法奥实时口 %1 ms 内没有新的有效位姿（累计 %2 帧、"
                  "校验失败 %3 帧）。请检查控制器是否在推 20004 状态包。")
                  .arg(m_timeoutMs)
                  .arg(m_parser.acceptedFrames())
                  .arg(m_parser.rejectedChecksums());
    return RobotPose::Status::Timeout;
}

QString FairinoPoseReader::lastError() const
{
    return m_error;
}
