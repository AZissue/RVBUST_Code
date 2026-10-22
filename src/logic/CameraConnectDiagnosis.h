#pragma once

// ── 相机连接失败诊断（3.0 E-05） ──
//
// 现场只看到一句「相机连接失败」时，排查方向会被带偏：驱动没装、网段不对、
// 上一次没释放干净，三种原因的处理动作完全不同。这里把连接过程中**实际观察
// 到的事实**（SDK 是否初始化、有没有枚举到设备、GigE 网络状态、原始错误文本）
// 变成三样东西：
//
//   * Cause    —— 原因分类（驱动/SDK、没枚举到、掉线、占用、网段、IP 冲突…）
//   * headline —— 一句短标题，给 toast / 状态栏；
//   * advice   —— 可执行的处理顺序，给左侧提示与日志。
//
// 全部是纯函数：不认识 RVC 类型，也不碰界面，便于单测。RVC 状态码到
// NetworkStatus 的映射留在 CameraManager（那里才 include RVC）。
//
// 判据来源：
//   * RVC::NetworkDeviceStatus_ 的四个值（见 third_party/RVC/include/RVC/RVC.h）；
//   * 3.3 已有的文本关键字规则（CameraRelease::classify），这里只做转发，
//     避免和重试策略出现两套互相矛盾的说法。

#include <QHostAddress>
#include <QString>
#include <QStringList>

#include "logic/CameraRelease.h"

namespace CameraConnect {

// 与 RVC::NetworkDeviceStatus_ 的**文档顺序**一一对应：
// OK / Not_Reachable / In_Use / Conflict。不直接使用 RVC 枚举，是为了让这个
// 头也能在不链接相机 SDK 的单测里编译。
enum class NetworkStatus {
    Unknown = -1,
    Ok = 0,
    NotReachable = 1,
    InUse = 2,
    Conflict = 3,
};

enum class Cause {
    SdkInitFailed,      // RVC::SystemInit 返回 false / 抛异常
    NoDevice,           // 枚举到 0 个设备（供电、线缆、网段、驱动）
    EnumFailed,         // 枚举调用本身报错
    DeviceGone,         // 列表里还有，连接时已经找不到（掉线/被抢走）
    DeviceInfoFailed,   // 能枚举到，但 GetDeviceInfo 失败
    Unsupported,        // 设备不支持 X1/X2 接口
    DeviceBusy,         // GigE In_Use / 文本表明被占用
    NetworkUnreachable, // GigE Not_Reachable —— 网段/IP 问题
    IpConflict,         // GigE Conflict
    OpenFailed,         // Open 失败，且没有更具体的硬证据
    Unknown,            // 什么都不知道
};

// 连接过程中观察到的事实。默认值 = 「一切正常，只是 Open 失败」。
struct Evidence {
    bool sdkReady = true;        // RVC::SystemInit 成功
    bool enumerationOk = true;   // SystemListDevices 没报错
    bool enumeratedAny = true;   // 至少枚举到一个设备
    bool deviceFound = true;     // 指定序列号能解析到设备
    bool deviceInfoOk = true;    // GetDeviceInfo 成功
    bool supportsX1X2 = true;    // DeviceInfo 报告支持 X1 或 X2
    NetworkStatus network = NetworkStatus::Unknown;
    QString cameraIp;            // GetNetworkConfig 读到的相机 IP（GigE）
    QString cameraMask;
    QString errorText;           // SDK/异常原文
    QStringList hostSubnets;     // "以太网=192.168.0.10/255.255.255.0"
};

// 原因判定顺序 = 排查顺序：越早的事实越硬。
inline Cause diagnose(const Evidence& e)
{
    if (!e.sdkReady)
        return Cause::SdkInitFailed;
    if (!e.enumerationOk)
        return Cause::EnumFailed;
    if (!e.enumeratedAny)
        return Cause::NoDevice;
    if (!e.deviceFound)
        return Cause::DeviceGone;
    if (!e.deviceInfoOk)
        return Cause::DeviceInfoFailed;
    if (!e.supportsX1X2)
        return Cause::Unsupported;

    switch (e.network) {
    case NetworkStatus::InUse:        return Cause::DeviceBusy;
    case NetworkStatus::NotReachable: return Cause::NetworkUnreachable;
    case NetworkStatus::Conflict:     return Cause::IpConflict;
    default: break;
    }

    // 没有硬证据时退回 SDK 原始文本（沿用 3.3 的关键字规则）。
    switch (CameraRelease::classify(e.errorText, /*deviceFound=*/true,
                                    /*deviceInUse=*/false)) {
    case CameraRelease::ConnectFailure::DeviceBusy:  return Cause::DeviceBusy;
    case CameraRelease::ConnectFailure::Unsupported: return Cause::Unsupported;
    case CameraRelease::ConnectFailure::SdkError:    return Cause::OpenFailed;
    default:                                         return Cause::Unknown;
    }
}

// 重试能否帮上忙：占用和一般性 Open 失败值得等 1+2+3 秒；网段/IP/掉线/驱动
// 这类问题等 3 秒不会自己好，重试只会推迟操作员该看到的那条提示。
inline bool retryCanHelp(Cause c)
{
    // 委托给 3.3 的 shouldRetry：重试策略只能有一份，否则两处迟早会给出
    // 互相矛盾的说法（比如这里说该等、日志里的规则说不该等）。
    switch (c) {
    case Cause::DeviceBusy:
        return CameraRelease::shouldRetry(CameraRelease::ConnectFailure::DeviceBusy);
    case Cause::OpenFailed:
        return CameraRelease::shouldRetry(CameraRelease::ConnectFailure::SdkError);
    case Cause::Unknown:
        return CameraRelease::shouldRetry(CameraRelease::ConnectFailure::Unknown);
    default:
        return false;
    }
}

// 一句短标题（toast / 状态栏）。每个 Cause 都必须有，测试会逐条检查。
inline QString headline(Cause c)
{
    switch (c) {
    case Cause::SdkInitFailed:      return QStringLiteral("相机 SDK 未就绪");
    case Cause::NoDevice:           return QStringLiteral("未找到相机");
    case Cause::EnumFailed:         return QStringLiteral("相机枚举失败");
    case Cause::DeviceGone:         return QStringLiteral("相机已掉线");
    case Cause::DeviceInfoFailed:   return QStringLiteral("读取相机信息失败");
    case Cause::Unsupported:        return QStringLiteral("相机型号不支持");
    case Cause::DeviceBusy:         return QStringLiteral("相机被占用");
    case Cause::NetworkUnreachable: return QStringLiteral("相机网络不可达");
    case Cause::IpConflict:         return QStringLiteral("相机 IP 冲突");
    case Cause::OpenFailed:         return QStringLiteral("相机打开失败");
    default:                        return QStringLiteral("相机连接失败");
    }
}

// ── 网段判断（纯字符串，可在单测里喂任意数据） ──

// "255.255.255.0" 与 "24" 两种写法都接受；无效掩码返回 false。
inline quint32 ipv4MaskValue(const QString& text, bool* ok = nullptr)
{
    const QString t = text.trimmed();
    bool numOk = false;
    const int prefix = t.toInt(&numOk);
    if (numOk) {
        const bool valid = prefix >= 0 && prefix <= 32;
        if (ok) *ok = valid;
        if (!valid) return 0;
        return prefix == 0 ? 0u : (0xFFFFFFFFu << (32 - prefix));
    }

    bool ipOk = false;
    const quint32 v = QHostAddress(t).toIPv4Address(&ipOk);
    // 0.0.0.0 不是可用掩码（QHostAddress 会把它解析成 0）。
    if (ok) *ok = ipOk && v != 0;
    return v;
}

// 主机网卡里是否存在与相机同一网段的地址。
// hostSubnets 的每一项形如 "以太网=192.168.0.10/255.255.255.0"（名字可省略、
// 等号可省略）；无法解析的项跳过，不做任何猜测。
inline bool anyHostOnSubnet(const QString& cameraIp, const QString& cameraMask,
                            const QStringList& hostSubnets)
{
    bool ipOk = false;
    const quint32 cam = QHostAddress(cameraIp.trimmed()).toIPv4Address(&ipOk);
    if (!ipOk) return false;

    bool maskOk = false;
    const quint32 camMask = ipv4MaskValue(cameraMask, &maskOk);
    if (!maskOk) return false;

    for (const QString& entry : hostSubnets) {
        const int eq = entry.indexOf(QLatin1Char('='));
        const QString body = (eq >= 0 ? entry.mid(eq + 1) : entry).trimmed();
        const int slash = body.lastIndexOf(QLatin1Char('/'));
        if (slash <= 0) continue;

        bool hostIpOk = false;
        const quint32 hostIp =
            QHostAddress(body.left(slash).trimmed()).toIPv4Address(&hostIpOk);
        if (!hostIpOk) continue;

        bool hostMaskOk = false;
        ipv4MaskValue(body.mid(slash + 1), &hostMaskOk);
        if (!hostMaskOk) continue;

        if ((cam & camMask) == (hostIp & camMask))
            return true;
    }
    return false;
}

inline QString hostSubnetText(const QStringList& hostSubnets)
{
    return hostSubnets.isEmpty()
        ? QStringLiteral("（本机没有可用的 IPv4 网卡）")
        : hostSubnets.join(QStringLiteral("、"));
}

// 完整建议（左侧提示 / 日志）。`retriesTried` 是已经跑过的重试次数，占用的
// 文案会把它写进去，免得提示与实际发生的事对不上。
inline QString advice(const Evidence& e, Cause c, int retriesTried)
{
    switch (c) {
    case Cause::SdkInitFailed:
        return QStringLiteral(
                   "相机 SDK（RVC）初始化失败，程序还没走到查找设备这一步——"
                   "通常不是相机本身的问题。\n"
                   "按顺序检查：① 确认是从完整发布包解压运行（RVC 运行时 DLL "
                   "必须和 exe 在同一目录）；② 重新安装相机驱动 / RVC SDK 后重启"
                   "程序；③ 重启电脑再试。\n"
                   "原始信息：%1")
            .arg(e.errorText.isEmpty() ? QStringLiteral("（无）") : e.errorText);

    case Cause::NoDevice:
        return QStringLiteral(
                   "没有枚举到任何相机。按顺序检查：\n"
                   "① 相机电源（指示灯）与网线/USB 是否插紧；\n"
                   "② 本机网卡是否与相机同网段（本机网卡：%1）；\n"
                   "③ 设备管理器里能否看到相机——看不到通常是驱动没装；\n"
                   "④ 相机是否被其它程序占用（同一台相机只能被一个进程打开）。\n"
                   "网段不一致是 GigE 相机最常见的连不上原因：先用机身标签或 "
                   "RVCManager 核对相机 IP；确认后可在 RVCManager 里用「一键配置」"
                   "把相机配到本机网段，拍摄参数也在那里调试。")
            .arg(hostSubnetText(e.hostSubnets));

    case Cause::EnumFailed:
        return QStringLiteral(
                   "枚举相机时 SDK 报错：%1。\n"
                   "建议重新插拔网线/USB、重启相机电源；仍失败请重启程序或电脑。")
            .arg(e.errorText.isEmpty() ? QStringLiteral("（无）") : e.errorText);

    case Cause::DeviceGone:
        return QStringLiteral(
                   "设备列表里还有它，但连接时已经找不到：可能刚被拔掉、断电，"
                   "或被其它程序抢先连走。请重新插拔后，在设备列表点「刷新」"
                   "再试。");

    case Cause::DeviceInfoFailed:
        return QStringLiteral(
                   "能枚举到设备，但读取设备信息失败（SDK 返回错误）。\n"
                   "请重新插拔后重试；反复出现请把运行日志发给支持。");

    case Cause::Unsupported:
        return QStringLiteral(
                   "该设备不支持 X1/X2 接口，本程序无法用它采集数据。"
                   "请确认相机型号属于 RVC X1/X2 系列。");

    case Cause::DeviceBusy:
        return CameraRelease::operatorHint(
            CameraRelease::ConnectFailure::DeviceBusy, retriesTried, e.errorText);

    case Cause::NetworkUnreachable: {
        QString msg = QStringLiteral(
            "相机在总线上，但网络不可达（RVC 状态 Not_Reachable）——"
            "这是网段/IP 问题，不是相机电源问题。\n");
        if (e.cameraIp.isEmpty()) {
            msg += QStringLiteral("没能读到相机 IP；本机网卡：%1。\n"
                                  "先用 RVCManager 或机身标签核对相机 IP，再看网卡"
                                  "是否在同一网段。")
                       .arg(hostSubnetText(e.hostSubnets));
        } else {
            msg += QStringLiteral("相机 IP：%1/%2；本机网卡：%3。\n")
                       .arg(e.cameraIp,
                            e.cameraMask.isEmpty() ? QStringLiteral("?")
                                                   : e.cameraMask,
                            hostSubnetText(e.hostSubnets));
            if (anyHostOnSubnet(e.cameraIp, e.cameraMask, e.hostSubnets))
                msg += QStringLiteral(
                    "网卡与相机已在同一网段仍不可达：检查网线/交换机端口、相机 IP "
                    "是否与其它设备冲突，以及防火墙是否拦截了 GigE 发现。");
            else
                msg += QStringLiteral(
                    "当前 RVC 相机与网卡不在同一网段：可以在 RVCManager（RVC "
                    "厂商工具）里用「一键配置」把相机配到本机网段，拍摄参数也在"
                    "那里调试。也可以手动把网卡 IPv4 改到与相机同网段（例如相机 "
                    "192.168.0.10/255.255.255.0 → 网卡 "
                    "192.168.0.100/255.255.255.0）。");
        }
        return msg;
    }

    case Cause::IpConflict:
        return e.cameraIp.isEmpty()
            ? QStringLiteral("相机 IP 与网络中的其它设备冲突（RVC 状态 Conflict）。"
                             "请在 RVCManager 里修改相机 IP，或找出占用同一 IP "
                             "的设备后重试。")
            : QStringLiteral("相机 IP %1 与网络中的其它设备冲突（RVC 状态 "
                             "Conflict）。请在 RVCManager 里修改相机 IP，或找出"
                             "占用同一 IP 的设备后重试。")
                  .arg(e.cameraIp);

    case Cause::OpenFailed:
        return QStringLiteral(
                   "相机能找到，但打开失败：%1。\n"
                   "建议重新插拔网线/USB、重启相机电源；若刚被其它程序用过，"
                   "等 10 秒再试。")
            .arg(e.errorText.isEmpty() ? QStringLiteral("（无）") : e.errorText);

    default:
        return CameraRelease::operatorHint(
            CameraRelease::ConnectFailure::Unknown, retriesTried, e.errorText);
    }
}

} // namespace CameraConnect
