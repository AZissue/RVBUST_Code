#include "logic/FairinoXmlRpcClient.h"

#include <QElapsedTimer>
#include <QNetworkProxy>
#include <QTcpSocket>

namespace {

QString transportError(const QString& host, quint16 port, const QString& what)
{
    return QStringLiteral("法奥 XML-RPC %1:%2 %3").arg(host).arg(port).arg(what);
}

} // namespace

void FairinoXmlRpcClient::setEndpoint(const QString& host, quint16 port)
{
    m_host = host;
    m_port = port == 0 ? 20003 : port;
}

bool FairinoXmlRpcClient::call(const QString& method,
                               const QList<FairinoXmlRpc::Value>& params,
                               QList<FairinoXmlRpc::Value>& values,
                               QString* error)
{
    m_error.clear();
    values.clear();
    if (m_host.trimmed().isEmpty()) {
        m_error = QStringLiteral("法奥 XML-RPC：未填写 IP");
        if (error)
            *error = m_error;
        return false;
    }

    QTcpSocket socket;
    // 与 UR/NRC/Efort 适配器相同：VM/办公网常被系统代理干扰，原始 TCP 必须直连。
    socket.setProxy(QNetworkProxy::NoProxy);
    socket.connectToHost(m_host, m_port);
    if (!socket.waitForConnected(m_timeoutMs)) {
        m_error = transportError(m_host, m_port,
                                 QStringLiteral("连接失败：%1")
                                     .arg(socket.errorString()));
        if (error)
            *error = m_error;
        return false;
    }

    const QByteArray request = FairinoXmlRpc::buildHttpPost(
        m_host, m_port,
        FairinoXmlRpc::buildMethodCall(method, params).toUtf8());
    const qint64 written = socket.write(request);
    if (written != request.size() || !socket.waitForBytesWritten(m_timeoutMs)) {
        m_error = transportError(m_host, m_port,
                                 QStringLiteral("发送 %1 请求失败：%2")
                                     .arg(method, socket.errorString()));
        if (error)
            *error = m_error;
        return false;
    }

    QByteArray buffer;
    QByteArray body;
    QElapsedTimer timer;
    timer.start();
    QString httpError;

    while (true) {
        const FairinoXmlRpc::HttpStatus status = FairinoXmlRpc::takeHttpResponse(
            buffer, socket.state() != QAbstractSocket::ConnectedState, body,
            &httpError);
        if (status == FairinoXmlRpc::HttpStatus::Complete)
            break;
        if (status == FairinoXmlRpc::HttpStatus::Invalid) {
            m_error = transportError(m_host, m_port,
                                     QStringLiteral("应答无效：%1").arg(httpError));
            if (error)
                *error = m_error;
            return false;
        }

        if (socket.bytesAvailable() > 0) {
            buffer += socket.readAll();
            continue;
        }

        const qint64 remaining = m_timeoutMs - timer.elapsed();
        if (remaining <= 0) {
            m_error = transportError(
                m_host, m_port,
                QStringLiteral("等待 %1 应答超时（%2 ms）")
                    .arg(method).arg(m_timeoutMs));
            if (error)
                *error = m_error;
            return false;
        }

        if (socket.state() == QAbstractSocket::ConnectedState) {
            if (!socket.waitForReadyRead(static_cast<int>(remaining))) {
                if (socket.state() == QAbstractSocket::ConnectedState) {
                    m_error = transportError(
                        m_host, m_port,
                        QStringLiteral("等待 %1 应答超时（%2 ms）")
                            .arg(method).arg(m_timeoutMs));
                    if (error)
                        *error = m_error;
                    return false;
                }
                // Peer closed: the loop's next parse can frame a close-delimited
                // response, or report that the connection ended early.
                buffer += socket.readAll();
            }
        } else {
            buffer += socket.readAll();
            if (buffer.isEmpty()) {
                m_error = transportError(
                    m_host, m_port,
                    QStringLiteral("连接已关闭，未收到 %1 的应答").arg(method));
                if (error)
                    *error = m_error;
                return false;
            }
            // Re-parse with connectionClosed=true; if it still needs more, the
            // controller closed before completing the response.
            const FairinoXmlRpc::HttpStatus finalStatus =
                FairinoXmlRpc::takeHttpResponse(buffer, true, body, &httpError);
            if (finalStatus == FairinoXmlRpc::HttpStatus::Complete)
                break;
            m_error = transportError(
                m_host, m_port,
                QStringLiteral("连接提前关闭，应答不完整（%1）").arg(httpError));
            if (error)
                *error = m_error;
            return false;
        }
    }

    QString fault;
    QString parseError;
    if (!FairinoXmlRpc::parseMethodResponse(body, values, &fault, &parseError)) {
        m_error = fault.isEmpty()
            ? transportError(m_host, m_port,
                             QStringLiteral("%1 应答解析失败：%2")
                                 .arg(method, parseError))
            : transportError(m_host, m_port,
                             QStringLiteral("%1 返回 fault：%2")
                                 .arg(method, fault));
        if (error)
            *error = m_error;
        return false;
    }
    return true;
}

bool FairinoXmlRpcClient::callOk(const QString& method,
                                 const QList<FairinoXmlRpc::Value>& params,
                                 QList<FairinoXmlRpc::Value>& values,
                                 QString* error)
{
    if (!call(method, params, values, error))
        return false;
    int code = 0;
    QString codeError;
    if (!FairinoXmlRpc::firstErrorCode(values, &code, &codeError)) {
        m_error = transportError(m_host, m_port,
                                 QStringLiteral("%1 应答无效：%2")
                                     .arg(method, codeError));
        if (error)
            *error = m_error;
        return false;
    }
    if (code != 0) {
        m_error = transportError(m_host, m_port,
                                 QStringLiteral("%1 失败：%2")
                                     .arg(method, errorCodeText(code)));
        if (error)
            *error = m_error;
        return false;
    }
    return true;
}

QString FairinoXmlRpcClient::errorCodeText(int code)
{
    // 官方 SDK 只保证 0=成功、负数/非 0=失败，具体码表在《控制器通讯指令
    // 协议用户手册》里。没有逐码证据就不编含义，界面上给数字 + 出处。
    return QStringLiteral("法奥错误码 %1（请查控制器通讯指令手册的返回值表）")
        .arg(code);
}
