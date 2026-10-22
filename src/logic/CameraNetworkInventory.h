#pragma once

// ── 本机 IPv4 网卡快照（3.0 E-05） ──
//
// 用来回答"NoDevice / NetworkUnreachable"时那个最实际的问题：这台机器
// 到底有哪些网段？收集部分是对 QNetworkInterface 的薄封装（不做单测），
// 字符串解析与同网段判断在 CameraConnectDiagnosis.h（纯函数，有单测）。
//
// 输出形如 "以太网=192.168.0.10/255.255.255.0"。名字保留下来，是因为现场
// 常常插着多张网卡（工控机 + USB 网卡），只给 IP 对不上是哪一根。

#include <QAbstractSocket>
#include <QNetworkAddressEntry>
#include <QNetworkInterface>
#include <QStringList>

namespace CameraConnect {

inline QStringList hostIpv4Subnets()
{
    QStringList out;
    for (const QNetworkInterface& iface : QNetworkInterface::allInterfaces()) {
        const auto flags = iface.flags();
        if (!(flags & QNetworkInterface::IsUp))
            continue;
        if (flags & QNetworkInterface::IsLoopBack)
            continue;

        for (const QNetworkAddressEntry& entry : iface.addressEntries()) {
            if (entry.ip().protocol() != QAbstractSocket::IPv4Protocol)
                continue;
            const QString ip = entry.ip().toString();
            if (ip.isEmpty())
                continue;
            out << QStringLiteral("%1=%2/%3")
                       .arg(iface.humanReadableName(), ip,
                            entry.netmask().toString());
        }
    }
    return out;
}

} // namespace CameraConnect
