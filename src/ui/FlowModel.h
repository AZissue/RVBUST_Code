#pragma once

// FlowModel：QtNodes v3 AbstractGraphModel 的实现。
// 画布节点与 core::Process 的模块实例双向同步：
//   画布加节点 → Process 加模块；画布连线 → Process 连线（带端口类型校验）。
// Process 是真实执行图，QtNodes 只是它的 UI 投影。
// 参数编辑由 PropertyPanel 按 ParamDesc 统一承担（不再有模块特判内嵌 widget）。

#include <unordered_map>
#include <unordered_set>

#include <QSize>

#include <QtNodes/AbstractGraphModel>

#include "core/Process.h"

namespace rvc {

class FlowModel : public QtNodes::AbstractGraphModel {
    Q_OBJECT
public:
    explicit FlowModel(Process& process, QObject* parent = nullptr);
    ~FlowModel() override = default;

    // ---- AbstractGraphModel 接口 ----
    QtNodes::NodeId newNodeId() override;
    std::unordered_set<QtNodes::NodeId> allNodeIds() const override;
    std::unordered_set<QtNodes::ConnectionId> allConnectionIds(QtNodes::NodeId nodeId) const override;
    std::unordered_set<QtNodes::ConnectionId> connections(QtNodes::NodeId nodeId,
                                                          QtNodes::PortType portType,
                                                          QtNodes::PortIndex index) const override;
    bool connectionExists(QtNodes::ConnectionId const connectionId) const override;
    QtNodes::NodeId addNode(QString const nodeType = QString()) override;
    bool connectionPossible(QtNodes::ConnectionId const connectionId) const override;
    void addConnection(QtNodes::ConnectionId const connectionId) override;
    bool nodeExists(QtNodes::NodeId const nodeId) const override;
    QVariant nodeData(QtNodes::NodeId nodeId, QtNodes::NodeRole role) const override;
    bool setNodeData(QtNodes::NodeId nodeId, QtNodes::NodeRole role, QVariant value) override;
    QVariant portData(QtNodes::NodeId nodeId, QtNodes::PortType portType,
                      QtNodes::PortIndex index, QtNodes::PortRole role) const override;
    bool setPortData(QtNodes::NodeId nodeId, QtNodes::PortType portType,
                     QtNodes::PortIndex index, QVariant const& value,
                     QtNodes::PortRole role = QtNodes::PortRole::Data) override;
    bool deleteConnection(QtNodes::ConnectionId const connectionId) override;
    bool deleteNode(QtNodes::NodeId const nodeId) override;

    // Solution 加载后调用：通知场景按 Process 当前内容整体重建
    void resetFromProcess();

private:
    // 端口索引 ↔ 端口名互转（索引即模块端口声明表中的下标）
    std::string portName(QtNodes::NodeId nodeId, QtNodes::PortType portType,
                         QtNodes::PortIndex index) const;
    QtNodes::PortIndex portIndex(const ProcessNode& node, QtNodes::PortType portType,
                                 const std::string& name) const;
    QtNodes::ConnectionId toConnectionId(const ProcessLink& link) const;

    Process& process_;
    // QtNodes 几何计算回写的节点尺寸（NodeRole::Size 需要可读写存储）
    std::unordered_map<QtNodes::NodeId, QSize> nodeSizes_;
};

} // namespace rvc
