#include "engine_runner.h"

#include "pcsearch/pipeline/graph.h"

namespace app {

GraphRunner::GraphRunner(pcsearch::pipeline::Graph* graph, QObject* parent)
    : QObject(parent), graph_(graph) {}

void GraphRunner::run(bool to_selected, const QString& stop_node) {
    cancel_.store(false);
    const std::string stop = stop_node.toStdString();
    const std::string* stop_ptr =
        (to_selected && !stop.empty()) ? &stop : nullptr;
    bool ok = false;
    if (graph_->batchEnabled()) {
        // Chunked batch execution (PROJECT §8.4): K comes from the graph's
        // batch-enabled source node (load_cloud stream/chunked mode).
        const auto on_block = [this](std::int64_t done, std::int64_t total) {
            captureDisplay();
            emit blockProgress(static_cast<int>(done), static_cast<int>(total));
        };
        ok = graph_->executeChunked(graph_->batchChunkSize(), &cancel_, on_block,
                                    stop_ptr);
    } else if (stop_ptr) {
        ok = graph_->executeThrough(*stop_ptr, &cancel_);
    } else {
        ok = graph_->execute(&cancel_);
    }
    captureDisplay();
    for (const auto& [id, stats] : graph_->lastRunStats()) {
        if (stats.executed) {
            emit nodeFinished(QString::fromStdString(id), stats.elapsed_ms);
        }
    }
    emit finished(ok, QString::fromStdString(graph_->lastError()));
}

void GraphRunner::captureDisplay() {
    std::vector<DisplayEntry> snap;
    for (auto* node : graph_->nodes()) {
        if (node->type() != "display3d") continue;
        const auto* out = graph_->output(node->id());
        if (!out) continue;
        DisplayEntry entry;
        entry.node_id = node->id();
        entry.viewport = node->params().getString("viewport");
        entry.objects = *out;
        snap.push_back(std::move(entry));
    }
    {
        std::lock_guard<std::mutex> lock(snapshot_mutex_);
        snapshot_ = std::move(snap);
    }
}

std::vector<DisplayEntry> GraphRunner::latestDisplay() const {
    std::lock_guard<std::mutex> lock(snapshot_mutex_);
    return snapshot_;
}

}  // namespace app
