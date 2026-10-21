#include "logic/RobotProgram.h"

#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonParseError>
#include <QUuid>

#include <cmath>

namespace RobotProgram {

namespace {

double clampValue(double v, double lo, double hi)
{
    if (!std::isfinite(v))
        return lo;
    return v < lo ? lo : (v > hi ? hi : v);
}

QJsonArray poseToJson(const Pose& p)
{
    QJsonArray a;
    for (double v : p)
        a.append(v);
    return a;
}

// 读取 6 个数。缺失/类型错误/非有限值都算解析失败——静默补 0 会生成一个
// "看起来没问题、实际把机器人开向原点"的节点。
bool poseFromJson(const QJsonValue& value, Pose& out, QString& error)
{
    const QJsonArray a = value.toArray();
    if (a.size() != 6) {
        error = QStringLiteral("位姿必须是 6 个数值");
        return false;
    }
    for (int i = 0; i < 6; ++i) {
        if (!a.at(i).isDouble() || !std::isfinite(a.at(i).toDouble())) {
            error = QStringLiteral("位姿第 %1 个值不是有效数值").arg(i + 1);
            return false;
        }
        out[static_cast<std::size_t>(i)] = a.at(i).toDouble();
    }
    return true;
}

QString number(double v, int decimals = 1)
{
    return QString::number(v, 'f', decimals);
}

} // namespace

NodeKind kindOf(const NodePayload& payload)
{
    if (std::holds_alternative<MoveNode>(payload))
        return NodeKind::Move;
    if (std::holds_alternative<PhotoNode>(payload))
        return NodeKind::Photo;
    return NodeKind::Wait;
}

QString kindLabel(NodeKind kind)
{
    switch (kind) {
    case NodeKind::Move:  return QStringLiteral("移动");
    case NodeKind::Photo: return QStringLiteral("拍照");
    case NodeKind::Wait:  return QStringLiteral("等待");
    }
    return QString();
}

QString kindTag(NodeKind kind)
{
    switch (kind) {
    case NodeKind::Move:  return QStringLiteral("MOVE");
    case NodeKind::Photo: return QStringLiteral("PHOTO");
    case NodeKind::Wait:  return QStringLiteral("WAIT");
    }
    return QString();
}

QString displayTitle(const NodePayload& payload)
{
    if (const auto* move = std::get_if<MoveNode>(&payload)) {
        if (move->space == MoveNode::Space::Joint)
            return QStringLiteral("移动 · 关节");
        return QStringLiteral("移动 · 笛卡尔");
    }
    if (std::holds_alternative<PhotoNode>(payload))
        return QStringLiteral("拍照采集");
    const auto& wait = std::get<WaitNode>(payload);
    return QStringLiteral("等待 %1 s").arg(number(wait.seconds));
}

QString displayDetail(const NodePayload& payload)
{
    if (const auto* move = std::get_if<MoveNode>(&payload)) {
        const Pose& t = move->target;
        if (move->space == MoveNode::Space::Joint) {
            return QStringLiteral("J1 %1 · J2 %2 · J3 %3 · J4 %4 · J5 %5 · J6 %6")
                .arg(number(t[0]), number(t[1]), number(t[2]),
                     number(t[3]), number(t[4]), number(t[5]));
        }
        return QStringLiteral("X %1 · Y %2 · Z %3 · RX %4 · RY %5 · RZ %6")
            .arg(number(t[0]), number(t[1]), number(t[2]),
                 number(t[3]), number(t[4]), number(t[5]));
    }
    if (const auto* photo = std::get_if<PhotoNode>(&payload)) {
        return photo->autoSave
            ? QStringLiteral("读位姿 → 拍照 → 识别 → 保存")
            : QStringLiteral("读位姿 → 拍照 → 识别（不保存）");
    }
    return QStringLiteral("保持当前位置");
}

QString newNodeId()
{
    return QUuid::createUuid().toString(QUuid::WithoutBraces);
}

MoveNode clampMove(MoveNode node)
{
    node.speedPct = clampValue(node.speedPct, 1.0, 100.0);
    node.toleranceMm = clampValue(node.toleranceMm, 0.1, 100.0);
    node.toleranceDeg = clampValue(node.toleranceDeg, 0.1, 90.0);
    node.settleTimeoutMs = static_cast<int>(
        clampValue(static_cast<double>(node.settleTimeoutMs), 500.0, 120000.0));
    for (double& v : node.target) {
        if (!std::isfinite(v))
            v = 0.0;
    }
    return node;
}

Node makeMove(const Pose& target, MoveNode::Space space, double speedPct)
{
    MoveNode move;
    move.space = space;
    move.target = target;
    move.speedPct = speedPct;
    return Node{ newNodeId(), clampMove(move) };
}

Node makePhoto(bool autoSave)
{
    return Node{ newNodeId(), PhotoNode{ autoSave } };
}

Node makeWait(double seconds)
{
    WaitNode wait;
    wait.seconds = clampValue(seconds, 0.0, 3600.0);
    return Node{ newNodeId(), wait };
}

QJsonObject toJson(const Program& program)
{
    QJsonObject root;
    root.insert(QStringLiteral("version"), kProgramJsonVersion);
    root.insert(QStringLiteral("name"), program.name);

    QJsonArray nodes;
    for (const Node& node : program.nodes) {
        QJsonObject n;
        n.insert(QStringLiteral("id"), node.id);
        if (const auto* move = std::get_if<MoveNode>(&node.payload)) {
            n.insert(QStringLiteral("type"), QStringLiteral("move"));
            n.insert(QStringLiteral("space"),
                     move->space == MoveNode::Space::Joint
                         ? QStringLiteral("joint") : QStringLiteral("cartesian"));
            n.insert(QStringLiteral("target"), poseToJson(move->target));
            n.insert(QStringLiteral("speedPct"), move->speedPct);
            n.insert(QStringLiteral("toleranceMm"), move->toleranceMm);
            n.insert(QStringLiteral("toleranceDeg"), move->toleranceDeg);
            n.insert(QStringLiteral("settleTimeoutMs"), move->settleTimeoutMs);
        } else if (const auto* photo = std::get_if<PhotoNode>(&node.payload)) {
            n.insert(QStringLiteral("type"), QStringLiteral("photo"));
            n.insert(QStringLiteral("autoSave"), photo->autoSave);
        } else {
            const auto& wait = std::get<WaitNode>(node.payload);
            n.insert(QStringLiteral("type"), QStringLiteral("wait"));
            n.insert(QStringLiteral("seconds"), wait.seconds);
        }
        nodes.append(n);
    }
    root.insert(QStringLiteral("nodes"), nodes);
    return root;
}

ParseResult fromJson(const QJsonObject& object)
{
    ParseResult result;
    const int version = object.value(QStringLiteral("version")).toInt(0);
    if (version != kProgramJsonVersion) {
        result.error = QStringLiteral("不支持的机器人程序版本: %1").arg(version);
        return result;
    }
    if (!object.value(QStringLiteral("nodes")).isArray()) {
        result.error = QStringLiteral("机器人程序缺少 nodes 数组");
        return result;
    }

    Program program;
    program.name = object.value(QStringLiteral("name"))
                       .toString(QStringLiteral("未命名程序"));

    const QJsonArray nodes = object.value(QStringLiteral("nodes")).toArray();
    for (int i = 0; i < nodes.size(); ++i) {
        if (!nodes.at(i).isObject()) {
            result.error = QStringLiteral("第 %1 个节点不是对象").arg(i + 1);
            return result;
        }
        const QJsonObject n = nodes.at(i).toObject();
        const QString type = n.value(QStringLiteral("type")).toString();
        Node node;
        node.id = n.value(QStringLiteral("id")).toString();
        if (node.id.isEmpty())
            node.id = newNodeId();

        if (type == QLatin1String("move")) {
            MoveNode move;
            const QString space = n.value(QStringLiteral("space"))
                                      .toString(QStringLiteral("cartesian"));
            if (space == QLatin1String("cartesian")) {
                move.space = MoveNode::Space::Cartesian;
            } else if (space == QLatin1String("joint")) {
                move.space = MoveNode::Space::Joint;
            } else {
                result.error = QStringLiteral("第 %1 个节点的 space 无效: %2")
                                   .arg(i + 1).arg(space);
                return result;
            }
            QString poseError;
            if (!poseFromJson(n.value(QStringLiteral("target")), move.target,
                              poseError)) {
                result.error = QStringLiteral("第 %1 个节点（移动）：%2")
                                   .arg(i + 1).arg(poseError);
                return result;
            }
            move.speedPct = n.value(QStringLiteral("speedPct")).toDouble(30.0);
            move.toleranceMm = n.value(QStringLiteral("toleranceMm")).toDouble(2.0);
            move.toleranceDeg = n.value(QStringLiteral("toleranceDeg")).toDouble(1.0);
            move.settleTimeoutMs = n.value(QStringLiteral("settleTimeoutMs")).toInt(15000);
            node.payload = clampMove(move);
        } else if (type == QLatin1String("photo")) {
            node.payload = PhotoNode{
                n.value(QStringLiteral("autoSave")).toBool(true) };
        } else if (type == QLatin1String("wait")) {
            WaitNode wait;
            wait.seconds = clampValue(
                n.value(QStringLiteral("seconds")).toDouble(1.0), 0.0, 3600.0);
            node.payload = wait;
        } else {
            result.error = QStringLiteral("第 %1 个节点类型未知: '%2'")
                               .arg(i + 1).arg(type);
            return result;
        }
        program.nodes.push_back(node);
    }

    result.ok = true;
    result.program = program;
    return result;
}

bool saveToFile(const Program& program, const QString& path, QString* error)
{
    QFile f(path);
    if (!f.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        if (error)
            *error = QStringLiteral("无法写入文件: %1").arg(f.errorString());
        return false;
    }
    const QByteArray bytes =
        QJsonDocument(toJson(program)).toJson(QJsonDocument::Indented);
    if (f.write(bytes) != bytes.size()) {
        if (error)
            *error = QStringLiteral("写入文件失败: %1").arg(f.errorString());
        return false;
    }
    return true;
}

ParseResult loadFromFile(const QString& path)
{
    ParseResult result;
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly)) {
        result.error = QStringLiteral("无法打开文件: %1").arg(f.errorString());
        return result;
    }
    QJsonParseError parseError;
    const QJsonDocument doc = QJsonDocument::fromJson(f.readAll(), &parseError);
    if (parseError.error != QJsonParseError::NoError || !doc.isObject()) {
        result.error = QStringLiteral("JSON 格式错误: %1")
                           .arg(parseError.errorString());
        return result;
    }
    return fromJson(doc.object());
}

} // namespace RobotProgram
