#include "Process.h"

#include <deque>
#include <set>

namespace rvc {

int Process::addNode(const std::string& typeId)
{
    ModulePtr module = ModuleRegistry::instance().create(typeId);
    if (!module)
        return -1;

    ProcessNode node;
    node.id = nextNodeId_++;
    node.typeId = typeId;
    node.module = std::move(module);
    const int id = node.id;
    nodes_.emplace(id, std::move(node));
    return id;
}

int Process::addNodeWithId(const std::string& typeId, int id)
{
    if (nodes_.count(id))
        return -1;
    ModulePtr module = ModuleRegistry::instance().create(typeId);
    if (!module)
        return -1;

    ProcessNode node;
    node.id = id;
    node.typeId = typeId;
    node.module = std::move(module);
    nodes_.emplace(id, std::move(node));
    if (id >= nextNodeId_)
        nextNodeId_ = id + 1;
    return id;
}

bool Process::removeNode(int nodeId)
{
    if (!nodes_.count(nodeId))
        return false;

    // 删除与该节点相连的所有连线
    std::vector<ProcessLink> kept;
    kept.reserve(links_.size());
    for (const auto& l : links_) {
        if (l.fromNode != nodeId && l.toNode != nodeId)
            kept.push_back(l);
    }
    links_ = std::move(kept);

    nodes_.erase(nodeId);
    return true;
}

ProcessNode* Process::node(int id)
{
    auto it = nodes_.find(id);
    return it != nodes_.end() ? &it->second : nullptr;
}

const ProcessNode* Process::node(int id) const
{
    auto it = nodes_.find(id);
    return it != nodes_.end() ? &it->second : nullptr;
}

ModuleBase* Process::module(int id)
{
    ProcessNode* n = node(id);
    return n ? n->module.get() : nullptr;
}

void Process::setNodePosition(int id, double x, double y)
{
    if (ProcessNode* n = node(id)) {
        n->x = x;
        n->y = y;
    }
}

bool Process::reachable(int fromNode, int toNode) const
{
    // BFS 沿连线方向（from → to）
    std::deque<int> queue{fromNode};
    std::set<int> visited{fromNode};
    while (!queue.empty()) {
        const int cur = queue.front();
        queue.pop_front();
        if (cur == toNode)
            return true;
        for (const auto& l : links_) {
            if (l.fromNode == cur && !visited.count(l.toNode)) {
                visited.insert(l.toNode);
                queue.push_back(l.toNode);
            }
        }
    }
    return false;
}

bool Process::canConnect(int fromNode, const std::string& fromPort,
                         int toNode, const std::string& toPort, std::string* err) const
{
    auto fail = [err](const std::string& msg) {
        if (err) *err = msg;
        return false;
    };

    if (fromNode == toNode)
        return fail("cannot connect a node to itself");

    const ProcessNode* from = node(fromNode);
    const ProcessNode* to = node(toNode);
    if (!from || !to)
        return fail("node not found");

    // 上游端口必须是其输出端口，下游端口必须是其输入端口
    DataType outType{};
    bool found = false;
    for (const auto& p : from->module->outputPorts()) {
        if (p.name == fromPort) { outType = p.type; found = true; break; }
    }
    if (!found)
        return fail("source port is not an output port of the upstream module");

    DataType inType{};
    found = false;
    for (const auto& p : to->module->inputPorts()) {
        if (p.name == toPort) { inType = p.type; found = true; break; }
    }
    if (!found)
        return fail("target port is not an input port of the downstream module");

    // 类型校验：PointCloud 只能连 PointCloud，以此类推
    if (outType != inType)
        return fail(std::string("port type mismatch: ") + dataTypeName(outType) +
                    " -> " + dataTypeName(inType));

    // 一个输入端口只允许一个订阅来源
    for (const auto& l : links_) {
        if (l.toNode == toNode && l.toPort == toPort)
            return fail("input port already connected");
    }

    // 成环检测：若 toNode 已可达 fromNode，则新连线会构成环
    if (reachable(toNode, fromNode))
        return fail("connection would create a cycle");

    return true;
}

bool Process::addLink(int fromNode, const std::string& fromPort,
                      int toNode, const std::string& toPort, std::string* err)
{
    if (!canConnect(fromNode, fromPort, toNode, toPort, err))
        return false;
    links_.push_back(ProcessLink{fromNode, fromPort, toNode, toPort});
    return true;
}

bool Process::removeLink(int fromNode, const std::string& fromPort,
                         int toNode, const std::string& toPort)
{
    for (auto it = links_.begin(); it != links_.end(); ++it) {
        if (it->fromNode == fromNode && it->fromPort == fromPort &&
            it->toNode == toNode && it->toPort == toPort) {
            links_.erase(it);
            return true;
        }
    }
    return false;
}

void Process::clear()
{
    nodes_.clear();
    links_.clear();
    outputCache_.clear();
    nextNodeId_ = 1;
}

std::vector<int> Process::topologicalOrder(std::string* err) const
{
    // Kahn 算法
    std::map<int, int> inDegree;
    for (const auto& [id, n] : nodes_)
        inDegree[id] = 0;
    for (const auto& l : links_)
        inDegree[l.toNode] += 1;

    std::deque<int> queue;
    for (const auto& [id, deg] : inDegree) {
        if (deg == 0)
            queue.push_back(id);
    }

    std::vector<int> order;
    order.reserve(nodes_.size());
    while (!queue.empty()) {
        const int cur = queue.front();
        queue.pop_front();
        order.push_back(cur);
        for (const auto& l : links_) {
            if (l.fromNode == cur) {
                if (--inDegree[l.toNode] == 0)
                    queue.push_back(l.toNode);
            }
        }
    }

    if (order.size() != nodes_.size()) {
        if (err)
            *err = "process graph contains a cycle";
        return {};
    }
    return order;
}

} // namespace rvc
