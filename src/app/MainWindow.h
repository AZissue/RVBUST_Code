#pragma once

#include <QMainWindow>
#include <QString>
#include <QStringList>
#include <QFutureWatcher>
#include <array>
#include <vector>
#include "models/CalibrationMode.h"
#include "logic/AppConfig.h"
#include "logic/CalibrationService.h"
#include "logic/EfortPoseReader.h"
#include "logic/NrcJsonReader.h"
#include "logic/RobotPose.h"
#include "logic/URRealtimeReader.h"
#include "logic/BoardPoseFit.h"
#include "logic/FrameBuffer.h"
#include "logic/UiStallWatchdog.h"
#include "ui/ActionButtons.h"
#include "ui/MeasurementSnapshot.h"

// Forward declarations
class CameraManager;
class DataManager;
class LogManager;
class CaptureFlow;
class TopNavBar;
class ModeSelector;
class Image2DView;
class VisSceneView;
class DataInputArea;
class ActionButtons;
class SidePanel;
class ToastOverlay;
class ToolsPanel;
class HelpDialog;
class QShowEvent;
class QTimer;
class QThread;
struct DeviceEntry;

// kind values for RobotWorker::readPose / its poseReady() signal: which UI
// request asked for the pose decides where the answer goes.
enum RobotReadKind {
    RobotReadCapturePose       = 0,   // 「拍照位姿」 → robot_capture_pose 卡片
    RobotReadTouchPose         = 1,   // 「戳点位姿」 → robot_target_xyz 卡片
    RobotReadAutoBeforeCapture = 2    // 拍照前自动读取 → robot_capture_pose 卡片
};

// ── Robot channel worker (T-009) ──
// Every robot operation is a *blocking* network call (waitForConnected /
// waitForReadyRead, up to 1.5 s).  QTcpSocket is thread-affine, so the whole
// channel — the four readers and every call on them — lives on one dedicated
// thread (moveToThread); the UI thread only talks to it through queued
// signals/slots.  That is what keeps a connect / read / capture-time read from
// freezing the window (and the UI stall watchdog from firing).
class RobotWorker : public QObject {
    Q_OBJECT
public:
    explicit RobotWorker(QObject* parent = nullptr);
    ~RobotWorker() override;

public slots:
    // All of these run on the worker thread.  connectRobot mirrors the old
    // MainWindow::onRobotConnect body (protocol-specific setup + connect()).
    void connectRobot(const QString& host, quint16 port, int protocol, int format,
                      double scale, quint8 unitId, quint16 startAddress);
    void disconnectRobot();
    void simulateConnect();
    void readPose(int kind);

signals:
    // ok=false → error carries the adapter's lastError() text.
    void connectFinished(bool ok, const QString& label, const QString& error);
    // fields = the six pose numbers already formatted "%.3f" (x y z rx ry rz),
    // so the cross-thread hop needs no custom metatype.
    void poseReady(int kind, bool ok, const QStringList& fields, const QString& error);

private:
    RobotPose::Reader* readerFor(int protocol);

    // The four readers live here, not in MainWindow: they own the QTcpSocket and
    // must only ever be touched from this worker's thread.
    RobotPose::ModbusTcpReader   m_robotReader;
    RobotPose::URRealtimeReader  m_urReader;
    RobotPose::NrcJsonReader     m_nrcReader;
    EfortPoseReader::EfortReader m_eftReader;
    int  m_protocol    = 0;
    bool m_simulated   = false;
    int  m_simCounter  = 0;   // 模拟位姿每次 +10（原来是函数内的 static n）
};

// MainWindow is the UI assembler / signal adapter.  Business logic of the
// capture->detect->save pipeline lives in CaptureFlow; the settings dialog
// lives in SettingsDialog.  Keeping this class thin makes it easy to grow the
// UI without entangling it with the workflow.
class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    explicit MainWindow(QWidget* parent = nullptr);
    ~MainWindow() override;

protected:
    void changeEvent(QEvent* event) override;
    void closeEvent(QCloseEvent* event) override;
    void showEvent(QShowEvent* event) override;
    // WM_QUERYENDSESSION / WM_ENDSESSION: release the camera (bounded) before
    // Windows logs off or shuts down, so the device is not left occupied.
    bool nativeEvent(const QByteArray& eventType, void* message, long* result) override;
    // Idle detection for the preview pause (任务 3.4).
    bool eventFilter(QObject* watched, QEvent* event) override;

private:
    // UI construction
    void buildUi();
    void wireSignals();
    void registerShortcuts();

    // Mode management
    void onModeChanged(bool eyeInHand, bool markerType, bool concentric);
    void onCaliboardParamsChanged(int patternW, int patternH, float circleStep);
    void resetSession();
    // 顶栏「新建会话」：确认后开一组新数据（模式不变）。这是除「启动」与
    // 「切换标定类型」之外唯一的开新会话入口 —— 以前没有它，现场只能重启程序。
    void onNewSessionRequested();

    // 使用说明（顶栏「帮助」按钮 / F1）。chapterId 为空时打开第一章；
    // 正文里的章节互链也走它。窗口首次调用时才创建。
    void showHelp(const QString& chapterId = QString());

    // Camera
    void onConnectCamera();
    void onDisconnectCamera();
    void startPreScan();
    void proceedWithDevices(const std::vector<DeviceEntry>& devices);
    // 相机维护 →「释放相机」: 断开 + 重新扫描, for the "device looks occupied /
    // wedged" case.  Also used by the OS-session path (shorter device wait).
    void releaseCameraNow(int deviceWaitMs, const QString& why);
    // 任务 3.4: pause the preview after N seconds without user input, and resume
    // it the moment anything happens again.
    void onUserActivity();
    void onIdleTimeout();
    // 任务 2: push the three automation switches into CaptureFlow / UI state.
    void applyAutoFlowSettings();
    // 任务 2: 识别成功 → 自动保存（同一套必填项校验）.
    void onDetectionFinished(bool ok);

    // Workflow (UI choreography only; business logic is in CaptureFlow)
    void onCapture();
    void saveFromCards();
    void on2dPixelPicked(int x, int y);
    // 像素→3D（在线）：工具页请求用当前采集帧跑一次查询，结果用
    // ToolsPanel::setOnlinePixelResult 回填。
    void onPixelTo3DOnlineQueryRequested(int pixelX, int pixelY);
    // 在线取点的唯一实现（主 2D 点击与工具页「计算」共用）：
    // 用当前采集帧跑 PixelTo3DService，成功填 point，失败给出可读中文 message。
    bool queryPixelFromCurrentFrame(int pixelX, int pixelY,
                                    std::array<double, 3>& point, QString& message);
    // 像素→3D（离线）：工具页请求把主 2D 视窗冻结到这张离线图上 / 解冻。
    void onPixelTo3DOfflineImageRequested(const QString& imagePath);
    void onPixelTo3DOfflineImageEnded();
    void onCalibrate();
    // 工具页「用当前会话」：把当前会话目录与每组机器人位姿喂回面板（无记录也回一次）。
    void onCalibrationSessionRequested();
    void onCalibrationFinished();
    void onRobotConnect(const QString& host, quint16 port,
                        int protocol, int format, double scale,
                        quint8 unitId, quint16 startAddress);
    void onRobotDisconnect();
    void onRobotRead();
    void onRobotReadTouch();
    void onRobotSimulateConnect();
    // T-009: answers from the robot worker thread (queued into this thread).
    void onRobotConnectFinished(bool ok, const QString& label, const QString& error);
    void onRobotPoseReady(int kind, bool ok, const QStringList& fields,
                          const QString& error);
    void updateRobotReadBar();

    // ── 机器人协议分派：搬到了 RobotWorker::readerFor()（worker 线程）──
    // MainWindow 不再持有 reader，也不再直接调用它们的阻塞方法。

    // T-009: stop the robot worker thread before this window goes away, so a
    // blocking call in flight can never touch a half-destroyed object.
    void shutdownRobotThread();

signals:
    // UI → robot worker.  The worker lives on its own thread, so every one of
    // these is delivered as a queued call; the UI thread never blocks on it.
    void robotConnectRequested(const QString& host, quint16 port, int protocol,
                               int format, double scale, quint8 unitId,
                               quint16 startAddress);
    void robotDisconnectRequested();
    void robotSimulateConnectRequested();
    void robotReadPoseRequested(int kind);

private:
    // Card updates
    void onCardChanged(const QString& field, const QString& value);

    // Stage 8 advisory features (report only, never block the workflow)
    // 刷「当前 vs 最近已采」引导。读哪张卡片由当前标定方式决定
    // （DataQualityCheck::sourceFor），所以不需要调用方给值。
    void updatePoseGuide();
    void refreshQualityReport();
    void onBoardMarkers(const std::vector<std::array<float, 3>>& pts3d);
    void syncBoardHistory();
    void refreshBoardOverlay();

    // Measurement tool -> 3D viewport (P4): deviation colouring of the captured
    // cloud through the existing per-point RGB channel, plus sphere/arrow/text
    // annotations for the fitted plane and the measured region.
    void onMeasurementUpdated(const Measurement::Snapshot& snapshot);

    // State helpers
    void setBusy(const QString& text, ActionButtons::BusyTarget target);
    void setConnectBusy(const QString& text);
    void clearBusy();

    // UI-thread stall watchdog (D5): a 100 ms heart-beat that reports a late
    // tick as "[WATCHDOG] UI stall NNN ms (...)" so a frozen UI leaves a trace
    // in the runtime log with the stage that was running.
    void startUiWatchdog();
    void onWatchdogTick();
    // Bracket a synchronous UI-thread heavy operation so a stall reported right
    // after it can name the culprit in the log line.
    void beginHeavyOp(const QString& name);
    void endHeavyOp();

    // Dialogs
    void showSettingsDialog();

    // Owned managers / services
    AppConfig          m_config;
    CameraManager*     m_camera = nullptr;
    DataManager*       m_data   = nullptr;
    LogManager*        m_logger = nullptr;
    CaptureFlow*       m_flow   = nullptr;

    // Owned UI widgets
    TopNavBar*      m_topNav        = nullptr;
    ModeSelector*   m_modeSelector  = nullptr;
    Image2DView*    m_view2d        = nullptr;
    VisSceneView*   m_view3d        = nullptr;
    DataInputArea*  m_dataInput     = nullptr;
    ActionButtons*  m_actionButtons = nullptr;
    SidePanel*      m_sidePanel     = nullptr;
    ToastOverlay*   m_toast         = nullptr;
    ToolsPanel*     m_toolsPanel    = nullptr;
    // 使用说明窗口（顶栏「帮助」/ F1）：非模态、首次打开时创建，之后常驻一份。
    HelpDialog*     m_helpDialog    = nullptr;

    // Measurement overlay state (3D): object handles of the last annotations and
    // whether the uploaded cloud currently carries deviation colours.
    std::vector<int> m_measureHandles;
    bool m_cloudColored = false;
    // Per-point RGB of the last deviation colouring, kept so a later re-upload
    // of the same frame (e.g. the marker-highlight pass after 识别) can restore
    // the colouring instead of silently dropping it.
    FrameBuffer::FloatBuf m_measureCloudColors;

    // Current mode
    EyeHandMode m_eyeHandMode = EyeHandMode::EyeInHand;
    CalibType   m_calibType   = CalibType::Marker;
    MarkerType  m_markerType  = MarkerType::ConcentricCircle;
    int         m_caliboardW    = 4;     // columns, short side
    int         m_caliboardH    = 11;    // rows, long side, must be odd
    float       m_caliboardStep = 7.0f;  // A9

    QString m_saveBaseDir;
    bool m_busy = false;
    bool m_savePathFellBack = false;   // portable-build: configured path unusable
    std::vector<DeviceEntry> m_cachedDevices;
    bool m_preScanning = false;
    bool m_connectRequested = false;

    // ── Round 5: automation + lifetime ──
    // (第 12 回合 任务 1 删掉了 m_useCameraParams：拍摄参数已完全交由相机持有。)
    bool m_autoDetectAfterCapture = false; // 任务 2 (all default off)
    bool m_autoSaveAfterDetect = false;
    // 任务 3.4: 0 = never pause the preview on idle.
    int  m_idlePauseSec = 60;
    QTimer* m_idleTimer = nullptr;
    bool m_idlePreviewPaused = false;

    // Stage 4: online 2D-pixel -> 3D point
    int m_pickSphereHandle = -1;               // 3D highlight sphere
    std::vector<int> m_correspondIndex;        // cached line-scan reverse index
    int m_correspondW = 0;
    int m_correspondH = 0;
    bool m_correspondBuilt = false;

    // Stage 7: in-app calibration (async, UI stays responsive)
    QFutureWatcher<CalibrationService::Result>* m_calibWatcher = nullptr;

    // Stage 8: board-pose overlay (advisory visualization)
    struct BoardFrameEntry {
        int frameNo = 0;
        BoardPoseFit::Pose pose;
    };
    std::vector<BoardFrameEntry> m_boardFrames;      // one fitted pose per saved frame
    BoardPoseFit::Pose m_pendingBoardPose;           // last detected frame's board pose

    // Stage 8: robot communication (isolated, default off).
    // T-009: the readers themselves now live in the worker on m_robotThread; the
    // UI only holds the thread handle and the logical connection state below.
    // 0 = Modbus TCP, 1 = UR Realtime, 2 = 博纳斯(纳博特) JSON/TCP（协议号语义不变）
    QThread*     m_robotThread = nullptr;
    RobotWorker* m_robotWorker = nullptr;
    bool m_robotAutoRead = false;
    bool m_robotConnected = false;     // logical connection (real or simulated)
    bool m_robotSimulated = false;     // "模拟连接成功" — no real socket

    // Window centering (restore/clamp once on first show)
    bool m_windowPositioned = false;

    // UI-thread stall watchdog (D5).  All state is touched on the UI thread
    // only — the watchdog adds no thread of its own and no shared state.
    QTimer* m_watchdogTimer = nullptr;
    UiStallWatchdog::Watchdog m_watchdog;
    QString m_heavyOpName;              // last synchronous UI-thread heavy op
    double  m_heavyOpStartMs = -1.0;
    double  m_heavyOpEndMs   = -1.0;
    bool    m_uploading3d    = false;   // inside VisSceneView::updatePointCloud
};
