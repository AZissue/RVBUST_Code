#pragma once

#include "pcsearch/core_data/object.h"
#include "pcsearch/pipeline/node.h"
#include "pcsearch/pipeline/registry.h"

#include <atomic>
#include <functional>
#include <map>
#include <set>
#include <string>
#include <vector>

namespace pcsearch::pipeline {

struct Edge {
    std::string from_id;
    int from_port = 0;
    std::string to_id;
    int to_port = 0;
};

struct NodeRunStats {
    double elapsed_ms = 0.0;
    bool executed = false;
    bool skipped = false;
};

// Called after each successful block of a chunked execution with the number
// of processed frames and the total frame count (PROJECT §8.4 progress).
using BlockProgressFn = std::function<void(std::int64_t done, std::int64_t total)>;

class Graph {
public:
    explicit Graph(NodeRegistry* registry = &NodeRegistry::instance())
        : registry_(registry) {}

    Node* addNode(const std::string& type);
    // Add a node with an explicit id (used when loading solutions). Fails
    // (returns nullptr) if the id is already taken or the type is unknown.
    Node* addNode(const std::string& type, const std::string& explicit_id);
    void removeNode(const std::string& id);
    // Remove every node and edge (used when loading a solution).
    void clear();
    Node* node(const std::string& id) const;
    std::vector<Node*> nodes() const;

    bool connect(const std::string& from_id, int from_port, const std::string& to_id,
                 int to_port);
    // Check whether a connection is legal (nodes/ports exist, kinds match)
    // without modifying the graph. Fills connectError() on failure.
    bool canConnect(const std::string& from_id, int from_port,
                    const std::string& to_id, int to_port) const;
    bool disconnect(const std::string& from_id, int from_port, const std::string& to_id,
                    int to_port);
    const std::vector<Edge>& edges() const { return edges_; }

    void setParam(const std::string& node_id, const std::string& name,
                  ParamValue value);
    Params& params(const std::string& node_id);

    // Mark a node (and everything downstream) for recomputation.
    void markDirty(const std::string& node_id);
    // Run the graph. Returns false and records lastError() on failure.
    // `cancel` (optional) is checked between nodes so a UI shutdown can stop
    // a long run instead of destroying the worker thread mid-execution.
    bool execute(std::atomic_bool* cancel = nullptr);
    // Chunked batch execution: repeatedly runs the graph over windows of
    // `chunk_size` frames from every batch-enabled source node (PROJECT §8.4),
    // fail-fast on the first failing block. Results keep only the last block
    // (the display shows the block's last frame). Falls back to execute()
    // when no source reports batchEnabled().
    bool executeChunked(std::int64_t chunk_size, std::atomic_bool* cancel = nullptr,
                        const BlockProgressFn& on_block = {});
    // True when any node in the graph drives chunked batch execution.
    bool batchEnabled() const;
    // Largest K requested by the graph's batch-enabled sources.
    std::int64_t batchChunkSize() const;
    const core::ObjectList* output(const std::string& node_id, int port = 0) const;
    bool hasFailed(const std::string& node_id) const;
    std::string lastError() const { return last_error_; }
    void markError(const std::string& message) { last_error_ = message; }
    std::string connectError() const { return connect_error_; }
    const std::map<std::string, NodeRunStats>& lastRunStats() const {
        return last_run_stats_;
    }
    void clearResults();

private:
    std::vector<std::string> topologicalOrder();
    void propagateDirty(const std::string& seed);
    static bool kindsCompatible(const std::string& out_kind,
                                const std::string& in_kind);

    NodeRegistry* registry_;
    std::map<std::string, NodePtr> nodes_;
    std::vector<std::string> node_order_;
    std::vector<Edge> edges_;

    std::map<std::string, std::vector<core::ObjectList>> results_;
    std::set<std::string> dirty_;
    std::set<std::string> failed_;
    std::string last_error_;
    mutable std::string connect_error_;
    std::map<std::string, NodeRunStats> last_run_stats_;
};

}  // namespace pcsearch::pipeline
