#include "engine_runner.h"

#include "pcsearch/pipeline/graph.h"

namespace app {

GraphRunner::GraphRunner(pcsearch::pipeline::Graph* graph, QObject* parent)
    : QObject(parent), graph_(graph) {}

void GraphRunner::run() {
    cancel_.store(false);
    const bool ok = graph_->execute(&cancel_);
    for (const auto& [id, stats] : graph_->lastRunStats()) {
        if (stats.executed) {
            emit nodeFinished(QString::fromStdString(id), stats.elapsed_ms);
        }
    }
    emit finished(ok, QString::fromStdString(graph_->lastError()));
}

}  // namespace app
