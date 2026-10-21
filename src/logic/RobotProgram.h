#pragma once

// ── 机器人程序节点（数据模型，纯值对象）────────────────────────────────
//
// 「机器人控制台」的程序由一串节点组成：移动 / 拍照采集 / 等待。节点只装
// 数据，不碰 UI、不碰网络——这样它能在单测里逐字段验证，也能原样存成 JSON
// 供以后保存/载入程序。
//
// 以后加新节点（例如 IO、螺旋、条件）只需要：
//   1. 在这里加一个 payload 结构并放进 NodePayload 变体；
//   2. 在 ProgramRunner 的分派处实现执行语义；
//   3. 在 RobotProgramPanel 的列表标题/详情里加一行文案。
// 其余逻辑（列表、运行、停止、单步）不用改。
#include <QJsonObject>
#include <QString>

#include <array>
#include <variant>
#include <vector>

namespace RobotProgram {

enum class NodeKind { Move, Photo, Wait };

// 位置单位 mm，姿态单位度（与卡片、坐标转换页一致）。关节单位度。
using Pose = std::array<double, 6>;

struct MoveNode {
    enum class Space { Cartesian, Joint };
    Space space = Space::Cartesian;
    Pose target{};                 // Cartesian: x y z rx ry rz；Joint: j1..j6
    double speedPct = 30.0;        // 1..100，UR 的 movel/movej 速度百分比
    double toleranceMm = 2.0;      // 到位判据（笛卡尔直线距离）
    double toleranceDeg = 1.0;     // 到位判据（姿态/关节角）
    int settleTimeoutMs = 15000;   // 超过这个时间未到位 = 失败
};

struct PhotoNode {
    // 一条龙：读机器人位姿 → 拍照 → 识别 → 保存。false = 只采集不保存。
    bool autoSave = true;
};

struct WaitNode {
    double seconds = 1.0;          // 0..3600
};

using NodePayload = std::variant<MoveNode, PhotoNode, WaitNode>;

NodeKind kindOf(const NodePayload& payload);
QString kindLabel(NodeKind kind);          // 移动 / 拍照 / 等待
QString kindTag(NodeKind kind);            // MOVE / PHOTO / WAIT（列表小标签）
QString displayTitle(const NodePayload& payload);
QString displayDetail(const NodePayload& payload);

struct Node {
    QString id;                    // 稳定标识，供选中/日志/将来撤销使用
    NodePayload payload;
};

struct Program {
    QString name = QStringLiteral("未命名程序");
    std::vector<Node> nodes;
};

// 构造节点（自动生成 id）。数值在这里收敛到合法区间，越界不是错误而是
// 被夹到安全边界——用户在界面上乱填也没法生成一个会撞人的速度。
Node makeMove(const Pose& target, MoveNode::Space space,
              double speedPct = 30.0);
Node makePhoto(bool autoSave = true);
Node makeWait(double seconds);
QString newNodeId();

// 把节点数值收敛到合法区间（解析外部 JSON / 界面输入都走这里）。
MoveNode clampMove(MoveNode node);

constexpr int kProgramJsonVersion = 1;
QJsonObject toJson(const Program& program);

struct ParseResult {
    bool ok = false;
    QString error;
    Program program;
};

ParseResult fromJson(const QJsonObject& object);
// 文件读写（UTF-8 JSON）；失败时 error 是一句可读中文。
bool saveToFile(const Program& program, const QString& path,
                QString* error = nullptr);
ParseResult loadFromFile(const QString& path);

} // namespace RobotProgram
