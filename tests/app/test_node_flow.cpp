#include "node_flow_widget.h"
#include "node_titles.h"
#include "params_panel.h"
#include "point_cloud_view.h"

#include "pcsearch/pipeline/graph.h"
#include "pcsearch/pipeline/nodes/core_nodes.h"

#include <QImage>
#include <QComboBox>
#include <QLineEdit>
#include <QPushButton>
#include <QSignalSpy>
#include <QSpinBox>
#include <QtTest/QtTest>

#include <filesystem>
#include <cmath>
#include <string>

namespace {

using pcsearch::pipeline::Graph;

}  // namespace

class NodeFlowTest : public QObject {
    Q_OBJECT
private slots:
    void initTestCase() { pcsearch::pipeline::registerCoreNodes(); }

    void dragConnect() {
        Graph g;
        auto* load = g.addNode("load_cloud");
        auto* zf = g.addNode("z_filter");
        app::NodeFlowWidget w;
        w.setGraph(&g);
        w.addNode(load, QPointF(10, 10));
        w.addNode(zf, QPointF(310, 10));
        w.resize(800, 400);

        const QPointF a = w.outputPortPos(load->id(), 0);
        const QPointF b = w.inputPortPos(zf->id(), 0);
        // Port centers sit on the node edge; click 2px inside the port circle.
        const QPoint va = w.mapFromScene(a - QPointF(2, 0));
        const QPoint vb = w.mapFromScene(b);

        QSignalSpy status_spy(&w, &app::NodeFlowWidget::statusMessage);
        QSignalSpy spy(&w, &app::NodeFlowWidget::connectionRequested);
        QTest::mousePress(w.viewport(), Qt::LeftButton, Qt::NoModifier, va);
        QTest::mouseMove(w.viewport(), vb);
        QTest::mouseRelease(w.viewport(), Qt::LeftButton, Qt::NoModifier, vb);

        QCOMPARE(spy.count(), 1);
        QCOMPARE(spy.first().at(0).toString(), QString::fromStdString(load->id()));
        QCOMPARE(spy.first().at(1).toInt(), 0);
        QCOMPARE(spy.first().at(2).toString(), QString::fromStdString(zf->id()));
        QCOMPARE(spy.first().at(3).toInt(), 0);
    }

    void dragToEmptySpaceKeepsPending() {
        Graph g;
        auto* load = g.addNode("load_cloud");
        app::NodeFlowWidget w;
        w.setGraph(&g);
        w.addNode(load, QPointF(0, 0));
        w.resize(600, 300);

        const QPointF a = w.outputPortPos(load->id(), 0);
        const QPoint va = w.mapFromScene(a);
        QSignalSpy spy(&w, &app::NodeFlowWidget::connectionRequested);
        QTest::mousePress(w.viewport(), Qt::LeftButton, Qt::NoModifier, va);
        QTest::mouseMove(w.viewport(), va + QPoint(200, 200));
        QTest::mouseRelease(w.viewport(), Qt::LeftButton, Qt::NoModifier,
                            va + QPoint(200, 200));
        QCOMPARE(spy.count(), 0);
    }

    void deleteKeyEmitsRequest() {
        Graph g;
        auto* load = g.addNode("load_cloud");
        app::NodeFlowWidget w;
        w.setGraph(&g);
        w.addNode(load, QPointF(0, 0));
        w.resize(600, 300);

        w.selectNode(load->id());
        QSignalSpy spy(&w, &app::NodeFlowWidget::nodeDeleteRequested);
        w.setFocus();
        QTest::keyClick(&w, Qt::Key_Delete);
        QCOMPARE(spy.count(), 1);
        QCOMPARE(spy.first().at(0).toString(), QString::fromStdString(load->id()));

        w.removeNode(load->id());
        QCOMPARE(w.nodeCount(), 0);
    }

    void dragNodeMovesEdge() {
        Graph g;
        auto* load = g.addNode("load_cloud");
        auto* zf = g.addNode("z_filter");
        app::NodeFlowWidget w;
        w.setGraph(&g);
        w.addNode(load, QPointF(10, 10));
        w.addNode(zf, QPointF(310, 10));
        w.resize(800, 400);
        g.connect(load->id(), 0, zf->id(), 0);
        w.addEdge(QString::fromStdString(load->id()), 0,
                  QString::fromStdString(zf->id()), 0);
        QCOMPARE(w.edgeCount(), 1);

        const QPointF before = w.edgeEndPoint(0);
        const QPointF node_before = w.nodePosition(zf->id());
        const QPoint press = w.mapFromScene(QPointF(310, 10));
        const QPoint release = w.mapFromScene(QPointF(410, 10));
        QTest::mousePress(w.viewport(), Qt::LeftButton, Qt::NoModifier, press);
        QTest::mouseMove(w.viewport(), release);
        QTest::mouseRelease(w.viewport(), Qt::LeftButton, Qt::NoModifier, release);

        const QPointF node_after = w.nodePosition(zf->id());
        const QPointF after = w.edgeEndPoint(0);
        const int rebuilds = w.rebuildCount();
        QVERIFY(std::abs(node_after.x() - (node_before.x() + 100.0)) < 1.0);
        QVERIFY(std::abs(after.x() - (before.x() + 100.0)) < 1.0);
        QVERIFY(rebuilds >= 2);
        QVERIFY(std::abs(after.y() - before.y()) < 1.0);

        // Right-click disconnect is wired to the widget API.
        w.removeEdge(QString::fromStdString(load->id()), 0,
                     QString::fromStdString(zf->id()), 0);
        QCOMPARE(w.edgeCount(), 0);
    }

    void chineseTitles() {
        Graph g;
        auto* load = g.addNode("load_cloud");
        app::NodeFlowWidget w;
        w.setGraph(&g);
        w.addNode(load, QPointF(10, 10));
        QCOMPARE(w.displayTitle(load), QString::fromUtf8("点云加载"));
        w.setChinese(false);
        QCOMPARE(w.displayTitle(load), QStringLiteral("Load Cloud"));
        w.setChinese(true);
        QCOMPARE(w.displayTitle(load), QString::fromUtf8("点云加载"));
    }

    void backgroundStyles() {
        Graph g;
        app::NodeFlowWidget w;
        w.setGraph(&g);
        w.resize(300, 200);

        QCOMPARE(w.canvasStyleName(), QStringLiteral("grid"));
        w.setCanvasStyle(QStringLiteral("dots"));
        QCOMPARE(w.canvasStyleName(), QStringLiteral("dots"));
        w.setCanvasStyle(QStringLiteral("solid"));
        QCOMPARE(w.canvasStyleName(), QStringLiteral("solid"));
        w.setCanvasStyle(QStringLiteral("grid"));
        QCOMPARE(w.canvasStyleName(), QStringLiteral("grid"));

        const std::filesystem::path img =
            std::filesystem::temp_directory_path() / "pcsearch_bg_test.png";
        QImage image(16, 16, QImage::Format_RGB32);
        image.fill(QColor(20, 80, 200));
        QVERIFY(image.save(QString::fromStdString(img.string())));
        w.loadBackgroundImage(QString::fromStdString(img.string()));
        QCOMPARE(w.canvasStyleName(), QStringLiteral("image"));
        std::filesystem::remove(img);
    }

    void paramsPanelHasNoNodeActionButton() {
        // Node-specific action buttons (Box ROI reset bounds) live on the 3D
        // viewport toolbar (MainWindow::updateNodeActionButtons), not in the
        // params panel anymore.
        Graph g;
        auto* box = g.addNode("box_roi");
        app::ParamsPanel panel;
        panel.showNode(box);
        QVERIFY(panel.findChild<QPushButton*>() == nullptr);
    }

    void paramsPanelLoadCloudDoesNotCrash() {
        // Regression: File params used to default to a double (0.0) instead of
        // an empty string; rendering the Load Cloud editor then threw
        // std::bad_variant_access and terminated the app before any cloud was
        // loaded.
        Graph g;
        auto* load = g.addNode("load_cloud");
        QVERIFY(load->params().getString("path").empty());
        app::ParamsPanel panel;
        panel.showNode(load);
        QVERIFY(panel.findChild<QLineEdit*>() != nullptr);
    }

    void chunkSizeEnabledOnlyInChunkedMode() {
        // Chunk Size is meaningless in stream/all mode; the editor must be
        // disabled unless Read Mode == chunked (PROJECT §8.4).
        Graph g;
        auto* load = g.addNode("load_cloud");
        app::ParamsPanel panel;
        panel.showNode(load);
        auto* chunk = panel.findChild<QSpinBox*>(QStringLiteral("chunk_size"));
        auto* mode = panel.findChild<QComboBox*>(QStringLiteral("mode"));
        QVERIFY(chunk != nullptr);
        QVERIFY(mode != nullptr);
        QVERIFY(!chunk->isEnabled());  // default mode = stream
        mode->setCurrentIndex(1);      // chunked
        QVERIFY(chunk->isEnabled());
        mode->setCurrentIndex(0);      // stream
        QVERIFY(!chunk->isEnabled());
        mode->setCurrentIndex(2);      // all
        QVERIFY(!chunk->isEnabled());
    }

    void paramsAreChineseByDefault() {
        // Parameter labels and enum values render in Chinese in the default
        // Chinese mode, including the newly added batch / multi-box params.
        QCOMPARE(app::paramLabel("Read Mode", true), QStringLiteral("读取模式"));
        QCOMPARE(app::paramLabel("Batch Folder", true), QStringLiteral("批量文件夹"));
        QCOMPARE(app::paramLabel("Box Count", true), QStringLiteral("盒数量"));
        QCOMPARE(app::enumValueLabel("stream", true), QStringLiteral("逐帧"));
        QCOMPARE(app::enumValueLabel("chunked", true), QStringLiteral("分批"));
        QCOMPARE(app::enumValueLabel("all", true), QStringLiteral("全部"));
        QCOMPARE(app::enumValueLabel("auto", true), QStringLiteral("自动"));
        // English mode keeps the raw values.
        QCOMPARE(app::paramLabel("Read Mode", false), QStringLiteral("Read Mode"));
        QCOMPARE(app::enumValueLabel("chunked", false), QStringLiteral("chunked"));
    }

    void displayDecimationCapsGpuWork() {
        // Small clouds render fully; huge RVC clouds (5MP / stitched 10M+)
        // are decimated to a GPU-friendly cap without touching pipeline data.
        QCOMPARE(app::PointCloudView::displayStride(1000000), 1);
        QCOMPARE(app::PointCloudView::displayStride(1500000), 1);
        QCOMPARE(app::PointCloudView::displayStride(5013504), 4);
        QVERIFY(app::PointCloudView::displayCount(5013504) <= 1500000);
        QVERIFY(app::PointCloudView::displayCount(10000000) <= 1500000);
        QCOMPARE(app::PointCloudView::displayCount(1500000), 1500000);
        QCOMPARE(app::PointCloudView::displayCount(0), 0);

        // Hardware tiers (PROJECT §8.6): Low keeps the historical 1.5M cap,
        // Standard/High raise the per-object cap; the viewport capacity
        // budget stays 30M regardless of tier.
        QCOMPARE(app::PointCloudView::maxDisplayPointsForTier(
                     app::HardwareTier::Low),
                 1500000);
        QCOMPARE(app::PointCloudView::maxDisplayPointsForTier(
                     app::HardwareTier::Standard),
                 3000000);
        QCOMPARE(app::PointCloudView::maxDisplayPointsForTier(
                     app::HardwareTier::High),
                 10000000);
        QCOMPARE(app::PointCloudView::displayStride(
                     3000001, app::HardwareTier::Standard),
                 2);
        QCOMPARE(app::PointCloudView::displayCount(
                     10000000, app::HardwareTier::High),
                 10000000);
        QCOMPARE(app::PointCloudView::displayCount(
                     3000001, app::HardwareTier::Standard),
                 1500001);
        QCOMPARE(app::PointCloudView::kViewportPointBudget, 30000000);
    }
};

QTEST_MAIN(NodeFlowTest)
#include "test_node_flow.moc"
