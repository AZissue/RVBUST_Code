#include "app/MainWindow.h"

#include "logic/CameraManager.h"
#include "logic/CalibrationService.h"
#include "logic/CaptureFlow.h"
#include "logic/RobotPose.h"
#include "logic/PixelTo3DService.h"
#include "logic/DataManager.h"
#include "logic/LogManager.h"
#include "logic/PoseGuide.h"
#include "logic/DataQualityCheck.h"
#include "logic/ToolInputParser.h"
#include "logic/FrameBuffer.h"
#include "logic/LogPresentation.h"
#include "logic/RuntimeLog.h"
#include "logic/AutoFlowPolicy.h"
#include "logic/CameraRelease.h"
#include "ui/TopNavBar.h"
#include "ui/ModeSelector.h"
#include "ui/Image2DView.h"
#include "ui/VisSceneView.h"
#include "ui/DataInputArea.h"
#include "ui/ActionButtons.h"
#include "ui/SidePanel.h"
#include "ui/ToastOverlay.h"
#include "ui/SettingsDialog.h"
#include "ui/DeviceListDialog.h"
#include "ui/ToolsPanel.h"

#include "ui/Theme.h"

#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QSplitter>
#include <QShortcut>
#include <QMessageBox>
#include <QDialog>
#include <QApplication>
#include <QGuiApplication>
#include <QCloseEvent>
#include <QShowEvent>
#include <QKeySequence>
#include <QScreen>
#include <QVariantMap>
#include <QStringList>
#include <QDir>
#include <QDateTime>
#include <QFileInfo>
#include <QTimer>
#include <QtConcurrent>
#include <vector>
#include <array>
#include <tuple>
#ifdef _WIN32
#  ifndef NOMINMAX
#    define NOMINMAX
#  endif
#  include <windows.h>   // WM_QUERYENDSESSION / WM_ENDSESSION (任务 3.2)
#  ifdef ERROR
#    undef ERROR
#  endif
#endif

namespace {
// 任务 3.1: bounded wait for an in-flight capture/detection worker on close.
constexpr int kCloseWorkerWaitMs = 3000;
// 任务 3.2: bounded release attempt when Windows ends the session (<= 2 s).
constexpr int kSessionEndWaitMs = 1500;
} // namespace

MainWindow::MainWindow(QWidget* parent)
    : QMainWindow(parent)
{
    m_config.load();

    setWindowTitle(QStringLiteral("手眼标定数据收集助手 V1.0"));
    // Size/position is finalized in showEvent() (after the window frame exists)
    // so the window is centered and its title bar is never stranded off-screen.
    setMinimumSize(1280, 720);
    resize(1280, 720);

    // Create owned objects
    m_camera = new CameraManager(this);
    m_data   = new DataManager(this);
    m_logger = new LogManager(this);
    m_flow   = new CaptureFlow(m_camera, m_data, this);
    m_calibWatcher = new QFutureWatcher<CalibrationService::Result>(this);
    connect(m_calibWatcher, &QFutureWatcher<CalibrationService::Result>::finished,
            this, &MainWindow::onCalibrationFinished);

    m_saveBaseDir = m_config.saveBaseDir();

    // Portable-build fallback: on another machine the saved path (e.g. an old
    // dev-machine directory baked into the INI) may not exist or may not be
    // writable.  Fall back to <exe>/data (then Documents) so the green build
    // works out of the box, and persist the correction.
    if (!QDir().mkpath(m_saveBaseDir) || !QFileInfo(m_saveBaseDir).isWritable()) {
        QString portable = QCoreApplication::applicationDirPath()
                         + QStringLiteral("/data");
        if (!QDir().mkpath(portable) || !QFileInfo(portable).isWritable())
            portable = QDir::homePath()
                     + QStringLiteral("/Documents/HandEyeCalibData");
        QDir().mkpath(portable);
        m_saveBaseDir = portable;
        m_config.setSaveBaseDir(portable);
        m_savePathFellBack = true;
    }

    m_camera->setParamsOnConnect(m_config.cameraParams());
    m_flow->setErrorThreshold(m_config.caliboardErrorThreshold());

    // ── Round 5 startup policy ──
    // 任务 1: whether the camera's own capture parameters win over the saved
    // ones (default true — the operator tunes them in the vendor tool first).
    m_useCameraParams = m_config.useCameraParams();
    m_camera->setUseCameraParams(m_useCameraParams);
    // 任务 3.3/3.4: bounded connect retry + the "is the camera still there"
    // scan, which used to run every 5 s.
    m_camera->setConnectRetryCount(m_config.connectRetryCount());
    m_camera->setHealthCheckInterval(m_config.healthCheckIntervalSec() * 1000);
    RuntimeLog::log("[CAM] startup: use_camera_params=%d, connect_retry=%d, "
                    "health_interval=%d s",
                    m_useCameraParams ? 1 : 0, m_camera->connectRetryCount(),
                    m_config.healthCheckIntervalSec());

    // 任务 3.4: idle-preview pause.  0 = never pause.
    m_idlePauseSec = m_config.idlePausePreviewSec();
    m_idleTimer = new QTimer(this);
    m_idleTimer->setSingleShot(true);
    connect(m_idleTimer, &QTimer::timeout, this, &MainWindow::onIdleTimeout);
    if (m_idlePauseSec > 0) {
        // Watch application-wide input so "连续 N 秒无操作" means the whole app,
        // not just this window's widgets.
        qApp->installEventFilter(this);
        m_idleTimer->start(m_idlePauseSec * 1000);
    }

    // 任务 3.1: belt-and-braces release for exit paths that do not go through
    // closeEvent.  shutdown() is idempotent, so when closeEvent already ran this
    // is a logged no-op rather than a second Close/Destroy.
    connect(qApp, &QCoreApplication::aboutToQuit, this, [this]() {
        // Same reason as closeEvent: the Vis close has to be requested while the
        // app is still alive or it never returns (see the block in closeEvent).
        if (m_view3d)
            m_view3d->shutdown();
        if (!m_camera)
            return;
        m_camera->stopPreview();
        m_camera->shutdown();
        const auto r = m_camera->lastRelease();
        RuntimeLog::log("[CAM] release on aboutToQuit: attempted=%d released=%d %s",
                        r.attempted ? 1 : 0, r.released ? 1 : 0,
                        r.detail.isEmpty() ? "" : qPrintable(r.detail));
    });

    buildUi();
    wireSignals();
    registerShortcuts();
    // 任务 2: flow automation + the single source of truth for 自动读取机器人位姿.
    // Applied after buildUi() because it also syncs the tools-panel checkbox.
    applyAutoFlowSettings();

    // Restore last mode
    m_eyeHandMode = m_config.eyeInHand() ? EyeHandMode::EyeInHand : EyeHandMode::EyeToHand;
    m_calibType   = m_config.markerType() ? CalibType::Marker : CalibType::TcpTouch;
    m_markerType  = m_config.markerConcentric() ? MarkerType::ConcentricCircle : MarkerType::AsymmetricGrid;
    m_modeSelector->setMode(
        m_eyeHandMode == EyeHandMode::EyeInHand,
        m_calibType == CalibType::Marker,
        m_markerType == MarkerType::ConcentricCircle);

    CalibrationMode mode;
    mode.eyeHand = m_eyeHandMode;
    mode.calibType = m_calibType;
    mode.markerType = m_markerType;
    m_flow->setMode(mode);

    // Restore caliboard pattern params
    m_caliboardW    = m_config.caliboardPatternW();
    m_caliboardH    = m_config.caliboardPatternH();
    m_caliboardStep = m_config.caliboardCircleStep();
    m_modeSelector->setCaliboardParams(m_caliboardW, m_caliboardH, m_caliboardStep);
    m_flow->setCaliboardParams(m_caliboardW, m_caliboardH, m_caliboardStep);
    m_dataInput->updateVisibility(
        m_eyeHandMode == EyeHandMode::EyeInHand,
        m_calibType == CalibType::Marker);
    resetSession();

    // Delayed notice once the UI exists (event loop is not running yet here).
    if (m_savePathFellBack) {
        QTimer::singleShot(0, this, [this]() {
            m_toast->showMessage(
                QStringLiteral("原保存目录不可用，已切换到 %1").arg(m_saveBaseDir),
                false);
            m_logger->warning(
                QStringLiteral("保存目录不可用，自动切换到: %1").arg(m_saveBaseDir));
        });
    }

    // UI-thread stall watchdog: armed before any heavy work so the very first
    // freeze is already covered by the runtime log.
    startUiWatchdog();

    // Warm up the camera system + device scan in the background so that
    // clicking 连接 later goes straight to the device list and Open().
    startPreScan();
}

MainWindow::~MainWindow()
{
    // closeEvent normally released the camera already; this is the abnormal
    // path (destruction without a close, e.g. an explicit qApp->quit()).  The
    // call is the same either way because shutdown() is idempotent — on the
    // normal path it is a logged no-op, which is also the evidence that a
    // second teardown does not repeat Close/Destroy.
    if (m_idleTimer)
        m_idleTimer->stop();
    if (m_camera) {
        m_camera->stopPreview();
        m_camera->shutdown();
        const auto r = m_camera->lastRelease();
        RuntimeLog::log("[CAM] release on teardown: attempted=%d released=%d %s",
                        r.attempted ? 1 : 0, r.released ? 1 : 0,
                        r.detail.isEmpty() ? "" : qPrintable(r.detail));
    }
}

// ── UI Construction ───────────────────────────────────────────────────

void MainWindow::buildUi()
{
    auto* central = new QWidget(this);
    setCentralWidget(central);
    auto* mainLayout = new QVBoxLayout(central);
    mainLayout->setContentsMargins(0, 24, 0, 24);
    mainLayout->setSpacing(0);

    m_topNav = new TopNavBar(this);
    mainLayout->addWidget(m_topNav);

    mainLayout->addSpacing(16);

    m_modeSelector = new ModeSelector(this);
    mainLayout->addWidget(m_modeSelector);

    mainLayout->addSpacing(24);

    auto* hSplitter = new QSplitter(Qt::Horizontal, this);
    hSplitter->setStyleSheet(QStringLiteral("QSplitter::handle { background-color: %1; width: 2px; }")
                            .arg(Theme::BORDER_DEFAULT));

    auto* leftPanel = new QWidget(this);
    auto* leftLayout = new QVBoxLayout(leftPanel);
    leftLayout->setContentsMargins(24, 0, 24, 0);
    leftLayout->setSpacing(12);

    auto* viewRow = new QHBoxLayout();
    m_view2d = new Image2DView(this);
    m_view3d = new VisSceneView(this);
    viewRow->addWidget(m_view2d, 1);
    viewRow->addWidget(m_view3d, 1);
    leftLayout->addLayout(viewRow, 1);

    m_dataInput = new DataInputArea(this);
    leftLayout->addWidget(m_dataInput);

    m_actionButtons = new ActionButtons(this);
    leftLayout->addWidget(m_actionButtons);

    hSplitter->addWidget(leftPanel);

    auto* rightPanel = new QWidget(this);
    auto* rightLayout = new QVBoxLayout(rightPanel);
    rightLayout->setContentsMargins(0, 0, 0, 0);
    m_sidePanel = new SidePanel(this);
    rightLayout->addWidget(m_sidePanel);
    hSplitter->addWidget(rightPanel);

    hSplitter->setStretchFactor(0, 3);
    hSplitter->setStretchFactor(1, 1);

    mainLayout->addWidget(hSplitter, 1);

    m_toast = new ToastOverlay(this);

    // Tools panel (v2.0): non-modal, created once and shown on demand.
    m_toolsPanel = new ToolsPanel(this);
}

// ── Signal/Slot Wiring ────────────────────────────────────────────────

void MainWindow::wireSignals()
{
    // Mode changes
    connect(m_modeSelector, &ModeSelector::modeChanged,
            this, &MainWindow::onModeChanged);
    connect(m_modeSelector, &ModeSelector::caliboardParamsChanged,
            this, &MainWindow::onCaliboardParamsChanged);

    // Camera signals
    connect(m_camera, &CameraManager::previewFrameReady, this,
            // livePreview=true: streaming frames take the cheap nearest-neighbour
            // path and the 200 ms settle timer does one smooth pass afterwards.
            [this](const QImage& img) { m_view2d->updateFrame(img, true, true); });
    connect(m_camera, &CameraManager::previewRightFrameReady, this,
            [this](const QImage& img) { m_view3d->showImage(img); });
    connect(m_camera, &CameraManager::captureComplete,
            m_flow, &CaptureFlow::onCaptureReady);
    connect(m_camera, &CameraManager::captureComplete, this, [this]() {
        // New frame: line-scan reverse index and the pick highlight are stale.
        m_correspondBuilt = false;
        if (m_pickSphereHandle >= 0) {
            m_view3d->removeObject(m_pickSphereHandle);
            m_pickSphereHandle = -1;
        }
        // 上一次取点在主 2D 视窗留下的十字标记同样过期（新一次识别会重画）。
        m_view2d->clearMarkers();
    });
    connect(m_view2d, &Image2DView::pixelClicked, this, [this](int x, int y) {
        // 既有行为（黄球 + 相机目标点卡片 + 提示）保持不变。
        on2dPixelPicked(x, y);
        // 离线工具打开期间，同一次点击再转发一份给「像素→3D」页。
        if (m_toolsPanel && m_toolsPanel->isVisible()
            && m_toolsPanel->pixelTo3DOffline()) {
            m_toolsPanel->onMainViewPixelClicked(x, y);
        }
    });
    connect(m_camera, &CameraManager::cameraError, this,
            [this](const QString& msg) {
                m_logger->error(msg);
                m_sidePanel->setTip(msg, true);
                clearBusy();
                m_flow->setDetectEnabled(false);
                m_flow->setSaveEnabled(false);
            });
    connect(m_camera, &CameraManager::cameraConnected, this, [this]() {
        m_topNav->setCameraStatus(true, m_camera->deviceName());
        m_actionButtons->setCaptureEnabled(true);
        m_actionButtons->setPreviewActive(false);
        m_actionButtons->setPreviewEnabled(true);
        clearBusy();

        // 任务 1: with use_camera_params on, the values now in effect are the
        // ones the camera itself holds — write them back so 设置 shows "相机
        // 当前值" instead of a stale saved set.
        QString detail;
        if (m_useCameraParams) {
            const auto readBack = m_camera->cameraReadSettings();
            if (!readBack.isEmpty()) {
                QVariantMap asMap;
                QStringList parts;
                for (auto it = readBack.constBegin(); it != readBack.constEnd(); ++it) {
                    asMap[it.key()] = it.value();
                    parts << QStringLiteral("%1=%2").arg(it.key()).arg(it.value());
                }
                m_config.setCameraParams(asMap);
                detail = QStringLiteral("，相机参数(%1)")
                             .arg(parts.join(QStringLiteral(", ")));
            }
        }
        m_logger->success(QStringLiteral("相机连接成功%1").arg(detail));
    });
    connect(m_camera, &CameraManager::cameraDisconnected, this, [this]() {
        m_topNav->setCameraStatus(false);
        m_view3d->hideImage();
        m_actionButtons->setCaptureEnabled(false);
        m_actionButtons->setPreviewActive(false);
        m_actionButtons->setPreviewEnabled(false);
        m_logger->info(QStringLiteral("相机已断开"));
    });

    // CaptureFlow -> UI
    connect(m_flow, &CaptureFlow::busyChanged, this, [this](bool busy, const QString& text) {
        if (busy) {
            if (text.contains(QStringLiteral("识别")))
                setBusy(text, ActionButtons::BusyTarget::Detect);
            else
                setBusy(text, ActionButtons::BusyTarget::Capture);
        } else {
            clearBusy();
        }
    });
    connect(m_flow, &CaptureFlow::detectEnabledChanged,
            m_actionButtons, &ActionButtons::setDetectEnabled);
    connect(m_flow, &CaptureFlow::saveEnabledChanged,
            m_actionButtons, &ActionButtons::setSaveEnabled);
    connect(m_actionButtons, &ActionButtons::calcClicked,
            this, &MainWindow::onCalibrate);
    connect(m_data, &DataManager::dataChanged, this, [this]() {
        m_actionButtons->setCalcEnabled(m_data->count() > 0);
    });
    // 工具面板「手眼标定」页：用当前会话一键算（路径与位姿由主窗口给回）
    connect(m_toolsPanel, &ToolsPanel::calibrationSessionRequested, this,
            &MainWindow::onCalibrationSessionRequested);
    // Robot communication (isolated; wiring is inert until the user connects)
    connect(m_toolsPanel, &ToolsPanel::robotConnectRequested,
            this, &MainWindow::onRobotConnect);
    connect(m_toolsPanel, &ToolsPanel::robotDisconnectRequested,
            this, &MainWindow::onRobotDisconnect);
    connect(m_toolsPanel, &ToolsPanel::robotSimulateConnectRequested,
            this, &MainWindow::onRobotSimulateConnect);
    connect(m_toolsPanel, &ToolsPanel::robotAutoReadToggled, this,
            [this](bool on) {
                m_robotAutoRead = on;
                // 任务 2: the checkbox is a view of AppConfig's single key, so a
                // change here is persisted and shows up in 设置 next time.
                m_config.setAutoReadRobotPose(on);
            });
    // 任务 2: 识别成功 → 自动保存（走既有必填项校验）.
    connect(m_flow, &CaptureFlow::detectionFinished,
            this, &MainWindow::onDetectionFinished);
    // Robot read buttons live in the ActionButtons row (visible while connected)
    connect(m_actionButtons, &ActionButtons::readCapturePoseClicked,
            this, &MainWindow::onRobotRead);
    connect(m_actionButtons, &ActionButtons::readTouchPoseClicked,
            this, &MainWindow::onRobotReadTouch);
    connect(m_flow, &CaptureFlow::imageCaptured, this,
            [this](const QImage& img) {
                m_view2d->updateFrame(img);
                // A new capture invalidates the previous detection's pickable
                // markers until the new frame is recognized again.
                m_view3d->setMarkerPickEnabled(false);
                m_view3d->setSelectableMarkers({}, {});
                // Stale board pose until the new frame is recognized.
                m_view3d->clearBoardFrame();
                m_pendingBoardPose = BoardPoseFit::Pose{};
                // Measurement page data source: the organized 3D grid of this
                // very capture, handed over by refcount (no copy of the ~37 MB
                // buffer).  CameraManager published it before emitting the
                // capture result this slot runs on, so it matches `img`.
                FrameBuffer::DoubleBuf grid;
                int gw = 0, gh = 0;
                const bool haveGrid = m_camera->lastGrid(grid, gw, gh);
                m_toolsPanel->setMeasurementCloud(haveGrid ? grid : FrameBuffer::DoubleBuf{},
                                                  gw, gh, img.width(), img.height());
            });
    connect(m_flow, &CaptureFlow::pointCloudReady, this,
            // Shared buffers: the payload is handed over by refcount, no copy.
            [this](const FrameBuffer::FloatBuf& pts, const FrameBuffer::FloatBuf& cols) {
                m_uploading3d = true;
                beginHeavyOp(QStringLiteral("3D点云上传(%1点)")
                                 .arg(pts ? pts->size() / 3 : 0));
                m_view3d->updatePointCloud(pts, cols);
                endHeavyOp();
                m_uploading3d = false;
            });
    connect(m_flow, &CaptureFlow::markersDisplayReady, this,
            [this](const std::vector<std::tuple<float, float, std::string>>& overlay2d,
                   const std::vector<std::array<float, 3>>& highlights3d,
                   const std::vector<int>& highlightIndices) {
                m_view2d->drawMarkers(overlay2d);
                // NOTE (reported, not changed): this re-uploads the same geometry
                // that pointCloudReady() already uploaded, and without colours.
                // Kept as-is because the visible result is identical and the
                // behaviour cannot be re-verified without the GUI.
                beginHeavyOp(QStringLiteral("3D点云重传(标记)"));
                // Keep an active measurement colouring: the colours belong to
                // this same cloud (same frame, same point count), so re-using
                // them is both correct and cheaper than dropping them here.
                const FrameBuffer::FloatBuf& pts = m_flow->capturedPoints();
                const bool keepColors = m_measureCloudColors && pts
                                        && m_measureCloudColors->size() == pts->size();
                m_view3d->updatePointCloud(pts, keepColors ? m_measureCloudColors
                                                           : FrameBuffer::FloatBuf{});
                endHeavyOp();
                m_view3d->highlightPoints(highlights3d);
                m_view3d->setSelectableMarkers(highlights3d, highlightIndices);
                m_view3d->setMarkerPickEnabled(true);
                onBoardMarkers(highlights3d);
            });
    connect(m_view3d, &VisSceneView::markerPicked, this,
            [this](int index, float x, float y, float z) {
                auto* card = m_dataInput->card("camera_target_xyz");
                if (!card)
                    return;
                card->setValue(QStringLiteral("%1 %2 %3")
                                   .arg(x, 0, 'f', 3)
                                   .arg(y, 0, 'f', 3)
                                   .arg(z, 0, 'f', 3));
                m_toast->showMessage(
                    QStringLiteral("已选择识别点 #%1 填充相机目标点").arg(index), true);
                m_logger->info(QStringLiteral("3D 选择识别点 #%1 填充相机目标点")
                               .arg(index));
            });
    // Measurement tool (3D 测量一体化工具 parity).  The panel computes, the
    // views only paint: ROI rectangles go to the 2D view, the snapshot goes to
    // the 2D display pages and to the 3D deviation/annotation overlay.
    connect(m_view2d, &Image2DView::roiSelected,
            m_toolsPanel, &ToolsPanel::onRoiSelected);
    connect(m_toolsPanel, &ToolsPanel::roisChanged,
            m_view2d, &Image2DView::setRois);
    // 2D 视图工具栏的「清除 ROI」（P3.3）：清的是工具面板里的状态，叠加快照
    // 由面板随后的 roisChanged({}, {}) 擦掉。
    connect(m_view2d, &Image2DView::roiClearRequested,
            m_toolsPanel, &ToolsPanel::clearMeasurementRois);
    // P4：测量方法的说明与结果进操作日志（面板不直接碰 logger）。
    connect(m_toolsPanel, &ToolsPanel::logMessage, this,
            [this](const QString& line) { m_logger->info(line); });
    connect(m_toolsPanel, &ToolsPanel::measurementUpdated,
            m_view2d, &Image2DView::setMeasurement);
    connect(m_toolsPanel, &ToolsPanel::measurementUpdated,
            this, &MainWindow::onMeasurementUpdated);
    // The 3D "偏差着色" toolbar button and the panel's checkbox are two views of
    // one state — route each to the other so they cannot drift apart.
    connect(m_view3d, &VisSceneView::deviationColoringToggled,
            m_toolsPanel, &ToolsPanel::setDeviationColoring);
    connect(m_toolsPanel, &ToolsPanel::pixelTo3DOnlineQueryRequested,
            this, &MainWindow::onPixelTo3DOnlineQueryRequested);
    connect(m_toolsPanel, &ToolsPanel::pixelTo3DOfflineImageRequested,
            this, &MainWindow::onPixelTo3DOfflineImageRequested);
    connect(m_toolsPanel, &ToolsPanel::pixelTo3DOfflineImageEnded,
            this, &MainWindow::onPixelTo3DOfflineImageEnded);
    connect(m_toolsPanel, &ToolsPanel::deviationColoringChanged,
            m_view3d, &VisSceneView::setDeviationColoringChecked);
    connect(m_flow, &CaptureFlow::clearMarkersRequested,
            m_view2d, &Image2DView::clearMarkers);
    connect(m_flow, &CaptureFlow::tipRequested,
            m_sidePanel, &SidePanel::setTip);
    connect(m_sidePanel, &SidePanel::qualityCheckRequested,
            this, &MainWindow::refreshQualityReport);
    connect(m_flow, &CaptureFlow::toastRequested, this,
            [this](const QString& text, bool success) {
                m_toast->showMessage(text, success);
            });
    connect(m_flow, &CaptureFlow::logRequested, this,
            [this](const QString& msg, const QString& level) {
                if (level == QLatin1String("success"))      m_logger->success(msg);
                else if (level == QLatin1String("warning")) m_logger->warning(msg);
                else if (level == QLatin1String("error"))   m_logger->error(msg);
                else                                        m_logger->info(msg);
            });
    connect(m_flow, &CaptureFlow::autoFillCardRequested, this,
            [this](const QString& field, const QString& value) {
                auto* card = m_dataInput->card(field);
                if (card) card->setValue(value);
            });
    connect(m_flow, &CaptureFlow::cardInvalidRequested, this,
            [this](const QString& field) {
                auto* card = m_dataInput->card(field);
                if (card) card->setStatus(QStringLiteral("error"));
            });

    // Top nav
    connect(m_topNav, &TopNavBar::connectCameraClicked,
            this, &MainWindow::onConnectCamera);
    connect(m_topNav, &TopNavBar::disconnectCameraClicked,
            this, &MainWindow::onDisconnectCamera);
    connect(m_topNav, &TopNavBar::settingsClicked,
            this, &MainWindow::showSettingsDialog);
    connect(m_modeSelector, &ModeSelector::toolsClicked, this, [this]() {
        m_toolsPanel->show();
        m_toolsPanel->raise();
        m_toolsPanel->activateWindow();
    });
    connect(m_topNav, &TopNavBar::helpClicked, this, [this]() {
        QMessageBox::about(this, QStringLiteral("关于"),
            QStringLiteral("手眼标定数据收集助手 V1.0\n\n"
                           "基于 RVC X1/X2 相机的手眼标定数据采集工具。\n\n"
                           "支持眼在手上/眼在手外两种安装方式，\n"
                           "以及标记物标定和戳点标定两种标定方法。"));
    });

    // Action buttons
    connect(m_actionButtons, &ActionButtons::captureClicked,
            this, &MainWindow::onCapture);
    connect(m_actionButtons, &ActionButtons::detectClicked,
            m_flow, &CaptureFlow::detect);
    connect(m_actionButtons, &ActionButtons::saveClicked,
            this, &MainWindow::saveFromCards);
    connect(m_actionButtons, &ActionButtons::undoClicked,
            m_flow, &CaptureFlow::undo);
    connect(m_actionButtons, &ActionButtons::previewToggled, this,
            [this](bool on) {
                if (on) {
                    m_camera->startPreview();
                    m_actionButtons->setPreviewActive(true);
                    m_logger->info(QStringLiteral("预览已开启"));
                } else {
                    m_camera->stopPreview();
                    m_view3d->hideImage();
                    m_actionButtons->setPreviewActive(false);
                    m_logger->info(QStringLiteral("预览已停止"));
                }
            });

    // Data cards
    auto* card1 = m_dataInput->card("camera_target_xyz");
    auto* card2 = m_dataInput->card("robot_capture_pose");
    auto* card3 = m_dataInput->card("robot_target_xyz");
    if (card1) connect(card1, &DataInputCard::valueChanged, this, [this](const QString& v) { onCardChanged("camera_target_xyz", v); });
    if (card2) connect(card2, &DataInputCard::valueChanged, this, [this](const QString& v) { onCardChanged("robot_capture_pose", v); });
    if (card3) connect(card3, &DataInputCard::valueChanged, this, [this](const QString& v) { onCardChanged("robot_target_xyz", v); });

    // Data manager
    connect(m_data, &DataManager::progressUpdated, this, [this](int cur, int /*total*/) {
        m_topNav->updateProgress(cur);
        m_actionButtons->setUndoEnabled(cur > 0);
    });
    connect(m_data, &DataManager::dataChanged, this, [this]() {
        m_sidePanel->updateFilePreview(
            m_eyeHandMode == EyeHandMode::EyeInHand,
            m_calibType == CalibType::Marker,
            m_data->allRecords());
        syncBoardHistory();
        // Refresh pose guidance too (每保存/读入一帧刷新「当前 vs 最近已采」).
        auto* poseCard = m_dataInput->card(QStringLiteral("robot_capture_pose"));
        if (poseCard)
            updatePoseGuide(poseCard->value());
    });

    // Log manager →「操作日志」面板（第 10 回合 P4）。
    // 这条连接以前是个空 lambda，所以文件日志里明明有 [测量-说明] / [测量-结果]，
    // 界面上却看不到。现在真的转发：logAdded(时间戳, 正文, 级别) → appendLog()。
    // 只转发"值得上屏"的条目（MeasureTools::shouldShowInPanel：只有测量日志）——
    // LogManager 里其余条目（相机扫描/机器人连接/看门狗/设置更新…）大多同时还会走
    // setTip()，整表转发会重复显示并刷屏；它们照旧只进文件日志。
    connect(m_logger, &LogManager::logAdded, this,
            [this](const QString& /*timestamp*/, const QString& message, const QString& level) {
                if (!MeasureTools::shouldShowInPanel(message.toStdString()))
                    return;
                m_sidePanel->appendLog(level, message);
            });
}

void MainWindow::registerShortcuts()
{
    auto* shortcutSave = new QShortcut(QKeySequence("Ctrl+S"), this);
    connect(shortcutSave, &QShortcut::activated, this, &MainWindow::saveFromCards);

    auto* shortcutUndo = new QShortcut(QKeySequence("Ctrl+Z"), this);
    connect(shortcutUndo, &QShortcut::activated, m_flow, &CaptureFlow::undo);

    auto* shortcutRefresh = new QShortcut(QKeySequence("F5"), this);
    connect(shortcutRefresh, &QShortcut::activated, this, [this]() {
        if (m_camera && m_camera->isConnected()) {
            m_camera->stopPreview();
            m_camera->startPreview();
            m_logger->info(QStringLiteral("刷新预览"));
        }
    });

    auto* shortcutFull = new QShortcut(QKeySequence("F11"), this);
    connect(shortcutFull, &QShortcut::activated, this, [this]() {
        if (isFullScreen()) showNormal(); else showFullScreen();
    });
}

// ── Mode Management ───────────────────────────────────────────────────

void MainWindow::onModeChanged(bool eyeInHand, bool markerType, bool concentric)
{
    auto newEyeHand = eyeInHand ? EyeHandMode::EyeInHand : EyeHandMode::EyeToHand;
    auto newCalib   = markerType ? CalibType::Marker : CalibType::TcpTouch;
    auto newMarker  = concentric ? MarkerType::ConcentricCircle : MarkerType::AsymmetricGrid;

    bool typeChanged = (m_calibType != newCalib) || (m_markerType != newMarker);

    // Confirm before applying — if user cancels, revert the selector
    if (typeChanged && m_data->count() > 0) {
        auto reply = QMessageBox::question(this, QStringLiteral("切换标定类型"),
                                           QStringLiteral("切换标定类型将清空当前采集数据，是否继续？"));
        // Modal wait is user think-time, not a UI stall — do not report it.
        m_watchdog.reset();
        if (reply != QMessageBox::Yes) {
            m_modeSelector->blockSignals(true);
            m_modeSelector->setMode(
                m_eyeHandMode == EyeHandMode::EyeInHand,
                m_calibType == CalibType::Marker,
                m_markerType == MarkerType::ConcentricCircle);
            m_modeSelector->blockSignals(false);
            return;
        }
    }

    m_eyeHandMode = newEyeHand;
    m_calibType   = newCalib;
    m_markerType  = newMarker;

    CalibrationMode mode;
    mode.eyeHand = m_eyeHandMode;
    mode.calibType = m_calibType;
    mode.markerType = m_markerType;
    m_flow->setMode(mode);

    m_dataInput->updateVisibility(eyeInHand, markerType);
    m_sidePanel->updateFilePreview(eyeInHand, markerType, m_data->allRecords());
    updateRobotReadBar();

    if (typeChanged) {
        resetSession();
    }

    m_config.setLastMode(eyeInHand, markerType, concentric);

    auto markerStr = markerType
        ? (concentric ? QStringLiteral("同心圆") : QStringLiteral("黑底白圆"))
        : QStringLiteral("戳点");
    m_logger->info(QStringLiteral("模式切换: %1, %2")
                   .arg(eyeInHand ? QStringLiteral("眼在手上") : QStringLiteral("眼在手外"))
                   .arg(markerStr));
}

void MainWindow::onCaliboardParamsChanged(int patternW, int patternH, float circleStep)
{
    m_caliboardW = patternW;
    m_caliboardH = patternH;
    m_caliboardStep = circleStep;
    m_flow->setCaliboardParams(patternW, patternH, circleStep);
    m_config.setCaliboardParams(patternW, patternH, circleStep);
}

void MainWindow::resetSession()
{
    m_data->newSession(m_saveBaseDir, m_eyeHandMode, m_calibType);

    // Session metadata (mode, caliboard spec, camera params) is recorded in
    // the application log instead of a config.json — the calibration pipeline
    // only needs png/ply/txt in the session directory.
    QStringList metaParts;
    metaParts << QStringLiteral("手眼模式=%1")
                     .arg(m_eyeHandMode == EyeHandMode::EyeInHand
                              ? QStringLiteral("眼在手上")
                              : QStringLiteral("眼在手外"));
    metaParts << QStringLiteral("标定方法=%1")
                     .arg(m_calibType == CalibType::Marker
                              ? QStringLiteral("标记物")
                              : QStringLiteral("戳点"));
    metaParts << QStringLiteral("标记物类型=%1")
                     .arg(m_markerType == MarkerType::ConcentricCircle
                              ? QStringLiteral("同心圆")
                              : QStringLiteral("黑底白圆"));
    metaParts << QStringLiteral("标定板=%1x%2 步距=%3mm")
                     .arg(m_caliboardW).arg(m_caliboardH).arg(m_caliboardStep);
    if (m_camera) {
        QStringList paramParts;
        const auto s = m_camera->currentSettings();
        for (auto it = s.begin(); it != s.end(); ++it)
            paramParts << QStringLiteral("%1=%2").arg(it.key()).arg(it.value());
        if (!paramParts.isEmpty())
            metaParts << QStringLiteral("相机参数(%1)").arg(paramParts.join(QStringLiteral(", ")));
    }
    m_logger->info(QStringLiteral("新建会话: %1").arg(metaParts.join(QStringLiteral(", "))));

    m_view2d->clear();
    m_view3d->clear();
    m_topNav->updateProgress(0);
    m_flow->setDetectEnabled(false);
    m_flow->setSaveEnabled(false);
    m_actionButtons->setUndoEnabled(false);
    m_sidePanel->setTip(QStringLiteral("请移动机器人到下一个位姿并点击拍照"));
    m_flow->reset();

    // Stage 8 advisory state resets with the session.
    m_boardFrames.clear();
    m_pendingBoardPose = BoardPoseFit::Pose{};
    m_sidePanel->setPoseGuide(
        QStringLiteral("读取机器人位姿后显示与已采位姿的差异"), false);
    m_sidePanel->setQualityReport(
        QStringLiteral("<span style='color:%1'>采集数据后点击「运行质检」查看结果</span>")
            .arg(Theme::TEXT_HINT));
}

// ── Camera ────────────────────────────────────────────────────────────

void MainWindow::onConnectCamera()
{
    if (m_preScanning) {
        // Startup pre-scan still running; continue automatically when done.
        // setConnectBusy() repaints the busy state directly — no nested event
        // loop here, which could re-enter this very handler.
        m_connectRequested = true;
        setConnectBusy(QStringLiteral("正在搜索相机..."));
        m_logger->info(QStringLiteral("正在搜索相机..."));
        return;
    }
    if (m_cachedDevices.empty()) {
        setConnectBusy(QStringLiteral("正在搜索相机..."));
        m_logger->info(QStringLiteral("正在搜索相机..."));
        m_camera->scanDevicesAsync([this](const std::vector<DeviceEntry>& devices) {
            clearBusy();
            m_cachedDevices = devices;
            proceedWithDevices(devices);
        });
        return;
    }
    proceedWithDevices(m_cachedDevices);
}

void MainWindow::startPreScan()
{
    if (m_preScanning)
        return;
    m_preScanning = true;
    QTimer::singleShot(0, this, [this]() {
        // SystemInit must run on the UI thread (device objects are created
        // here later); the enumeration itself runs in a worker.
        m_camera->prewarmSystem();
        m_camera->scanDevicesAsync([this](const std::vector<DeviceEntry>& devices) {
            m_preScanning = false;
            m_cachedDevices = devices;
            if (m_connectRequested) {
                m_connectRequested = false;
                clearBusy();
                proceedWithDevices(devices);
            }
        });
    });
}

void MainWindow::proceedWithDevices(const std::vector<DeviceEntry>& devices)
{
    if (devices.empty()) {
        m_toast->showMessage(QStringLiteral("未找到相机设备，请检查连接"), false);
        return;
    }

    DeviceListDialog dlg(this, devices, [this]() { return m_camera->listDevices(); });
    const int dlgResult = dlg.exec();
    // The modal wait is user think-time, not a UI stall — re-baseline the
    // watchdog so it does not report the dialog's lifetime as a freeze.
    m_watchdog.reset();
    if (dlgResult != QDialog::Accepted)
        return;

    const QString serial = dlg.selectedSerial();
    if (serial.isEmpty())
        return;

    // Connect synchronously on the UI thread: RVC camera objects must be
    // created on the thread that later drives the preview (UI thread).
    setConnectBusy(QStringLiteral("连接中..."));
    m_logger->info(QStringLiteral("正在连接设备 %1").arg(serial));
    beginHeavyOp(QStringLiteral("相机连接"));

    const bool ok = m_camera->initWithDeviceSerial(serial);
    endHeavyOp();
    clearBusy();
    if (!ok)
        m_toast->showMessage(QStringLiteral("相机连接失败"), false);
}

void MainWindow::onDisconnectCamera()
{
    m_actionButtons->setCaptureEnabled(false);
    m_camera->shutdown();
    m_logger->info(QStringLiteral("相机已断开"));
}

// ── Workflow (UI choreography) ────────────────────────────────────────

void MainWindow::onCapture()
{
    if (!m_camera->isConnected()) {
        m_toast->showMessage(QStringLiteral("请先连接相机"), false);
        return;
    }
    // Optional: read the robot pose right before capturing when auto-read is
    // enabled.  This never affects the capture pipeline itself.
    if (m_robotAutoRead && m_robotConnected) {
        RobotPose::Pose pose;
        if (readRobotPose(pose)) {
            auto* card = m_dataInput->card(QStringLiteral("robot_capture_pose"));
            if (card) {
                const QString value = QStringLiteral("%1 %2 %3 %4 %5 %6")
                    .arg(pose.xyz[0], 0, 'f', 3)
                    .arg(pose.xyz[1], 0, 'f', 3)
                    .arg(pose.xyz[2], 0, 'f', 3)
                    .arg(pose.rpy[0], 0, 'f', 3)
                    .arg(pose.rpy[1], 0, 'f', 3)
                    .arg(pose.rpy[2], 0, 'f', 3);
                card->setValue(value);
                updatePoseGuide(value);
            }
        } else {
            m_sidePanel->setTip(
                QStringLiteral("机器人位姿读取失败：%1")
                    .arg(robotLastError()),
                true);
        }
    }
    // Stop preview and hide right-camera overlay before 3D capture
    if (m_camera->isPreviewing()) {
        m_camera->stopPreview();
        m_actionButtons->setPreviewActive(false);
    }
    m_view3d->hideImage();
    m_flow->beginCapture();
}

void MainWindow::saveFromCards()
{
    auto* card1 = m_dataInput->card("camera_target_xyz");
    auto* card2 = m_dataInput->card("robot_capture_pose");
    auto* card3 = m_dataInput->card("robot_target_xyz");

    m_flow->save(card1 ? card1->value() : QString(),
                 card2 ? card2->value() : QString(),
                 card3 ? card3->value() : QString());
}

// 在线取点：用当前采集帧跑一次共享服务。所有「拿不到数据」的情形都返回可读中文 message。
bool MainWindow::queryPixelFromCurrentFrame(int pixelX, int pixelY,
                                            std::array<double, 3>& point,
                                            QString& message)
{
    if (!m_camera->isConnected()) {
        message = QStringLiteral("请先连接相机并拍照后再点击取点");
        return false;
    }

    // Shared buffers: lastGrid()/lastCorrespond() hand back a refcount of the
    // capture's grid/correspond map instead of copying ~37 MB / ~25 MB on every
    // click in the image.
    FrameBuffer::DoubleBuf grid;
    int gw = 0, gh = 0;
    if (!m_camera->lastGrid(grid, gw, gh)) {
        message = QStringLiteral("请先拍照采集数据");
        return false;
    }

    PixelTo3DService::Source src;
    src.xyzMm = &(*grid);

    if (m_camera->lastGridAligned()) {
        // 对齐帧：点云按图像网格排布，服务走直查。
        src.imageWidth = gw;
        src.imageHeight = gh;
    } else {
        // 线扫未对齐帧：把对应图填进 Source（沿用既有的"每次采集只取一次"缓存）。
        FrameBuffer::DoubleBuf cmap;
        int cw = 0, ch = 0;
        if (!m_correspondBuilt) {
            if (m_camera->lastCorrespond(cmap, cw, ch)) {
                m_correspondW = cw;
                m_correspondH = ch;
                m_correspondBuilt = true;
            }
        }
        if (!m_correspondBuilt
            || !m_camera->lastCorrespond(cmap, m_correspondW, m_correspondH)) {
            message = QStringLiteral("线扫未对齐模式下未获得对应图，无法取点");
            return false;
        }
        src.correspondMap = &(*cmap);
        src.imageWidth = m_correspondW;
        src.imageHeight = m_correspondH;
    }

    const PixelTo3DService::Query q =
        PixelTo3DService::query(src, pixelX, pixelY);
    if (q.status != PixelTo3DService::Status::Ok) {
        message = QString::fromStdString(PixelTo3DService::statusText(q.status));
        return false;
    }
    point = q.pointMm;
    message.clear();
    return true;
}

void MainWindow::on2dPixelPicked(int x, int y)
{
    std::array<double, 3> pt{};
    QString message;
    const bool ok = queryPixelFromCurrentFrame(x, y, pt, message);

    // 在线模式且工具页正停在「像素→3D」页：同一次查询的结果推给工具页结果行。
    if (m_toolsPanel && m_toolsPanel->isVisible()
        && m_toolsPanel->onlinePixelTo3DActive()) {
        m_toolsPanel->setOnlinePixelResult(x, y, ok, pt[0], pt[1], pt[2], message);
    }

    if (!ok) {
        m_toast->showMessage(message, false);
        return;
    }

    if (m_pickSphereHandle >= 0)
        m_view3d->removeObject(m_pickSphereHandle);
    m_pickSphereHandle = m_view3d->addSphere(
        { static_cast<float>(pt[0]), static_cast<float>(pt[1]),
          static_cast<float>(pt[2]) },
        2.0f, { 1.0f, 0.85f, 0.1f });

    // 主 2D 视窗留一个取点标记（与识别圆心标记同一套绘制；下一次拍照/识别
    // 由既有逻辑重画或清掉）。
    m_view2d->drawMarkers(
        { { static_cast<float>(x), static_cast<float>(y), std::string() } });

    const QString value = QStringLiteral("%1 %2 %3")
        .arg(pt[0], 0, 'f', 3).arg(pt[1], 0, 'f', 3).arg(pt[2], 0, 'f', 3);
    auto* card = m_dataInput->card(QStringLiteral("camera_target_xyz"));
    if (card)
        card->setValue(value);

    m_sidePanel->setTip(
        QStringLiteral("像素 (%1, %2) → 3D (%3) mm，已填入相机目标点")
            .arg(x).arg(y).arg(value),
        false);
    m_logger->info(
        QStringLiteral("2D 点击取点: 像素 (%1, %2) → 3D (%3)")
            .arg(x).arg(y).arg(value));
}

void MainWindow::onPixelTo3DOnlineQueryRequested(int pixelX, int pixelY)
{
    // 工具页「计算」走的是同一条链路，只是由它自己发起。
    std::array<double, 3> pt{};
    QString message;
    const bool ok = queryPixelFromCurrentFrame(pixelX, pixelY, pt, message);
    m_toolsPanel->setOnlinePixelResult(
        pixelX, pixelY, ok, pt[0], pt[1], pt[2], message);
}

void MainWindow::onPixelTo3DOfflineImageRequested(const QString& imagePath)
{
    const QImage img(imagePath);
    if (img.isNull()) {
        const QString name = QFileInfo(imagePath).fileName();
        m_logger->error(QStringLiteral("像素→3D：无法加载离线图像 %1").arg(imagePath));
        m_toast->showMessage(QStringLiteral("无法加载离线图像：%1").arg(name), false);
        return;
    }
    m_view2d->setFrozenImage(img);
}

void MainWindow::onPixelTo3DOfflineImageEnded()
{
    m_view2d->clearFrozenImage();
}

void MainWindow::onCalibrate()
{
    if (m_calibWatcher->isRunning())
        return;
    const auto records = m_data->allRecords();
    if (records.empty()) {
        m_toast->showMessage(QStringLiteral("请先采集并保存标定数据"), false);
        return;
    }

    // Advisory quality check runs once before calibrating — reports only, it
    // never blocks the calibration (PROJECT.md "质量告警不拦截").
    refreshQualityReport();

    std::vector<QString> poseLines;
    poseLines.reserve(records.size());
    for (const auto& r : records)
        poseLines.push_back(r.robotCapturePose);

    CalibrationService::Params params;
    params.eyeInHand = (m_eyeHandMode == EyeHandMode::EyeInHand);
    params.markerType =
        (m_markerType == MarkerType::ConcentricCircle) ? 1 : 0;

    const QString folder = m_data->saveDir();
    setBusy(QStringLiteral("计算中..."), ActionButtons::BusyTarget::Calc);
    m_calibWatcher->setFuture(QtConcurrent::run([folder, poseLines, params]() {
        return CalibrationService::calibrateMarker(folder, poseLines, params);
    }));
}

void MainWindow::onCalibrationSessionRequested()
{
    const auto records = m_data->allRecords();
    QStringList poseLines;
    for (const auto& r : records) {
        if (!r.robotCapturePose.trimmed().isEmpty())
            poseLines.push_back(r.robotCapturePose);
    }
    // 没有记录时也要回一次（空 poseLines），让面板给出可读提示。
    m_toolsPanel->useCurrentSession(
        m_data->saveDir(), poseLines,
        m_eyeHandMode == EyeHandMode::EyeInHand,
        m_markerType == MarkerType::ConcentricCircle);
}

void MainWindow::onCalibrationFinished()
{
    clearBusy();
    const auto r = m_calibWatcher->result();
    if (!r.ok) {
        const QString msg = QStringLiteral("标定失败：%1").arg(r.error);
        m_sidePanel->setCalibrationResult(msg);
        m_toast->showMessage(msg, false);
        m_logger->error(msg);
        return;
    }

    QString text = QStringLiteral("标定成功（使用 %1 组数据）\n"
                                  "总平均误差: %2 mm\n\n"
                                  "4×4 矩阵（行主序）:\n")
        .arg(r.usedCount).arg(r.totalMeanError, 0, 'f', 3);
    for (int row = 0; row < 4; ++row) {
        QStringList vals;
        for (int col = 0; col < 4; ++col)
            vals << QString::number(
                r.matrix[static_cast<std::size_t>(row * 4 + col)], 'f', 6);
        text += vals.join(QStringLiteral("  ")) + QLatin1Char('\n');
    }

    text += QStringLiteral("\n逐组误差:\n");
    const std::size_t n = r.errors.size();
    for (std::size_t i = 0; i < n; ++i) {
        const bool failed2d = static_cast<std::size_t>(r.success2D.size()) > i
            && r.success2D[i] != 1;
        const bool failed3d = static_cast<std::size_t>(r.success3D.size()) > i
            && r.success3D[i] != 1;
        text += QStringLiteral("  第 %1 组: %2 mm%3\n")
            .arg(i + 1).arg(r.errors[i], 0, 'f', 3)
            .arg((failed2d || failed3d) ? QStringLiteral("（识别失败）") : QString());
    }

    m_sidePanel->setCalibrationResult(text);
    m_sidePanel->setTip(
        QStringLiteral("标定完成：总平均误差 %1 mm")
            .arg(r.totalMeanError, 0, 'f', 3),
        false);
    m_logger->success(
        QStringLiteral("标定完成：总平均误差 %1 mm，使用 %2 组数据")
            .arg(r.totalMeanError, 0, 'f', 3).arg(r.usedCount));
}

void MainWindow::onRobotConnect(const QString& host, quint16 port,
                                int protocol, int format, double scale,
                                quint8 unitId, quint16 startAddress)
{
    m_robotProtocol = protocol;

    if (protocol == 2) {
        // 博纳斯/纳博特 JSON over TCP: like UR, no register format/scale to
        // configure — the adapter owns the framing and the JSON payload.
        m_nrcReader.setTimeoutMs(1500);
        if (!m_nrcReader.connect(host, port)) {
            m_robotSimulated = false;
            m_robotConnected = false;
            m_toolsPanel->setRobotStatus(QStringLiteral("连接失败"), true);
            m_sidePanel->setTip(
                QStringLiteral("机器人连接失败：%1").arg(m_nrcReader.lastError()),
                true);
            m_logger->error(QStringLiteral("机器人连接失败：%1")
                                .arg(m_nrcReader.lastError()));
            updateRobotReadBar();
            return;
        }
        m_robotSimulated = false;
        m_robotConnected = true;
        m_toolsPanel->setRobotConnected(true);
        m_toolsPanel->setRobotStatus(QStringLiteral("已连接"), false);
        m_sidePanel->setTip(
            QStringLiteral("机器人已连接（%1:%2，博纳斯 JSON/TCP）").arg(host).arg(port), false);
        m_logger->success(
            QStringLiteral("机器人已连接（%1:%2，博纳斯 JSON/TCP）").arg(host).arg(port));
        updateRobotReadBar();
        return;
    }

    if (protocol == 1) {
        // UR Realtime interface: no register format/scale to configure.
        m_urReader.setTimeoutMs(1500);
        if (!m_urReader.connect(host, port)) {
            m_robotSimulated = false;
            m_robotConnected = false;
            m_toolsPanel->setRobotStatus(QStringLiteral("连接失败"), true);
            m_sidePanel->setTip(
                QStringLiteral("机器人连接失败：%1").arg(m_urReader.lastError()),
                true);
            m_logger->error(QStringLiteral("机器人连接失败：%1")
                                .arg(m_urReader.lastError()));
            updateRobotReadBar();
            return;
        }
        m_robotSimulated = false;
        m_robotConnected = true;
        m_toolsPanel->setRobotConnected(true);
        m_toolsPanel->setRobotStatus(QStringLiteral("已连接"), false);
        m_sidePanel->setTip(QStringLiteral("机器人已连接（%1:%2，UR Realtime）").arg(host).arg(port), false);
        m_logger->success(QStringLiteral("机器人已连接（%1:%2，UR Realtime）").arg(host).arg(port));
        updateRobotReadBar();
        return;
    }

    RobotPose::ModbusConfig cfg;
    switch (format) {
    case 1:  cfg.format = RobotPose::RegisterFormat::Int32Scaled; break;
    case 2:  cfg.format = RobotPose::RegisterFormat::Int16Scaled; break;
    default: cfg.format = RobotPose::RegisterFormat::Float32; break;
    }
    cfg.scale = scale;
    cfg.unitId = unitId;
    cfg.startAddress = startAddress;
    cfg.timeoutMs = 1500;
    m_robotReader.setConfig(cfg);

    if (!m_robotReader.connect(host, port)) {
        m_robotSimulated = false;
        m_robotConnected = false;
        m_toolsPanel->setRobotStatus(QStringLiteral("连接失败"), true);
        m_sidePanel->setTip(
            QStringLiteral("机器人连接失败：%1").arg(m_robotReader.lastError()),
            true);
        m_logger->error(QStringLiteral("机器人连接失败：%1")
                            .arg(m_robotReader.lastError()));
        updateRobotReadBar();
        return;
    }
    m_robotSimulated = false;
    m_robotConnected = true;
    m_toolsPanel->setRobotConnected(true);
    m_toolsPanel->setRobotStatus(QStringLiteral("已连接"), false);
    m_sidePanel->setTip(QStringLiteral("机器人已连接（%1:%2）").arg(host).arg(port), false);
    m_logger->success(QStringLiteral("机器人已连接（%1:%2）").arg(host).arg(port));
    updateRobotReadBar();
}

void MainWindow::onRobotDisconnect()
{
    m_robotReader.disconnect();
    m_urReader.disconnect();
    m_nrcReader.disconnect();
    m_robotConnected = false;
    m_robotSimulated = false;
    m_toolsPanel->setRobotConnected(false);
    m_toolsPanel->setRobotStatus(QStringLiteral("未连接"), false);
    m_logger->info(QStringLiteral("机器人已断开"));
    updateRobotReadBar();
}

void MainWindow::onRobotSimulateConnect()
{
    // "模拟连接成功" — no real Modbus socket; only sets the logical connected
    // state so the read buttons / cards can be exercised in the UI.
    m_robotReader.disconnect();
    m_urReader.disconnect();
    m_nrcReader.disconnect();
    m_robotSimulated = true;
    m_robotConnected = true;
    m_toolsPanel->setRobotConnected(true);
    m_toolsPanel->setRobotStatus(QStringLiteral("已连接（模拟）"), false);
    m_sidePanel->setTip(QStringLiteral("机器人已模拟连接（无真机）"), false);
    m_logger->success(QStringLiteral("机器人模拟连接成功"));
    updateRobotReadBar();
}

bool MainWindow::readRobotPose(RobotPose::Pose& pose)
{
    if (m_robotSimulated) {
        // Deterministic dummy pose so the read buttons / cards can be verified
        // without real Modbus hardware.
        static int n = 0;
        const double base = 100.0 + (n++ % 50) * 10.0;
        pose.xyz = { base, base + 1.0, base + 2.0 };
        pose.rpy = { 0.0, 0.0, 0.0 };
        return true;
    }
    if (m_robotProtocol == 2)
        return m_nrcReader.readPose(pose) == RobotPose::Status::Ok;
    if (m_robotProtocol == 1)
        return m_urReader.readPose(pose) == RobotPose::Status::Ok;
    return m_robotReader.readPose(pose) == RobotPose::Status::Ok;
}

QString MainWindow::robotLastError() const
{
    if (m_robotProtocol == 2)
        return m_nrcReader.lastError();
    return m_robotProtocol == 1 ? m_urReader.lastError() : m_robotReader.lastError();
}

void MainWindow::onRobotRead()
{
    if (!m_robotConnected) {
        m_sidePanel->setTip(QStringLiteral("请先连接机器人"), true);
        return;
    }
    RobotPose::Pose pose;
    if (!readRobotPose(pose)) {
        m_sidePanel->setTip(
            QStringLiteral("机器人位姿读取失败：%1")
                .arg(robotLastError()),
            true);
        m_logger->error(QStringLiteral("机器人位姿读取失败：%1")
                            .arg(robotLastError()));
        return;
    }
    const QString value = QStringLiteral("%1 %2 %3 %4 %5 %6")
        .arg(pose.xyz[0], 0, 'f', 3)
        .arg(pose.xyz[1], 0, 'f', 3)
        .arg(pose.xyz[2], 0, 'f', 3)
        .arg(pose.rpy[0], 0, 'f', 3)
        .arg(pose.rpy[1], 0, 'f', 3)
        .arg(pose.rpy[2], 0, 'f', 3);
    auto* card = m_dataInput->card(QStringLiteral("robot_capture_pose"));
    if (card)
        card->setValue(value);
    updatePoseGuide(value);
    m_sidePanel->setTip(QStringLiteral("已读取机器人位姿并填入卡片"), false);
    m_logger->info(QStringLiteral("机器人位姿读取成功: %1").arg(value));
}

void MainWindow::onRobotReadTouch()
{
    if (!m_robotConnected) {
        m_sidePanel->setTip(QStringLiteral("请先连接机器人"), true);
        return;
    }
    RobotPose::Pose pose;
    if (!readRobotPose(pose)) {
        m_sidePanel->setTip(
            QStringLiteral("机器人位姿读取失败：%1")
                .arg(robotLastError()),
            true);
        m_logger->error(QStringLiteral("机器人位姿读取失败：%1")
                            .arg(robotLastError()));
        return;
    }
    const QString value = QStringLiteral("%1 %2 %3")
        .arg(pose.xyz[0], 0, 'f', 3)
        .arg(pose.xyz[1], 0, 'f', 3)
        .arg(pose.xyz[2], 0, 'f', 3);
    auto* card = m_dataInput->card(QStringLiteral("robot_target_xyz"));
    if (card)
        card->setValue(value);
    m_sidePanel->setTip(QStringLiteral("已读取机器人 TCP 点并填入卡片"), false);
    m_logger->info(QStringLiteral("机器人 TCP 点读取成功: %1").arg(value));
}

void MainWindow::updateRobotReadBar()
{
    // The read buttons live in the ActionButtons row; show them only while a
    // robot connection is active, and 「戳点位姿」 additionally only in
    // 戳点标定 mode.
    const bool tcp = (m_calibType == CalibType::TcpTouch);
    if (m_actionButtons) {
        m_actionButtons->setReadCapturePoseVisible(m_robotConnected);
        m_actionButtons->setReadTouchPoseVisible(m_robotConnected && tcp);
    }
}

// ── Card Updates ──────────────────────────────────────────────────────

void MainWindow::onCardChanged(const QString& field, const QString& value)
{
    // Advisory pose guidance refreshes on the robot capture pose (current vs
    // nearest collected).  Report-only; never blocks the edit.
    if (field == QStringLiteral("robot_capture_pose"))
        updatePoseGuide(value);

    // Real-time format hint: calibration data must use ASCII numbers separated
    // by spaces / English commas.  Saving is blocked separately in
    // CaptureFlow::validateSaveInputs.
    if (CaptureFlow::containsCjkFormatChars(value)) {
        m_sidePanel->setTip(
            QStringLiteral("检测到中文格式字符，请使用英文逗号或空格分隔数值"), true);
    }

    // Card edits during capture→detect→save flow are buffered in the widgets
    // and read fresh by save(); skip updating existing records.
    if (m_flow->hasUnsavedCapture())
        return;

    int idx = m_data->currentIndex();
    if (idx > 0)
        m_data->updateRecord(idx, field, value);
}

// ── Stage 8 Advisory Features ─────────────────────────────────────────
// Pose guide, quality check and board-pose overlay are all report-only:
// they never gate capture / save / calibrate (see PROJECT.md).

namespace {
PoseGuide::Pose poseGuideFromText(const QString& text, bool& ok)
{
    PoseGuide::Pose p;
    const auto parsed = ToolInputParser::parseNumberList(text.toStdString(), 6);
    ok = (parsed.status == ToolInputParser::ParseStatus::Ok);
    if (ok) {
        for (int i = 0; i < 3; ++i) p.xyz[i] = parsed.values[static_cast<std::size_t>(i)];
        for (int i = 0; i < 3; ++i) p.rpyDeg[i] = parsed.values[static_cast<std::size_t>(3 + i)];
    }
    return p;
}
} // namespace

void MainWindow::updatePoseGuide(const QString& poseText)
{
    bool ok = false;
    const PoseGuide::Pose current = poseGuideFromText(poseText, ok);
    if (!ok) {
        m_sidePanel->setPoseGuide(
            QStringLiteral("机器人拍照位姿需为 6 个数值（x y z rx ry rz）"), false);
        return;
    }

    std::vector<PoseGuide::Pose> collected;
    collected.reserve(static_cast<std::size_t>(m_data->count()));
    for (const auto& r : m_data->allRecords()) {
        bool cok = false;
        const PoseGuide::Pose cp = poseGuideFromText(r.robotCapturePose, cok);
        if (cok) collected.push_back(cp);
    }

    if (collected.empty()) {
        m_sidePanel->setPoseGuide(
            QStringLiteral("暂无已采位姿参考，可自由采集"), false);
        return;
    }

    const PoseGuide::Guide g = PoseGuide::guide(current, collected);
    if (g.tooClose) {
        m_sidePanel->setPoseGuide(
            QStringLiteral("与第 %1 组位姿过于接近（间距 %2 mm / 角差 %3°），建议拉开位置或旋转角度")
                .arg(g.refIndex + 1)
                .arg(g.distanceMm, 0, 'f', 1)
                .arg(g.angleDeg, 0, 'f', 1),
            true);
    } else {
        m_sidePanel->setPoseGuide(
            QStringLiteral("最近第 %1 组：间距 %2 mm / 角差 %3°，分散度良好")
                .arg(g.refIndex + 1)
                .arg(g.distanceMm, 0, 'f', 1)
                .arg(g.angleDeg, 0, 'f', 1),
            false);
    }
}

void MainWindow::refreshQualityReport()
{
    std::vector<DataQualityCheck::Record> records;
    for (const auto& r : m_data->allRecords()) {
        records.push_back(DataQualityCheck::recordFromText(
            r.robotCapturePose, r.cameraErrorPct, r.markerCount));
    }

    const DataQualityCheck::Report rep = DataQualityCheck::run(records);

    auto levelColor = [](DataQualityCheck::Level lvl) -> QString {
        switch (lvl) {
        case DataQualityCheck::Level::Pass: return QStringLiteral("#52C41A");
        case DataQualityCheck::Level::Warn: return QStringLiteral("#FAAD14");
        case DataQualityCheck::Level::Fail: return QStringLiteral("#F5222D");
        }
        return QStringLiteral("#8C8C8C");
    };
    auto levelTag = [](DataQualityCheck::Level lvl) -> QString {
        switch (lvl) {
        case DataQualityCheck::Level::Pass: return QStringLiteral("通过");
        case DataQualityCheck::Level::Warn: return QStringLiteral("提示");
        case DataQualityCheck::Level::Fail: return QStringLiteral("不足");
        }
        return QStringLiteral("—");
    };

    QString html = QStringLiteral("<p style='margin:2px 0;'><b>总体：%1</b></p>")
                       .arg(rep.overall.toHtmlEscaped());

    auto appendCheck = [&](const QString& name, const DataQualityCheck::Check& c) {
        html += QStringLiteral("<p style='margin:3px 0; color:%1;'>%2 <b>%3</b>：%4</p>")
                    .arg(levelColor(c.level),
                         levelTag(c.level),
                         name,
                         c.summary.toHtmlEscaped());
        for (const auto& d : c.details)
            html += QStringLiteral("<p style='margin:1px 0 1px 12px; font-size:11px; color:#8C8C8C;'>· %1</p>")
                        .arg(d.toHtmlEscaped());
    };

    appendCheck(QStringLiteral("数量"), rep.count);
    appendCheck(QStringLiteral("近重复"), rep.nearDup);
    appendCheck(QStringLiteral("离群"), rep.outlier);
    appendCheck(QStringLiteral("单帧误差"), rep.frameError);
    appendCheck(QStringLiteral("分散度"), rep.spread);

    m_sidePanel->setQualityReport(html);
}

void MainWindow::onBoardMarkers(const std::vector<std::array<float, 3>>& pts3d)
{
    const BoardPoseFit::Pose pose = BoardPoseFit::fit(pts3d);
    if (!pose.valid) {
        m_view3d->clearBoardFrame();
        m_pendingBoardPose = BoardPoseFit::Pose{};
        return;
    }

    m_pendingBoardPose = pose;

    VisSceneView::BoardFrame frame;
    frame.frameNo = 0;                     // current frame
    frame.centerMM = pose.center;
    frame.quat = pose.quat;
    frame.extentXMM = pose.extentX;
    frame.extentYMM = pose.extentY;
    m_view3d->setBoardFrame(frame);
}

void MainWindow::syncBoardHistory()
{
    const int n = m_data->count();
    // Grow: one record was saved since the last sync — record its fitted pose.
    while (static_cast<int>(m_boardFrames.size()) < n) {
        BoardFrameEntry entry;
        entry.frameNo = static_cast<int>(m_boardFrames.size()) + 1;
        entry.pose = m_pendingBoardPose;   // may be invalid (no board fitted)
        m_boardFrames.push_back(entry);
        m_pendingBoardPose = BoardPoseFit::Pose{};
    }
    // Shrink: records were removed (undo) — drop trailing history frames.
    while (static_cast<int>(m_boardFrames.size()) > n)
        m_boardFrames.pop_back();

    refreshBoardOverlay();
}

void MainWindow::refreshBoardOverlay()
{
    std::vector<VisSceneView::BoardFrame> frames;
    frames.reserve(m_boardFrames.size());
    for (const auto& e : m_boardFrames) {
        if (!e.pose.valid) continue;
        VisSceneView::BoardFrame f;
        f.frameNo = e.frameNo;
        f.centerMM = e.pose.center;
        f.quat = e.pose.quat;
        f.extentXMM = e.pose.extentX;
        f.extentYMM = e.pose.extentY;
        frames.push_back(f);
    }
    m_view3d->setBoardHistory(frames);
}

// Measurement tool -> 3D viewport (P4).
//
// Two independent things happen here, both through interfaces the 3D view
// already had (no new Vis command, no change to the pick path):
//   1. the captured cloud is re-uploaded with per-point RGB computed from the
//      panel's robust ±3σ(MAD) deviation scale — the exact same colour function
//      the 2D 偏差图 page uses;
//   2. the fitted plane and the measured region are marked with a sphere, a
//      normal arrow and a text label (尺寸总图 values).
void MainWindow::onMeasurementUpdated(const Measurement::Snapshot& snapshot)
{
    const FrameBuffer::FloatBuf& pts = m_flow->capturedPoints();

    // ── deviation colouring ──
    // The panel builds one RGB triple per *valid* cloud point, following the
    // same NaN/zero scan PointCloudUtils::filterValidPoints uses, so the array
    // is index-aligned with `pts`.  A size mismatch means the cloud is from a
    // different frame; colouring it would misplace every point, so it is
    // skipped rather than drawn wrong.
    const bool canColor = snapshot.hasCloudColors && pts && snapshot.cloudColors
                          && snapshot.cloudColors->size() * 3 == pts->size();
    if (canColor) {
        const std::vector<std::array<float, 3>>& src = *snapshot.cloudColors;
        std::vector<float> flat;
        flat.reserve(src.size() * 3);
        for (const std::array<float, 3>& c : src) {
            flat.push_back(c[0]);
            flat.push_back(c[1]);
            flat.push_back(c[2]);
        }
        beginHeavyOp(QStringLiteral("3D偏差着色(%1点)").arg(flat.size() / 3));
        m_measureCloudColors = FrameBuffer::makeFloat(std::move(flat));
        m_view3d->updatePointCloud(pts, m_measureCloudColors);
        endHeavyOp();
        m_cloudColored = true;
    } else if (m_cloudColored && pts) {
        // Colouring was switched off (or the capture changed): back to the
        // plain cloud, once.
        beginHeavyOp(QStringLiteral("3D点云重传(取消着色)"));
        m_measureCloudColors.reset();
        m_view3d->updatePointCloud(pts);
        endHeavyOp();
        m_cloudColored = false;
    }

    // ── annotations ──
    for (int handle : m_measureHandles)
        m_view3d->removeObject(handle);
    m_measureHandles.clear();

    const std::array<float, 3> accent = { 1.0f, 0.655f, 0.149f };   // 255,167,38
    const std::array<float, 3> line = { 0.353f, 0.667f, 0.961f };   // 90,170,245
    if (snapshot.hasPlane) {
        const std::array<float, 3> p = { static_cast<float>(snapshot.planePoint[0]),
                                         static_cast<float>(snapshot.planePoint[1]),
                                         static_cast<float>(snapshot.planePoint[2]) };
        std::array<float, 3> n = { static_cast<float>(snapshot.planeNormal[0]),
                                   static_cast<float>(snapshot.planeNormal[1]),
                                   static_cast<float>(snapshot.planeNormal[2]) };
        const float len = std::sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]);
        if (len > 1e-6f)
            for (float& v : n) v /= len;

        int h = m_view3d->addSphere(p, 2.5f, accent);
        if (h >= 0) m_measureHandles.push_back(h);
        // 40 mm normal arrow: long enough to read at working distance, short
        // enough not to leave the field of view.
        const std::array<float, 3> tip = { p[0] + n[0] * 40.0f, p[1] + n[1] * 40.0f,
                                           p[2] + n[2] * 40.0f };
        h = m_view3d->addArrow(p, tip, 1.5f, line);
        if (h >= 0) m_measureHandles.push_back(h);
        if (!snapshot.label.isEmpty()) {
            const std::array<float, 3> at = { p[0], p[1], p[2] + 25.0f };
            h = m_view3d->addText(snapshot.label, at, 0.02f, accent);
            if (h >= 0) m_measureHandles.push_back(h);
        }
    }
    if (snapshot.hasRoiBox) {
        const std::array<float, 3> c = {
            static_cast<float>(0.5 * (snapshot.boxMin[0] + snapshot.boxMax[0])),
            static_cast<float>(0.5 * (snapshot.boxMin[1] + snapshot.boxMax[1])),
            static_cast<float>(0.5 * (snapshot.boxMin[2] + snapshot.boxMax[2]))
        };
        const std::array<float, 3> half = {
            static_cast<float>(0.5 * (snapshot.boxMax[0] - snapshot.boxMin[0])),
            static_cast<float>(0.5 * (snapshot.boxMax[1] - snapshot.boxMin[1])),
            static_cast<float>(0.5 * (snapshot.boxMax[2] - snapshot.boxMin[2]))
        };
        const int h = m_view3d->addBox(c, half, accent);
        if (h >= 0) m_measureHandles.push_back(h);
        if (!snapshot.label.isEmpty()) {
            const int t = m_view3d->addText(snapshot.label,
                                            { c[0], c[1], c[2] + half[2] + 10.0f },
                                            0.02f, accent);
            if (t >= 0) m_measureHandles.push_back(t);
        }
    }
}

// ── State Helpers ─────────────────────────────────────────────────────

void MainWindow::setBusy(const QString& text, ActionButtons::BusyTarget target)
{
    m_busy = true;
    m_actionButtons->setBusy(target, text);
    // Paint the busy state synchronously without dispatching queued events.
    // A nested processEvents() here would run the camera/capture handlers while
    // this call is still on the stack — the re-entrancy the field crash needs.
    m_actionButtons->repaint();
}

void MainWindow::setConnectBusy(const QString& text)
{
    m_busy = true;
    m_topNav->setConnectBusy(true, text);
    m_topNav->repaint();   // same non-reentrant paint, see setBusy()
}

void MainWindow::clearBusy()
{
    m_busy = false;
    m_topNav->setConnectBusy(false, {});
    m_actionButtons->clearBusy();
}

// ── UI-thread stall watchdog (D5) ─────────────────────────────────────

void MainWindow::startUiWatchdog()
{
    const int threshold = m_config.uiStallThresholdMs();
    m_watchdog.setThresholdMs(threshold);
    m_watchdog.setIntervalMs(UiStallWatchdog::kDefaultIntervalMs);

    if (!m_watchdogTimer) {
        m_watchdogTimer = new QTimer(this);
        // CoarseTimer: the OS may coalesce it, which costs nothing measurable
        // and the reporting threshold is 5x the interval anyway.
        m_watchdogTimer->setTimerType(Qt::CoarseTimer);
        connect(m_watchdogTimer, &QTimer::timeout,
                this, &MainWindow::onWatchdogTick);
    }
    m_watchdog.reset();
    m_watchdogTimer->start(static_cast<int>(m_watchdog.intervalMs()));
    RuntimeLog::log("[WATCHDOG] armed interval=%d ms threshold=%d ms",
                    static_cast<int>(m_watchdog.intervalMs()), threshold);
}

void MainWindow::onWatchdogTick()
{
    UiStallWatchdog::Context ctx;
    ctx.previewing = m_camera && m_camera->isPreviewing();
    ctx.capturing  = m_busy;
    ctx.uploading3d = m_uploading3d;
    const FrameBuffer::FloatBuf& pts = m_flow->capturedPoints();
    ctx.pointCount = pts ? static_cast<long long>(pts->size() / 3) : 0;

    const UiStallWatchdog::Tick t = m_watchdog.tick(UiStallWatchdog::nowMs(), ctx);
    if (!t.stalled)
        return;

    std::string msg = UiStallWatchdog::formatStall(t.stallMs, ctx);
    // Name the last synchronous UI-thread operation when it overlaps the stall
    // window, so the log says "what" and not only "how long".
    const double stallStart = UiStallWatchdog::nowMs() - t.stallMs;
    if (!m_heavyOpName.isEmpty() && m_heavyOpEndMs >= stallStart) {
        msg += " 最近重活=";
        msg += m_heavyOpName.toStdString();
    }
    RuntimeLog::log("[WATCHDOG] %s", msg.c_str());
    // Mirror to the operator-visible log so a freeze is visible without opening
    // the technical file (dual-track logging is a project rule).
    m_logger->warning(QStringLiteral("[WATCHDOG] ") + QString::fromStdString(msg));
}

void MainWindow::beginHeavyOp(const QString& name)
{
    m_heavyOpName   = name;
    m_heavyOpStartMs = UiStallWatchdog::nowMs();
    m_heavyOpEndMs   = m_heavyOpStartMs;
}

void MainWindow::endHeavyOp()
{
    m_heavyOpEndMs = UiStallWatchdog::nowMs();
    if (m_heavyOpStartMs < 0.0)
        return;
    const double costMs = m_heavyOpEndMs - m_heavyOpStartMs;
    // Only the operations that can actually stall the UI are worth a line.
    if (costMs >= 30.0) {
        RuntimeLog::log("[UI] %s 耗时 %.0f ms",
                        qPrintable(m_heavyOpName), costMs);
    }
}

// ── Round 5: automation / idle / camera release ───────────────────────

void MainWindow::applyAutoFlowSettings()
{
    m_autoDetectAfterCapture = m_config.autoDetectAfterCapture();
    m_autoSaveAfterDetect = m_config.autoSaveAfterDetect();
    m_robotAutoRead = m_config.autoReadRobotPose();

    m_flow->setAutoDetectAfterCapture(m_autoDetectAfterCapture);
    // One config key, two views: 设置 checkbox and the tools-panel checkbox.
    m_toolsPanel->setRobotAutoRead(m_robotAutoRead);
    RuntimeLog::log("[FLOW] automation: auto_detect=%d auto_save=%d auto_read_pose=%d",
                    m_autoDetectAfterCapture ? 1 : 0, m_autoSaveAfterDetect ? 1 : 0,
                    m_robotAutoRead ? 1 : 0);
}

void MainWindow::onDetectionFinished(bool ok)
{
    if (!m_autoSaveAfterDetect)
        return;

    // Queued so the auto-save runs after the detection's busy state has cleared
    // — the same sequence the operator gets by clicking 保存, and the cards are
    // fully settled by then (the detection auto-fills camera_target_xyz first).
    QTimer::singleShot(0, this, [this, ok]() {
        if (!m_autoSaveAfterDetect)
            return;   // switched off in between
        auto* card1 = m_dataInput->card("camera_target_xyz");
        auto* card2 = m_dataInput->card("robot_capture_pose");
        auto* card3 = m_dataInput->card("robot_target_xyz");
        const QString v1 = card1 ? card1->value() : QString();
        const QString v2 = card2 ? card2->value() : QString();
        const QString v3 = card3 ? card3->value() : QString();

        // Exactly the validation the manual 保存 button runs.  Quality warnings
        // never block, but a missing required field does (PROJECT.md §3).
        CalibrationMode mode;
        mode.eyeHand = m_eyeHandMode;
        mode.calibType = m_calibType;
        mode.markerType = m_markerType;
        const auto issue = CaptureFlow::validateSaveInputs(v1, v2, v3, mode);

        const auto decision = AutoFlowPolicy::decideAutoSave(
            true, ok, issue.ok, issue.message);
        if (!decision.trigger) {
            RuntimeLog::log("[FLOW] %s", qPrintable(decision.reason));
            m_logger->info(decision.reason);
            return;
        }
        RuntimeLog::log("[FLOW] auto-save triggered (识别成功 + 必填项校验通过)");
        m_logger->info(QStringLiteral("自动保存：识别成功且必填项校验通过，正在保存"));
        m_flow->save(v1, v2, v3);
    });
}

void MainWindow::onUserActivity()
{
    // Anything the user does resumes the preview we paused, and re-arms the
    // idle timer.  Nothing is resumed that we did not pause ourselves.
    if (m_idlePreviewPaused) {
        m_idlePreviewPaused = false;
        if (m_camera && m_camera->isConnected()) {
            m_camera->resumePreview();
            RuntimeLog::log("[CAM] preview resumed (user activity)");
        }
    }
    if (m_idleTimer && m_idlePauseSec > 0)
        m_idleTimer->start(m_idlePauseSec * 1000);
}

void MainWindow::onIdleTimeout()
{
    if (!m_camera || !m_camera->isConnected() || !m_camera->isPreviewing())
        return;
    m_camera->pausePreview();
    m_idlePreviewPaused = true;
    RuntimeLog::log("[CAM] preview paused after %d s idle "
                    "(frees the device for other tools)", m_idlePauseSec);
}

bool MainWindow::eventFilter(QObject* watched, QEvent* event)
{
    switch (event->type()) {
    case QEvent::MouseButtonPress:
    case QEvent::MouseButtonRelease:
    case QEvent::MouseMove:
    case QEvent::Wheel:
    case QEvent::KeyPress:
    case QEvent::TouchBegin:
        onUserActivity();
        break;
    default:
        break;
    }
    return QMainWindow::eventFilter(watched, event);
}

void MainWindow::releaseCameraNow(int deviceWaitMs, const QString& why)
{
    if (!m_camera)
        return;
    const qint64 t0 = QDateTime::currentMSecsSinceEpoch();
    m_camera->shutdown(deviceWaitMs);
    const auto report = m_camera->lastRelease();
    const qint64 elapsed = QDateTime::currentMSecsSinceEpoch() - t0;

    if (report.attempted && !report.released) {
        RuntimeLog::log("[CAM] %s: release INCOMPLETE after %lld ms: %s",
                        qPrintable(why), elapsed, qPrintable(report.detail));
        m_logger->warning(QStringLiteral("相机释放未完成（%1）：%2")
                              .arg(why, report.detail));
    } else {
        RuntimeLog::log("[CAM] %s: released in %lld ms (noop=%d)",
                        qPrintable(why), elapsed, report.attempted ? 0 : 1);
        m_logger->info(QStringLiteral("相机已释放（%1），用时 %2 ms").arg(why).arg(elapsed));
    }

    // Re-enumerate so "相机被占用/状态异常" can be cleared on the spot: the bus
    // scan is what makes the next 连接 go straight to Open().
    m_cachedDevices.clear();
    m_camera->scanDevicesAsync([this](const std::vector<DeviceEntry>& devices) {
        m_cachedDevices = devices;
        RuntimeLog::log("[CAM] rescan after release: %zu device(s)", devices.size());
        m_logger->info(QStringLiteral("释放后重新扫描：发现 %1 个设备")
                           .arg(static_cast<int>(devices.size())));
    });
}

// ── Settings Dialog ───────────────────────────────────────────────────

void MainWindow::showSettingsDialog()
{
    SettingsDialog dlg(m_config, m_camera, m_data, this);
    // 相机维护 →「释放相机」: runs while the (modal) dialog is open, so the
    // operator sees the result immediately instead of after pressing OK.
    connect(&dlg, &SettingsDialog::cameraReleaseRequested, this, [this]() {
        releaseCameraNow(CameraManager::SHUTDOWN_DEVICE_WAIT_MS,
                         QStringLiteral("手动释放相机"));
    });

    const int dlgResult = dlg.exec();
    m_watchdog.reset();   // modal think-time is not a UI stall
    if (dlgResult != QDialog::Accepted)
        return;

    m_saveBaseDir = dlg.saveBaseDir();
    m_config.setSaveBaseDir(m_saveBaseDir);

    // Caliboard accuracy warning threshold
    const float threshold = dlg.errorThreshold();
    m_config.setCaliboardErrorThreshold(threshold);
    m_flow->setErrorThreshold(threshold);

    // ── 任务 1: capture-parameter source ──
    // Only push values when the operator actually edited them: with
    // use_camera_params on, re-applying the (displayed) values would be exactly
    // the "下发参数" the setting exists to avoid.
    m_useCameraParams = dlg.useCameraParams();
    m_config.setUseCameraParams(m_useCameraParams);
    m_camera->setUseCameraParams(m_useCameraParams);
    if (dlg.cameraParamsEdited()) {
        const auto params = dlg.cameraParams();
        for (auto it = params.begin(); it != params.end(); ++it)
            m_camera->setParameter(it.key(), it.value().toFloat());
        RuntimeLog::log("[CAM] settings: %d 项拍摄参数已下发到相机", params.size());
    } else {
        RuntimeLog::log("[CAM] settings: 拍摄参数未修改，未下发任何参数 (use_camera_params=%d)",
                        m_useCameraParams ? 1 : 0);
    }

    // Persist what is in effect (with use_camera_params on these are the values
    // read from the camera, which is what 设置 must display next time).
    QVariantMap current;
    const auto settings = m_camera->currentSettings();
    for (auto it = settings.begin(); it != settings.end(); ++it)
        current[it.key()] = it.value();
    m_config.setCameraParams(current);

    // ── 任务 2: automation + 任务 3.4: lifetime tuning ──
    m_config.setAutoDetectAfterCapture(dlg.autoDetectAfterCapture());
    m_config.setAutoSaveAfterDetect(dlg.autoSaveAfterDetect());
    m_config.setAutoReadRobotPose(dlg.autoReadRobotPose());
    m_config.setIdlePausePreviewSec(dlg.idlePausePreviewSec());
    m_config.setHealthCheckIntervalSec(dlg.healthCheckIntervalSec());
    applyAutoFlowSettings();
    m_camera->setHealthCheckInterval(dlg.healthCheckIntervalSec() * 1000);

    m_idlePauseSec = dlg.idlePausePreviewSec();
    if (m_idlePauseSec > 0) {
        m_idleTimer->start(m_idlePauseSec * 1000);
    } else {
        m_idleTimer->stop();
        // Switching the feature off must not leave the preview paused by it.
        if (m_idlePreviewPaused && m_camera->isConnected()) {
            m_idlePreviewPaused = false;
            m_camera->resumePreview();
        }
    }

    // Backup restore (mode + records already restored inside DataManager)
    if (!dlg.restoredBackupPath().isEmpty()) {
        const auto restoredMode = m_data->mode();
        m_eyeHandMode = restoredMode.first;
        m_calibType   = restoredMode.second;

        CalibrationMode mode;
        mode.eyeHand = m_eyeHandMode;
        mode.calibType = m_calibType;
        mode.markerType = m_markerType;
        m_flow->setMode(mode);

        // Sync the selector without triggering the change-confirm flow
        m_modeSelector->blockSignals(true);
        m_modeSelector->setMode(
            m_eyeHandMode == EyeHandMode::EyeInHand,
            m_calibType == CalibType::Marker,
            m_markerType == MarkerType::ConcentricCircle);
        m_modeSelector->blockSignals(false);

        m_dataInput->updateVisibility(
            m_eyeHandMode == EyeHandMode::EyeInHand,
            m_calibType == CalibType::Marker);
        m_sidePanel->updateFilePreview(
            m_eyeHandMode == EyeHandMode::EyeInHand,
            m_calibType == CalibType::Marker,
            m_data->allRecords());
        updateRobotReadBar();

        m_config.setLastMode(
            m_eyeHandMode == EyeHandMode::EyeInHand,
            m_calibType == CalibType::Marker,
            m_markerType == MarkerType::ConcentricCircle);

        m_toast->showMessage(
            QStringLiteral("已从备份恢复 %1 条记录").arg(m_data->count()), true);
        m_logger->info(QStringLiteral("已从备份恢复: %1")
                       .arg(dlg.restoredBackupPath()));
    }

    m_logger->info(QStringLiteral("设置已更新"));
}

// ── Window Events ─────────────────────────────────────────────────────

void MainWindow::showEvent(QShowEvent* event)
{
    QMainWindow::showEvent(event);

    if (m_windowPositioned)
        return;
    m_windowPositioned = true;

    // Finalize size/position here rather than in the constructor: before show()
    // the window frame does not exist yet, so any centering math that ran
    // pre-show used the wrong geometry and could strand the title bar above the
    // desktop on first launch (higher-DPI / smaller screens).  Doing it in
    // showEvent() — after the frame is materialized — fixes that.
    QScreen* screen = QGuiApplication::primaryScreen();
    if (!screen)
        return;                     // no screen yet; keep the default geometry

    const QRect avail = screen->availableGeometry();

    const QRect saved = m_config.windowGeometry();
    int w = saved.width()  > 0 ? saved.width()  : 1280;
    int h = saved.height() > 0 ? saved.height() : 720;
    w = qMin(w, avail.width());
    h = qMin(h, avail.height());
    resize(w, h);

    // x()/y() of a top-level window include the frame, so center using the
    // frame geometry to keep the window truly centered.
    const QRect frame = frameGeometry();
    int x = avail.x() + (avail.width()  - frame.width())  / 2;
    int y = avail.y() + (avail.height() - frame.height()) / 2;

    const bool savedOnScreen =
        saved.x() >= 0 && saved.y() >= 0
        && saved.x() < avail.x() + avail.width()  - 40
        && saved.y() < avail.y() + avail.height() - 40;
    if (savedOnScreen) {
        x = saved.x();
        y = saved.y();
    }

    // Clamp so the title bar is always reachable, whatever the resolution.
    x = qMax(avail.x(), qMin(x, avail.x() + avail.width()  - frame.width()));
    y = qMax(avail.y(), qMin(y, avail.y() + avail.height() - frame.height()));
    move(x, y);
}

void MainWindow::changeEvent(QEvent* event)
{
    QMainWindow::changeEvent(event);
    if (event->type() == QEvent::WindowStateChange) {
        if (isMinimized()) {
            if (m_camera) m_camera->pausePreview();
        } else if (m_camera && m_camera->isConnected()) {
            m_camera->resumePreview();
        }
    } else if (event->type() == QEvent::ActivationChange) {
        // The embedded native Vis child (VisSceneView, SetParent'd in) is
        // z-ordered with SetWindowPos(..., HWND_BOTTOM, ...); on some Windows
        // setups this leaves the top-level frame itself behind other apps
        // when the user re-selects it (taskbar/Alt-Tab) instead of coming to
        // the front like a normal window. Force the frame to the top of the
        // z-order whenever Windows marks it active.
        if (isActiveWindow())
            raise();
    }
}

bool MainWindow::nativeEvent(const QByteArray& eventType, void* message, long* result)
{
#ifdef _WIN32
    if (eventType == QByteArrayLiteral("windows_generic_MSG")
            || eventType == QByteArrayLiteral("windows_dispatcher_MSG")) {
        MSG* msg = static_cast<MSG*>(message);
        if (msg && msg->message == WM_QUERYENDSESSION) {
            // 任务 3.2: release the camera before Windows logs off / shuts down,
            // bounded so we never hold the session end up.  This message can
            // arrive several times; shutdown() is idempotent, so the repeats are
            // no-ops.  Always answer TRUE — refusing to end the session would
            // leave the operator with a machine that will not shut down.
            RuntimeLog::log("[CAM] WM_QUERYENDSESSION (lParam=0x%llx): releasing camera",
                            static_cast<unsigned long long>(msg->lParam));
            if (m_camera) {
                if (m_idleTimer)
                    m_idleTimer->stop();
                m_camera->stopPreview();
                m_camera->shutdown(kSessionEndWaitMs);
                const auto r = m_camera->lastRelease();
                RuntimeLog::log("[CAM] session-end release: released=%d %s",
                                r.released ? 1 : 0,
                                r.detail.isEmpty() ? "" : qPrintable(r.detail));
            }
            if (result) *result = TRUE;
            return true;
        }
        if (msg && msg->message == WM_ENDSESSION) {
            // Confirm the state after the decision: either the session really is
            // ending (the release above already ran) or it was cancelled.
            RuntimeLog::log("[CAM] WM_ENDSESSION (ending=%d): camera %s",
                            msg->wParam ? 1 : 0,
                            (m_camera && m_camera->isConnected()) ? "still connected"
                                                                  : "released");
            if (result) *result = TRUE;
            return true;
        }
    }
#endif
    return QMainWindow::nativeEvent(eventType, message, result);
}

void MainWindow::closeEvent(QCloseEvent* event)
{
    const qint64 t0 = QDateTime::currentMSecsSinceEpoch();
    m_config.setWindowGeometry(x(), y(), width(), height());
    m_config.save();
    m_data->saveBackup(true);

    // The idle pause must not fire (and resumePreview must not run) while the
    // camera is being torn down.
    if (m_idleTimer)
        m_idleTimer->stop();
    qApp->removeEventFilter(this);

    // Shut down camera while event loop is still running.  The 3D view is
    // torn down here as well, for the same reason — see the block below.
    if (m_camera) {
        m_camera->disconnect(this);
        // 1. stop the preview — no new frames are scheduled from here on.
        m_camera->stopPreview();
        // 2. bounded wait for in-flight workers so the teardown below is
        //    deterministic instead of racing a live capture/detection thread.
        //    Bounded (3 s): a truly hung SDK call must not block the close.
        const bool captureIdle = m_camera->waitForCaptureIdle(kCloseWorkerWaitMs);
        if (m_flow) {
            const bool detectIdle = m_flow->waitForIdle(kCloseWorkerWaitMs);
            // Drop a late detection result instead of letting it reach a window
            // that is already going away.
            m_flow->abandonPendingWork();
            m_flow->disconnect(this);
            if (!detectIdle)
                RuntimeLog::log("[FLOW] detection still running at close");
        }
        // 3. release the device (X.Close -> Destroy -> SystemShutdown).
        m_camera->shutdown();
        const auto report = m_camera->lastRelease();
        const qint64 elapsed = QDateTime::currentMSecsSinceEpoch() - t0;
        RuntimeLog::log("[CAM] release on close: %lld ms (preview stopped, captured=%d, "
                        "released=%d)",
                        elapsed, captureIdle ? 0 : 1, report.released ? 1 : 0);
        if (!report.released) {
            // Never silent: a half-released device is exactly what makes the
            // *next* start look like "相机被占用".
            RuntimeLog::log("[CAM] release on close FAILED: %s", qPrintable(report.detail));
        }
        // The pointer deliberately stays valid: the aboutToQuit fallback and
        // ~MainWindow below re-enter the (now idempotent) shutdown(), which
        // logs a no-op line instead of being skipped behind a null check.
    }

    // ── 3D view ──
    // Must be torn down while the application is still alive, i.e. here and not
    // in ~VisSceneView().  Measured (round 6, close_probe on a freshly connected
    // camera): calling VisSceneView::shutdown() from ~VisSceneView() never
    // returns — Vis::View::Close() ends up in MSVCP140!_Cnd_wait waiting for a
    // signal from a Vis/OSG render thread that no longer exists once the loop is
    // gone (`3D: Vis close did not return within 3000 ms — exiting without it`),
    // which is what left the process alive after the window had disappeared.
    // The same call from closeEvent completes in ~0.3 s and logs `3D: Vis
    // closed`.  Whether the message pump runs meanwhile is irrelevant (verified
    // with the UI thread blocked and not pumping); what matters is that the app
    // is still alive when the close is requested.
    //
    // Red line (PROJECT §3) is kept by shutdown() itself: the synchronous Vis
    // command runs on a worker thread, never on the UI thread, and this thread
    // only waits for it — bounded by kViewCloseWaitMs so a wedged render thread
    // can never hold the exit up again.
    if (m_view3d)
        m_view3d->shutdown();

    event->accept();
}
