#include "main_window.h"
#include "node_flow_widget.h"
#include "toolbox_widget.h"

#include "pcsearch/pipeline/nodes/core_nodes.h"

#include <QApplication>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QStackedWidget>
#include <QSurfaceFormat>
#include <QTemporaryDir>
#include <QTreeWidget>
#include <QWheelEvent>
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
    // After "run to node", the properties panel must default to the selected
    // node's outputs (the just-computed result), not its inputs.
    void runToNodeDefaultsToOutputs();
    // Zoom-out auto-switches the canvas to the read-only outline; Ctrl+wheel-up
    // over the outline (or the layout buttons) must switch back.
    void canvasZoomOutSwitchesToOutlineAndBack();

private:
    QString writePly(QTemporaryDir& dir) const;
    QTreeWidget* canvasTree(app::MainWindow& w) const;
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

namespace {
void sendWheel(QWidget* target, int angle_delta, Qt::KeyboardModifiers mods) {
    const QPointF pos(target->rect().center());
    QWheelEvent ev(pos, target->mapToGlobal(pos.toPoint()), QPoint(0, 0),
                   QPoint(0, angle_delta), Qt::NoButton, mods,
                   Qt::NoScrollPhase, false);
    QApplication::sendEvent(target, &ev);
}
}  // namespace

QTreeWidget* MainWindowTest::propsTree(app::MainWindow& w) const {
    for (QTreeWidget* tree : w.findChildren<QTreeWidget*>()) {
        const QString head = tree->headerItem()->text(0);
        if (head == QLatin1String("Object") || head == QString::fromUtf8("对象")) {
            return tree;
        }
    }
    return nullptr;
}

QTreeWidget* MainWindowTest::canvasTree(app::MainWindow& w) const {
    for (QTreeWidget* t : w.findChildren<QTreeWidget*>()) {
        const QString head = t->headerItem()->text(0);
        if (head == QLatin1String("Node") || head == QString::fromUtf8("节点")) {
            return t;
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
    const QString failed = QLatin1String("Graph execution failed");
    QPlainTextEdit* log = logView(w);
    const int done_before = log ? log->toPlainText().count(done) : 0;
    const int failed_before = log ? log->toPlainText().count(failed) : 0;
    while (timer.elapsed() < timeout_ms) {
        QTest::qWait(25);
        if (log && log->toPlainText().count(done) > done_before) return true;
        if (log && log->toPlainText().count(failed) > failed_before) {
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
    QTreeWidget* canvas = canvasTree(w);
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

void MainWindowTest::runToNodeDefaultsToOutputs() {
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString ply = writePly(dir);
    app::MainWindow w;
    QVERIFY(w.loadDemo(ply));
    w.runGraph();
    QVERIFY(waitForRun(w));

    QTreeWidget* canvas = canvasTree(w);
    QVERIFY(canvas);
    const QString load_id = canvas->topLevelItem(0)->text(0);
    const QString roi_id = canvas->topLevelItem(1)->text(0);

    // loadDemo already selected box_roi; re-run only up to it.
    w.runGraph(true);
    QVERIFY(waitForRun(w));

    QTreeWidget* tree = propsTree(w);
    QVERIFY(tree);
    const QList<QTreeWidgetItem*> selected = tree->selectedItems();
    QVERIFY2(selected.size() > 0, "run-to-node must leave a non-empty selection");
    for (QTreeWidgetItem* item : selected) {
        QVERIFY2(item->text(3) == roi_id,
                 "run-to-node default selection must show the node outputs");
    }

    // The Select All button keeps its meaning: it falls back to the input
    // group (upstream source) again.
    QPushButton* button = selectAllButton(w);
    QVERIFY(button);
    button->click();
    QTest::qWait(50);
    const QList<QTreeWidgetItem*> after = tree->selectedItems();
    QVERIFY2(after.size() > 0, "Select All after run-to-node must keep a selection");
    for (QTreeWidgetItem* item : after) {
        QVERIFY2(item->text(3) == load_id,
                 "Select All must select the input group again");
    }
}

void MainWindowTest::canvasZoomOutSwitchesToOutlineAndBack() {
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString ply = writePly(dir);
    app::MainWindow w;
    QVERIFY(w.loadDemo(ply));

    auto* flow = w.findChild<app::NodeFlowWidget*>();
    QVERIFY(flow);
    auto* stack = w.findChild<QStackedWidget*>();
    QVERIFY(stack);
    QCOMPARE(stack->currentWidget(), static_cast<QWidget*>(flow));

    // Ctrl+wheel out far enough (10 notches of 1/1.15) to cross 0.35.
    for (int i = 0; i < 10; ++i) {
        sendWheel(flow->viewport(), -240, Qt::ControlModifier);
    }
    QTest::qWait(20);
    QVERIFY2(stack->currentWidget() != static_cast<QWidget*>(flow),
             "zoom-out must switch to the outline layout");

    auto* toolbox = w.findChild<app::ToolboxWidget*>();
    QVERIFY(toolbox);
    QVERIFY2(!toolbox->isEnabled(),
             "outline layout must be read-only (no node placement)");

    // Ctrl+wheel-up over the outline returns to the canvas.
    QTreeWidget* outline = canvasTree(w);
    QVERIFY(outline);
    sendWheel(outline->viewport(), 240, Qt::ControlModifier);
    QTest::qWait(20);
    QCOMPARE(stack->currentWidget(), static_cast<QWidget*>(flow));
    QVERIFY(toolbox->isEnabled());
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
