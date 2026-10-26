#pragma once

// ── 法奥（FAIRINO）XML-RPC 报文（纯函数，可单测）────────────────────────
//
// 法奥官方 SDK（fairino v2.1.7.1，Python）在 20003 端口上说的是**标准 XML-RPC
// over HTTP**（Robot.py: xmlrpc.client.ServerProxy("http://<ip>:20003")）。
// 本程序不引入 Python 运行时，也不链接 .pyd，因此自己构造请求、解析应答。
//
// 这一层只做"字节 ↔ 值"的转换，不碰网络：
//   * buildMethodCall：方法名 + 参数 → methodCall XML；
//   * buildHttpPost：HTTP/1.1 POST /RPC2 请求（Python xmlrpc 的默认路径）；
//   * takeHttpResponse：增量解析 HTTP 应答（Content-Length / chunked /
//     Connection: close），让调用方可以边收边判；
//   * parseMethodResponse：methodResponse XML → Value 列表，fault 单独报。
//
// 证据：Robot.py 的每个方法都直接调用 self.robot.<Method>(...)，应答形如
//   <array><data><value><int>0</int></value> ... </data></array>
// 成功时第 1 个值是错误码 0，其后是返回值（见 GetInverseKin / GetForwardKin
// 的 Python 解包方式）。这里两者都支持：只有一个 param 且是数组时展开，
// 多个 param 时按顺序返回。
#include <QByteArray>
#include <QList>
#include <QString>
#include <QtGlobal>

namespace FairinoXmlRpc {

struct Value {
    enum class Kind { Null, Int, Double, Bool, String, Array };

    Kind kind = Kind::Null;
    qint64 intValue = 0;
    double doubleValue = 0.0;
    bool boolValue = false;
    QString stringValue;
    QList<Value> arrayValue;

    static Value fromInt(qint64 v);
    static Value fromDouble(double v);
    static Value fromBool(bool v);
    static Value fromString(const QString& v);
    static Value fromArray(const QList<Value>& v);

    bool isNumber() const { return kind == Kind::Int || kind == Kind::Double; }
    // Int，或没有小数部分的 Double。范围检查交给调用方。
    bool asInt(qint64* out) const;
    bool asDouble(double* out) const;
};

// 浮点字面量：保留足够有效位，避免 1.23456789 被截成 1.23457。
QString formatDouble(double v);

// <methodCall><methodName>…</methodName><params>…</params></methodCall>
QString buildMethodCall(const QString& method, const QList<Value>& params);

// HTTP/1.1 POST /RPC2。Connection: close：每次调用一条连接，避免控制器
// keep-alive/超时策略造成"上一条请求的应答被当成这一条的"。
QByteArray buildHttpPost(const QString& host, quint16 port,
                         const QByteArray& methodCallUtf8);

enum class HttpStatus {
    NeedMore,   // 还没收全，继续读 socket
    Complete,   // body 已给出
    Invalid     // 不是 HTTP/200、长度越界、chunked 编码坏了
};

// 从 buffer 中增量取一条 HTTP 应答。
//   connectionClosed：对端已断开（用于没有 Content-Length 的 close-delimited
//   应答；有 Content-Length 时不影响）。
//   body：成功时填响应体；失败/未完成不动。
//   error：失败原因（中文）。
// 注意：Complete 时会把这一条应答从 buffer 中移除；NeedMore 时保留。
HttpStatus takeHttpResponse(QByteArray& buffer, bool connectionClosed,
                            QByteArray& body, QString* error);

// methodResponse XML → values。
//   fault 非空：XML-RPC fault（服务器明确报错），values 为空。
//   error 非空：不是合法 XML / 不是 methodResponse / 结构不认识。
bool parseMethodResponse(const QByteArray& xml, QList<Value>& values,
                         QString* fault, QString* error);

// 便捷：应答第 1 个值必须是 int 错误码。
bool firstErrorCode(const QList<Value>& values, int* code, QString* error);

} // namespace FairinoXmlRpc
