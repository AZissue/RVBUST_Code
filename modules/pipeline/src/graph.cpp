#include "pcsearch/pipeline/graph.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <queue>
#include <sstream>
#include <stdexcept>

namespace pcsearch::pipeline {

Node* Graph::addNode(const std::string& type) {
    NodePtr node = registry_->create(type);
    std::string base = type;
    std::string id = base;
    int counter = 1;
    while (nodes_.count(id)) {
        id = base + "_" + std::to_string(counter++);
    }
    node->setId(id);
    node->setup();
    const std::string nid = node->id();
    nodes_[nid] = std::move(node);
    node_order_.push_back(nid);
    dirty_.insert(nid);
    return nodes_[nid].get();
}

Node* Graph::addNode(const std::string& type, const std::string& explicit_id) {
    if (explicit_id.empty()) return addNode(type);
    if (nodes_.count(explicit_id)) return nullptr;
    NodePtr node = registry_->create(type);
    node->setId(explicit_id);
    node->setup();
    const std::string nid = node->id();
    nodes_[nid] = std::move(node);
    node_order_.push_back(nid);
    dirty_.insert(nid);
    return nodes_[nid].get();
}

void Graph::removeNode(const std::string& id) {
    nodes_.erase(id);
    results_.erase(id);
    dirty_.erase(id);
    failed_.erase(id);
    node_order_.erase(std::remove(node_order_.begin(), node_order_.end(), id),
                      node_order_.end());
    edges_.erase(std::remove_if(edges_.begin(), edges_.end(),
                                [&](const Edge& e) {
                                    return e.from_id == id || e.to_id == id;
                                }),
                 edges_.end());
}

void Graph::clear() {
    nodes_.clear();
    node_order_.clear();
    edges_.clear();
    results_.clear();
    dirty_.clear();
    failed_.clear();
    last_error_.clear();
    connect_error_.clear();
    last_run_stats_.clear();
}

Node* Graph::node(const std::string& id) const {
    const auto it = nodes_.find(id);
    return it == nodes_.end() ? nullptr : it->second.get();
}

std::vector<Node*> Graph::nodes() const {
    std::vector<Node*> out;
    out.reserve(node_order_.size());
    for (const auto& id : node_order_) {
        out.push_back(nodes_.at(id).get());
    }
    return out;
}

bool Graph::connect(const std::string& from_id, int from_port, const std::string& to_id,
                    int to_port) {
    if (!canConnect(from_id, from_port, to_id, to_port)) return false;
    // One connection per input port.
    edges_.erase(std::remove_if(edges_.begin(), edges_.end(),
                                [&](const Edge& e) {
                                    return e.to_id == to_id && e.to_port == to_port;
                                }),
                 edges_.end());
    edges_.push_back(Edge{from_id, from_port, to_id, to_port});
    markDirty(to_id);
    return true;
}

bool Graph::canConnect(const std::string& from_id, int from_port,
                       const std::string& to_id, int to_port) const {
    connect_error_.clear();
    Node* from = node(from_id);
    Node* to = node(to_id);
    if (!from || !to) {
        connect_error_ = "unknown node in connection";
        return false;
    }
    if (from_port < 0 || from_port >= static_cast<int>(from->outputCount())) {
        connect_error_ = "output port out of range";
        return false;
    }
    if (to_port < 0 || to_port >= static_cast<int>(to->inputCount())) {
        connect_error_ = "input port out of range";
        return false;
    }
    const std::string out_kind = from->outputKind(static_cast<std::size_t>(from_port));
    const std::string in_kind = to->inputKind(static_cast<std::size_t>(to_port));
    if (!kindsCompatible(out_kind, in_kind)) {
        connect_error_ = "port type mismatch: '" +
                         (out_kind.empty() ? "any" : out_kind) + "' -> '" +
                         (in_kind.empty() ? "any" : in_kind) + "'";
        return false;
    }
    return true;
}

bool Graph::kindsCompatible(const std::string& out_kind,
                            const std::string& in_kind) {
    if (out_kind.empty() || in_kind.empty()) return true;
    if (out_kind == in_kind) return true;
    if (out_kind == "any" || in_kind == "any") return true;
    return false;
}

bool Graph::disconnect(const std::string& from_id, int from_port,
                       const std::string& to_id, int to_port) {
    const auto before = edges_.size();
    edges_.erase(std::remove_if(edges_.begin(), edges_.end(),
                                [&](const Edge& e) {
                                    return e.from_id == from_id && e.from_port == from_port &&
                                           e.to_id == to_id && e.to_port == to_port;
                                }),
                 edges_.end());
    if (edges_.size() != before) {
        markDirty(to_id);
        return true;
    }
    return false;
}

void Graph::setParam(const std::string& node_id, const std::string& name,
                     ParamValue value) {
    Node* n = node(node_id);
    if (!n) throw std::runtime_error("unknown node: " + node_id);
    n->params().set(name, std::move(value));
    markDirty(node_id);
}

Params& Graph::params(const std::string& node_id) {
    Node* n = node(node_id);
    if (!n) throw std::runtime_error("unknown node: " + node_id);
    return n->params();
}

void Graph::propagateDirty(const std::string& seed) {
    dirty_.insert(seed);
    std::queue<std::string> q;
    q.push(seed);
    while (!q.empty()) {
        const std::string id = q.front();
        q.pop();
        for (const auto& e : edges_) {
            if (e.from_id == id && !dirty_.count(e.to_id)) {
                dirty_.insert(e.to_id);
                q.push(e.to_id);
            }
        }
    }
}

void Graph::markDirty(const std::string& node_id) {
    if (!node(node_id)) return;
    propagateDirty(node_id);
}

std::vector<std::string> Graph::topologicalOrder() {
    std::map<std::string, int> indegree;
    for (const auto& id : node_order_) indegree[id] = 0;
    for (const auto& e : edges_) {
        if (indegree.count(e.to_id)) ++indegree[e.to_id];
    }
    std::queue<std::string> q;
    for (const auto& [id, d] : indegree) {
        if (d == 0) q.push(id);
    }
    std::vector<std::string> order;
    while (!q.empty()) {
        const std::string id = q.front();
        q.pop();
        order.push_back(id);
        for (const auto& e : edges_) {
            if (e.from_id == id && --indegree[e.to_id] == 0) {
                q.push(e.to_id);
            }
        }
    }
    if (order.size() != node_order_.size()) {
        last_error_ = "graph contains a cycle";
        return {};
    }
    return order;
}

bool Graph::execute(std::atomic_bool* cancel) {
    last_error_.clear();
    last_run_stats_.clear();
    const std::vector<std::string> order = topologicalOrder();
    if (order.empty()) {
        return false;
    }

    for (const auto& id : order) {
        if (cancel && cancel->load()) {
            last_error_ = "execution cancelled";
            return false;
        }
        Node* n = nodes_[id].get();
        // Already computed and not dirty.
        if (!dirty_.count(id) && results_.count(id)) {
            last_run_stats_[id].skipped = true;
            continue;
        }
        if (failed_.count(id)) continue;

        std::vector<core::ObjectList> inputs(n->inputCount());
        bool input_failed = false;
        for (const auto& e : edges_) {
            if (e.to_id != id) continue;
            if (e.to_port < 0 || e.to_port >= static_cast<int>(inputs.size())) continue;
            const auto src_it = results_.find(e.from_id);
            if (src_it == results_.end() || failed_.count(e.from_id)) {
                input_failed = true;
                break;
            }
            if (e.from_port < static_cast<int>(src_it->second.size())) {
                inputs[static_cast<std::size_t>(e.to_port)] = src_it->second[static_cast<std::size_t>(e.from_port)];
            }
        }
        if (input_failed) {
            failed_.insert(id);
            last_error_ = "node '" + id + "' has an unavailable input";
            return false;
        }

        try {
            const auto start = std::chrono::steady_clock::now();
            std::vector<core::ObjectList> outs = n->executeAll(inputs, n->params());
            const auto end = std::chrono::steady_clock::now();
            last_run_stats_[id].elapsed_ms =
                std::chrono::duration<double, std::milli>(end - start).count();
            last_run_stats_[id].executed = true;
            results_[id] = std::move(outs);
            dirty_.erase(id);
            failed_.erase(id);
        } catch (const std::exception& e) {
            std::fprintf(stderr, "[debug] node '%s' failed: %s\n", id.c_str(), e.what());
            failed_.insert(id);
            results_.erase(id);
            last_error_ = "node '" + id + "' failed: " + e.what();
            return false;
        }
    }
    return true;
}

bool Graph::batchEnabled() const {
    for (const auto& [id, n] : nodes_) {
        if (n->batchEnabled()) return true;
    }
    return false;
}

std::int64_t Graph::batchChunkSize() const {
    std::int64_t k = 1;
    for (const auto& [id, n] : nodes_) {
        if (n->batchEnabled()) k = std::max(k, n->batchChunkSize());
    }
    return k;
}

bool Graph::executeChunked(std::int64_t chunk_size, std::atomic_bool* cancel) {
    if (chunk_size <= 0) chunk_size = 1;
    std::int64_t total = 0;
    for (const auto& [id, n] : nodes_) {
        if (n->batchEnabled()) total = std::max(total, n->batchTotal());
    }
    // Nothing batchable (or an empty batch): one normal pass. Empty source
    // lists then propagate as empty output (PROJECT §8.3.4), no error.
    if (total <= 0) return execute(cancel);

    last_error_.clear();
    std::int64_t start = 0;
    bool ok = true;
    while (start < total) {
        if (cancel && cancel->load()) {
            last_error_ = "execution cancelled";
            ok = false;
            break;
        }
        for (const auto& [id, n] : nodes_) {
            // Every node sees the block window: source nodes use it to read
            // the right frames, downstream nodes use batch_start for stable
            // cross-block naming. Nodes that are not batch sources ignore the
            // window when they have nothing to read (see LoadCloudNode).
            n->setContext(NodeContext{start, chunk_size, total});
        }
        // Wipe results and dirty state so every node re-runs for this block;
        // after the loop only the last block's results are retained.
        clearResults();
        if (!execute(cancel)) {
            ok = false;
            break;
        }
        start += chunk_size;
    }
    for (const auto& [id, n] : nodes_) n->setContext(NodeContext{});
    return ok;
}

const core::ObjectList* Graph::output(const std::string& node_id, int port) const {
    const auto it = results_.find(node_id);
    if (it == results_.end()) return nullptr;
    if (port < 0 || port >= static_cast<int>(it->second.size())) return nullptr;
    return &it->second[static_cast<std::size_t>(port)];
}

bool Graph::hasFailed(const std::string& node_id) const {
    return failed_.count(node_id) > 0;
}

void Graph::clearResults() {
    results_.clear();
    failed_.clear();
    dirty_.clear();
    for (const auto& [id, node] : nodes_) {
        dirty_.insert(id);
    }
}

}  // namespace pcsearch::pipeline
