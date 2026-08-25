#include "engine_runner.h"

#include "pcsearch/pipeline/graph.h"

namespace app {

GraphRunner::GraphRunner(pcsearch::pipeline::Graph* graph, QObject* parent)
    : QObject(parent), graph_(graph) {}

void GraphRunner::run() {
    cancel_.store(false);
    bool ok = false;
    if (graph_->batchEnabled()) {
        // Chunked batch execution (PROJECT §8.4): K comes from the graph's
        // batch-enabled source node (load_cloud stream/chunked mode).
        ok = graph_->executeChunked(graph_->batchChunkSize(), &cancel_);
    } else {
        ok = graph_->execute(&cancel_);
    }
    for (const auto& [id, stats] : graph_->lastRunStats()) {
        if (stats.executed) {
            emit nodeFinished(QString::fromStdString(id), stats.elapsed_ms);
        }
    }
    emit finished(ok, QString::fromStdString(graph_->lastError()));
}

}  // namespace app
