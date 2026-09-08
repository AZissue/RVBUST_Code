#pragma once

#include <QMainWindow>
#include <QString>
#include <QFutureWatcher>
#include <array>
#include <vector>
#include "models/CalibrationMode.h"
#include "logic/AppConfig.h"
#include "logic/CalibrationService.h"
#include "logic/RobotPose.h"
#include "ui/ActionButtons.h"

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
class QPushButton;
class QCheckBox;
class QShowEvent;
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

    // Workflow (UI choreography only; business logic is in CaptureFlow)
    void onCapture();
    void saveFromCards();
    void on2dPixelPicked(int x, int y);
    void onCalibrate();
    void onCalibrationFinished();
    void onRobotConnect(const QString& host, quint16 port,
                        int format, double scale,
                        quint8 unitId, quint16 startAddress);
    void onRobotDisconnect();
    void onRobotRead();
    void onRobotReadTouch();
    void onRobotSimulateConnect();
    bool readRobotPose(RobotPose::Pose& pose);
    void updateRobotReadBar();

    // Card updates
    void onCardChanged(const QString& field, const QString& value);

    // State helpers
    void setBusy(const QString& text, ActionButtons::BusyTarget target);
    void setConnectBusy(const QString& text);
    void clearBusy();

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

    // Stage 4: online 2D-pixel -> 3D point
    int m_pickSphereHandle = -1;               // 3D highlight sphere
    std::vector<int> m_correspondIndex;        // cached line-scan reverse index
    int m_correspondW = 0;
    int m_correspondH = 0;
    bool m_correspondBuilt = false;

    // Stage 7: in-app calibration (async, UI stays responsive)
    QFutureWatcher<CalibrationService::Result>* m_calibWatcher = nullptr;

    // Stage 8: robot communication (isolated, default off)
    RobotPose::ModbusTcpReader m_robotReader;
    bool m_robotAutoRead = false;
    bool m_robotConnected = false;     // logical connection (real or simulated)
    bool m_robotSimulated = false;     // "模拟连接成功" — no real socket

    // Main-interface robot read bar (visible only while connected)
    QWidget*      m_robotReadBar = nullptr;
    QPushButton*  m_btnReadCapturePose = nullptr;
    QPushButton*  m_btnReadTouchPose = nullptr;
    QCheckBox*    m_robotAutoReadCheck = nullptr;

    // Window centering (restore/clamp once on first show)
    bool m_windowPositioned = false;
};
