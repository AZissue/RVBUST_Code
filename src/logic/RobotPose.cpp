#include "logic/RobotPose.h"

#include <QTcpSocket>
#include <QDataStream>
#include <QThread>
#include <cstring>

namespace RobotPose {

QString statusText(Status s)
{
    switch (s) {
    case Status::Ok:            return QStringLiteral("成功");
    case Status::NotConnected:  return QStringLiteral("未连接");
    case Status::Timeout:       return QStringLiteral("读取超时");
    case Status::ProtocolError: return QStringLiteral("协议错误");
    case Status::ConfigError:   return QStringLiteral("配置错误");
    }
    return {};
}

namespace {

quint16 be16(const QByteArray& d, int off)
{
    return (static_cast<quint16>(static_cast<unsigned char>(d[off])) << 8)
         | static_cast<quint16>(static_cast<unsigned char>(d[off + 1]));
}

quint32 be32(const QByteArray& d, int off)
{
    return (static_cast<quint32>(static_cast<unsigned char>(d[off])) << 24)
         | (static_cast<quint32>(static_cast<unsigned char>(d[off + 1])) << 16)
         | (static_cast<quint32>(static_cast<unsigned char>(d[off + 2])) << 8)
         | static_cast<quint32>(static_cast<unsigned char>(d[off + 3]));
}

float beFloat32(const QByteArray& d, int off)
{
    const quint32 raw = be32(d, off);
    float f = 0.0f;
    std::memcpy(&f, &raw, sizeof(f));
    return f;
}

} // namespace

ModbusTcpReader::~ModbusTcpReader()
{
    disconnect();
}

bool ModbusTcpReader::connect(const QString& host, quint16 port)
{
    disconnect();
    m_socket = new QTcpSocket;
    m_socket->connectToHost(host, port);
    if (!m_socket->waitForConnected(m_cfg.timeoutMs)) {
        m_error = QStringLiteral("连接 %1:%2 失败: %3")
                      .arg(host).arg(port).arg(m_socket->errorString());
        disconnect();
        return false;
    }
    m_error.clear();
    return true;
}

void ModbusTcpReader::disconnect()
{
    if (m_socket) {
        if (m_socket->state() != QAbstractSocket::UnconnectedState)
            m_socket->disconnectFromHost();
        m_socket->deleteLater();
        m_socket = nullptr;
    }
}

bool ModbusTcpReader::isConnected() const
{
    return m_socket
        && m_socket->state() == QAbstractSocket::ConnectedState;
}

int ModbusTcpReader::requiredRegisters() const
{
    return m_cfg.format == RegisterFormat::Int16Scaled ? 6 : 12;
}

Status ModbusTcpReader::readRegisters(quint16 count, QByteArray& data)
{
    if (!isConnected())
        return Status::NotConnected;

    QByteArray req;
    const quint16 tid = ++m_transactionId;
    auto put16 = [&req](quint16 v) {
        req.push_back(static_cast<char>((v >> 8) & 0xFF));
        req.push_back(static_cast<char>(v & 0xFF));
    };
    put16(tid);                 // transaction id
    put16(0);                   // protocol id
    put16(6);                   // length: unit + function + addr + qty
    req.push_back(static_cast<char>(m_cfg.unitId));
    req.push_back(0x03);        // read holding registers
    put16(m_cfg.startAddress);
    put16(count);

    if (m_socket->write(req) != req.size())
        return Status::ProtocolError;
    m_socket->flush();

    const int expected = 9 + static_cast<int>(count) * 2;
    while (data.size() < expected) {
        if (!m_socket->waitForReadyRead(m_cfg.timeoutMs)) {
            m_error = QStringLiteral("等待响应超时");
            return Status::Timeout;
        }
        data += m_socket->readAll();
    }
    if (data.size() < 9)
        return Status::ProtocolError;

    const quint8 func = static_cast<quint8>(data[7]);
    if (func == 0x83) {          // exception response
        m_error = QStringLiteral("Modbus 异常码 %1")
                      .arg(static_cast<int>(static_cast<quint8>(data[8])));
        return Status::ProtocolError;
    }
    if (func != 0x03)
        return Status::ProtocolError;
    const int byteCount = static_cast<unsigned char>(data[8]);
    if (byteCount != static_cast<int>(count) * 2)
        return Status::ProtocolError;
    return Status::Ok;
}

Status ModbusTcpReader::parseRegisters(const QByteArray& data,
                                       std::array<double, 6>& out) const
{
    if (m_cfg.format == RegisterFormat::Int16Scaled) {
        for (int i = 0; i < 6; ++i)
            out[static_cast<std::size_t>(i)] =
                static_cast<qint16>(be16(data, 9 + i * 2)) * m_cfg.scale;
    } else if (m_cfg.format == RegisterFormat::Int32Scaled) {
        for (int i = 0; i < 6; ++i)
            out[static_cast<std::size_t>(i)] =
                static_cast<qint32>(be32(data, 9 + i * 4)) * m_cfg.scale;
    } else {
        for (int i = 0; i < 6; ++i)
            out[static_cast<std::size_t>(i)] =
                static_cast<double>(beFloat32(data, 9 + i * 4));
    }
    return Status::Ok;
}

Status ModbusTcpReader::readPose(Pose& out)
{
    QByteArray data;
    const Status s = readRegisters(static_cast<quint16>(requiredRegisters()), data);
    if (s != Status::Ok)
        return s;
    std::array<double, 6> vals{};
    const Status p = parseRegisters(data, vals);
    if (p != Status::Ok)
        return p;
    out.xyz = { vals[0], vals[1], vals[2] };
    out.rpy = { vals[3], vals[4], vals[5] };
    m_error.clear();
    return Status::Ok;
}

QString ModbusTcpReader::lastError() const
{
    return m_error;
}

} // namespace RobotPose
