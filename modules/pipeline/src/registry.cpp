#include "pcsearch/pipeline/registry.h"

#include <stdexcept>

namespace pcsearch::pipeline {

NodeRegistry& NodeRegistry::instance() {
    static NodeRegistry registry;
    return registry;
}

void NodeRegistry::registerNode(const std::string& type, const std::string& title,
                                const std::string& category, NodeFactory factory) {
    info_[type] = NodeInfo{type, title, category};
    factories_[type] = std::move(factory);
}

NodePtr NodeRegistry::create(const std::string& type) const {
    const auto it = factories_.find(type);
    if (it == factories_.end()) {
        throw std::runtime_error("unknown node type: " + type);
    }
    return it->second();
}

bool NodeRegistry::contains(const std::string& type) const {
    return factories_.count(type) > 0;
}

std::vector<NodeInfo> NodeRegistry::all() const {
    std::vector<NodeInfo> out;
    out.reserve(info_.size());
    for (const auto& [type, info] : info_) {
        out.push_back(info);
    }
    return out;
}

}  // namespace pcsearch::pipeline

