#pragma once

// 流程（Process）：模块实例有向图。
// 真实执行图，可无头运行；画布（QtNodes）只是它的 UI 投影。

#include <map>
#include <memory>
#include <string>
#include <vector>

#include "ModuleBase.h"
#include "ModuleRegistry.h"

namespace rvc {

// 流程节点：一个模块实例 + 画布位置
struct ProcessNode {
    int       id = -1;
    std::string typeId;
    ModulePtr module;
    double    x = 0.0;  // 画布坐标（供 Solution 保存/恢复布局）
    double    y = 0.0;
};

// 连线 = 订阅：上游节点输出端口 → 下游节点输入端口
struct ProcessLink {
    int        fromNode = -1;
    std::string fromPort;
    int        toNode = -1;
    std::string toPort;
};

class Process {
public:
    // ---- 图构建 ----

    // 按类型 ID 创建模块实例并加入流程；失败（未知类型）返回 -1
    int addNode(const std::string& typeId);

    // 以指定 ID 添加节点（Solution 加载时保持文件中的节点 ID）；
    // 未知类型或 ID 冲突返回 -1
    int addNodeWithId(const std::string& typeId, int id);

    // 删除节点及其所有连线
    bool removeNode(int nodeId);

    // 连线前校验：端口存在、方向正确、数据类型一致、不成环
    bool canConnect(int fromNode, const std::string& fromPort,
                    int toNode, const std::string& toPort, std::string* err = nullptr) const;

    // 建立连线（内部调用 canConnect 校验）
    bool addLink(int fromNode, const std::string& fromPort,
                 int toNode, const std::string& toPort, std::string* err = nullptr);

    bool removeLink(int fromNode, const std::string& fromPort,
                    int toNode, const std::string& toPort);

    void clear();

    // ---- 查询 ----

    const std::map<int, ProcessNode>& nodes() const { return nodes_; }
    const std::vector<ProcessLink>& links() const { return links_; }

    ProcessNode* node(int id);
    const ProcessNode* node(int id) const;
    ModuleBase* module(int id);

    void setNodePosition(int id, double x, double y);

    // 拓扑排序（Kahn）。检测到环时返回空表并填 err。
    std::vector<int> topologicalOrder(std::string* err = nullptr) const;

    // ---- 输出端口值缓存（一次运行内有效，供下游模块读取）----

    void clearOutputCache() { outputCache_.clear(); }
    void setCachedOutput(int nodeId, const std::string& port, PortValue value)
    {
        outputCache_[{nodeId, port}] = std::move(value);
    }
    bool hasCachedOutput(int nodeId, const std::string& port) const
    {
        return outputCache_.count({nodeId, port}) > 0;
    }
    PortValue cachedOutput(int nodeId, const std::string& port) const
    {
        auto it = outputCache_.find({nodeId, port});
        return it != outputCache_.end() ? it->second : PortValue{};
    }

private:
    // 从 fromNode 沿连线反向可达 toNode 则为 true（用于成环检测）
    bool reachable(int fromNode, int toNode) const;

    int nextNodeId_ = 1;
    std::map<int, ProcessNode> nodes_;
    std::vector<ProcessLink>   links_;

    using CacheKey = std::pair<int, std::string>;
    std::map<CacheKey, PortValue> outputCache_;
};

} // namespace rvc
