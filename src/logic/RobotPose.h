#pragma once

#include <QString>
#include <array>
#include <cmath>

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
    // Modbus adapters: degrees, static XYZ euler angles (R = Rz*Ry*Rx).
    // UR Realtime adapter (URRealtimeReader): UR reports actual_tcp_pose as a
    // rotation VECTOR (axis-angle, radians), not a static-XYZ euler angle.
    // We do NOT convert it to degrees/euler here (units would be wrong if we
    // just relabeled radians as degrees). Callers reading from the UR adapter
    // must treat rpy as (rx, ry, rz) axis-angle in radians and label it as
    // such in the UI/log; do not feed it into eyeToHand/eyeInHand transforms
    // that assume static-XYZ degrees without an explicit conversion.
    std::array<double, 3> rpy{};   // degrees, static XYZ (Modbus) OR axis-angle radians (UR)
};

enum class Status {
    Ok,
    NotConnected,
    Timeout,
    ProtocolError,
    ConfigError
};

QString statusText(Status s);

// ── 位姿分量健全性（第 13 回合）───────────────────────────────────────
//
// "六个分量全是 0" 与 "出现 NaN/Inf" 都不是一个真实位姿，而是"没读到 / 读错
// 位置"的形状。UR 读取侧早就按 fail-closed 拒绝全 0（那是现场一次 (0,0,0,0,0,0)
// 静默写进卡片换来的），但这条规则当时只写在那一处：Modbus / 博纳斯(NRC) /
// 埃夫特三个 reader 会把同样的东西当成 Ok 返回，静默变成一个偏掉的标定结果 ——
// 也就是说 UR 那类"成功但错"的问题一直在其他机器人上。判据放这里一处，共用。
enum class PoseSanity {
    Ok,
    NotFinite,   // 有 NaN / Inf
    AllZero      // 六个分量全是 0
};

inline PoseSanity checkPoseSanity(const std::array<double, 6>& v)
{
    for (double d : v) {
        if (!std::isfinite(d))
            return PoseSanity::NotFinite;
    }
    for (double d : v) {
        if (d != 0.0)
            return PoseSanity::Ok;
    }
    return PoseSanity::AllZero;
}

// 中文原因。协议专属的排查提示（探测脚本名、寄存器地址…）由调用方接在后面。
inline QString poseSanityText(PoseSanity s)
{
    switch (s) {
    case PoseSanity::NotFinite:
        return QStringLiteral("读到的位姿出现非有限值(NaN/Inf)，字段偏移或单位可能错位");
    case PoseSanity::AllZero:
        return QStringLiteral("读到的位姿六个分量全为 0，不是真实位姿（很可能是地址/字段错位）");
    case PoseSanity::Ok:
        break;
    }
    return QString();
}

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
