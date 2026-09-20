#include "logic/EfortPoseReader.h"

// SDK 头只在本编译单元里出现（见头文件顶部注释）。
// EfortSdk.h 里对 _MSC_VER 无条件 `__declspec(dllexport)`，链接到厂商的
// EftSdk.lib 导入库即可；它同时 `using namespace std;`，因此 Qt 头放在后面。
#include "EfortSdk.h"

#include <QCoreApplication>
#include <QDir>

#include <cmath>
#include <exception>

namespace EfortPoseReader {

namespace {

constexpr double kDegPerRad = 180.0 / 3.14159265358979323846;

// EftSdk.dll 是按**当前工作目录**去找 log4cpp.conf 的（真机实测：run.bat 从
// 仓库根启动 → CWD = 仓库根 → 报 "File log4cpp.conf does not exist"；010 已经
// 把配置部署到 exe 旁边，但对不上 CWD 时仍然找不到）。所以在调用 SDK 之前把
// CWD 临时切到 exe 目录，离开作用域立刻还原。
//
// RAII：还原写在析构里，所以正常返回、提前 return、以及 SDK 抛异常展开栈时
// 都会还原（析构发生在 catch 之前）。只影响埃夫特这条链路，程序别处不改 CWD。
class ScopedWorkingDir {
public:
    ScopedWorkingDir()
        : m_previous(QDir::currentPath())
    {
        const QString exeDir = QCoreApplication::applicationDirPath();
        if (!exeDir.isEmpty() && exeDir != m_previous)
            QDir::setCurrent(exeDir);
    }

    ~ScopedWorkingDir()
    {
        // 还原到进入前的原值；setCurrent 不抛异常，析构因此是 noexcept 的。
        if (m_previous.isEmpty() || QDir::currentPath() == m_previous)
            return;
        QDir::setCurrent(m_previous);
    }

    ScopedWorkingDir(const ScopedWorkingDir&) = delete;
    ScopedWorkingDir& operator=(const ScopedWorkingDir&) = delete;

private:
    QString m_previous;
};

// 只能在 catch 块里调用：把当前异常翻成一句可读中文。
// SDK（EftSdk.dll）会在内部抛 C++ 异常（实测 SEH 0xE06D7363 从 KERNELBASE 抛出），
// 一旦让它穿出 Qt 槽，Qt5 就直接终止进程——所以下面每个 SDK 调用点都带 try/catch。
QString exceptionText()
{
    try {
        throw;
    } catch (const std::exception& e) {
        // what() 是窄字符串，Windows 上按系统 ANSI 代码页解（中文异常文本多为 GBK）。
        return QString::fromLocal8Bit(e.what());
    } catch (...) {
        return QStringLiteral("非 std::exception 的未知异常");
    }
}

} // namespace

bool normalizePose(const double raw[6], bool rawIsMillimeter, bool rawIsDegree,
                   RobotPose::Pose& out)
{
    if (raw == nullptr)
        return false;
    for (int i = 0; i < 6; ++i) {
        if (!std::isfinite(raw[i]))
            return false;
    }

    const double lengthScale = rawIsMillimeter ? 1.0 : 1000.0;
    const double angleScale = rawIsDegree ? 1.0 : kDegPerRad;

    RobotPose::Pose pose;
    for (int i = 0; i < 3; ++i) {
        const double mm = raw[i] * lengthScale;
        if (!std::isfinite(mm))
            return false;
        pose.xyz[static_cast<std::size_t>(i)] = mm;
    }
    for (int i = 0; i < 3; ++i) {
        const double deg = raw[3 + i] * angleScale;
        if (!std::isfinite(deg))
            return false;
        pose.rpy[static_cast<std::size_t>(i)] = deg;
    }

    // 转换全部成功后才写 out（失败路径不改 out）。
    out = pose;
    return true;
}

RobotPose::Status statusFromSdkCode(int code)
{
    switch (code) {
    case ERROR_OK:
        return RobotPose::Status::Ok;
    case ERROR_CONNECT_FAILED:
    case ERROR_NO_CONNECTION:
    case ERROR_CONNECTION_BROKEN:
        return RobotPose::Status::NotConnected;
    case ERROR_THIRD_OPERATION_TIME_OUT:
        return RobotPose::Status::Timeout;
    case ERROR_ACCESS_REJECTED:
    case ERROR_PARA_INVALID:
    case ERROR_DEVICE_NOT_EXIST:
    case ERROR_DEVICE_EXIT:
        return RobotPose::Status::ConfigError;
    default:
        return RobotPose::Status::ProtocolError;
    }
}

QString sdkErrorText(int code)
{
    if (code == ERROR_OK)
        return QStringLiteral("成功");
    const QString mapped = RobotPose::statusText(statusFromSdkCode(code));
    return QStringLiteral("%1（SDK 返回码 %2）").arg(mapped).arg(code);
}

EfortReader::~EfortReader()
{
    disconnect();
}

bool EfortReader::connect(const QString& host, quint16 port)
{
    disconnect();
    m_error.clear();

    const QString trimmed = host.trimmed();
    if (trimmed.isEmpty()) {
        m_error = QStringLiteral("埃夫特：IP 地址不能为空");
        return false;
    }

    QString address = trimmed;
    if (!address.contains(QLatin1Char(':')) && port != 0)
        address += QLatin1Char(':') + QString::number(port);

    unsigned int devId = 0;
    int ret = ERROR_OK;
    QString thrown;
    try {
        const std::string addr = address.toStdString();
        const ScopedWorkingDir cwdGuard;   // SDK 找 log4cpp.conf 靠 CWD
        ret = RobotAPI::ConnectRobot(addr, devId);
    } catch (const std::exception&) {
        thrown = exceptionText();
    } catch (...) {
        thrown = exceptionText();
    }
    if (!thrown.isEmpty()) {
        m_devId = 0;
        m_connected = false;
        m_error = QStringLiteral("埃夫特：连接 %1 失败（SDK 抛出异常：%2）")
                      .arg(address, thrown);
        return false;
    }

    if (ret != ERROR_OK) {
        m_devId = 0;
        m_connected = false;
        m_error = QStringLiteral("埃夫特连接失败：%1（地址 %2）")
                      .arg(sdkErrorText(ret), address);
        return false;
    }

    m_devId = devId;
    m_connected = true;
    return true;
}

void EfortReader::disconnect()
{
    if (m_connected) {
        unsigned int devId = m_devId;
        // 析构路径上：异常一律吞掉并记账，绝不外抛、绝不 terminate。
        try {
            const ScopedWorkingDir cwdGuard;   // SDK 找 log4cpp.conf 靠 CWD
            RobotAPI::DisconnectRobot(devId);
        } catch (const std::exception&) {
            m_error = QStringLiteral("埃夫特断开时 SDK 抛出异常：%1")
                          .arg(exceptionText());
        } catch (...) {
            m_error = QStringLiteral("埃夫特断开时 SDK 抛出异常：%1")
                          .arg(exceptionText());
        }
    }
    m_connected = false;
    m_devId = 0;
}

RobotPose::Status EfortReader::readPose(RobotPose::Pose& out)
{
    if (!m_connected) {
        m_error = QStringLiteral("埃夫特：尚未连接机器人");
        return RobotPose::Status::NotConnected;
    }

    // 基坐标下的 TCP 位姿（不带 CFG 参数）。
    RobotAPI::RobotPos pos;
    int ret = ERROR_OK;
    QString thrown;
    try {
        const ScopedWorkingDir cwdGuard;   // SDK 找 log4cpp.conf 靠 CWD
        ret = RobotAPI::GetBaseCoordinatePos(pos, m_devId);
    } catch (const std::exception&) {
        thrown = exceptionText();
    } catch (...) {
        thrown = exceptionText();
    }
    if (!thrown.isEmpty()) {
        m_error = QStringLiteral("埃夫特读取位姿失败（SDK 抛出异常：%1）").arg(thrown);
        return RobotPose::Status::ProtocolError;
    }

    if (ret != ERROR_OK) {
        m_error = QStringLiteral("埃夫特读取位姿失败：%1").arg(sdkErrorText(ret));
        return statusFromSdkCode(ret);
    }

    const double raw[6] = { pos.x, pos.y, pos.z, pos.a, pos.b, pos.c };
    // 单位按 SDK 结构体字段的通常约定当作 mm / 度传入；真实单位未经真机确认，
    // 见 EfortPoseReader.h 与 008 交回说明里的「欧拉角约定」一节。
    if (!normalizePose(raw, true, true, out)) {
        m_error = QStringLiteral(
                      "埃夫特位姿含非有限值（x %1 y %2 z %3 a %4 b %5 c %6）")
                      .arg(pos.x).arg(pos.y).arg(pos.z)
                      .arg(pos.a).arg(pos.b).arg(pos.c);
        return RobotPose::Status::ProtocolError;
    }

    m_error.clear();
    return RobotPose::Status::Ok;
}

QString EfortReader::lastError() const
{
    return m_error;
}

} // namespace EfortPoseReader
