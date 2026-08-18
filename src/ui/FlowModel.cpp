#include "FlowModel.h"

#include <algorithm>

#include <QPointF>
#include <QSize>

#include <QtNodes/Definitions>
#include <QtNodes/NodeData>
#include <QtNodes/NodeStyle>
#include <QtNodes/StyleCollection>

#include "core/ModuleRegistry.h"

namespace rvc {

FlowModel::FlowModel(Process& process, QObject* parent)
    : QtNodes::AbstractGraphModel(), process_(process)
{
    setParent(parent);
}

QtNodes::NodeId FlowModel::newNodeId()
{
    QtNodes::NodeId id = 1;
    for (const auto& [nodeId, node] : process_.nodes())
        id = std::max(id, static_cast<QtNodes::NodeId>(nodeId + 1));
    return id;
}

std::unordered_set<QtNodes::NodeId> FlowModel::allNodeIds() const
{
    std::unordered_set<QtNodes::NodeId> ids;
    for (const auto& [nodeId, node] : process_.nodes())
        ids.insert(static_cast<QtNodes::NodeId>(nodeId));
    return ids;
}

std::string FlowModel::portName(QtNodes::NodeId nodeId, QtNodes::PortType portType,
                                QtNodes::PortIndex index) const
{
    const ProcessNode* n = process_.node(static_cast<int>(nodeId));
    if (!n)
        return {};
    const auto ports = portType == QtNodes::PortType::In ? n->module->inputPorts()
                                                         : n->module->outputPorts();
    if (index >= ports.size())
        return {};
    return ports[index].name;
}

QtNodes::PortIndex FlowModel::portIndex(const ProcessNode& node, QtNodes::PortType portType,
                                        const std::string& name) const
{
    const auto ports = portType == QtNodes::PortType::In ? node.module->inputPorts()
                                                         : node.module->outputPorts();
    for (size_t i = 0; i < ports.size(); ++i) {
        if (ports[i].name == name)
            return static_cast<QtNodes::PortIndex>(i);
    }
    return QtNodes::InvalidPortIndex;
}

QtNodes::ConnectionId FlowModel::toConnectionId(const ProcessLink& link) const
{
    const ProcessNode* from = process_.node(link.fromNode);
    const ProcessNode* to = process_.node(link.toNode);
    if (!from || !to)
        return {QtNodes::InvalidNodeId, 0, QtNodes::InvalidNodeId, 0};
    return {static_cast<QtNodes::NodeId>(link.fromNode),
            portIndex(*from, QtNodes::PortType::Out, link.fromPort),
            static_cast<QtNodes::NodeId>(link.toNode),
            portIndex(*to, QtNodes::PortType::In, link.toPort)};
}

std::unordered_set<QtNodes::ConnectionId> FlowModel::allConnectionIds(QtNodes::NodeId nodeId) const
{
    std::unordered_set<QtNodes::ConnectionId> out;
    for (const auto& l : process_.links()) {
        if (l.fromNode == static_cast<int>(nodeId) || l.toNode == static_cast<int>(nodeId))
            out.insert(toConnectionId(l));
    }
    return out;
}

std::unordered_set<QtNodes::ConnectionId> FlowModel::connections(QtNodes::NodeId nodeId,
                                                                 QtNodes::PortType portType,
                                                                 QtNodes::PortIndex index) const
{
    std::unordered_set<QtNodes::ConnectionId> out;
    const int id = static_cast<int>(nodeId);
    for (const auto& l : process_.links()) {
        if (portType == QtNodes::PortType::In) {
            if (l.toNode == id && l.toPort == portName(nodeId, QtNodes::PortType::In, index))
                out.insert(toConnectionId(l));
        } else if (portType == QtNodes::PortType::Out) {
            if (l.fromNode == id && l.fromPort == portName(nodeId, QtNodes::PortType::Out, index))
                out.insert(toConnectionId(l));
        }
    }
    return out;
}

bool FlowModel::connectionExists(QtNodes::ConnectionId const connectionId) const
{
    const std::string fromPort = portName(connectionId.outNodeId, QtNodes::PortType::Out,
                                          connectionId.outPortIndex);
    const std::string toPort = portName(connectionId.inNodeId, QtNodes::PortType::In,
                                        connectionId.inPortIndex);
    for (const auto& l : process_.links()) {
        if (l.fromNode == static_cast<int>(connectionId.outNodeId) && l.fromPort == fromPort &&
            l.toNode == static_cast<int>(connectionId.inNodeId) && l.toPort == toPort)
            return true;
    }
    return false;
}

QtNodes::NodeId FlowModel::addNode(QString const nodeType)
{
    // nodeType 即注册表中的模块类型 ID
    const int id = process_.addNode(nodeType.toStdString());
    if (id < 0)
        return QtNodes::InvalidNodeId;
    Q_EMIT nodeCreated(static_cast<QtNodes::NodeId>(id));
    return static_cast<QtNodes::NodeId>(id);
}

bool FlowModel::connectionPossible(QtNodes::ConnectionId const connectionId) const
{
    // 连线 = 订阅：委托 Process 做端口存在性 + 数据类型 + 成环校验
    const std::string fromPort = portName(connectionId.outNodeId, QtNodes::PortType::Out,
                                          connectionId.outPortIndex);
    const std::string toPort = portName(connectionId.inNodeId, QtNodes::PortType::In,
                                        connectionId.inPortIndex);
    if (fromPort.empty() || toPort.empty())
        return false;
    return process_.canConnect(static_cast<int>(connectionId.outNodeId), fromPort,
                               static_cast<int>(connectionId.inNodeId), toPort);
}

void FlowModel::addConnection(QtNodes::ConnectionId const connectionId)
{
    const std::string fromPort = portName(connectionId.outNodeId, QtNodes::PortType::Out,
                                          connectionId.outPortIndex);
    const std::string toPort = portName(connectionId.inNodeId, QtNodes::PortType::In,
                                        connectionId.inPortIndex);
    if (process_.addLink(static_cast<int>(connectionId.outNodeId), fromPort,
                         static_cast<int>(connectionId.inNodeId), toPort))
        Q_EMIT connectionCreated(connectionId);
}

bool FlowModel::nodeExists(QtNodes::NodeId const nodeId) const
{
    return process_.node(static_cast<int>(nodeId)) != nullptr;
}

QVariant FlowModel::nodeData(QtNodes::NodeId nodeId, QtNodes::NodeRole role) const
{
    const ProcessNode* n = process_.node(static_cast<int>(nodeId));
    if (!n)
        return {};

    switch (role) {
    case QtNodes::NodeRole::Type:
        return QString::fromStdString(n->typeId);
    case QtNodes::NodeRole::Position:
        return QPointF(n->x, n->y);
    case QtNodes::NodeRole::Caption:
        return QString::fromStdString(n->module->name());
    case QtNodes::NodeRole::CaptionVisible:
        return true;
    case QtNodes::NodeRole::Style: {
        // 与 DataFlowGraphModel 一致：返回 QVariantMap（QJsonObject 变体无法被
        // QJsonDocument::fromVariant 正确转换，会导致样式读出无效颜色、节点全黑）
        return QtNodes::StyleCollection::nodeStyle().toJson().toVariantMap();
    }
    case QtNodes::NodeRole::Size: {
        auto it = nodeSizes_.find(nodeId);
        return it != nodeSizes_.end() ? QVariant(it->second) : QVariant(QSize());
    }
    case QtNodes::NodeRole::InPortCount:
        return static_cast<unsigned int>(n->module->inputPorts().size());
    case QtNodes::NodeRole::OutPortCount:
        return static_cast<unsigned int>(n->module->outputPorts().size());
    default:
        return {};
    }
}

bool FlowModel::setNodeData(QtNodes::NodeId nodeId, QtNodes::NodeRole role, QVariant value)
{
    if (!nodeExists(nodeId))
        return false;

    switch (role) {
    case QtNodes::NodeRole::Position: {
        const QPointF pos = value.toPointF();
        process_.setNodePosition(static_cast<int>(nodeId), pos.x(), pos.y());
        Q_EMIT nodePositionUpdated(nodeId);
        return true;
    }
    case QtNodes::NodeRole::Size:
        nodeSizes_[nodeId] = value.toSize();
        return true;
    case QtNodes::NodeRole::Caption:
        if (ModuleBase* m = process_.module(static_cast<int>(nodeId))) {
            m->setName(value.toString().toStdString());
            Q_EMIT nodeUpdated(nodeId);
            return true;
        }
        return false;
    default:
        return false;
    }
}

QVariant FlowModel::portData(QtNodes::NodeId nodeId, QtNodes::PortType portType,
                             QtNodes::PortIndex index, QtNodes::PortRole role) const
{
    const ProcessNode* n = process_.node(static_cast<int>(nodeId));
    if (!n)
        return {};
    const auto ports = portType == QtNodes::PortType::In ? n->module->inputPorts()
                                                         : n->module->outputPorts();
    if (index >= ports.size())
        return {};
    const PortDecl& decl = ports[index];

    switch (role) {
    case QtNodes::PortRole::DataType: {
        const QString t = QString::fromLatin1(dataTypeName(decl.type));
        return QVariant::fromValue(QtNodes::NodeDataType{t, t});
    }
    case QtNodes::PortRole::Caption:
        return QString::fromStdString(decl.name);
    case QtNodes::PortRole::CaptionVisible:
        return true;
    case QtNodes::PortRole::ConnectionPolicyRole:
        // 输入端口单一订阅来源；输出端口可广播给多个下游
        return QVariant::fromValue(portType == QtNodes::PortType::In
                                       ? QtNodes::ConnectionPolicy::One
                                       : QtNodes::ConnectionPolicy::Many);
    default:
        return {};
    }
}

bool FlowModel::setPortData(QtNodes::NodeId, QtNodes::PortType, QtNodes::PortIndex,
                            QVariant const&, QtNodes::PortRole)
{
    // 端口运行数据不通过画布回写（执行结果由 Engine 直接写 Process 缓存）
    return false;
}

bool FlowModel::deleteConnection(QtNodes::ConnectionId const connectionId)
{
    const std::string fromPort = portName(connectionId.outNodeId, QtNodes::PortType::Out,
                                          connectionId.outPortIndex);
    const std::string toPort = portName(connectionId.inNodeId, QtNodes::PortType::In,
                                        connectionId.inPortIndex);
    if (process_.removeLink(static_cast<int>(connectionId.outNodeId), fromPort,
                            static_cast<int>(connectionId.inNodeId), toPort)) {
        Q_EMIT connectionDeleted(connectionId);
        return true;
    }
    return false;
}

bool FlowModel::deleteNode(QtNodes::NodeId const nodeId)
{
    if (!nodeExists(nodeId))
        return false;

    nodeSizes_.erase(nodeId);

    const bool ok = process_.removeNode(static_cast<int>(nodeId));
    if (ok)
        Q_EMIT nodeDeleted(nodeId);
    return ok;
}

void FlowModel::resetFromProcess()
{
    Q_EMIT modelReset();
}

} // namespace rvc
