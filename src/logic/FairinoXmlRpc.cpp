#include "logic/FairinoXmlRpc.h"

#include <QMap>
#include <QXmlStreamReader>

#include <cmath>
#include <limits>

namespace FairinoXmlRpc {

namespace {

constexpr int kMaxHeaderBytes = 64 * 1024;
constexpr int kMaxBodyBytes = 8 * 1024 * 1024;

QString xmlEscape(const QString& text)
{
    QString out;
    out.reserve(text.size());
    for (const QChar c : text) {
        switch (c.unicode()) {
        case '&': out += QLatin1String("&amp;"); break;
        case '<': out += QLatin1String("&lt;"); break;
        case '>': out += QLatin1String("&gt;"); break;
        case '"': out += QLatin1String("&quot;"); break;
        case '\'': out += QLatin1String("&apos;"); break;
        default: out += c; break;
        }
    }
    return out;
}

void appendValueXml(QString& out, const Value& value)
{
    out += QLatin1String("<value>");
    switch (value.kind) {
    case Value::Kind::Int:
        out += QStringLiteral("<int>%1</int>").arg(value.intValue);
        break;
    case Value::Kind::Double:
        out += QStringLiteral("<double>%1</double>")
                   .arg(formatDouble(value.doubleValue));
        break;
    case Value::Kind::Bool:
        out += QStringLiteral("<boolean>%1</boolean>")
                   .arg(value.boolValue ? 1 : 0);
        break;
    case Value::Kind::String:
        out += QStringLiteral("<string>%1</string>")
                   .arg(xmlEscape(value.stringValue));
        break;
    case Value::Kind::Array:
        out += QLatin1String("<array><data>");
        for (const Value& item : value.arrayValue)
            appendValueXml(out, item);
        out += QLatin1String("</data></array>");
        break;
    case Value::Kind::Null:
        out += QLatin1String("<nil/>");
        break;
    }
    out += QLatin1String("</value>");
}

} // namespace

Value Value::fromInt(qint64 v)
{
    Value out;
    out.kind = Kind::Int;
    out.intValue = v;
    return out;
}

Value Value::fromDouble(double v)
{
    Value out;
    out.kind = Kind::Double;
    out.doubleValue = v;
    return out;
}

Value Value::fromBool(bool v)
{
    Value out;
    out.kind = Kind::Bool;
    out.boolValue = v;
    return out;
}

Value Value::fromString(const QString& v)
{
    Value out;
    out.kind = Kind::String;
    out.stringValue = v;
    return out;
}

Value Value::fromArray(const QList<Value>& v)
{
    Value out;
    out.kind = Kind::Array;
    out.arrayValue = v;
    return out;
}

bool Value::asInt(qint64* out) const
{
    if (!out)
        return false;
    if (kind == Kind::Int) {
        *out = intValue;
        return true;
    }
    if (kind == Kind::Double && std::isfinite(doubleValue)) {
        const double rounded = std::round(doubleValue);
        if (std::fabs(doubleValue - rounded) <= 1e-9
            && rounded >= static_cast<double>(std::numeric_limits<qint64>::min())
            && rounded <= static_cast<double>(std::numeric_limits<qint64>::max())) {
            *out = static_cast<qint64>(rounded);
            return true;
        }
    }
    return false;
}

bool Value::asDouble(double* out) const
{
    if (!out)
        return false;
    if (kind == Kind::Int) {
        *out = static_cast<double>(intValue);
        return true;
    }
    if (kind == Kind::Double) {
        *out = doubleValue;
        return true;
    }
    return false;
}

QString formatDouble(double v)
{
    if (!std::isfinite(v))
        return QStringLiteral("0");
    return QString::number(v, 'g', 17);
}

QString buildMethodCall(const QString& method, const QList<Value>& params)
{
    QString out;
    out.reserve(256 + params.size() * 64);
    out += QLatin1String("<?xml version=\"1.0\"?>\n<methodCall>\n<methodName>");
    out += xmlEscape(method);
    out += QLatin1String("</methodName>\n<params>\n");
    for (const Value& param : params) {
        out += QLatin1String("<param>");
        appendValueXml(out, param);
        out += QLatin1String("</param>\n");
    }
    out += QLatin1String("</params>\n</methodCall>\n");
    return out;
}

QByteArray buildHttpPost(const QString& host, quint16 port,
                         const QByteArray& methodCallUtf8)
{
    QByteArray out;
    out.reserve(methodCallUtf8.size() + 256);
    out += "POST /RPC2 HTTP/1.1\r\n";
    out += "Host: " + host.toUtf8() + ':' + QByteArray::number(port) + "\r\n";
    out += "User-Agent: HandEyeCalibrationTool-FAIRINO\r\n";
    out += "Content-Type: text/xml\r\n";
    out += "Accept-Encoding: identity\r\n";
    out += "Connection: close\r\n";
    out += "Content-Length: " + QByteArray::number(methodCallUtf8.size()) + "\r\n";
    out += "\r\n";
    out += methodCallUtf8;
    return out;
}

namespace {

QByteArray trimAscii(const QByteArray& in)
{
    return in.trimmed();
}

// Decode a chunked body starting at bodyStart. On Complete, remove the whole
// response (header + chunked body) from buffer and fill body.
HttpStatus decodeChunked(QByteArray& buffer, int bodyStart, QByteArray& body,
                         QString* error)
{
    int pos = bodyStart;
    QByteArray out;
    while (true) {
        const int lineEnd = buffer.indexOf("\r\n", pos);
        if (lineEnd < 0)
            return HttpStatus::NeedMore;
        QByteArray sizeLine = buffer.mid(pos, lineEnd - pos);
        const int semi = sizeLine.indexOf(';');
        if (semi >= 0)
            sizeLine = sizeLine.left(semi);
        sizeLine = trimAscii(sizeLine);
        bool ok = false;
        const qint64 size = sizeLine.toLongLong(&ok, 16);
        if (!ok || size < 0 || size > kMaxBodyBytes) {
            if (error)
                *error = QStringLiteral("HTTP chunked 长度无效：%1")
                             .arg(QString::fromLatin1(sizeLine));
            return HttpStatus::Invalid;
        }
        pos = lineEnd + 2;
        if (size == 0) {
            // Trailer section ends with an empty line.
            while (true) {
                const int end = buffer.indexOf("\r\n", pos);
                if (end < 0)
                    return HttpStatus::NeedMore;
                if (end == pos) {
                    pos += 2;
                    buffer.remove(0, pos);
                    body = out;
                    return HttpStatus::Complete;
                }
                pos = end + 2;
            }
        }
        if (buffer.size() < pos + size + 2)
            return HttpStatus::NeedMore;
        if (out.size() + size > kMaxBodyBytes) {
            if (error)
                *error = QStringLiteral("HTTP 应答超过 %1 字节上限")
                             .arg(kMaxBodyBytes);
            return HttpStatus::Invalid;
        }
        out += buffer.mid(pos, static_cast<int>(size));
        pos += static_cast<int>(size);
        if (buffer.mid(pos, 2) != QByteArrayLiteral("\r\n")) {
            if (error)
                *error = QStringLiteral("HTTP chunked 块缺少 CRLF");
            return HttpStatus::Invalid;
        }
        pos += 2;
    }
}

} // namespace

HttpStatus takeHttpResponse(QByteArray& buffer, bool connectionClosed,
                            QByteArray& body, QString* error)
{
    const int headerEnd = buffer.indexOf("\r\n\r\n");
    if (headerEnd < 0) {
        if (buffer.size() > kMaxHeaderBytes) {
            if (error)
                *error = QStringLiteral("HTTP 应答头超过 %1 字节上限")
                             .arg(kMaxHeaderBytes);
            return HttpStatus::Invalid;
        }
        return HttpStatus::NeedMore;
    }

    const QList<QByteArray> lines = buffer.left(headerEnd).split('\n');
    if (lines.isEmpty()) {
        if (error)
            *error = QStringLiteral("HTTP 应答没有状态行");
        return HttpStatus::Invalid;
    }
    const QByteArray statusLine = lines.first().trimmed();
    const QList<QByteArray> statusParts = statusLine.split(' ');
    if (statusParts.size() < 2 || !statusParts.first().startsWith("HTTP/")) {
        if (error)
            *error = QStringLiteral("HTTP 状态行无法解析：%1")
                         .arg(QString::fromLatin1(statusLine.left(80)));
        return HttpStatus::Invalid;
    }
    bool codeOk = false;
    const int statusCode = statusParts.at(1).toInt(&codeOk);
    if (!codeOk || statusCode != 200) {
        if (error)
            *error = QStringLiteral("控制器 HTTP/XML-RPC 返回 %1（期望 200）")
                         .arg(QString::fromLatin1(statusLine.left(80)));
        return HttpStatus::Invalid;
    }

    qint64 contentLength = -1;
    bool chunked = false;
    bool headerComplete = false;
    for (int i = 1; i < lines.size(); ++i) {
        const QByteArray line = lines.at(i).trimmed();
        if (line.isEmpty()) {
            headerComplete = true;
            continue;
        }
        const int colon = line.indexOf(':');
        if (colon <= 0)
            continue;
        const QByteArray name = line.left(colon).trimmed().toLower();
        const QByteArray value = line.mid(colon + 1).trimmed();
        if (name == "content-length") {
            bool lenOk = false;
            contentLength = value.toLongLong(&lenOk);
            if (!lenOk || contentLength < 0) {
                if (error)
                    *error = QStringLiteral("HTTP Content-Length 无效：%1")
                                 .arg(QString::fromLatin1(value.left(40)));
                return HttpStatus::Invalid;
            }
        } else if (name == "transfer-encoding") {
            chunked = value.toLower().contains("chunked");
        }
    }
    Q_UNUSED(headerComplete);

    const int bodyStart = headerEnd + 4;
    if (chunked)
        return decodeChunked(buffer, bodyStart, body, error);

    if (contentLength >= 0) {
        if (contentLength > kMaxBodyBytes) {
            if (error)
                *error = QStringLiteral("HTTP 应答 %1 字节，超过上限 %2")
                             .arg(contentLength).arg(kMaxBodyBytes);
            return HttpStatus::Invalid;
        }
        if (buffer.size() < bodyStart + contentLength)
            return HttpStatus::NeedMore;
        body = buffer.mid(bodyStart, static_cast<int>(contentLength));
        buffer.remove(0, bodyStart + static_cast<int>(contentLength));
        return HttpStatus::Complete;
    }

    // No framing headers: only a closed connection can delimit the body.
    if (!connectionClosed)
        return HttpStatus::NeedMore;
    body = buffer.mid(bodyStart);
    buffer.clear();
    if (body.size() > kMaxBodyBytes) {
        if (error)
            *error = QStringLiteral("HTTP 应答超过 %1 字节上限").arg(kMaxBodyBytes);
        return HttpStatus::Invalid;
    }
    return HttpStatus::Complete;
}

namespace {

Value readValue(QXmlStreamReader& xml);

// Qt 5.14 has no QXmlStreamReader::depth(), and readNextStartElement() reports
// false for *any* EndElement - not just the parent's. A loop that calls it while
// the reader still sits on a child's close tag therefore stops after the first
// child (this silently truncated FAIRINO arrays and fault structs once).
// Walk raw tokens and count nesting ourselves.
void skipSubtree(QXmlStreamReader& xml)
{
    // Positioned on a StartElement; consumes it and returns on its EndElement.
    if (!xml.isStartElement())
        return;
    int level = 1;
    while (level > 0 && !xml.atEnd() && !xml.hasError()) {
        xml.readNext();
        if (xml.isStartElement())
            ++level;
        else if (xml.isEndElement())
            --level;
    }
}

// Positioned on <struct>; returns on </struct>.
QMap<QString, Value> readStruct(QXmlStreamReader& xml)
{
    QMap<QString, Value> members;
    int level = 0;   // elements still open below <struct>
    while (!xml.atEnd() && !xml.hasError()) {
        xml.readNext();
        if (xml.isEndElement()) {
            if (level == 0)
                break;   // </struct>
            --level;
            continue;
        }
        if (!xml.isStartElement())
            continue;
        if (xml.name() != QLatin1String("member")) {
            skipSubtree(xml);
            continue;
        }

        // The member is parsed inline: readElementText()/readValue()/skipSubtree
        // all consume their element completely, so `level` stays balanced.
        QString name;
        Value value;
        int memberLevel = 0;
        while (!xml.atEnd() && !xml.hasError()) {
            xml.readNext();
            if (xml.isEndElement()) {
                if (memberLevel == 0)
                    break;   // </member>
                --memberLevel;
                continue;
            }
            if (!xml.isStartElement())
                continue;
            if (xml.name() == QLatin1String("name"))
                name = xml.readElementText();
            else if (xml.name() == QLatin1String("value"))
                value = readValue(xml);
            else
                skipSubtree(xml);
        }
        if (!name.isEmpty())
            members.insert(name, value);
    }
    return members;
}

// Positioned on <value>; returns on </value>.
Value readValue(QXmlStreamReader& xml)
{
    Value out;
    bool typeParsed = false;
    int level = 0;
    while (!xml.atEnd() && !xml.hasError()) {
        xml.readNext();
        if (xml.isEndElement()) {
            if (level == 0)
                break;   // </value>
            --level;
            continue;
        }
        if (!xml.isStartElement())
            continue;
        if (typeParsed) {
            skipSubtree(xml);   // XML-RPC allows exactly one type per <value>
            continue;
        }
        typeParsed = true;

        const auto name = xml.name();
        if (name == QLatin1String("int") || name == QLatin1String("i4")
            || name == QLatin1String("i8")) {
            bool ok = false;
            const qint64 v = xml.readElementText().trimmed().toLongLong(&ok);
            if (ok)
                out = Value::fromInt(v);
        } else if (name == QLatin1String("double")) {
            bool ok = false;
            const double v = xml.readElementText().trimmed().toDouble(&ok);
            if (ok)
                out = Value::fromDouble(v);
        } else if (name == QLatin1String("boolean")) {
            const QString text = xml.readElementText().trimmed().toLower();
            out = Value::fromBool(text == QLatin1String("1")
                                  || text == QLatin1String("true"));
        } else if (name == QLatin1String("string")
                   || name == QLatin1String("base64")) {
            out = Value::fromString(xml.readElementText());
        } else if (name == QLatin1String("nil")) {
            skipSubtree(xml);
        } else if (name == QLatin1String("array")) {
            QList<Value> items;
            int arrayLevel = 0;
            bool dataSeen = false;
            while (!xml.atEnd() && !xml.hasError()) {
                xml.readNext();
                if (xml.isEndElement()) {
                    if (arrayLevel == 0)
                        break;   // </array>
                    --arrayLevel;
                    continue;
                }
                if (!xml.isStartElement())
                    continue;
                if (dataSeen || xml.name() != QLatin1String("data")) {
                    skipSubtree(xml);
                    continue;
                }
                dataSeen = true;
                int dataLevel = 0;
                while (!xml.atEnd() && !xml.hasError()) {
                    xml.readNext();
                    if (xml.isEndElement()) {
                        if (dataLevel == 0)
                            break;   // </data>
                        --dataLevel;
                        continue;
                    }
                    if (!xml.isStartElement())
                        continue;
                    if (xml.name() == QLatin1String("value"))
                        items.append(readValue(xml));
                    else
                        skipSubtree(xml);
                }
            }
            out = Value::fromArray(items);
        } else if (name == QLatin1String("struct")) {
            const QMap<QString, Value> members = readStruct(xml);
            // Structs are only needed for faults; keep faultString readable.
            out = Value::fromString(members.value(QStringLiteral("faultString"))
                                        .stringValue);
        } else {
            skipSubtree(xml);
        }
    }
    return out;
}

} // namespace

bool parseMethodResponse(const QByteArray& xmlBytes, QList<Value>& values,
                         QString* fault, QString* error)
{
    values.clear();
    if (fault)
        fault->clear();
    if (error)
        error->clear();

    QXmlStreamReader xml(xmlBytes);
    if (!xml.readNextStartElement()) {
        if (error)
            *error = QStringLiteral("XML-RPC 应答为空或不是 XML");
        return false;
    }
    if (xml.name() != QLatin1String("methodResponse")) {
        if (error)
            *error = QStringLiteral("XML-RPC 应答根节点是 %1，期望 methodResponse")
                         .arg(xml.name().toString());
        return false;
    }

    QList<Value> params;
    QString faultText;
    int rootLevel = 0;
    while (!xml.atEnd() && !xml.hasError()) {
        xml.readNext();
        if (xml.isEndElement()) {
            if (rootLevel == 0)
                break;   // </methodResponse>
            --rootLevel;
            continue;
        }
        if (!xml.isStartElement())
            continue;

        if (xml.name() == QLatin1String("params")) {
            int paramsLevel = 0;
            while (!xml.atEnd() && !xml.hasError()) {
                xml.readNext();
                if (xml.isEndElement()) {
                    if (paramsLevel == 0)
                        break;   // </params>
                    --paramsLevel;
                    continue;
                }
                if (!xml.isStartElement())
                    continue;
                if (xml.name() != QLatin1String("param")) {
                    skipSubtree(xml);
                    continue;
                }
                int paramLevel = 0;
                while (!xml.atEnd() && !xml.hasError()) {
                    xml.readNext();
                    if (xml.isEndElement()) {
                        if (paramLevel == 0)
                            break;   // </param>
                        --paramLevel;
                        continue;
                    }
                    if (!xml.isStartElement())
                        continue;
                    if (xml.name() == QLatin1String("value"))
                        params.append(readValue(xml));
                    else
                        skipSubtree(xml);
                }
            }
        } else if (xml.name() == QLatin1String("fault")) {
            int faultLevel = 0;
            while (!xml.atEnd() && !xml.hasError()) {
                xml.readNext();
                if (xml.isEndElement()) {
                    if (faultLevel == 0)
                        break;   // </fault>
                    --faultLevel;
                    continue;
                }
                if (!xml.isStartElement())
                    continue;
                if (xml.name() != QLatin1String("value")) {
                    skipSubtree(xml);
                    continue;
                }
                int valueLevel = 0;
                while (!xml.atEnd() && !xml.hasError()) {
                    xml.readNext();
                    if (xml.isEndElement()) {
                        if (valueLevel == 0)
                            break;   // </value>
                        --valueLevel;
                        continue;
                    }
                    if (!xml.isStartElement())
                        continue;
                    if (xml.name() == QLatin1String("struct")) {
                        const QMap<QString, Value> members = readStruct(xml);
                        const QString text =
                            members.value(QStringLiteral("faultString"))
                                .stringValue;
                        qint64 code = 0;
                        const bool hasCode =
                            members.value(QStringLiteral("faultCode"))
                                .asInt(&code);
                        faultText = hasCode
                            ? QStringLiteral("%1（faultCode %2）")
                                  .arg(text).arg(code)
                            : text;
                    } else {
                        skipSubtree(xml);
                    }
                }
            }
        } else {
            skipSubtree(xml);
        }
    }

    if (xml.hasError()) {
        if (error)
            *error = QStringLiteral("XML-RPC 应答解析失败：%1（行 %2）")
                         .arg(xml.errorString()).arg(xml.lineNumber());
        return false;
    }
    if (!faultText.isEmpty()) {
        if (fault)
            *fault = faultText;
        return false;
    }
    if (params.isEmpty()) {
        if (error)
            *error = QStringLiteral("XML-RPC 应答没有 params");
        return false;
    }

    // FAIRINO controllers wrap the result in one array value (the Python SDK
    // unpacks it as a tuple). Unwrap so callers see (error, value...).
    if (params.size() == 1 && params.first().kind == Value::Kind::Array)
        values = params.first().arrayValue;
    else
        values = params;
    return true;
}

bool firstErrorCode(const QList<Value>& values, int* code, QString* error)
{
    if (values.isEmpty()) {
        if (error)
            *error = QStringLiteral("XML-RPC 应答没有错误码");
        return false;
    }
    qint64 raw = 0;
    if (!values.first().asInt(&raw)) {
        if (error)
            *error = QStringLiteral("XML-RPC 应答第 1 个值不是整数错误码");
        return false;
    }
    if (code)
        *code = static_cast<int>(raw);
    return true;
}

} // namespace FairinoXmlRpc
