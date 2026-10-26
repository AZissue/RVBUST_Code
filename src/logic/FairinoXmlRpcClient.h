#pragma once

// 法奥 20003 XML-RPC 阻塞客户端。
//
// 每次调用一条短 TCP 连接（Connection: close）：控制器 XML-RPC 服务是
// 请求/应答，不需要长连接；这样重连、超时、上一条应答错位都不会跨调用残留。
//
// QTcpSocket 的阻塞 waitFor* 不要求事件循环，但 socket 对象有线程亲和性：
// **必须在将要使用它的线程里构造/调用**。本类自身不创建线程；控制台的
// worker 线程和机器人通信的 RobotWorker 各自在正确线程里调用。
#include <QString>

#include "logic/FairinoXmlRpc.h"

class FairinoXmlRpcClient {
public:
    void setEndpoint(const QString& host, quint16 port);
    void setTimeoutMs(int ms) { m_timeoutMs = ms; }
    int timeoutMs() const { return m_timeoutMs; }

    const QString& host() const { return m_host; }
    quint16 port() const { return m_port; }
    const QString& lastError() const { return m_error; }

    // 传输 + XML-RPC 解析成功即返回 true（不检查业务错误码）。
    bool call(const QString& method,
              const QList<FairinoXmlRpc::Value>& params,
              QList<FairinoXmlRpc::Value>& values, QString* error = nullptr);

    // 在上面的基础上要求第 1 个值（错误码）为 0。失败时 error 带上
    // "法奥错误码 N"；controller/manual 的对照说明由调用方补。
    bool callOk(const QString& method,
                const QList<FairinoXmlRpc::Value>& params,
                QList<FairinoXmlRpc::Value>& values, QString* error = nullptr);

    static QString errorCodeText(int code);

private:
    QString m_host;
    quint16 m_port = 20003;
    int m_timeoutMs = 2500;
    QString m_error;
};
