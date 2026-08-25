#pragma once

#include <QString>
#include <array>

class QTcpSocket;

// Unified robot pose reader interface (stage 8).
//
// Adapters (Modbus TCP first; FANUC/KUKA/UR later) implement readPose() so the
// UI only talks to this interface.  All poses are normalized to millimeters
// and degrees with static XYZ euler angles (R = Rz·Ry·Rx), matching the
// calibration card and the coordinate-transform tool.
//
// The module is fully isolated: nothing in the capture/save/detect pipeline
// depends on it, and the UI wiring defaults to disabled.
namespace RobotPose {

struct Pose {
    std::array<double, 3> xyz{};   // mm
    std::array<double, 3> rpy{};   // degrees, static XYZ
};

enum class Status {
    Ok,
    NotConnected,
    Timeout,
    ProtocolError,
    ConfigError
};

QString statusText(Status s);

class Reader {
public:
    virtual ~Reader() = default;
    virtual bool connect(const QString& host, quint16 port) = 0;
    virtual void disconnect() = 0;
    virtual Status readPose(Pose& out) = 0;
    virtual QString lastError() const = 0;
};

// How the six pose values are packed in Modbus holding registers.
enum class RegisterFormat {
    Float32,      // 2 registers per value, IEEE-754 big-endian
    Int32Scaled,  // 2 registers per value, int32 big-endian * scale
    Int16Scaled   // 1 register per value, int16 big-endian * scale
};

struct ModbusConfig {
    quint16 startAddress = 0;
    RegisterFormat format = RegisterFormat::Float32;
    double scale = 1.0;       // raw * scale -> mm / degrees
    quint8 unitId = 1;
    int timeoutMs = 1000;
};

class ModbusTcpReader : public Reader {
public:
    ModbusTcpReader() = default;
    ~ModbusTcpReader() override;

    bool connect(const QString& host, quint16 port) override;
    void disconnect() override;
    Status readPose(Pose& out) override;
    QString lastError() const override;

    void setConfig(const ModbusConfig& cfg) { m_cfg = cfg; }
    const ModbusConfig& config() const { return m_cfg; }
    bool isConnected() const;

private:
    Status readRegisters(quint16 count, QByteArray& data);
    Status parseRegisters(const QByteArray& data, std::array<double, 6>& out) const;
    int requiredRegisters() const;

    ModbusConfig m_cfg;
    QTcpSocket* m_socket = nullptr;
    quint16 m_transactionId = 0;
    QString m_error;
};

} // namespace RobotPose
