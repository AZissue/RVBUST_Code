#include "MainWindow.h"

#include <QAction>
#include <QApplication>
#include <QCloseEvent>
#include <QDockWidget>
#include <QFileDialog>
#include <QGraphicsScene>
#include <QHeaderView>
#include <QHBoxLayout>
#include <QLabel>
#include <QMainWindow>
#include <QMenuBar>
#include <QMouseEvent>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QShortcut>
#include <QStatusBar>
#include <QTabWidget>
#include <QTableWidget>
#include <QToolBar>
#include <QToolButton>
#include <QVBoxLayout>

#ifdef Q_OS_WIN
#include <windows.h>
#include <windowsx.h>
#endif

#include <QtNodes/BasicGraphicsScene>
#include <QtNodes/Definitions>
#include <QtNodes/internal/NodeGraphicsObject.hpp>

#include "EngineRunner.h"
#include "FlowModel.h"
#include "FlowView.h"
#include "PropertyPanel.h"
#include "Theme.h"
#include "Toolbox.h"
#include "Viewport3D.h"
#include "ViewportManager.h"
#include "core/Engine.h"
#include "modules/CloudUtils.h"
#include "modules/acquisition/LoadPlyModule.h"
#include "modules/display/Display3DModule.h"
#include "modules/fit/FitPlaneModule.h"
#include "modules/measure/PointToPlaneDistanceModule.h"
#include "modules/preprocess/BoxRoiModule.h"
#include "modules/preprocess/VoxelDownsampleModule.h"

namespace rvc {

namespace {

QToolButton* makeTitleButton(const QString& text, QWidget* parent)
{
    auto* btn = new QToolButton(parent);
    btn->setText(text);
    btn->setToolButtonStyle(Qt::ToolButtonTextOnly);
    btn->setProperty("class", "title-button");
    btn->setFixedSize(40, 28);
    btn->setCursor(Qt::PointingHandCursor);
    return btn;
}

} // namespace

MainWindow::MainWindow(QWidget* parent)
    : QWidget(parent)
{
    setWindowTitle(QStringLiteral("RvcVisionStudio — RVC 3D 视觉流程编排"));
    resize(1440, 900);
    setWindowFlags(Qt::Window | Qt::FramelessWindowHint);
    setAttribute(Qt::WA_TranslucentBackground, false);

    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);

    // ---- 自定义暗色标题栏 ----
    titleBar_ = new QWidget(this);
    titleBar_->setObjectName(QStringLiteral("titleBar"));
    titleBar_->setFixedHeight(32);
    auto* titleLayout = new QHBoxLayout(titleBar_);
    titleLayout->setContentsMargins(12, 0, 0, 0);
    titleLayout->setSpacing(0);

    titleLabel_ = new QLabel(windowTitle(), titleBar_);
    titleLabel_->setObjectName(QStringLiteral("titleLabel"));
    titleLabel_->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);

    auto* minBtn = makeTitleButton(QStringLiteral("−"), titleBar_);
    maxButton_ = makeTitleButton(QStringLiteral("□"), titleBar_);
    auto* closeBtn = makeTitleButton(QStringLiteral("×"), titleBar_);
    closeBtn->setObjectName(QStringLiteral("closeBtn"));

    connect(minBtn, &QToolButton::clicked, this, &QWidget::showMinimized);
    connect(maxButton_, &QToolButton::clicked, this, [this]() {
        if (isMaximized())
            showNormal();
        else
            showMaximized();
        updateMaximizeButton();
    });
    connect(closeBtn, &QToolButton::clicked, this, []() {
        QApplication::quit();
    });

    titleLayout->addWidget(titleLabel_);
    titleLayout->addStretch();
    titleLayout->addWidget(minBtn);
    titleLayout->addWidget(maxButton_);
    titleLayout->addWidget(closeBtn);

    root->addWidget(titleBar_);

    // ---- 内部 QMainWindow：承载菜单/工具栏/Dock/中央画布 ----
    inner_ = new QMainWindow(this);
    inner_->setWindowFlags(Qt::Widget);
    inner_->setObjectName(QStringLiteral("innerMainWindow"));
    root->addWidget(inner_, 1);

    setupWorkspace(inner_);

    // 更新标题栏文字
    connect(this, &QWidget::windowTitleChanged, titleLabel_, &QLabel::setText);
}

MainWindow::~MainWindow() = default;

void MainWindow::setupWorkspace(QMainWindow* w)
{
    // ---- 视窗管理器（多 3D 视窗 Dock，按名路由）----
    viewportManager_ = new ViewportManager(w, this);
    viewportManager_->setRoiPickedHandler([this](RoiBox roi) { onRoiPicked(roi); });

    // Display3D 显示回调注入：可能在 worker 线程触发，
    // 必须 QueuedConnection 投递回 GUI 线程更新视口
    Display3DModule::setDisplayCallback(
        [this](const std::string& viewport, PointCloud cloud, DisplayOverlays overlays) {
            QMetaObject::invokeMethod(
                this,
                [this, viewport, cloud = std::move(cloud), overlays = std::move(overlays)]() mutable {
                    viewportManager_->routeDisplay(viewport, std::move(cloud),
                                                   std::move(overlays));
                },
                Qt::QueuedConnection);
        });

    // ---- 中央：流程画布 ----
    flowModel_ = new FlowModel(solution_.process(), this);
    scene_.reset(new QtNodes::BasicGraphicsScene(*flowModel_)); // 无 parent，由 unique_ptr 管理生命周期
    view_ = new FlowView(*flowModel_, scene_.get(), this);
    w->setCentralWidget(view_);

    // ---- Dock：工具箱（左）----
    toolbox_ = new Toolbox(this);
    toolbox_->reload();
    toolboxDock_ = new QDockWidget(QStringLiteral("工具箱"), w);
    toolboxDock_->setObjectName(QStringLiteral("dock_toolbox"));
    toolboxDock_->setWidget(toolbox_);
    w->addDockWidget(Qt::LeftDockWidgetArea, toolboxDock_);

    // Ctrl+F 聚焦工具箱搜索
    auto* searchShortcut = new QShortcut(QKeySequence(QStringLiteral("Ctrl+F")), this);
    connect(searchShortcut, &QShortcut::activated, this, [this]() {
        toolboxDock_->show();
        toolboxDock_->raise();
        toolbox_->focusSearch();
    });

    // ---- Dock：属性（右）----
    propertyPanel_ = new PropertyPanel(this, this);
    propertyPanel_->currentCloudProvider = [this]() -> PointCloud {
        if (viewportManager_) {
            if (Viewport3D* vp = viewportManager_->ensureViewport(QStringLiteral("主视窗")))
                return vp->cloud();
        }
        return {};
    };
    propertyDock_ = new QDockWidget(QStringLiteral("属性"), w);
    propertyDock_->setObjectName(QStringLiteral("dock_property"));
    propertyDock_->setWidget(propertyPanel_);
    w->addDockWidget(Qt::RightDockWidgetArea, propertyDock_);

    // ---- Dock：日志/结果（下）----
    logView_ = new QPlainTextEdit(this);
    logView_->setReadOnly(true);
    logView_->setMaximumBlockCount(5000);

    resultsTable_ = new QTableWidget(this);
    resultsTable_->setColumnCount(3);
    resultsTable_->setHorizontalHeaderLabels(
        {QStringLiteral("模块"), QStringLiteral("输出"), QStringLiteral("数值（米/度）")});
    resultsTable_->horizontalHeader()->setStretchLastSection(true);
    resultsTable_->setEditTriggers(QAbstractItemView::NoEditTriggers);

    auto* bottomTabs = new QTabWidget(this);
    bottomTabs->addTab(logView_, QStringLiteral("日志"));
    bottomTabs->addTab(resultsTable_, QStringLiteral("结果"));
    bottomDock_ = new QDockWidget(QStringLiteral("日志 / 结果"), w);
    bottomDock_->setObjectName(QStringLiteral("dock_bottom"));
    bottomDock_->setWidget(bottomTabs);
    w->addDockWidget(Qt::BottomDockWidgetArea, bottomDock_);

    // ---- 窗口菜单：Dock 显示/折叠 + 添加3D视窗 ----
    windowMenu_ = w->menuBar()->addMenu(QStringLiteral("窗口"));
    windowMenu_->addAction(toolboxDock_->toggleViewAction());
    windowMenu_->addAction(propertyDock_->toggleViewAction());
    windowMenu_->addAction(bottomDock_->toggleViewAction());
    windowMenu_->addSeparator();
    windowMenu_->addAction(QStringLiteral("添加3D视窗"), viewportManager_,
                           &ViewportManager::addViewport);
    windowMenu_->addSeparator();
    connect(viewportManager_, &ViewportManager::viewportDockAdded, this,
            [this](QDockWidget* dock) { windowMenu_->addAction(dock->toggleViewAction()); });

    // ---- 主 3D 视窗（创建信号会把 toggleViewAction 挂进窗口菜单）----
    viewportManager_->ensureViewport(QStringLiteral("主视窗"));

    // ---- 工具栏 ----
    QToolBar* bar = w->addToolBar(QStringLiteral("主工具栏"));
    bar->setMovable(false);
    runAction_ = bar->addAction(QStringLiteral("▶ 运行"));
    QAction* openAction = bar->addAction(QStringLiteral("打开方案"));
    QAction* saveAction = bar->addAction(QStringLiteral("保存方案"));
    connect(runAction_, &QAction::triggered, this, &MainWindow::runOnce);
    connect(openAction, &QAction::triggered, this, &MainWindow::loadSolution);
    connect(saveAction, &QAction::triggered, this, &MainWindow::saveSolution);
    // 「运行」是本区域唯一 Primary 按钮（琥珀橙），其余为 Ghost
    if (QWidget* runBtn = bar->widgetForAction(runAction_)) {
        runBtn->setProperty("class", "primary");
        runBtn->style()->unpolish(runBtn);
        runBtn->style()->polish(runBtn);
    }

    // ---- 异步执行器 ----
    engineRunner_ = new EngineRunner(this);
    connect(engineRunner_, &EngineRunner::moduleFinished, this, &MainWindow::onModuleFinished,
            Qt::QueuedConnection);
    connect(engineRunner_, &EngineRunner::runFinished, this, &MainWindow::onRunFinished,
            Qt::QueuedConnection);

    // 画布选中变化 → 参数面板 + 框选 ROI 回写目标
    connect(scene_.get(), &QGraphicsScene::selectionChanged, this,
            &MainWindow::onSceneSelectionChanged);

    // 双击工具箱条目 → 在画布中心实例化
    connect(toolbox_, &Toolbox::moduleActivated, this, [this](const QString& typeId) {
        const QtNodes::NodeId id = flowModel_->addNode(typeId);
        if (id != QtNodes::InvalidNodeId)
            flowModel_->setNodeData(id, QtNodes::NodeRole::Position, QPointF(100, 100));
    });

    appendLog(QStringLiteral(
        "就绪。拖模块连线后点运行；选中节点可编辑参数；视窗「框选ROI」可把框选范围写回选中模块。"));
}

void MainWindow::updateMaximizeButton()
{
    if (!maxButton_)
        return;
    maxButton_->setText(isMaximized() ? QStringLiteral("❐") : QStringLiteral("□"));
}

void MainWindow::mouseDoubleClickEvent(QMouseEvent* event)
{
    if (titleBar_ && titleBar_->geometry().contains(event->pos())) {
        if (isMaximized())
            showNormal();
        else
            showMaximized();
        updateMaximizeButton();
    }
    QWidget::mouseDoubleClickEvent(event);
}

void MainWindow::closeEvent(QCloseEvent* event)
{
    // QWidget::close 默认只隐藏窗口；无边框主窗需显式退出应用
    QApplication::quit();
    QWidget::closeEvent(event);
}

bool MainWindow::nativeEvent(const QByteArray& eventType, void* message, qintptr* result)
{
#ifdef Q_OS_WIN
    if (eventType == "windows_generic_MSG") {
        MSG* msg = static_cast<MSG*>(message);
        if (msg->message == WM_NCHITTEST) {
            const int x = GET_X_LPARAM(msg->lParam);
            const int y = GET_Y_LPARAM(msg->lParam);
            const QPoint pos = mapFromGlobal(QPoint(x, y));
            const QRect rc = rect();
            const int border = 8;

            // 边框缩放区域（优先于标题栏拖动）
            bool left = pos.x() < border;
            bool right = pos.x() > rc.width() - border;
            bool top = pos.y() < border;
            bool bottom = pos.y() > rc.height() - border;

            if (top && left)
                *result = HTTOPLEFT;
            else if (top && right)
                *result = HTTOPRIGHT;
            else if (bottom && left)
                *result = HTBOTTOMLEFT;
            else if (bottom && right)
                *result = HTBOTTOMRIGHT;
            else if (top)
                *result = HTTOP;
            else if (bottom)
                *result = HTBOTTOM;
            else if (left)
                *result = HTLEFT;
            else if (right)
                *result = HTRIGHT;
            else if (titleBar_ && titleBar_->geometry().contains(pos)) {
                // 标题栏：按钮区域保持 HTCLIENT，其余可拖动
                // childAt 需要 MainWindow 本地坐标（pos），不能用屏幕坐标 x/y
                QWidget* child = childAt(pos);
                if (qobject_cast<QToolButton*>(child))
                    *result = HTCLIENT;
                else
                    *result = HTCAPTION;
            } else {
                return QWidget::nativeEvent(eventType, message, result);
            }
            return true;
        }
    }
#else
    Q_UNUSED(eventType)
    Q_UNUSED(message)
    Q_UNUSED(result)
#endif
    return QWidget::nativeEvent(eventType, message, result);
}

void MainWindow::appendLog(const QString& line, LogLevel level)
{
    QString color = Theme::Color::InkSecondary;
    switch (level) {
    case LogLevel::Success: color = Theme::Color::Success; break;
    case LogLevel::Warning: color = Theme::Color::Warning; break;
    case LogLevel::Error:   color = Theme::Color::Danger;  break;
    case LogLevel::Normal:  break;
    }
    logView_->appendHtml(QStringLiteral("<span style=\"color:%1;\">%2</span>")
                             .arg(color, line.toHtmlEscaped()));
}

void MainWindow::onSceneSelectionChanged()
{
    auto* scene = qobject_cast<QtNodes::BasicGraphicsScene*>(view_->scene());
    if (!scene)
        return;
    selectedModule_ = nullptr;
    const auto items = scene->selectedItems();
    for (QGraphicsItem* item : items) {
        if (auto* nodeItem = dynamic_cast<QtNodes::NodeGraphicsObject*>(item)) {
            selectedModule_ = solution_.process().module(static_cast<int>(nodeItem->nodeId()));
            break;
        }
    }
    propertyPanel_->setModule(selectedModule_);
}

void MainWindow::onRoiPicked(const RoiBox& roi)
{
    if (!selectedModule_) {
        inner_->statusBar()->showMessage(
            QStringLiteral("请先在画布选中要写 ROI 的模块（ROI裁剪 / 拟合 / 测量）"), 8000);
        return;
    }

    // 交互过程防抖：与上次写入差异过小则跳过（box widget 拖拽会高频触发）
    if (lastWrittenRoi_.valid) {
        const float eps = 1e-6f;
        const bool same = (roi.min - lastWrittenRoi_.min).norm() < eps &&
                          (roi.max - lastWrittenRoi_.max).norm() < eps;
        if (same)
            return;
    }
    lastWrittenRoi_ = roi;

    // ROI裁剪模块：直接写其 6 个范围参数；拟合/测量：写 roiXxx 参数组并启用
    bool ok = false;
    if (selectedModule_->typeId() == BoxRoiModule::kTypeId) {
        ok = true;
        ok &= selectedModule_->setParam("xmin", static_cast<double>(roi.min.x()));
        ok &= selectedModule_->setParam("ymin", static_cast<double>(roi.min.y()));
        ok &= selectedModule_->setParam("zmin", static_cast<double>(roi.min.z()));
        ok &= selectedModule_->setParam("xmax", static_cast<double>(roi.max.x()));
        ok &= selectedModule_->setParam("ymax", static_cast<double>(roi.max.y()));
        ok &= selectedModule_->setParam("zmax", static_cast<double>(roi.max.z()));
    } else {
        ok = writeRoiToParams(*selectedModule_, roi);
    }

    if (ok) {
        appendLog(QStringLiteral("[框选ROI] 已写入「%1」：(%2, %3, %4) ~ (%5, %6, %7)")
                      .arg(QString::fromStdString(selectedModule_->name()))
                      .arg(roi.min.x()).arg(roi.min.y()).arg(roi.min.z())
                      .arg(roi.max.x()).arg(roi.max.y()).arg(roi.max.z()),
                  LogLevel::Success);
        // 参数面板若正显示该模块则刷新数值
        propertyPanel_->setModule(selectedModule_);
    } else {
        inner_->statusBar()->showMessage(
            QStringLiteral("选中模块不支持 ROI 参数（支持：ROI裁剪 / 拟合 / 测量类）"), 8000);
    }
}

void MainWindow::runOnce()
{
    if (!engineRunner_->start(solution_.process())) {
        inner_->statusBar()->showMessage(QStringLiteral("正在运行中，请等待完成"), 3000);
        return;
    }
    runAction_->setEnabled(false);
    appendLog(QStringLiteral("--- 开始运行（异步） ---"));
}

void MainWindow::onModuleFinished(const ModuleRunRecord& rec)
{
    const QString name = QString::fromStdString(rec.name);
    for (const auto& log : rec.logs)
        appendLog(QStringLiteral("[%1] %2").arg(name, QString::fromStdString(log)));
    if (!rec.success)
        appendLog(QStringLiteral("[%1] 执行失败").arg(name), LogLevel::Error);
    appendLog(QStringLiteral("[%1] 耗时 %2 ms").arg(name).arg(rec.elapsedMs, 0, 'f', 1));
}

void MainWindow::onRunFinished(const RunResult& result, double totalMs)
{
    engineRunner_->reset();
    runAction_->setEnabled(true);

    if (!result.error.empty()) {
        appendLog(QStringLiteral("[错误] %1").arg(QString::fromStdString(result.error)),
                  LogLevel::Error);
        inner_->statusBar()->showMessage(QStringLiteral("运行失败"), 5000);
        return;
    }

    int failed = 0;
    for (const auto& rec : result.records) {
        if (!rec.success)
            ++failed;
    }
    const int total = static_cast<int>(result.records.size());
    const QString summary =
        failed == 0
            ? QStringLiteral("运行完成：%1 个模块全部成功，总耗时 %2 ms").arg(total).arg(totalMs, 0, 'f', 1)
            : QStringLiteral("运行完成：%1 个模块，%2 个失败，总耗时 %3 ms")
                  .arg(total).arg(failed).arg(totalMs, 0, 'f', 1);
    appendLog(summary, failed == 0 ? LogLevel::Success : LogLevel::Warning);
    inner_->statusBar()->showMessage(summary, 5000);

    fillResultsTable();
}

void MainWindow::fillResultsTable()
{
    struct Row {
        QString module, port;
        double value;
    };
    std::vector<Row> rows;
    Process& proc = solution_.process();
    for (const auto& [id, node] : proc.nodes()) {
        for (const auto& outPort : node.module->outputPorts()) {
            if (outPort.type != DataType::Scalar)
                continue;
            const PortValue v = proc.cachedOutput(id, outPort.name);
            if (const double* d = v.get<double>())
                rows.push_back({QString::fromStdString(node.module->name()),
                                QString::fromStdString(outPort.name), *d});
        }
    }

    resultsTable_->setRowCount(static_cast<int>(rows.size()));
    const QFont monoFont(Theme::monoFontFamily(), 9);
    for (size_t i = 0; i < rows.size(); ++i) {
        resultsTable_->setItem(static_cast<int>(i), 0, new QTableWidgetItem(rows[i].module));
        resultsTable_->setItem(static_cast<int>(i), 1, new QTableWidgetItem(rows[i].port));
        // 数值列用等宽字体对齐（tnum 语义）
        auto* valueItem = new QTableWidgetItem(QString::number(rows[i].value, 'g', 10));
        valueItem->setFont(monoFont);
        valueItem->setTextAlignment(Qt::AlignRight | Qt::AlignVCenter);
        resultsTable_->setItem(static_cast<int>(i), 2, valueItem);
    }
}

void MainWindow::loadDemoFlow(const QString& plyPath)
{
    // 演示链路：加载PLY → ROI裁剪 → 降采样 → 平面拟合（订阅 ROI）→ 3D显示 + 点面距
    auto addNodeAt = [this](const char* typeId, double x, double y) {
        const QtNodes::NodeId id = flowModel_->addNode(QString::fromLatin1(typeId));
        if (id != QtNodes::InvalidNodeId)
            flowModel_->setNodeData(id, QtNodes::NodeRole::Position, QPointF(x, y));
        return id;
    };
    auto link = [this](QtNodes::NodeId out, QtNodes::PortIndex outPort, QtNodes::NodeId in,
                       QtNodes::PortIndex inPort) {
        flowModel_->addConnection(QtNodes::ConnectionId{out, outPort, in, inPort});
    };

    const QtNodes::NodeId loadId = addNodeAt(LoadPlyModule::kTypeId, 0, 0);
    const QtNodes::NodeId roiId = addNodeAt(BoxRoiModule::kTypeId, 280, 0);
    const QtNodes::NodeId voxelId = addNodeAt(VoxelDownsampleModule::kTypeId, 560, 0);
    const QtNodes::NodeId fitId = addNodeAt(FitPlaneModule::kTypeId, 840, 0);
    const QtNodes::NodeId dispId = addNodeAt(Display3DModule::kTypeId, 1120, -120);
    const QtNodes::NodeId distId = addNodeAt(PointToPlaneDistanceModule::kTypeId, 1120, 120);

    solution_.process().module(static_cast<int>(loadId))
        ->setParam("filePath", plyPath.toStdString());

    link(loadId, 0, roiId, 0);     // cloud → ROI裁剪
    link(roiId, 0, voxelId, 0);    // cloud → 降采样
    link(voxelId, 0, fitId, 0);    // cloud → 平面拟合
    link(roiId, 1, fitId, 1);      // roi → 平面拟合（订阅已设置的 ROI）
    link(voxelId, 0, dispId, 0);   // cloud → 3D显示
    link(fitId, 0, dispId, 1);     // plane → 3D显示（可选叠加）
    link(fitId, 1, distId, 0);     // inliers → 点面距
    link(fitId, 0, distId, 1);     // plane → 点面距

    // 选中拟合节点，让参数面板演示自动编辑控件
    if (auto* scene = qobject_cast<QtNodes::BasicGraphicsScene*>(view_->scene())) {
        scene->clearSelection();
        if (auto* item = scene->nodeGraphicsObject(fitId))
            item->setSelected(true);
        view_->fitInView(scene->itemsBoundingRect().adjusted(-60, -60, 60, 60),
                         Qt::KeepAspectRatio);
    }

    runOnce();
}

void MainWindow::loadSolution()
{
    const QString path = QFileDialog::getOpenFileName(
        this, QStringLiteral("打开方案"), QString(), QStringLiteral("方案文件 (*.rvs.json *.json)"));
    if (path.isEmpty())
        return;

    QString err;
    if (!solution_.load(path, &err)) {
        appendLog(QStringLiteral("[错误] 方案加载失败：%1").arg(err), LogLevel::Error);
        return;
    }
    flowModel_->resetFromProcess();
    appendLog(QStringLiteral("方案已加载：%1").arg(path), LogLevel::Success);
}

void MainWindow::saveSolution()
{
    const QString path = QFileDialog::getSaveFileName(
        this, QStringLiteral("保存方案"), QStringLiteral("solution.rvs.json"),
        QStringLiteral("方案文件 (*.rvs.json *.json)"));
    if (path.isEmpty())
        return;

    QString err;
    if (!solution_.save(path, &err)) {
        appendLog(QStringLiteral("[错误] 方案保存失败：%1").arg(err), LogLevel::Error);
        return;
    }
    appendLog(QStringLiteral("方案已保存：%1").arg(path), LogLevel::Success);
}

} // namespace rvc
