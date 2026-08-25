#pragma once

#include "pcsearch/pipeline/node.h"

#include <functional>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace pcsearch::pipeline {

using NodeFactory = std::function<NodePtr()>;

struct NodeInfo {
    std::string type;
    std::string title;
    std::string category;
};

class NodeRegistry {
public:
    static NodeRegistry& instance();

    void registerNode(const std::string& type, const std::string& title,
                      const std::string& category, NodeFactory factory);

    NodePtr create(const std::string& type) const;
    bool contains(const std::string& type) const;
    std::vector<NodeInfo> all() const;

private:
    std::map<std::string, NodeInfo> info_;
    std::map<std::string, NodeFactory> factories_;
};

}  // namespace pcsearch::pipeline

