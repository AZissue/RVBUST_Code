#pragma once

#include <QMainWindow>
#include <QString>
#include <QFutureWatcher>
#include <array>
#include <vector>
#include "models/CalibrationMode.h"
#include "logic/AppConfig.h"
#include "logic/CalibrationService.h"
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
class QShowEvent;
class QTimer;
struct DeviceEntry;

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
    void onCalibrate();
    void onCalibrationFinished();
    void onRobotConnect(const QString& host, quint16 port,
                        int protocol, int format, double scale,
                        quint8 unitId, quint16 startAddress);
    void onRobotDisconnect();
    void onRobotRead();
    void onRobotReadTouch();
    void onRobotSimulateConnect();
    bool readRobotPose(RobotPose::Pose& pose);
    QString robotLastError() const;
    void updateRobotReadBar();

    // Card updates
    void onCardChanged(const QString& field, const QString& value);

    // Stage 8 advisory features (report only, never block the workflow)
    void updatePoseGuide(const QString& poseText);
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

    // ── Round 5: camera parameter source + automation + lifetime ──
    bool m_useCameraParams = true;         // 任务 1 (mirrors AppConfig)
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

    // Stage 8: robot communication (isolated, default off)
    RobotPose::ModbusTcpReader m_robotReader;
    RobotPose::URRealtimeReader m_urReader;
    RobotPose::NrcJsonReader m_nrcReader;   // 博纳斯/纳博特 JSON over TCP
    // 0 = Modbus TCP, 1 = UR Realtime, 2 = 博纳斯(纳博特) JSON/TCP
    int m_robotProtocol = 0;
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
