#pragma once

#include "logic/RobotPose.h"

#include <QString>
#include <array>

// 埃夫特（EFORT）机器人通信适配器（用户反馈 7）。
//
// 厂商 SDK 是 third_party/EfortSDK（EftSdk.lib / EftSdk.dll + EfortSdk.h）。
// 与 Modbus / UR / 博纳斯三条链路一样，本文件只实现 RobotPose::Reader，
// 由 MainWindow 负责连接、断开与读位姿的编排；不碰采集/保存/检测管线。
//
// 本头文件**故意不包含 SDK 头**：EfortSdk.h 里是 `using namespace std;` +
// `__declspec(dllexport)` 的全局声明，包含进来会污染每个包含它的编译单元。
// SDK 的 include 只出现在 EfortPoseReader.cpp 里，所以 normalizePose()
// 这个纯函数可以在没有 SDK 的编译单元里被单测直接调用。
namespace EfortPoseReader {

// SDK 读到的 6 个原始值 → 项目约定（位置 mm、姿态度、静态 XYZ，R = Rz*Ry*Rx）。
// rawIsMillimeter / rawIsDegree 说明原始单位；输出永远归一化成 mm + 度。
// 任一坐标非有限值 → 返回 false 且不改 out。
bool normalizePose(const double raw[6], bool rawIsMillimeter, bool rawIsDegree,
                   RobotPose::Pose& out);

// SDK 返回码 → RobotPose::Status（纯函数，单测可直接断言）。
RobotPose::Status statusFromSdkCode(int code);

// SDK 返回码 → 可读中文（用于 lastError / 侧栏提示）。
QString sdkErrorText(int code);

// ---------------------------------------------------------------- 地址与端口
//
// 埃夫特这条链路的端口**不是我们能填的**：SDK 的 ConnectRobot 只收一个地址串，
// 端口在库里写死 —— rlibcpp-bcc.dll 的 TcpIpConnection 构造时 serverPort = 8100
// (0x1FA4)，EftSdk.dll 从不改它（连 setServerPort 都不导入），实际连接用的就是
// 这一个端口；发现设备走的是同一段 8100 扫描。厂商手册把 8000/8100 这段标为
// 「示教器 / SDK 内部使用，禁止占用」，与这里一致。
//
// 客户报的 8003 在 EftSdk.dll / rlibcpp-bcc.dll 里**根本不存在**（全库没有
// 0x1F43 这个立即数），也不在厂商的保留端口表里 —— 那是客户自己在示教器上开的
// 用户 socket（埃夫特允许自配 5 个 client / 3 个 server socket），不用于这条链路。
//
// 所以：用户把「IP:端口」整串粘进来时，必须把端口部分切掉只留 IP。原因是
// SDK 的地址解析 str2IpAddr 遇到非数字非 '.' 的字符不会报错 ——
// "192.168.0.1:8003" 会被它悄悄拼成 192.171.44.131（实测），连的是另一个地址，
// 现场只会看到"连不上"，没有第二种线索。
struct AddressSplit {
    QString ip;          // 去掉 ":端口" 和首尾空白之后的部分
    QString portSuffix;  // 冒号后面的原文（没有冒号时为空）
};

// 拆分 "192.168.0.1:8003" → { "192.168.0.1", "8003" }；没有冒号时 ip = 原文、
// portSuffix 为空；都做首尾 trim。只按**第一个**冒号切（IPv6 不适用，SDK 也只认
// 十进制点分 IPv4）。（纯函数，单测直接断言。）
AddressSplit splitAddress(const QString& raw);

// SDK 每次调用前都要读**当前工作目录**下的 log4cpp.conf（EftLogger 里
// _mkdir("log") + log4cpp::PropertyConfigurator::configure("log4cpp.conf")，
// 用的是找不到文件就抛的那一个重载）。EfortReader 在调用前会把 CWD 切到
// applicationDirPath()，所以"exe 旁边有没有这个文件"就等于"SDK 能不能找到"。
// 绿色包漏带它时，SDK 会在**任何 socket 之前**抛 "File log4cpp.conf does not
// exist"，把真正的原因（部署不完整）伪装成"连接失败"。自己先判一次。
bool logConfigPresent(const QString& dir);

// 缺文件时要给现场看的中文（带上期望路径），单独成函数便于单测断言。
QString logConfigMissingText(const QString& dir);

class EfortReader : public RobotPose::Reader {
public:
    EfortReader() = default;
    ~EfortReader() override;

    // `port` 对本协议**无意义，一律忽略**（原因见上面 splitAddress 的注释：
    // 端口在 SDK 里写死 8100）。`host` 里若带了 ":端口" 会被切掉，只把 IP
    // 交给 SDK —— 不切的话 SDK 会把它解析成另一个 IP。
    bool connect(const QString& host, quint16 port) override;
    void disconnect() override;
    RobotPose::Status readPose(RobotPose::Pose& out) override;
    QString lastError() const override;

    bool isConnected() const { return m_connected; }
    // 最近一次连接拿到的 devId（SDK 的多机器人句柄）。
    unsigned int deviceId() const { return m_devId; }

private:
    bool m_connected = false;
    unsigned int m_devId = 0;
    QString m_error;
};

} // namespace EfortPoseReader
