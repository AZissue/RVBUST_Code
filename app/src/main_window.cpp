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
#include <QButtonGroup>
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
#include <QTimer>
#include <QToolButton>
#include <QTreeWidget>
#include <QVBoxLayout>
#include <QWheelEvent>

#include <algorithm>
#include <map>
#include <set>

namespace app {

namespace {

// Roles attached to cloud-properties tree rows. Object rows carry all four;
// group rows carry only kPropsInputRole (input vs output group).
enum PropsRole {
    kPropsNodeRole = Qt::UserRole,  // QString: source node id
    kPropsPortRole,                 // int: port on the source node
    kPropsIndexRole,                // int: object index inside the port list
    kPropsInputRole,                // bool: true = input group
    kPropsInputPortRole,            // int: downstream input port (input rows only)
};

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
        setCanvasLayout(scale < 0.35 ? 1 : 0);
    });
    connect(toolbox_, &ToolboxWidget::nodeActivated, this, [this](const QString& type) {
        doAddNode(type, flow_->mapToScene(flow_->viewport()->rect().center()));
    });
    updateRunControls();
    connect(params_panel_, &ParamsPanel::paramChanged, this, &MainWindow::doParamChanged);
    connect(params_panel_, &ParamsPanel::actionRequested, this,
            &MainWindow::onParamsAction);
    connect(show_cloud_action_, &QAction::toggled, this,
            [this](bool) { applyDisplayTypeFilter(); });
    connect(show_box_action_, &QAction::toggled, this,
            [this](bool) { applyDisplayTypeFilter(); });
    connect(show_line_action_, &QAction::toggled, this,
            [this](bool) { applyDisplayTypeFilter(); });
    if (run_button_) {
        connect(run_button_, &QPushButton::clicked, this, &MainWindow::runGraph);
    }
    if (run_to_button_) {
        connect(run_to_button_, &QPushButton::clicked, this,
                [this] { runGraph(true); });
    }
    connect(transform_button_, &QPushButton::toggled, this,
            [this](bool on) {
                cloud_view_->setTransformToolActive(on);
                log(on ? tr("Move/Rotate tool: left-drag moves the selected "
                            "frames, right-drag rotates them")
                       : tr("Move/Rotate tool disabled"));
            });
    connect(reset_transform_button_, &QPushButton::clicked, this, [this] {
        cloud_view_->resetFrameTransforms(cloud_view_->transformTargets());
        log(tr("Transforms reset for the selected frames"));
    });
    connect(cloud_view_, &PointCloudView::roiEdited, this, &MainWindow::onRoiEdited);
    connect(cloud_view_, &PointCloudView::roiEditFinished, this,
            &MainWindow::onRoiEditFinished);
    connect(cloud_view_, &PointCloudView::displayInfo, this, &MainWindow::log);
    viewports_ = new ViewportManager(this, this);
    viewports_->setMainViewport(cloud_view_);

    // latest-wins display refresh: block progress restarts a short single-shot
    // timer, and the timeout applies only the newest block's layers. Rapid
    // blocks coalesce into one render instead of one per frame.
    display_timer_ = new QTimer(this);
    display_timer_->setInterval(100);
    display_timer_->setSingleShot(true);
    connect(display_timer_, &QTimer::timeout, this, &MainWindow::refreshDisplayLayers);

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
    // Layout switch: Canvas (node graph) / Outline (read-only node list).
    // Zoom-out below the threshold auto-switches to the outline; the buttons
    // (or Ctrl+wheel-up over the outline) always allow switching back.
    auto* canvas_switch = new QHBoxLayout;
    canvas_view_button_ = new QPushButton(tr("Canvas"), canvas_box);
    outline_view_button_ = new QPushButton(tr("Outline"), canvas_box);
    auto* canvas_switch_group = new QButtonGroup(canvas_box);
    canvas_view_button_->setCheckable(true);
    outline_view_button_->setCheckable(true);
    canvas_switch_group->addButton(canvas_view_button_);
    canvas_switch_group->addButton(outline_view_button_);
    canvas_view_button_->setChecked(true);
    canvas_switch->addWidget(canvas_view_button_);
    canvas_switch->addWidget(outline_view_button_);
    canvas_switch->addStretch(1);
    connect(canvas_view_button_, &QPushButton::clicked, this,
            [this] { setCanvasLayout(0); });
    connect(outline_view_button_, &QPushButton::clicked, this,
            [this] { setCanvasLayout(1); });
    canvas_layout->addLayout(canvas_switch);
    canvas_stack_ = new QStackedWidget(canvas_box);
    flow_ = new NodeFlowWidget(canvas_stack_);
    canvas_tree_ = new QTreeWidget(canvas_stack_);
    canvas_tree_->setHeaderLabels({tr("Node"), tr("Connections")});
    // The outline list is read-only: no in-place edits and no node placement.
    canvas_tree_->setEditTriggers(QAbstractItemView::NoEditTriggers);
    canvas_tree_->setDragDropMode(QAbstractItemView::NoDragDrop);
    canvas_tree_->viewport()->installEventFilter(this);
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
    run_button_ = new QPushButton(tr("Run All"), view_box);
    toolbar->addWidget(run_button_);
    run_to_button_ = new QPushButton(tr("Run to Node"), view_box);
    toolbar->addWidget(run_to_button_);
    // Node-specific function buttons live in this reserved area (e.g. Box ROI
    // -> 重置包围盒 / ROI 框选). Populated by updateNodeActionButtons().
    node_action_bar_ = new QHBoxLayout;
    node_action_bar_->setSpacing(4);
    toolbar->addLayout(node_action_bar_);
    // Per-frame Move/Rotate tool: left-drag translates the frames selected in
    // the properties panel, right-drag rotates them (see PointCloudView).
    transform_button_ = new QPushButton(tr("Move/Rotate"), view_box);
    transform_button_->setCheckable(true);
    toolbar->addWidget(transform_button_);
    reset_transform_button_ = new QPushButton(tr("Reset Transform"), view_box);
    toolbar->addWidget(reset_transform_button_);
    toolbar->addStretch(1);
    // "Show Data Types" multi-select filter (default all checked): clouds,
    // bounding boxes and lines (lines reserved for future geometry).
    toolbar->addWidget(new QLabel(tr("Show Data Types:"), view_box));
    show_types_button_ = new QToolButton(view_box);
    show_types_button_->setPopupMode(QToolButton::InstantPopup);
    auto* types_menu = new QMenu(show_types_button_);
    show_cloud_action_ = types_menu->addAction(tr("Point Clouds"));
    show_cloud_action_->setCheckable(true);
    show_cloud_action_->setChecked(true);
    show_box_action_ = types_menu->addAction(tr("Bounding Boxes"));
    show_box_action_->setCheckable(true);
    show_box_action_->setChecked(true);
    show_line_action_ = types_menu->addAction(tr("Lines"));
    show_line_action_->setCheckable(true);
    show_line_action_->setChecked(true);
    show_types_button_->setMenu(types_menu);
    show_types_button_->setText(tr("All"));
    toolbar->addWidget(show_types_button_);
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
    auto* props_toolbar = new QHBoxLayout;
    auto* select_all_btn = new QPushButton(tr("Select All"), props_box);
    auto* clear_sel_btn = new QPushButton(tr("Clear"), props_box);
    props_toolbar->addWidget(select_all_btn);
    props_toolbar->addWidget(clear_sel_btn);
    props_toolbar->addStretch(1);
    props_layout->addLayout(props_toolbar);
    results_tree_ = new QTreeWidget(props_box);
    results_tree_->setHeaderLabels(
        {tr("Object"), tr("Points"), tr("Kind"), tr("Source")});
    results_tree_->setSelectionMode(QAbstractItemView::ExtendedSelection);
    results_tree_->setSelectionBehavior(QAbstractItemView::SelectRows);
    props_layout->addWidget(results_tree_);
    applyPanelShadow(props_box);
    right_panel->addWidget(props_box);
    right_panel->setStretchFactor(0, 1);
    right_panel->setStretchFactor(1, 2);
    central->addWidget(right_panel);
    central->setStretchFactor(3, 0);

    connect(results_tree_, &QTreeWidget::itemSelectionChanged, this,
            &MainWindow::applyPropsSelection);
    connect(select_all_btn, &QPushButton::clicked, this,
            [this] { selectAllProps(true); });
    connect(clear_sel_btn, &QPushButton::clicked, this,
            [this] { selectAllProps(false); });

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
        run_button_->setText(tr("Run All"));
    }
    if (run_to_button_) {
        run_to_button_->setText(tr("Run to Node"));
    }
    updateNodeActionButtons();
    updateRunControls();
}

void MainWindow::changeEvent(QEvent* event) {
    if (event->type() == QEvent::LanguageChange) {
        retranslateUi();
    }
    QMainWindow::changeEvent(event);
}

bool MainWindow::eventFilter(QObject* watched, QEvent* event) {
    if (watched == (canvas_tree_ ? canvas_tree_->viewport() : nullptr) &&
        event->type() == QEvent::Wheel) {
        auto* wheel = static_cast<QWheelEvent*>(event);
        // Ctrl+wheel-up in the outline view means "zoom in": switch back to
        // the canvas so the user is never stuck in the read-only list.
        if ((wheel->modifiers() & Qt::ControlModifier) &&
            wheel->angleDelta().y() > 0) {
            setCanvasLayout(0);
            return true;
        }
    }
    return QMainWindow::eventFilter(watched, event);
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
    // Cloud-properties panel now shows this node's inputs + outputs and
    // defaults to selecting the input frames, which drives the 3D view and
    // the Box ROI baseline. Must run before enterRoiEdit() so the ROI
    // interaction sees the current node's frame selection.
    refreshPropsTree();
    const bool is_box_roi = node && node->type() == "box_roi";
    if (!is_box_roi) {
        cloud_view_->enableRoiEdit(false);
    }
    updateRoiBoxPreview();
    updateNodeActionButtons();
    if (is_box_roi && roi_button_) {
        // Auto-enter interactive ROI editing as soon as a Box ROI node is
        // selected, so the user does not have to select the node and then
        // click the ROI button (which now lives in the node action area).
        roi_button_->blockSignals(true);
        roi_button_->setChecked(true);
        roi_button_->blockSignals(false);
        enterRoiEdit();
    }
    updateRunControls();
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
    // ROI interactions operate on the frames selected in the properties
    // panel: when the user picked specific input frames, only those frames
    // contribute to the box baseline (multi-select merges them). An empty
    // selection keeps the historical "whole input" behavior.
    const std::vector<std::int64_t> selected = selectedInputIndices(0);
    for (const auto& e : graph_.edges()) {
        if (e.to_id != id || e.to_port != 0) continue;
        const auto* out = graph_.output(e.from_id, e.from_port);
        if (!out) continue;
        for (std::size_t i = 0; i < out->objects.size(); ++i) {
            if (!selected.empty() &&
                std::find(selected.begin(), selected.end(),
                          static_cast<std::int64_t>(i)) == selected.end()) {
                continue;
            }
            const auto& c = *out->objects[i]->cloud;
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
    display_routes_.erase(id.toStdString());
    for (const QString& name : viewports_->names()) {
        viewports_->viewport(name)->clearDisplayLayer(id);
    }
    flow_->removeNode(id.toStdString());
    refreshCanvasTree();
    if (selected_node_id_ == id.toStdString()) {
        selected_node_id_.clear();
        params_panel_->clearPanel();
        if (roi_button_) roi_button_->setChecked(false);
        cloud_view_->enableRoiEdit(false);
        cloud_view_->hideRoiBox();
        refreshPropsTree();
    }
    updateNodeActionButtons();
    updateRunControls();
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
        if (roi_button_) roi_button_->setChecked(false);
        return;
    }
    enterRoiEdit();
}

void MainWindow::enterRoiEdit() {
    pcsearch::pipeline::Node* node = graph_.node(selected_node_id_);
    if (!node || node->type() != "box_roi") return;
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
            log(tr("ROI edit enabled: left-drag the body to move, drag a face "
                   "handle along its normal to resize that axis, drag an edge "
                   "handle to rotate; wheel zooms; results are written back to "
                   "the Box ROI node"));
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
    log(tr("ROI edit enabled: left-drag the body to move, drag a face handle "
           "along its normal to resize that axis, drag an edge handle to "
           "rotate; wheel zooms; results are written back to the Box ROI node"));
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
        if (!roi_button_ || !roi_button_->isChecked()) {
            // Auto-enter ROI 框选 so the box is visible and immediately
            // operable; onRoiToggle re-places the widget with the new params.
            if (roi_button_) roi_button_->setChecked(true);
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
            if (roi_button_ && roi_button_->isChecked() &&
                selected_node_id_ == node_id.toStdString()) {
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

void MainWindow::runGraph(bool to_selected) {
    if (running_) {
        log(tr("Graph is already running"));
        return;
    }
    if (graph_.nodes().empty()) {
        log(tr("Nothing to run - add nodes first"));
        return;
    }
    if (to_selected && selected_node_id_.empty()) {
        log(tr("Select a node first, then run to node"));
        return;
    }
    running_ = true;
    last_run_to_selected_ = to_selected;
    setEditingEnabled(false);
    updateRunControls();
    statusBar()->showMessage(tr("Running graph..."));
    log(tr("Running graph..."));

    runner_ = new GraphRunner(&graph_);
    runner_thread_ = new QThread(this);
    runner_->moveToThread(runner_thread_);
    connect(runner_thread_, &QThread::finished, runner_, &QObject::deleteLater);
    connect(this, &MainWindow::runRequested, runner_, &GraphRunner::run);
    connect(runner_, &GraphRunner::nodeFinished, this,
            [this](const QString& id, double ms) {
                log(tr("Node %1: %2 ms").arg(id).arg(ms, 0, 'f', 1));
            });
    connect(runner_, &GraphRunner::blockProgress, this,
            [this](int, int) {
                if (display_timer_) display_timer_->start();
            });
    connect(runner_, &GraphRunner::finished, this, &MainWindow::onRunFinished);
    runner_thread_->start();
    emit runRequested(to_selected, QString::fromStdString(selected_node_id_));
}

void MainWindow::onRunFinished(bool ok, const QString& error) {
    if (display_timer_) display_timer_->stop();
    if (runner_thread_) {
        runner_thread_->quit();
        runner_thread_->wait();
        runner_thread_->deleteLater();
    }
    runner_ = nullptr;
    runner_thread_ = nullptr;
    running_ = false;
    setEditingEnabled(true);
    updateRunControls();

    if (ok) {
        log(tr("Graph executed successfully"));
        refreshResults(last_run_to_selected_ && !selected_node_id_.empty());
        // With a selected node, refreshResults() already re-applied the
        // properties selection to the 3D view; without one, show the last
        // node output (display3d layers take precedence on their viewports).
        if (selected_node_id_.empty()) showFallbackOutput();
        updateRoiBoxPreview();
        routeDisplayNodes();
        updateNodeActionButtons();
        statusBar()->showMessage(
            tr("Drag nodes here, connect ports, press F5 to run."));
    } else {
        log(error);
        statusBar()->showMessage(tr("Graph execution failed"));
    }
}

void MainWindow::routeDisplayNodes() {
    std::map<std::string, std::string> next_routes;
    std::set<std::string> selection_cleared;
    for (auto* node : graph_.nodes()) {
        if (node->type() != "display3d") continue;
        const std::string viewport_name = node->params().getString("viewport");
        const auto* out = graph_.output(node->id());
        if (!out) continue;
        PointCloudView* view = viewports_->viewport(
            QString::fromStdString(viewport_name));
        if (view) {
            const QString node_id = QString::fromStdString(node->id());
            const auto prev = display_routes_.find(node->id());
            if (prev != display_routes_.end() && prev->second != viewport_name) {
                viewports_->viewport(QString::fromStdString(prev->second))
                    ->clearDisplayLayer(node_id);
            }
            // Display 3D layers are authoritative on their viewport: drop the
            // node-selection layer once so selection and display do not stack.
            if (selection_cleared.insert(viewport_name).second) {
                view->clearDisplayLayer(PointCloudView::selectionLayerId());
            }
            view->setDisplayLayer(node_id, out);
            next_routes[node->id()] = viewport_name;
            log(tr("Displayed %1 in viewport %2")
                    .arg(QString::fromStdString(node->id()),
                         QString::fromStdString(viewport_name)));
        }
    }
    // Remove layers whose display3d node no longer exists / is no longer
    // routed (deleted nodes are already cleaned up in doDeleteNode, this
    // covers viewport renames and stale results).
    for (const auto& [node_id, viewport] : display_routes_) {
        if (!next_routes.count(node_id)) {
            viewports_->viewport(QString::fromStdString(viewport))
                ->clearDisplayLayer(QString::fromStdString(node_id));
        }
    }
    display_routes_ = std::move(next_routes);
}

void MainWindow::refreshDisplayLayers() {
    if (!runner_ || !running_) return;
    for (const auto& entry : runner_->latestDisplay()) {
        PointCloudView* view = viewports_->viewport(
            QString::fromStdString(entry.viewport));
        if (view) {
            view->setDisplayLayer(QString::fromStdString(entry.node_id),
                                  &entry.objects);
        }
    }
}

void MainWindow::setEditingEnabled(bool enabled) {
    toolbox_->setEnabled(enabled);
    flow_->setEnabled(enabled);
    params_panel_->setEnabled(enabled);
}

void MainWindow::updateRunControls() {
    const bool can_run = !running_ && !graph_.nodes().empty();
    if (run_button_) {
        run_button_->setEnabled(can_run);
        run_button_->setText(running_ ? tr("Running...") : tr("Run All"));
    }
    if (run_to_button_) {
        const bool can_run_to = can_run && !selected_node_id_.empty();
        run_to_button_->setEnabled(can_run_to);
        run_to_button_->setText(running_ ? tr("Running...") : tr("Run to Node"));
        run_to_button_->setToolTip(
            selected_node_id_.empty()
                ? tr("Select a node first, then run the graph up to it")
                : tr("Run the graph up to the selected node"));
    }
    if (run_action_) run_action_->setEnabled(can_run);
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
        showFallbackOutput();
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

void MainWindow::refreshResults(bool prefer_outputs) {
    refreshPropsTree(prefer_outputs);
}

namespace {

QString objKindText(const pcsearch::core::PointCloudObject& obj) {
    QString kinds;
    for (const auto& r : obj.regions) {
        if (!kinds.isEmpty()) kinds += ", ";
        kinds += QString::fromStdString(r.label);
    }
    return kinds;
}

QTreeWidgetItem* makeObjectRow(const pcsearch::core::PointCloudObject& obj,
                               const QString& source_node, int source_port,
                               int index, bool is_input, int input_port) {
    auto* item = new QTreeWidgetItem;
    item->setText(0, QString::fromStdString(obj.name));
    item->setText(1, obj.cloud ? QString::number(obj.cloud->size()) : QStringLiteral("0"));
    item->setText(2, objKindText(obj));
    item->setText(3, source_node);
    item->setData(0, kPropsNodeRole, source_node);
    item->setData(0, kPropsPortRole, source_port);
    item->setData(0, kPropsIndexRole, index);
    item->setData(0, kPropsInputRole, is_input);
    item->setData(0, kPropsInputPortRole, input_port);
    return item;
}

// True when a group actually contains object rows (the "(no inputs)"
// placeholder row alone does not count).
bool groupHasObjectRows(const QTreeWidgetItem* group) {
    for (int c = 0; c < group->childCount(); ++c) {
        const QTreeWidgetItem* port = group->child(c);
        for (int r = 0; r < port->childCount(); ++r) {
            if (port->child(r)->data(0, kPropsIndexRole).isValid()) return true;
        }
    }
    return false;
}

}  // namespace

void MainWindow::refreshPropsTree(bool prefer_outputs) {
    results_tree_->blockSignals(true);
    results_tree_->clear();
    const std::string sel = selected_node_id_;
    pcsearch::pipeline::Node* node = graph_.node(sel);

    if (!node) {
        // Nothing selected: fall back to a read-only list of every node's
        // first output (historical behavior).
        for (auto* n : graph_.nodes()) {
            auto* node_item = new QTreeWidgetItem(results_tree_);
            node_item->setText(0, QString::fromStdString(n->id()));
            const auto* out = graph_.output(n->id());
            if (!out) continue;
            for (std::size_t i = 0; i < out->objects.size(); ++i) {
                auto* obj_item = makeObjectRow(*out->objects[i],
                                               QString::fromStdString(n->id()), 0,
                                               static_cast<int>(i), false, -1);
                node_item->addChild(obj_item);
            }
            results_tree_->expandItem(node_item);
        }
        results_tree_->blockSignals(false);
        return;
    }

    auto* root = new QTreeWidgetItem(results_tree_);
    root->setText(0, QString::fromStdString(sel));
    root->setFlags(root->flags() & ~Qt::ItemIsSelectable);

    // ---- Inputs: upstream edges grouped by input port ----
    auto* in_group = new QTreeWidgetItem(root);
    in_group->setText(0, tr("Input"));
    in_group->setFlags(in_group->flags() & ~Qt::ItemIsSelectable);
    in_group->setData(0, kPropsInputRole, true);
    bool any_input = false;
    for (std::size_t p = 0; p < node->inputCount(); ++p) {
        const pcsearch::core::ObjectList* list = nullptr;
        QString from_id;
        int from_port = -1;
        for (const auto& e : graph_.edges()) {
            if (e.to_id != sel || e.to_port != static_cast<int>(p)) continue;
            from_id = QString::fromStdString(e.from_id);
            from_port = e.from_port;
            list = graph_.output(e.from_id, e.from_port);
            break;
        }
        if (!list || list->objects.empty()) continue;
        auto* port_item = new QTreeWidgetItem(in_group);
        port_item->setText(0, QStringLiteral("Port %1 (%2)")
                                 .arg(static_cast<int>(p))
                                 .arg(QString::fromStdString(node->inputKind(p))));
        port_item->setFlags(port_item->flags() & ~Qt::ItemIsSelectable);
        for (std::size_t i = 0; i < list->objects.size(); ++i) {
            auto* row = makeObjectRow(*list->objects[i], from_id,
                                      from_port, static_cast<int>(i), true,
                                      static_cast<int>(p));
            port_item->addChild(row);
            any_input = true;
        }
    }
    if (!any_input) {
        auto* empty = new QTreeWidgetItem(in_group);
        empty->setText(0, tr("(no inputs)"));
        empty->setFlags(empty->flags() & ~Qt::ItemIsSelectable);
    }

    // ---- Outputs: every output port of the selected node ----
    auto* out_group = new QTreeWidgetItem(root);
    out_group->setText(0, tr("Output"));
    out_group->setFlags(out_group->flags() & ~Qt::ItemIsSelectable);
    out_group->setData(0, kPropsInputRole, false);
    bool any_output = false;
    for (std::size_t p = 0; p < node->outputCount(); ++p) {
        const auto* list = graph_.output(sel, static_cast<int>(p));
        if (!list || list->objects.empty()) continue;
        auto* port_item = new QTreeWidgetItem(out_group);
        port_item->setText(0, QStringLiteral("Port %1 (%2)")
                                  .arg(static_cast<int>(p))
                                  .arg(QString::fromStdString(node->outputKind(p))));
        port_item->setFlags(port_item->flags() & ~Qt::ItemIsSelectable);
        for (std::size_t i = 0; i < list->objects.size(); ++i) {
            auto* row = makeObjectRow(*list->objects[i],
                                      QString::fromStdString(sel),
                                      static_cast<int>(p), static_cast<int>(i),
                                      false, -1);
            port_item->addChild(row);
            any_output = true;
        }
    }
    if (!any_output) {
        auto* empty = new QTreeWidgetItem(out_group);
        empty->setText(0, tr("(no outputs)"));
        empty->setFlags(empty->flags() & ~Qt::ItemIsSelectable);
    }

    results_tree_->expandAll();
    results_tree_->blockSignals(false);
    // Default selection drives the 3D view but must not reset a previously
    // configured Box ROI frame filter.
    props_sync_filter_ = false;
    selectAllProps(true, false, prefer_outputs);
    props_sync_filter_ = true;
}

void MainWindow::selectAllProps(bool select, bool sync_filter,
                                bool prefer_outputs) {
    // Decide the default group: inputs when the selected node actually has
    // input object rows, otherwise outputs. Two degenerate layouts must fall
    // back to outputs: source nodes whose input group only carries the
    // "(no inputs)" placeholder, and the no-node-selected fallback list where
    // object rows hang directly under the node root (no group/port layers).
    bool prefer_input = false;
    if (select) {
        bool has_input = false;
        bool has_output = false;
        for (int i = 0; i < results_tree_->topLevelItemCount(); ++i) {
            QTreeWidgetItem* root = results_tree_->topLevelItem(i);
            for (int g = 0; g < root->childCount(); ++g) {
                QTreeWidgetItem* child = root->child(g);
                if (child->data(0, kPropsIndexRole).isValid()) {
                    // Fallback list: rows directly under the node root.
                    has_output = true;
                    continue;
                }
                const bool input_group = child->data(0, kPropsInputRole).toBool();
                if (input_group) {
                    has_input = has_input || groupHasObjectRows(child);
                } else {
                    has_output = has_output || groupHasObjectRows(child);
                }
            }
        }
        prefer_input = has_input;
        (void)has_output;
    }
    if (prefer_outputs) prefer_input = false;

    std::vector<QTreeWidgetItem*> object_rows;
    for (int i = 0; i < results_tree_->topLevelItemCount(); ++i) {
        QTreeWidgetItem* root = results_tree_->topLevelItem(i);
        for (int g = 0; g < root->childCount(); ++g) {
            QTreeWidgetItem* child = root->child(g);
            if (child->data(0, kPropsIndexRole).isValid()) {
                // Fallback layout: rows hang directly under the node root.
                if (!select || !prefer_input) object_rows.push_back(child);
                continue;
            }
            const bool input_group = child->data(0, kPropsInputRole).toBool();
            if (select && input_group != prefer_input) continue;
            for (int c = 0; c < child->childCount(); ++c) {
                QTreeWidgetItem* port = child->child(c);
                for (int r = 0; r < port->childCount(); ++r) {
                    QTreeWidgetItem* row = port->child(r);
                    if (!row->data(0, kPropsIndexRole).isValid()) continue;
                    object_rows.push_back(row);
                }
            }
        }
    }
    if (select) {
        results_tree_->clearSelection();
        for (QTreeWidgetItem* row : object_rows) {
            row->setSelected(true);
        }
        if (!object_rows.empty()) results_tree_->setCurrentItem(object_rows.front());
    } else {
        results_tree_->clearSelection();
    }
    if (!sync_filter) props_sync_filter_ = false;
    applyPropsSelection();
    props_sync_filter_ = true;
}

std::vector<std::int64_t> MainWindow::selectedInputIndices(int port) const {
    std::vector<std::int64_t> out;
    const QList<QTreeWidgetItem*> selected = results_tree_->selectedItems();
    for (QTreeWidgetItem* item : selected) {
        if (!item->data(0, kPropsIndexRole).isValid()) continue;
        if (!item->data(0, kPropsInputRole).toBool()) continue;
        if (item->data(0, kPropsInputPortRole).toInt() != port) continue;
        out.push_back(item->data(0, kPropsIndexRole).toInt());
    }
    return out;
}

void MainWindow::applyPropsSelection() {
    struct Candidate {
        QString node;
        int port = 0;
        int index = 0;
        bool input = false;
    };
    std::vector<Candidate> inputs;
    std::vector<Candidate> outputs;
    const QList<QTreeWidgetItem*> selected = results_tree_->selectedItems();
    for (QTreeWidgetItem* item : selected) {
        if (!item->data(0, kPropsIndexRole).isValid()) continue;
        Candidate c;
        c.node = item->data(0, kPropsNodeRole).toString();
        c.port = item->data(0, kPropsPortRole).toInt();
        c.index = item->data(0, kPropsIndexRole).toInt();
        c.input = item->data(0, kPropsInputRole).toBool();
        (c.input ? inputs : outputs).push_back(c);
    }

    // Output selections win; otherwise input selections drive the view.
    const std::vector<Candidate>& chosen = outputs.empty() ? inputs : outputs;
    pcsearch::core::ObjectList show;
    std::vector<app::PointCloudView::FrameRef> targets;
    for (const Candidate& c : chosen) {
        const auto* list = graph_.output(c.node.toStdString(), c.port);
        if (!list || c.index < 0 ||
            static_cast<std::size_t>(c.index) >= list->objects.size()) {
            continue;
        }
        const auto& obj = list->objects[static_cast<std::size_t>(c.index)];
        const bool has_cloud = obj->cloud && obj->cloud->size() > 0;
        const bool has_box = obj->roi && obj->roi->valid;
        if (!has_cloud && !has_box) continue;
        show.objects.push_back(obj);
        app::PointCloudView::FrameRef ref;
        ref.source = c.node;
        ref.frame = QString::fromStdString(obj->name);
        targets.push_back(std::move(ref));
    }
    // The Move/Rotate tool acts on exactly the frames the selection shows.
    cloud_view_->setTransformTargets(targets);
    if (show.objects.empty()) {
        cloud_view_->clearView();
    } else {
        cloud_view_->showObjectList(&show);
    }
    if (props_sync_filter_) syncBoxRoiFilter();
    // ROI baseline follows the selected input frames (project requirement).
    updateRoiBoxPreview();
}

void MainWindow::syncBoxRoiFilter() {
    pcsearch::pipeline::Node* node = graph_.node(selected_node_id_);
    if (!node || node->type() != "box_roi") return;
    int total_input = 0;
    for (const auto& e : graph_.edges()) {
        if (e.to_id != selected_node_id_ || e.to_port != 0) continue;
        if (const auto* l = graph_.output(e.from_id, e.from_port)) {
            total_input = static_cast<int>(l->objects.size());
        }
        break;
    }
    std::vector<int> selected;
    const QList<QTreeWidgetItem*> items = results_tree_->selectedItems();
    for (QTreeWidgetItem* item : items) {
        if (!item->data(0, kPropsIndexRole).isValid()) continue;
        if (!item->data(0, kPropsInputRole).toBool()) continue;
        if (item->data(0, kPropsInputPortRole).toInt() != 0) continue;
        selected.push_back(item->data(0, kPropsIndexRole).toInt());
    }
    std::sort(selected.begin(), selected.end());
    std::string filter;
    // Proper subset only: select-all / clear keep "all frames" semantics.
    if (!selected.empty() && static_cast<int>(selected.size()) < total_input) {
        for (std::size_t k = 0; k < selected.size(); ++k) {
            if (k) filter += ",";
            filter += std::to_string(selected[k]);
        }
    }
    if (filter == node->params().getString("frame_filter")) return;
    try {
        graph_.setParam(selected_node_id_, "frame_filter",
                        pcsearch::pipeline::ParamValue{filter});
        log(tr("Box ROI frame filter: %1 (press F5 to recompute)")
                .arg(filter.empty() ? QStringLiteral("all frames")
                                    : QString::fromStdString(filter)));
    } catch (const std::exception& e) {
        log(QString::fromUtf8(e.what()));
    }
}

void MainWindow::showFallbackOutput() {
    // No node selected: show the last node that produced output (the old
    // "Show Output" combo's default). The view applies the type filter.
    const pcsearch::core::ObjectList* out = nullptr;
    for (auto* node : graph_.nodes()) {
        if (const auto* o = graph_.output(node->id())) out = o;
    }
    if (!out || out->objects.empty()) {
        cloud_view_->clearView();
        return;
    }
    cloud_view_->showObjectList(out);
}

void MainWindow::applyDisplayTypeFilter() {
    cloud_view_->setVisibleKinds(show_cloud_action_->isChecked(),
                                 show_box_action_->isChecked(),
                                 show_line_action_->isChecked());
    // Re-render the current content with the new filter. display3d layers are
    // re-routed; a selected node re-applies its properties selection; with no
    // selection the fallback output is shown.
    routeDisplayNodes();
    if (!selected_node_id_.empty()) {
        applyPropsSelection();
    } else {
        showFallbackOutput();
    }
}

void MainWindow::updateNodeActionButtons() {
    if (!node_action_bar_) return;
    // The ROI button lives in this bar and is rebuilt on every selection
    // change; drop the old pointer before the old widget is deleted.
    roi_button_ = nullptr;
    while (node_action_bar_->count() > 0) {
        QLayoutItem* item = node_action_bar_->takeAt(0);
        if (QWidget* w = item->widget()) w->deleteLater();
        delete item;
    }
    pcsearch::pipeline::Node* node = graph_.node(selected_node_id_);
    if (!node || node->type() != "box_roi") return;
    const std::string node_id = node->id();
    // ROI 框选 is Box ROI node-specific: it only appears here.
    roi_button_ = new QPushButton(tr("ROI"), this);
    roi_button_->setCheckable(true);
    node_action_bar_->addWidget(roi_button_);
    connect(roi_button_, &QPushButton::toggled, this, &MainWindow::onRoiToggle);
    auto* fit = new QPushButton(tr("Reset Bounds (Fit Input Cloud)"), this);
    connect(fit, &QPushButton::clicked, this,
            [this, node_id](bool) {
                onParamsAction(QString::fromStdString(node_id),
                               QLatin1String("fit_bounds"));
            });
    node_action_bar_->addWidget(fit);
}

void MainWindow::rebuildPalette() {
    toolbox_->populate(pcsearch::pipeline::NodeRegistry::instance().all(),
                       translator_ != nullptr);
}

void MainWindow::setCanvasLayout(int index) {
    const int page = index == 1 ? 1 : 0;
    if (page == canvas_layout_index_ && canvas_stack_->currentIndex() == page) {
        return;
    }
    canvas_layout_index_ = page;
    canvas_stack_->setCurrentIndex(page);
    if (canvas_view_button_) canvas_view_button_->setChecked(page == 0);
    if (outline_view_button_) outline_view_button_->setChecked(page == 1);
    // The outline is read-only: no node placement while it is active.
    if (toolbox_) toolbox_->setEnabled(page == 0);
    if (page == 1) {
        log(tr("Outline view is read-only; switch back to Canvas to edit the graph"));
    }
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
