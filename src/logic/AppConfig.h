#pragma once
#include <QSettings>
#include <QRect>
#include <QVariantMap>
#include <QString>

class AppConfig {
public:
    AppConfig();

    void load();
    void save();

    // Save base directory
    QString saveBaseDir() const;
    void setSaveBaseDir(const QString& path);

    // Last calibration mode
    bool eyeInHand() const;
    bool markerType() const;
    bool markerConcentric() const;
    void setLastMode(bool eyeInHand, bool markerType, bool concentric);

    // Window geometry
    QRect windowGeometry() const;
    void setWindowGeometry(int x, int y, int width, int height);

    // Camera parameters
    QVariantMap cameraParams() const;
    void setCameraParams(const QVariantMap& params);

    // When true (default), the values the camera itself holds are used as-is:
    // LoadCaptureOptionParameters() has already read them into the capture
    // options, and nothing is pushed over them.  The read-back values are still
    // written into camera_params so 设置 can display "相机当前值".
    bool useCameraParams() const;
    void setUseCameraParams(bool on);

    // ── Flow automation (第 5 回合 任务 2) — all default OFF ──
    bool autoDetectAfterCapture() const;   // 拍照成功 → 自动识别
    void setAutoDetectAfterCapture(bool on);
    bool autoSaveAfterDetect() const;      // 识别成功 → 自动保存（仍需必填项校验）
    void setAutoSaveAfterDetect(bool on);
    // 拍照时自动读取机器人位姿.  Single source of truth for both the settings
    // checkbox and the tools-panel checkbox, so the two can never disagree.
    bool autoReadRobotPose() const;
    void setAutoReadRobotPose(bool on);

    // ── Camera lifetime tuning (第 5 回合 任务 3.4) ──
    // Seconds of no user interaction before the preview is paused (0 = never).
    int idlePausePreviewSec() const;
    void setIdlePausePreviewSec(int sec);
    // Interval of the "is the camera still there" bus scan.  The old hard-coded
    // 5 s both spammed the log and took the device lock 12x/minute.
    int healthCheckIntervalSec() const;
    void setHealthCheckIntervalSec(int sec);
    // Bounded connect retry count (0 = no retry; delays are 1/2/3 s ...).
    int connectRetryCount() const;
    void setConnectRetryCount(int count);

    // Caliboard pattern
    int caliboardPatternW() const;
    int caliboardPatternH() const;
    float caliboardCircleStep() const;
    void setCaliboardParams(int patternW, int patternH, float circleStep);

    // Caliboard quality warning threshold (%)
    float caliboardErrorThreshold() const;
    void setCaliboardErrorThreshold(float pct);

    // UI-thread stall watchdog threshold (ms).  Default 500 ms; the
    // HEC_UI_STALL_MS environment variable overrides it for field diagnosis
    // without touching the settings file.
    int uiStallThresholdMs() const;
    void setUiStallThresholdMs(int ms);

    // Direct access to QSettings (for dialogs)
    QSettings& settings() { return m_settings; }

private:
    QSettings m_settings;
    QVariantMap m_data;
};
