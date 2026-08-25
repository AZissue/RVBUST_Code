#pragma once

#include <QObject>
#include <QString>

#include <atomic>

namespace pcsearch::pipeline {
class Graph;
}

namespace app {

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

public slots:
    void run();

signals:
    // Emitted for each node that actually ran (not skipped), with its wall
    // clock time in milliseconds.
    void nodeFinished(const QString& id, double elapsed_ms);
    void finished(bool ok, const QString& error);

private:
    pcsearch::pipeline::Graph* graph_;
    std::atomic_bool cancel_{false};
};

}  // namespace app
