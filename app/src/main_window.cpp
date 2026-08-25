#include "main_window.h"

#include "engine_runner.h"
#include "node_flow_widget.h"
#include "params_panel.h"
#include "point_cloud_view.h"
#include "simple_translator.h"
#include "themes.h"
#include "toolbox_widget.h"
#include "viewport_manager.h"

#include "pcsearch/filters/filters.h"
#include "pcsearch/pipeline/nodes/core_nodes.h"
#include "pcsearch/pipeline/json.h"
#include "pcsearch/pipeline/registry.h"
#include "pcsearch/pipeline/solution.h"

#include <QApplication>
#include <QActionGroup>
#include <QComboBox>
#include <QDir>
#include <QDockWidget>
#include <QFile>
#include <QFileDialog>
#include <QGraphicsDropShadowEffect>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QListWidget>
#include <QMenu>
#include <QMenuBar>
#include <QMimeData>
#include <QMessageBox>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QShortcut>
#include <QSplitter>
#include <QStatusBar>
#include <QStackedWidget>
#include <QTabWidget>
#include <QThread>
#include <QTreeWidget>
#include <QVBoxLayout>

#include <algorithm>
#include <map>

namespace app {

namespace {

void applyPanelShadow(QWidget* w) {
    auto* effect = new QGraphicsDropShadowEffect(w);
    effect->setBlurRadius(18);
    effect->setOffset(0, 3);
    effect->setColor(QColor(30, 64, 175, 46));
    w->setGraphicsEffect(effect);
}

// Convert a box_roi node's parameters (xmin..zmax extent + XYZ intrinsic Euler
// angles in degrees) into an oriented box: center, half extents and rotation.
bool boxRoiObbFromNode(const pcsearch::pipeline::Node& node, double center[3],
                       double half[3], double rot[3]) {
    try {
        const auto& p = node.params();
        const double xmin = p.getDouble("xmin"), xmax = p.getDouble("xmax");
        const double ymin = p.getDouble("ymin"), ymax = p.getDouble("ymax");
        const double zmin = p.getDouble("zmin"), zmax = p.getDouble("zmax");
        center[0] = 0.5 * (xmin + xmax);
        center[1] = 0.5 * (ymin + ymax);
        center[2] = 0.5 * (zmin + zmax);
        half[0] = 0.5 * (xmax - xmin);
        half[1] = 0.5 * (ymax - ymin);
        half[2] = 0.5 * (zmax - zmin);
        rot[0] = p.getDouble("rot_x");
        rot[1] = p.getDouble("rot_y");
        rot[2] = p.getDouble("rot_z");
        return true;
    } catch (...) {
        return false;
    }
}

}  // namespace

MainWindow::MainWindow(QWidget* parent) : QMainWindow(parent) {
    pcsearch::pipeline::registerCoreNodes();
    buildUi();
    flow_->setGraph(&graph_);
    retranslateUi();

    rebuildPalette();

    connect(flow_, &NodeFlowWidget::nodeAddRequested, this, &MainWindow::doAddNode);
    connect(flow_, &NodeFlowWidget::connectionRequested, this, &MainWindow::doConnect);
    connect(flow_, &NodeFlowWidget::nodeSelected, this, &MainWindow::doSelectNode);
    connect(flow_, &NodeFlowWidget::nodeDoubleClicked, this, &MainWindow::doSelectNode);
    connect(flow_, &NodeFlowWidget::nodeDeleteRequested, this,
            &MainWindow::doDeleteNode);
    connect(flow_, &NodeFlowWidget::edgeDisconnectRequested, this,
            &MainWindow::doDisconnect);
    connect(flow_, &NodeFlowWidget::statusMessage, this, &MainWindow::log);
    connect(flow_, &NodeFlowWidget::zoomScaleChanged, this, [this](double scale) {
        canvas_stack_->setCurrentIndex(scale < 0.35 ? 1 : 0);
    });
    connect(toolbox_, &ToolboxWidget::nodeActivated, this, [this](const QString& type) {
        doAddNode(type, flow_->mapToScene(flow_->viewport()->rect().center()));
    });
    connect(params_panel_, &ParamsPanel::paramChanged, this, &MainWindow::doParamChanged);
    connect(params_panel_, &ParamsPanel::actionRequested, this,
            &MainWindow::onParamsAction);
    connect(output_combo_, QOverload<int>::of(&QComboBox::currentIndexChanged), this,
            [this](int) { showSelectedOutput(); });
    if (run_button_) {
        connect(run_button_, &QPushButton::clicked, this, &MainWindow::runGraph);
    }
    if (roi_button_) {
        connect(roi_button_, &QPushButton::toggled, this, &MainWindow::onRoiToggle);
    }
    connect(cloud_view_, &PointCloudView::roiEdited, this, &MainWindow::onRoiEdited);
    connect(cloud_view_, &PointCloudView::roiEditFinished, this,
            &MainWindow::onRoiEditFinished);
    connect(cloud_view_, &PointCloudView::displayInfo, this, &MainWindow::log);
    viewports_ = new ViewportManager(this, this);
    viewports_->setMainViewport(cloud_view_);

    auto* find_shortcut = new QShortcut(QKeySequence::Find, this);
    connect(find_shortcut, &QShortcut::activated, toolbox_, &ToolboxWidget::focusSearch);

    statusBar()->showMessage(tr("Drag nodes here, connect ports, press F5 to run."));
}

MainWindow::~MainWindow() {
    // Never destroy the worker QThread while the graph is still executing:
    // Qt6 fail-fasts (0xc0000409) when a QThread is destroyed while running.
    // Ask the runner to stop at the next node boundary and wait for it.
    if (runner_thread_ && runner_thread_->isRunning()) {
        if (runner_) runner_->requestCancel();
        runner_thread_->quit();
        if (!runner_thread_->wait(30000)) {
            // The current node will finish soon (cancel is checked between
            // nodes); prefer blocking on close over destroying a running
            // thread and crashing.
            runner_thread_->wait();
        }
    }
}

void MainWindow::buildUi() {
    setWindowTitle("PointCloudSearch");
    resize(1560, 960);

    auto* central = new QSplitter(Qt::Horizontal, this);
    central->setChildrenCollapsible(true);

    // Column 1: functional components (draggable algorithm nodes).
    auto* palette_box = new QGroupBox(tr("Components"), central);
    auto* palette_layout = new QVBoxLayout(palette_box);
    toolbox_ = new ToolboxWidget(palette_box);
    palette_layout->addWidget(toolbox_);
    palette_box->setMinimumWidth(200);
    applyPanelShadow(palette_box);
    central->addWidget(palette_box);

    // Column 2: canvas (node graph; auto-switches to tree view when zoomed out).
    auto* canvas_box = new QGroupBox(tr("Canvas"), central);
    auto* canvas_layout = new QVBoxLayout(canvas_box);
    canvas_stack_ = new QStackedWidget(canvas_box);
    flow_ = new NodeFlowWidget(canvas_stack_);
    canvas_tree_ = new QTreeWidget(canvas_stack_);
    canvas_tree_->setHeaderLabels({tr("Node"), tr("Connections")});
    canvas_stack_->addWidget(flow_);
    canvas_stack_->addWidget(canvas_tree_);
    canvas_layout->addWidget(canvas_stack_);
    applyPanelShadow(canvas_box);
    central->addWidget(canvas_box);
    central->setStretchFactor(1, 1);

    // Column 3: 3D viewport.
    auto* view_box = new QWidget(central);
    auto* view_layout = new QVBoxLayout(view_box);
    auto* toolbar = new QHBoxLayout;
    run_button_ = new QPushButton(tr("Run"), view_box);
    toolbar->addWidget(run_button_);
    roi_button_ = new QPushButton(tr("ROI"), view_box);
    roi_button_->setCheckable(true);
    toolbar->addWidget(roi_button_);
    toolbar->addWidget(new QLabel(tr("Show Output:"), view_box));
    output_combo_ = new QComboBox(view_box);
    toolbar->addWidget(output_combo_, 1);
    view_layout->addLayout(toolbar);
    cloud_view_ = new PointCloudView(view_box);
    view_layout->addWidget(cloud_view_, 1);
    central->addWidget(view_box);

    // Column 4: parameters (top) + cloud properties / object list (bottom).
    auto* right_panel = new QSplitter(Qt::Vertical, central);
    right_panel->setChildrenCollapsible(true);
    auto* params_box = new QGroupBox(tr("Parameters"), right_panel);
    auto* params_layout = new QVBoxLayout(params_box);
    params_panel_ = new ParamsPanel(params_box);
    params_layout->addWidget(params_panel_);
    applyPanelShadow(params_box);
    right_panel->addWidget(params_box);

    auto* props_box = new QGroupBox(tr("Cloud Properties"), right_panel);
    auto* props_layout = new QVBoxLayout(props_box);
    results_tree_ = new QTreeWidget(props_box);
    results_tree_->setHeaderLabels({tr("Node"), tr("Object"), tr("Points"), tr("Kind")});
    props_layout->addWidget(results_tree_);
    applyPanelShadow(props_box);
    right_panel->addWidget(props_box);
    right_panel->setStretchFactor(0, 1);
    right_panel->setStretchFactor(1, 2);
    central->addWidget(right_panel);
    central->setStretchFactor(3, 0);

    setCentralWidget(central);

    auto* dock = new QDockWidget(tr("Log"), this);
    log_view_ = new QPlainTextEdit(dock);
    log_view_->setReadOnly(true);
    dock->setWidget(log_view_);
    addDockWidget(Qt::BottomDockWidgetArea, dock);
    applyPanelShadow(log_view_);

    file_menu_ = menuBar()->addMenu(tr("&File"));
    file_menu_->addAction(tr("Open Cloud..."), this, &MainWindow::openCloud, QKeySequence::Open);
    file_menu_->addAction(tr("Save Solution..."), this, &MainWindow::saveSolution);
    file_menu_->addAction(tr("Open Solution..."), this, &MainWindow::openSolution);
    run_action_ = file_menu_->addAction(tr("&Run Graph"), this, &MainWindow::runGraph,
                                        QKeySequence(Qt::Key_F5));
    file_menu_->addSeparator();
    file_menu_->addAction(tr("Exit"), this, &QWidget::close, QKeySequence::Quit);

    view_menu_ = menuBar()->addMenu(tr("&View"));
    auto* theme_menu = view_menu_->addMenu(tr("Theme"));
    auto* light = theme_menu->addAction(tr("Light"));
    auto* dark = theme_menu->addAction(tr("Dark"));
    light->setCheckable(true);
    dark->setCheckable(true);
    dark->setChecked(true);
    connect(light, &QAction::toggled, this, [this](bool on) {
        if (on) setThemeDark(false);
    });
    connect(dark, &QAction::toggled, this, [this](bool on) {
        if (on) setThemeDark(true);
    });

    auto* lang_menu = view_menu_->addMenu(tr("Language"));
    auto* zh = lang_menu->addAction(tr("中文"));
    auto* en = lang_menu->addAction(tr("English"));
    zh->setCheckable(true);
    en->setCheckable(true);
    zh->setChecked(true);
    connect(zh, &QAction::toggled, this, [this](bool on) {
        if (on) setLanguageChinese(true);
    });
    connect(en, &QAction::toggled, this, [this](bool on) {
        if (on) setLanguageChinese(false);
    });
    view_menu_->addSeparator();
    view_menu_->addAction(tr("Add 3D Viewport"), this,
                          [this]() { viewports_->addViewport(QString{}); });

    auto* bg_menu = view_menu_->addMenu(tr("Canvas Background"));
    auto* bg_group = new QActionGroup(this);
    auto* bg_grid = bg_menu->addAction(tr("Grid"));
    auto* bg_dots = bg_menu->addAction(tr("Dots"));
    auto* bg_solid = bg_menu->addAction(tr("Solid"));
    auto* bg_image = bg_menu->addAction(tr("Custom Image..."));
    for (auto* action : {bg_grid, bg_dots, bg_solid}) {
        action->setCheckable(true);
        bg_group->addAction(action);
    }
    bg_grid->setChecked(true);
    connect(bg_grid, &QAction::triggered, this,
            [this]() { flow_->setCanvasStyle(QStringLiteral("grid")); });
    connect(bg_dots, &QAction::triggered, this,
            [this]() { flow_->setCanvasStyle(QStringLiteral("dots")); });
    connect(bg_solid, &QAction::triggered, this,
            [this]() { flow_->setCanvasStyle(QStringLiteral("solid")); });
    connect(bg_image, &QAction::triggered, this, [this]() {
        const QString path = QFileDialog::getOpenFileName(
            this, tr("Load Canvas Background"), {},
            tr("Images (*.png *.jpg *.jpeg *.bmp *.gif);;All Files (*)"));
        if (!path.isEmpty()) flow_->loadBackgroundImage(path);
    });

    help_menu_ = menuBar()->addMenu(tr("&Help"));
    help_menu_->addAction(tr("About"), this, &MainWindow::showAbout);
}

void MainWindow::retranslateUi() {
    setWindowTitle(tr("PointCloudSearch"));
    file_menu_->setTitle(tr("&File"));
    view_menu_->setTitle(tr("&View"));
    help_menu_->setTitle(tr("&Help"));
    toolbox_->setSearchPlaceholder(tr("Search nodes..."));
    if (run_button_) {
        run_button_->setText(tr("Run"));
    }
}

void MainWindow::changeEvent(QEvent* event) {
    if (event->type() == QEvent::LanguageChange) {
        retranslateUi();
    }
    QMainWindow::changeEvent(event);
}

void MainWindow::log(const QString& message) {
    log_view_->appendPlainText(message);
}

void MainWindow::doAddNode(const QString& type, const QPointF& scene_pos) {
    if (running_) {
        log(tr("Graph is running; editing disabled"));
        return;
    }
    try {
        auto* node = graph_.addNode(type.toStdString());
        flow_->addNode(node, scene_pos);
        params_panel_->showNode(node);
        refreshCanvasTree();
        log(tr("Added node: %1").arg(QString::fromStdString(node->id())));
    } catch (const std::exception& e) {
        log(QString::fromUtf8(e.what()));
    }
}

void MainWindow::doConnect(const QString& from_id, int from_port, const QString& to_id,
                           int to_port) {
    if (running_) {
        log(tr("Graph is running; editing disabled"));
        return;
    }
    if (graph_.connect(from_id.toStdString(), from_port, to_id.toStdString(), to_port)) {
        flow_->addEdge(from_id, from_port, to_id, to_port);
        refreshCanvasTree();
        log(tr("Connected %1 -> %2").arg(from_id, to_id));
    } else {
        const QString error = QString::fromStdString(graph_.connectError());
        log(error.isEmpty() ? tr("Connection failed") : error);
    }
}

void MainWindow::doSelectNode(const QString& id) {
    selected_node_id_ = id.toStdString();
    pcsearch::pipeline::Node* node = graph_.node(selected_node_id_);
    params_panel_->showNode(node);
    if (node && node->type() != "box_roi") {
        roi_button_->setChecked(false);
        cloud_view_->enableRoiEdit(false);
    }
    showNodeInputCloud(selected_node_id_);
    updateRoiBoxPreview();
}

void MainWindow::showNodeInputCloud(const std::string& id) {
    const pcsearch::core::ObjectList* shown = nullptr;
    for (const auto& e : graph_.edges()) {
        if (e.to_id == id) {
            if (const auto* out = graph_.output(e.from_id, e.from_port)) {
                shown = out;
                break;
            }
        }
    }
    if (!shown) {
        shown = graph_.output(id, 0);
    }
    cloud_view_->showObjectList(shown);
}

bool MainWindow::nodeInputBounds(const std::string& id, double bounds[6],
                                 std::int64_t* valid_points) const {
    // Merge the axis-aligned bounds of every point cloud flowing INTO the
    // selected node, so "fit to input" covers the whole input object list.
    // Rows with NaN/Inf are skipped (PCL getMinMax3D / Open3D AABB semantics);
    // otherwise a single invalid point would corrupt the result (e.g. RVC
    // depth maps contain many NaN holes).
    bool found = false;
    std::int64_t points = 0;
    double mn[3] = {0.0, 0.0, 0.0};
    double mx[3] = {0.0, 0.0, 0.0};
    for (const auto& e : graph_.edges()) {
        if (e.to_id != id) continue;
        const auto* out = graph_.output(e.from_id, e.from_port);
        if (!out) continue;
        for (const auto& obj : out->objects) {
            const auto& c = *obj->cloud;
            Eigen::Vector3f o_mn, o_mx;
            std::int64_t valid = 0;
            if (!pcsearch::filters::computeBounds(c, o_mn, o_mx, &valid)) continue;
            points += valid;
            if (!found) {
                for (int k = 0; k < 3; ++k) {
                    mn[k] = o_mn[k];
                    mx[k] = o_mx[k];
                }
                found = true;
            } else {
                for (int k = 0; k < 3; ++k) {
                    mn[k] = (std::min)(mn[k], static_cast<double>(o_mn[k]));
                    mx[k] = (std::max)(mx[k], static_cast<double>(o_mx[k]));
                }
            }
        }
    }
    if (valid_points) *valid_points = points;
    if (!found) return false;
    bounds[0] = mn[0];
    bounds[1] = mx[0];
    bounds[2] = mn[1];
    bounds[3] = mx[1];
    bounds[4] = mn[2];
    bounds[5] = mx[2];
    return true;
}

void MainWindow::doDeleteNode(const QString& id) {
    if (running_) {
        log(tr("Graph is running; editing disabled"));
        return;
    }
    if (!graph_.node(id.toStdString())) return;
    graph_.removeNode(id.toStdString());
    flow_->removeNode(id.toStdString());
    refreshCanvasTree();
    refreshOutputCombo();
    if (selected_node_id_ == id.toStdString()) {
        selected_node_id_.clear();
        params_panel_->clearPanel();
        roi_button_->setChecked(false);
        cloud_view_->enableRoiEdit(false);
        cloud_view_->hideRoiBox();
    }
    log(tr("Deleted node: %1").arg(id));
}

void MainWindow::doDisconnect(const QString& from_id, int from_port, const QString& to_id,
                              int to_port) {
    if (running_) {
        log(tr("Graph is running; editing disabled"));
        return;
    }
    if (graph_.disconnect(from_id.toStdString(), from_port, to_id.toStdString(),
                          to_port)) {
        flow_->removeEdge(from_id, from_port, to_id, to_port);
        refreshCanvasTree();
        log(tr("Disconnected %1 -> %2").arg(from_id, to_id));
    }
}

void MainWindow::onRoiToggle(bool on) {
    if (!on) {
        cloud_view_->enableRoiEdit(false);
        // Re-enable the static wireframe preview box so the user still sees the
        // current Box ROI pose after exiting edit mode (the interaction box is
        // gone now, and updateRoiBoxPreview draws the single preview actor).
        updateRoiBoxPreview();
        return;
    }
    pcsearch::pipeline::Node* node = graph_.node(selected_node_id_);
    if (!node || node->type() != "box_roi") {
        log(tr("Select a Box ROI node first, then press ROI"));
        roi_button_->setChecked(false);
        return;
    }
    // If the box still has the default (unset) size, place it over the whole
    // input cloud so the user can see what will be cropped; otherwise keep the
    // user's current box pose (position / size / rotation).
    bool is_default = false;
    try {
        const auto& p = node->params();
        is_default = p.getDouble("xmin") <= -99999.0 &&
                     p.getDouble("xmax") >= 99999.0 &&
                     p.getDouble("ymin") <= -99999.0 &&
                     p.getDouble("ymax") >= 99999.0 &&
                     p.getDouble("zmin") <= -99999.0 &&
                     p.getDouble("zmax") >= 99999.0;
    } catch (...) {
    }
    if (is_default) {
        double bounds[6] = {0.0, 1.0, 0.0, 1.0, 0.0, 1.0};
        if (nodeInputBounds(selected_node_id_, bounds)) {
            cloud_view_->enableRoiEdit(true, bounds);
            cloud_view_->frameScene();
            log(tr("ROI edit enabled: left-drag the body to move, drag corner "
                   "handles to scale, drag edge handles to rotate; wheel zooms; "
                   "results are written back to the Box ROI node"));
            return;
        }
    }
    double center[3], half[3], rot[3];
    if (boxRoiObbFromNode(*node, center, half, rot)) {
        cloud_view_->enableRoiEditObb(true, center, half, rot);
    } else {
        const double bounds[6] = {0.0, 1.0, 0.0, 1.0, 0.0, 1.0};
        cloud_view_->enableRoiEdit(true, bounds);
    }
    cloud_view_->frameScene();
    log(tr("ROI edit enabled: left-drag the body to move, drag corner handles "
           "to scale, drag edge handles to rotate; wheel zooms; results are "
           "written back to the Box ROI node"));
}

void MainWindow::onRoiEdited(double cx, double cy, double cz, double hx, double hy,
                             double hz, double rx, double ry, double rz) {
    if (running_) return;
    pcsearch::pipeline::Node* node = graph_.node(selected_node_id_);
    if (!node || node->type() != "box_roi") return;
    // Live path: called on every mouse move during a drag. Only commit the
    // parameters here - rebuilding the panel / preview / log on every move is
    // what made ROI editing stutter and spam the log. The expensive UI work
    // happens once in onRoiEditFinished() when the drag ends.
    graph_.setParam(node->id(), "xmin", pcsearch::pipeline::ParamValue{cx - hx});
    graph_.setParam(node->id(), "xmax", pcsearch::pipeline::ParamValue{cx + hx});
    graph_.setParam(node->id(), "ymin", pcsearch::pipeline::ParamValue{cy - hy});
    graph_.setParam(node->id(), "ymax", pcsearch::pipeline::ParamValue{cy + hy});
    graph_.setParam(node->id(), "zmin", pcsearch::pipeline::ParamValue{cz - hz});
    graph_.setParam(node->id(), "zmax", pcsearch::pipeline::ParamValue{cz + hz});
    graph_.setParam(node->id(), "rot_x", pcsearch::pipeline::ParamValue{rx});
    graph_.setParam(node->id(), "rot_y", pcsearch::pipeline::ParamValue{ry});
    graph_.setParam(node->id(), "rot_z", pcsearch::pipeline::ParamValue{rz});
}

void MainWindow::onRoiEditFinished() {
    if (running_) return;
    pcsearch::pipeline::Node* node = graph_.node(selected_node_id_);
    if (!node || node->type() != "box_roi") return;
    const double cx = 0.5 * (node->params().getDouble("xmin") + node->params().getDouble("xmax"));
    const double cy = 0.5 * (node->params().getDouble("ymin") + node->params().getDouble("ymax"));
    const double cz = 0.5 * (node->params().getDouble("zmin") + node->params().getDouble("zmax"));
    const double hx = 0.5 * (node->params().getDouble("xmax") - node->params().getDouble("xmin"));
    const double hy = 0.5 * (node->params().getDouble("ymax") - node->params().getDouble("ymin"));
    const double hz = 0.5 * (node->params().getDouble("zmax") - node->params().getDouble("zmin"));
    const double rx = node->params().getDouble("rot_x");
    const double ry = node->params().getDouble("rot_y");
    const double rz = node->params().getDouble("rot_z");
    params_panel_->showNode(node);
    updateRoiBoxPreview();
    log(tr("ROI updated: center(%1, %2, %3) half(%4, %5, %6) rotation(%7, %8, "
           "%9) deg (press F5 to recompute)")
            .arg(cx).arg(cy).arg(cz).arg(hx).arg(hy).arg(hz).arg(rx).arg(ry).arg(rz));
}

void MainWindow::updateRoiBoxPreview() {
    pcsearch::pipeline::Node* node = graph_.node(selected_node_id_);
    if (!node || node->type() != "box_roi") {
        cloud_view_->hideRoiBox();
        return;
    }
    try {
        const auto& p = node->params();
        const double xmin = p.getDouble("xmin"), xmax = p.getDouble("xmax");
        const double ymin = p.getDouble("ymin"), ymax = p.getDouble("ymax");
        const double zmin = p.getDouble("zmin"), zmax = p.getDouble("zmax");
        const double rot_x = p.getDouble("rot_x");
        const double rot_y = p.getDouble("rot_y");
        const double rot_z = p.getDouble("rot_z");
        const bool default_box = xmin <= -99999.0 && xmax >= 99999.0 &&
                                 ymin <= -99999.0 && ymax >= 99999.0 &&
                                 zmin <= -99999.0 && zmax >= 99999.0;
        double center[3], half[3], rot[3];
        double bounds[6];
        if (default_box && nodeInputBounds(selected_node_id_, bounds)) {
            center[0] = 0.5 * (bounds[0] + bounds[1]);
            center[1] = 0.5 * (bounds[2] + bounds[3]);
            center[2] = 0.5 * (bounds[4] + bounds[5]);
            half[0] = 0.5 * (bounds[1] - bounds[0]);
            half[1] = 0.5 * (bounds[3] - bounds[2]);
            half[2] = 0.5 * (bounds[5] - bounds[4]);
            rot[0] = rot[1] = rot[2] = 0.0;
        } else {
            center[0] = 0.5 * (xmin + xmax);
            center[1] = 0.5 * (ymin + ymax);
            center[2] = 0.5 * (zmin + zmax);
            half[0] = 0.5 * (xmax - xmin);
            half[1] = 0.5 * (ymax - ymin);
            half[2] = 0.5 * (zmax - zmin);
            rot[0] = rot_x;
            rot[1] = rot_y;
            rot[2] = rot_z;
        }
        cloud_view_->showRoiBoxObb(center, half, rot);
    } catch (...) {
        cloud_view_->hideRoiBox();
    }
}

void MainWindow::onParamsAction(const QString& node_id, const QString& action) {
    if (running_) return;
    if (action != QLatin1String("fit_bounds")) return;
    pcsearch::pipeline::Node* node = graph_.node(node_id.toStdString());
    if (!node || node->type() != "box_roi") return;
    double bounds[6] = {0.0, 1.0, 0.0, 1.0, 0.0, 1.0};
    std::int64_t valid_points = 0;
    if (!nodeInputBounds(node->id(), bounds, &valid_points)) {
        log(tr("Reset bounds failed: Box ROI received no point cloud "
               "(connect Load Cloud -> Box ROI and run the graph first)"));
        return;
    }
    if (valid_points <= 0) {
        log(tr("Reset bounds failed: input cloud has no valid points "
               "(all NaN/Inf); add Remove Invalid Points before Box ROI"));
        return;
    }
    try {
        graph_.setParam(node->id(), "xmin", pcsearch::pipeline::ParamValue{bounds[0]});
        graph_.setParam(node->id(), "xmax", pcsearch::pipeline::ParamValue{bounds[1]});
        graph_.setParam(node->id(), "ymin", pcsearch::pipeline::ParamValue{bounds[2]});
        graph_.setParam(node->id(), "ymax", pcsearch::pipeline::ParamValue{bounds[3]});
        graph_.setParam(node->id(), "zmin", pcsearch::pipeline::ParamValue{bounds[4]});
        graph_.setParam(node->id(), "zmax", pcsearch::pipeline::ParamValue{bounds[5]});
        graph_.setParam(node->id(), "rot_x", pcsearch::pipeline::ParamValue{0.0});
        graph_.setParam(node->id(), "rot_y", pcsearch::pipeline::ParamValue{0.0});
        graph_.setParam(node->id(), "rot_z", pcsearch::pipeline::ParamValue{0.0});
    } catch (const std::exception& e) {
        log(tr("Reset bounds failed: %1").arg(QString::fromUtf8(e.what())));
        return;
    }
    if (selected_node_id_ == node->id()) {
        params_panel_->showNode(node);
        updateRoiBoxPreview();
        if (!roi_button_->isChecked()) {
            // Auto-enter ROI 框选 so the box is visible and immediately
            // operable; onRoiToggle re-places the widget with the new params.
            roi_button_->setChecked(true);
        } else {
            double center[3], half[3], rot[3];
            if (boxRoiObbFromNode(*node, center, half, rot)) {
                cloud_view_->enableRoiEditObb(true, center, half, rot);
            }
        }
        cloud_view_->frameScene();
    }
    log(tr("Reset bounds to input cloud (%1 valid points): x[%2, %3] y[%4, %5] "
           "z[%6, %7] (press F5 to recompute)")
            .arg(valid_points)
            .arg(bounds[0])
            .arg(bounds[1])
            .arg(bounds[2])
            .arg(bounds[3])
            .arg(bounds[4])
            .arg(bounds[5]));
}

void MainWindow::doParamChanged(const QString& node_id, const QString& name,
                                pcsearch::pipeline::ParamValue value) {
    if (running_) {
        log(tr("Graph is running; editing disabled"));
        return;
    }
    try {
        graph_.setParam(node_id.toStdString(), name.toStdString(), std::move(value));
        if (const auto* n = graph_.node(node_id.toStdString());
            n && n->type() == "box_roi") {
            updateRoiBoxPreview();
            // Keep the interactive box in sync when the user edits spin boxes
            // while ROI 框选 is active.
            if (roi_button_->isChecked() && selected_node_id_ == node_id.toStdString()) {
                double center[3], half[3], rot[3];
                if (boxRoiObbFromNode(*n, center, half, rot)) {
                    cloud_view_->enableRoiEditObb(true, center, half, rot);
                }
            }
        }
        log(tr("Param %1.%2 changed (dirty; press F5 to recompute)").arg(node_id, name));
    } catch (const std::exception& e) {
        log(QString::fromUtf8(e.what()));
    }
}

void MainWindow::runGraph() {
    if (running_) {
        log(tr("Graph is already running"));
        return;
    }
    if (graph_.nodes().empty()) {
        log(tr("Nothing to run - add nodes first"));
        return;
    }
    running_ = true;
    setEditingEnabled(false);
    statusBar()->showMessage(tr("Running graph..."));

    runner_ = new GraphRunner(&graph_);
    runner_thread_ = new QThread(this);
    runner_->moveToThread(runner_thread_);
    connect(runner_thread_, &QThread::finished, runner_, &QObject::deleteLater);
    connect(this, &MainWindow::runRequested, runner_, &GraphRunner::run);
    connect(runner_, &GraphRunner::nodeFinished, this,
            [this](const QString& id, double ms) {
                log(tr("Node %1: %2 ms").arg(id).arg(ms, 0, 'f', 1));
            });
    connect(runner_, &GraphRunner::finished, this, &MainWindow::onRunFinished);
    runner_thread_->start();
    emit runRequested();
}

void MainWindow::onRunFinished(bool ok, const QString& error) {
    if (runner_thread_) {
        runner_thread_->quit();
        runner_thread_->wait();
        runner_thread_->deleteLater();
    }
    runner_ = nullptr;
    runner_thread_ = nullptr;
    running_ = false;
    setEditingEnabled(true);

    if (ok) {
        log(tr("Graph executed successfully"));
        refreshResults();
        refreshOutputCombo();
        if (!selected_node_id_.empty()) {
            showNodeInputCloud(selected_node_id_);
        } else {
            showSelectedOutput();
        }
        updateRoiBoxPreview();
        routeDisplayNodes();
        statusBar()->showMessage(
            tr("Drag nodes here, connect ports, press F5 to run."));
    } else {
        log(error);
        statusBar()->showMessage(tr("Graph execution failed"));
    }
}

void MainWindow::routeDisplayNodes() {
    for (auto* node : graph_.nodes()) {
        if (node->type() != "display3d") continue;
        const std::string viewport_name = node->params().getString("viewport");
        const auto* out = graph_.output(node->id());
        if (!out) continue;
        PointCloudView* view = viewports_->viewport(
            QString::fromStdString(viewport_name));
        if (view) {
            view->showObjectList(out);
            log(tr("Displayed %1 in viewport %2")
                    .arg(QString::fromStdString(node->id()),
                         QString::fromStdString(viewport_name)));
        }
    }
}

void MainWindow::setEditingEnabled(bool enabled) {
    toolbox_->setEnabled(enabled);
    flow_->setEnabled(enabled);
    params_panel_->setEnabled(enabled);
    if (run_button_) {
        run_button_->setEnabled(enabled);
    }
    if (run_action_) {
        run_action_->setEnabled(enabled);
    }
}

void MainWindow::openCloud() {
    if (running_) {
        log(tr("Graph is running; editing disabled"));
        return;
    }
    const QString path = QFileDialog::getOpenFileName(
        this, tr("Open Cloud"), {},
        "Point Clouds (*.pcd *.ply *.xyz *.csv *.txt);;All Files (*)");
    if (path.isEmpty()) return;
    auto* node = graph_.addNode("load_cloud");
    graph_.setParam(node->id(), "path", pcsearch::pipeline::ParamValue{path.toStdString()});
    flow_->addNode(node, QPointF());
    params_panel_->showNode(node);
    runGraph();
}

void MainWindow::saveSolution() {
    if (running_) {
        log(tr("Graph is running; editing disabled"));
        return;
    }
    const QString path = QFileDialog::getSaveFileName(
        this, tr("Save Solution"), {},
        tr("PointCloudSearch Solution (*.pcsearch.json);;All Files (*)"));
    if (path.isEmpty()) return;

    pcsearch::pipeline::json::Value doc = pcsearch::pipeline::json::Value::object();
    doc["graph"] = pcsearch::pipeline::json::Value::string(
        pcsearch::pipeline::saveGraphJson(graph_));
    pcsearch::pipeline::json::Value positions =
        pcsearch::pipeline::json::Value::object();
    for (auto* node : graph_.nodes()) {
        const QPointF pos = flow_->nodePosition(node->id());
        pcsearch::pipeline::json::Value p = pcsearch::pipeline::json::Value::array();
        p.asArray().push_back(pcsearch::pipeline::json::Value::number(pos.x()));
        p.asArray().push_back(pcsearch::pipeline::json::Value::number(pos.y()));
        positions[node->id()] = std::move(p);
    }
    doc["positions"] = std::move(positions);

    QFile file(path);
    if (!file.open(QIODevice::WriteOnly)) {
        log(tr("Cannot write solution file"));
        return;
    }
    file.write(QByteArray::fromStdString(doc.dump()));
    log(tr("Solution saved: %1").arg(path));
}

void MainWindow::openSolution() {
    if (running_) {
        log(tr("Graph is running; editing disabled"));
        return;
    }
    const QString path = QFileDialog::getOpenFileName(
        this, tr("Open Solution"), {},
        tr("PointCloudSearch Solution (*.pcsearch.json);;All Files (*)"));
    if (path.isEmpty()) return;
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) {
        log(tr("Cannot open solution file"));
        return;
    }
    const std::string text = file.readAll().toStdString();
    try {
        const pcsearch::pipeline::json::Value doc =
            pcsearch::pipeline::json::Value::parse(text);
        const pcsearch::pipeline::json::Value* graph_json = doc.find("graph");
        if (!graph_json || !graph_json->isString()) {
            throw pcsearch::pipeline::json::JsonError("missing graph in solution");
        }
        if (!pcsearch::pipeline::loadGraphJson(graph_, graph_json->asString())) {
            log(QString::fromStdString(graph_.lastError()));
            return;
        }
        flow_->clearScene();

        std::map<std::string, QPointF> positions;
        const pcsearch::pipeline::json::Value* pos_json = doc.find("positions");
        if (pos_json && pos_json->isObject()) {
            for (const auto& [id, p] : pos_json->asObject()) {
                if (p.isArray() && p.asArray().size() == 2) {
                    positions[id] =
                        QPointF(p.asArray()[0].asNumber(), p.asArray()[1].asNumber());
                }
            }
        }
        int i = 0;
        for (auto* node : graph_.nodes()) {
            const auto it = positions.find(node->id());
            const QPointF pos = it == positions.end()
                                    ? QPointF(40.0 + 30.0 * i, 40.0 + 30.0 * i)
                                    : it->second;
            flow_->addNode(node, pos);
            ++i;
        }
        for (const auto& e : graph_.edges()) {
            flow_->addEdge(QString::fromStdString(e.from_id), e.from_port,
                           QString::fromStdString(e.to_id), e.to_port);
        }
        selected_node_id_.clear();
        params_panel_->clearPanel();
        refreshCanvasTree();
        refreshOutputCombo();
        log(tr("Solution loaded: %1").arg(path));
    } catch (const std::exception& e) {
        log(QString::fromUtf8(e.what()));
    }
}

bool MainWindow::loadDemo(const QString& plyPath) {
    if (running_ || plyPath.isEmpty()) return false;
    auto* load = graph_.addNode("load_cloud");
    graph_.setParam(load->id(), "path",
                    pcsearch::pipeline::ParamValue{plyPath.toStdString()});
    flow_->addNode(load, QPointF(-260, -140));
    auto* roi = graph_.addNode("box_roi");
    flow_->addNode(roi, QPointF(60, -140));
    auto* save = graph_.addNode("save_cloud");
    graph_.setParam(save->id(), "folder",
                    pcsearch::pipeline::ParamValue{QDir::tempPath().toStdString()});
    graph_.setParam(save->id(), "file_name",
                    pcsearch::pipeline::ParamValue{std::string("pcs_demo_out")});
    flow_->addNode(save, QPointF(380, -140));
    auto* display = graph_.addNode("display3d");
    flow_->addNode(display, QPointF(700, -140));
    graph_.connect(load->id(), 0, roi->id(), 0);
    graph_.connect(roi->id(), 0, save->id(), 0);
    graph_.connect(save->id(), 0, display->id(), 0);
    flow_->addEdge(QString::fromStdString(load->id()), 0,
                   QString::fromStdString(roi->id()), 0);
    flow_->addEdge(QString::fromStdString(roi->id()), 0,
                   QString::fromStdString(save->id()), 0);
    flow_->addEdge(QString::fromStdString(save->id()), 0,
                   QString::fromStdString(display->id()), 0);
    refreshCanvasTree();
    flow_->selectNode(roi->id());
    return true;
}

void MainWindow::setLanguageChinese(bool chinese) {
    if (chinese) {
        if (!translator_) {
            translator_ = new SimpleTranslator();
            QApplication::instance()->installTranslator(translator_);
        }
    } else {
        if (translator_) {
            QApplication::instance()->removeTranslator(translator_);
            delete translator_;
            translator_ = nullptr;
        }
    }
    flow_->setChinese(chinese);
    params_panel_->setChinese(chinese);
    retranslateUi();
    rebuildPalette();
}

void MainWindow::setThemeDark(bool dark) {
    auto* app = static_cast<QApplication*>(QApplication::instance());
    applyTheme(*app, dark);
    flow_->viewport()->update();
}

void MainWindow::showAbout() {
    QMessageBox::about(
        this, tr("About"),
        tr("PointCloudSearch - modular point cloud search & analysis toolkit.\n"
           "C++20 / Qt6 / VTK / PCL"));
}

void MainWindow::refreshResults() {
    results_tree_->clear();
    for (auto* node : graph_.nodes()) {
        auto* node_item = new QTreeWidgetItem(results_tree_);
        node_item->setText(0, QString::fromStdString(node->id()));
        const auto* out = graph_.output(node->id());
        if (!out) continue;
        for (const auto& obj : out->objects) {
            auto* obj_item = new QTreeWidgetItem(node_item);
            obj_item->setText(1, QString::fromStdString(obj->name));
            obj_item->setText(2, QString::number(obj->cloud->size()));
            QString kinds;
            for (const auto& r : obj->regions) {
                if (!kinds.isEmpty()) kinds += ", ";
                kinds += QString::fromStdString(r.label);
            }
            obj_item->setText(3, kinds);
        }
        results_tree_->expandItem(node_item);
    }
}

void MainWindow::refreshOutputCombo() {
    const QString previous = output_combo_->currentData().toString();
    output_combo_->clear();
    for (auto* node : graph_.nodes()) {
        if (!graph_.output(node->id())) continue;
        output_combo_->addItem(QString::fromStdString(node->id()),
                               QString::fromStdString(node->id()));
    }
    const int idx = output_combo_->findData(previous);
    output_combo_->setCurrentIndex(idx >= 0 ? idx : output_combo_->count() - 1);
}

void MainWindow::showSelectedOutput() {
    const QString id = output_combo_->currentData().toString();
    if (id.isEmpty()) {
        cloud_view_->clearView();
        return;
    }
    cloud_view_->showObjectList(graph_.output(id.toStdString()));
}

void MainWindow::rebuildPalette() {
    toolbox_->populate(pcsearch::pipeline::NodeRegistry::instance().all(),
                       translator_ != nullptr);
}

void MainWindow::refreshCanvasTree() {
    canvas_tree_->clear();
    for (auto* node : graph_.nodes()) {
        auto* item = new QTreeWidgetItem(canvas_tree_);
        item->setText(0, QString::fromStdString(node->id()));
        QString connections;
        for (const auto& e : graph_.edges()) {
            if (e.to_id == node->id()) {
                if (!connections.isEmpty()) connections += ", ";
                connections += QString::fromStdString(e.from_id);
            }
        }
        item->setText(1, connections);
        canvas_tree_->expandItem(item);
    }
}

}  // namespace app
