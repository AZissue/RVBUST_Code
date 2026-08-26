#include "main_window.h"

#include "pcsearch/pipeline/nodes/core_nodes.h"

#include <QApplication>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QSurfaceFormat>
#include <QTemporaryDir>
#include <QTreeWidget>
#include <QtTest/QtTest>

#ifdef PCSEARCH_HAS_VTK
#include <QVTKOpenGLNativeWidget.h>
#endif

#include <fstream>
#include <string>

namespace {

// A real MainWindow needs VTK, but the assertions in this file only inspect
// the cloud-properties tree selection and the viewport's display layers, both
// of which are regular Qt state (layers exist even before any GL frame).
class MainWindowTest : public QObject {
    Q_OBJECT

private slots:
    void initTestCase();

    // load_cloud has no real inputs ("(no inputs)" placeholder only), so
    // "Select All" must fall back to the output group. Regression: it picked
    // the empty input group, selected nothing, and the 3D view cleared.
    void selectAllFallsBackToOutputsForSourceNode();
    // A node with real input rows keeps the "inputs drive the view" default;
    // Select All must leave a non-empty selection and a selection layer.
    void selectAllKeepsInputsForFilterNode();
    // With no node selected the tree lists every node's first output directly
    // under the node root (no group/port layers); Select All must still work.
    void selectAllSelectsFallbackListWhenNothingSelected();

private:
    QString writePly(QTemporaryDir& dir) const;
    QTreeWidget* propsTree(app::MainWindow& w) const;
    QPushButton* selectAllButton(app::MainWindow& w) const;
    QPlainTextEdit* logView(app::MainWindow& w) const;
    bool waitForRun(app::MainWindow& w, int timeout_ms = 15000) const;
};

void MainWindowTest::initTestCase() {
    pcsearch::pipeline::registerCoreNodes();
    // Warm the PCL loader on the main thread: on this machine, first-time DLL
    // resolution of the PCL readers inside a worker thread deadlocks in ALPC
    // when the process already hosts a VTK/OpenGL context (the same reason
    // ctest needs the cmake -P wrapper). A tiny synchronous graph run in the
    // main thread forces the DLLs to load before the async runner touches them.
    QTemporaryDir dir;
    if (!dir.isValid()) return;
    const QString ply = dir.filePath("warm.ply");
    {
        std::ofstream out(ply.toStdString());
        out << "ply\n"
            << "format ascii 1.0\n"
            << "element vertex 1\n"
            << "property float x\n"
            << "property float y\n"
            << "property float z\n"
            << "end_header\n"
            << "1 2 3\n";
    }
    pcsearch::pipeline::Graph g;
    auto* load = g.addNode("load_cloud");
    g.setParam(load->id(), "path",
               pcsearch::pipeline::ParamValue{ply.toStdString()});
    QVERIFY2(g.execute(), g.lastError().c_str());
}

QString MainWindowTest::writePly(QTemporaryDir& dir) const {
    const QString path = dir.filePath("tiny.ply");
    std::ofstream out(path.toStdString());
    out << "ply\n"
        << "format ascii 1.0\n"
        << "element vertex 3\n"
        << "property float x\n"
        << "property float y\n"
        << "property float z\n"
        << "end_header\n"
        << "0 0 0\n"
        << "10 0 0\n"
        << "0 10 0\n";
    return path;
}

QTreeWidget* MainWindowTest::propsTree(app::MainWindow& w) const {
    for (QTreeWidget* tree : w.findChildren<QTreeWidget*>()) {
        const QString head = tree->headerItem()->text(0);
        if (head == QLatin1String("Object") || head == QString::fromUtf8("对象")) {
            return tree;
        }
    }
    return nullptr;
}

QPushButton* MainWindowTest::selectAllButton(app::MainWindow& w) const {
    for (QPushButton* b : w.findChildren<QPushButton*>()) {
        const QString text = b->text();
        if (text == QLatin1String("Select All") || text == QString::fromUtf8("全选")) {
            return b;
        }
    }
    return nullptr;
}

QPlainTextEdit* MainWindowTest::logView(app::MainWindow& w) const {
    return w.findChild<QPlainTextEdit*>();
}

bool MainWindowTest::waitForRun(app::MainWindow& w, int timeout_ms) const {
    QElapsedTimer timer;
    timer.start();
    const QString done = QLatin1String("Graph executed successfully");
    while (timer.elapsed() < timeout_ms) {
        QTest::qWait(25);
        QPlainTextEdit* log = logView(w);
        if (log && log->toPlainText().contains(done)) return true;
        if (log && log->toPlainText().contains(QLatin1String("Graph execution failed"))) {
            qWarning() << "graph run failed:" << log->toPlainText();
            return false;
        }
    }
    qWarning() << "timed out waiting for graph run; log so far:\n"
               << (logView(w) ? logView(w)->toPlainText() : QStringLiteral("<no log view>"));
    return false;
}

void MainWindowTest::selectAllFallsBackToOutputsForSourceNode() {
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString ply = writePly(dir);
    app::MainWindow w;
    QVERIFY(w.loadDemo(ply));
    w.runGraph();
    QVERIFY(waitForRun(w));

    // Select the load_cloud source node: its tree has an input group that only
    // contains the "(no inputs)" placeholder row.
    QTreeWidget* tree = propsTree(w);
    QVERIFY(tree);
    QPushButton* button = selectAllButton(w);
    QVERIFY(button);

    // Pick the load_cloud node id from the canvas tree (all nodes listed
    // in insertion order; the demo graph starts with load_cloud).
    QTreeWidget* canvas = nullptr;
    for (QTreeWidget* t : w.findChildren<QTreeWidget*>()) {
        const QString head = t->headerItem()->text(0);
        if (head == QLatin1String("Node") || head == QString::fromUtf8("节点")) {
            canvas = t;
            break;
        }
    }
    QVERIFY(canvas);
    const QString load_id = canvas->topLevelItem(0)->text(0);
    QMetaObject::invokeMethod(&w, "doSelectNode", Qt::DirectConnection,
                              Q_ARG(QString, load_id));
    QTest::qWait(50);

    button->click();
    QTest::qWait(50);

    const int selected = tree->selectedItems().size();
    QVERIFY2(selected > 0,
             "Select All on a source node must select its output frames, "
             "not clear the 3D view");
}

void MainWindowTest::selectAllKeepsInputsForFilterNode() {
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString ply = writePly(dir);
    app::MainWindow w;
    QVERIFY(w.loadDemo(ply));
    w.runGraph();
    QVERIFY(waitForRun(w));

    // loadDemo selects the box_roi node, which has real input rows after the
    // run. Select All must keep a non-empty selection.
    QTreeWidget* tree = propsTree(w);
    QVERIFY(tree);
    QPushButton* button = selectAllButton(w);
    QVERIFY(button);
    QVERIFY2(tree->selectedItems().size() > 0,
             "default selection after run must show the node inputs");
    button->click();
    QTest::qWait(50);
    QVERIFY2(tree->selectedItems().size() > 0,
             "Select All on a node with inputs must not empty the selection");
}

void MainWindowTest::selectAllSelectsFallbackListWhenNothingSelected() {
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString ply = writePly(dir);
    app::MainWindow w;
    QVERIFY(w.loadDemo(ply));
    w.runGraph();
    QVERIFY(waitForRun(w));

    // Delete the selected box_roi node: the tree falls back to one root per
    // node with object rows directly under the root.
    QTreeWidget* tree = propsTree(w);
    QVERIFY(tree);
    const QString roi_id = tree->topLevelItem(0)->text(0);
    QMetaObject::invokeMethod(&w, "doDeleteNode", Qt::DirectConnection,
                              Q_ARG(QString, roi_id));
    QTest::qWait(50);

    QPushButton* button = selectAllButton(w);
    QVERIFY(button);
    button->click();
    QTest::qWait(50);

    const int selected = tree->selectedItems().size();
    QVERIFY2(selected > 0,
             "Select All with no node selected must select the listed outputs, "
             "not clear the 3D view");
}

}  // namespace

int main(int argc, char** argv) {
#ifdef PCSEARCH_HAS_VTK
    QSurfaceFormat::setDefaultFormat(QVTKOpenGLNativeWidget::defaultFormat());
#endif
    QApplication app(argc, argv);
    MainWindowTest tc;
    QTEST_SET_MAIN_SOURCE_PATH
    return QTest::qExec(&tc, argc, argv);
}

#include "test_main_window.moc"
