#pragma once

#include "pcsearch/core_data/object.h"

#include <QObject>
#include <QString>

#include <atomic>
#include <mutex>
#include <string>
#include <vector>

namespace pcsearch::pipeline {
class Graph;
}

namespace app {

// Latest display3d outputs captured at a block boundary during chunked
// execution. Objects are shared_ptr-backed, so the snapshot keeps the cloud
// data alive even after the graph drops the previous block's results.
struct DisplayEntry {
    std::string node_id;
    std::string viewport;
    pcsearch::core::ObjectList objects;
};

// Executes a pipeline Graph on a worker thread. The graph must not be
// mutated while the runner is active; the UI disables editing during
// execution and refreshes results from the `finished` signal.
class GraphRunner : public QObject {
    Q_OBJECT
public:
    explicit GraphRunner(pcsearch::pipeline::Graph* graph, QObject* parent = nullptr);
    // Ask the running graph to stop at the next node boundary. Safe to call
    // from any thread.
    void requestCancel() { cancel_.store(true); }
    // Thread-safe snapshot of the display3d outputs from the most recent
    // completed block (or the final run). Used by the UI to refresh layers
    // mid-stream without touching the graph's result map on another thread.
    std::vector<DisplayEntry> latestDisplay() const;

public slots:
    // `to_selected` runs the graph only up to `stop_node` (incremental: dirty
    // nodes are re-executed, everything upstream of the last change is
    // skipped). `false` runs the whole graph.
    void run(bool to_selected, const QString& stop_node);

signals:
    // Emitted for each node that actually ran (not skipped), with its wall
    // clock time in milliseconds.
    void nodeFinished(const QString& id, double elapsed_ms);
    // Emitted after each successful block of a chunked run (done/total
    // frames). The UI coalesces these to refresh display layers.
    void blockProgress(int done, int total);
    void finished(bool ok, const QString& error);

private:
    void captureDisplay();
    pcsearch::pipeline::Graph* graph_;
    std::atomic_bool cancel_{false};
    mutable std::mutex snapshot_mutex_;
    std::vector<DisplayEntry> snapshot_;
};

}  // namespace app
