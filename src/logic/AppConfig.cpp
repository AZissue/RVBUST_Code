#include "logic/AppConfig.h"
#include <QDir>
#include <QJsonDocument>
#include <QJsonObject>
#include <QFile>
#include <QCoreApplication>
#include <QDebug>

AppConfig::AppConfig()
    : m_settings(QSettings::IniFormat, QSettings::UserScope,
                 QStringLiteral("RVBUST"), QStringLiteral("HandEyeTool"))
{
}

void AppConfig::load()
{
    m_settings.sync();

    m_data.clear();
    for (const auto& key : m_settings.allKeys()) {
        m_data[key] = m_settings.value(key);
    }
    if (m_settings.status() != QSettings::NoError) {
        qWarning("AppConfig::load: QSettings error, using defaults");
    }

    // Apply defaults for missing keys
    if (!m_data.contains("save_base_dir")) {
        m_data["save_base_dir"] = QDir::currentPath() + "/data";
    }
    if (!m_data.contains("eye_in_hand")) {
        m_data["eye_in_hand"] = true;
    }
    if (!m_data.contains("marker_type")) {
        m_data["marker_type"] = true;
    }
    if (!m_data.contains("marker_concentric")) {
        m_data["marker_concentric"] = true;
    }
    if (!m_data.contains("window_geometry")) {
        m_data["window_geometry"] = QVariantMap{
            {"x", -1}, {"y", -1}, {"width", 1920}, {"height", 1080}};
    }
    if (!m_data.contains("camera_params")) {
        m_data["camera_params"] = QVariantMap{};
    }
    if (!m_data.contains("caliboard_pattern_w")) {
        m_data["caliboard_pattern_w"] = 4;     // columns, short side
    }
    if (!m_data.contains("caliboard_pattern_h")) {
        m_data["caliboard_pattern_h"] = 11;    // rows, long side, must be odd
    }
    if (!m_data.contains("caliboard_circle_step")) {
        m_data["caliboard_circle_step"] = 7.0; // A9
    }
    if (!m_data.contains("caliboard_error_threshold")) {
        m_data["caliboard_error_threshold"] = 5.0;
    }
    if (!m_data.contains("ui_stall_threshold_ms")) {
        m_data["ui_stall_threshold_ms"] = 500;
    }
    // Default true: the operator tunes exposure/gain in the camera vendor tool
    // first, so the camera's own values must win unless told otherwise.
    if (!m_data.contains("use_camera_params")) {
        m_data["use_camera_params"] = true;
    }
    // Flow automation: all off, so an untouched install behaves as before.
    if (!m_data.contains("auto_detect_after_capture")) {
        m_data["auto_detect_after_capture"] = false;
    }
    if (!m_data.contains("auto_save_after_detect")) {
        m_data["auto_save_after_detect"] = false;
    }
    if (!m_data.contains("auto_read_robot_pose")) {
        m_data["auto_read_robot_pose"] = false;
    }
    if (!m_data.contains("idle_pause_preview_sec")) {
        m_data["idle_pause_preview_sec"] = 60;
    }
    if (!m_data.contains("health_check_interval_sec")) {
        m_data["health_check_interval_sec"] = 30;
    }
    if (!m_data.contains("connect_retry_count")) {
        m_data["connect_retry_count"] = 3;
    }
}

void AppConfig::save()
{
    for (auto it = m_data.constBegin(); it != m_data.constEnd(); ++it) {
        m_settings.setValue(it.key(), it.value());
    }
    m_settings.sync();
    if (m_settings.status() != QSettings::NoError) {
        qWarning("AppConfig::save: QSettings sync failed");
    }
}

QString AppConfig::saveBaseDir() const
{
    return m_data.value("save_base_dir", QDir::currentPath() + "/data").toString();
}

void AppConfig::setSaveBaseDir(const QString& path)
{
    m_data["save_base_dir"] = path;
    save();
}

bool AppConfig::eyeInHand() const
{
    return m_data.value("eye_in_hand", true).toBool();
}

bool AppConfig::markerType() const
{
    return m_data.value("marker_type", true).toBool();
}

bool AppConfig::markerConcentric() const
{
    return m_data.value("marker_concentric", true).toBool();
}

void AppConfig::setLastMode(bool eyeInHand, bool markerType, bool concentric)
{
    m_data["eye_in_hand"] = eyeInHand;
    m_data["marker_type"] = markerType;
    m_data["marker_concentric"] = concentric;
    save();
}

QRect AppConfig::windowGeometry() const
{
    auto geom = m_data.value("window_geometry").toMap();
    return QRect(geom.value("x", -1).toInt(),
                 geom.value("y", -1).toInt(),
                 geom.value("width", 1920).toInt(),
                 geom.value("height", 1080).toInt());
}

void AppConfig::setWindowGeometry(int x, int y, int width, int height)
{
    m_data["window_geometry"] = QVariantMap{
        {"x", x}, {"y", y}, {"width", width}, {"height", height}};
    // Deferred save — called from closeEvent
}

QVariantMap AppConfig::cameraParams() const
{
    return m_data.value("camera_params").toMap();
}

void AppConfig::setCameraParams(const QVariantMap& params)
{
    m_data["camera_params"] = params;
    save();
}

int AppConfig::caliboardPatternW() const
{
    return m_data.value("caliboard_pattern_w", 4).toInt();  // columns, short side
}

int AppConfig::caliboardPatternH() const
{
    return m_data.value("caliboard_pattern_h", 11).toInt();  // rows, long side, must be odd
}

float AppConfig::caliboardCircleStep() const
{
    return m_data.value("caliboard_circle_step", 7.0).toFloat();  // A9 default
}

void AppConfig::setCaliboardParams(int patternW, int patternH, float circleStep)
{
    m_data["caliboard_pattern_w"] = patternW;
    m_data["caliboard_pattern_h"] = patternH;
    m_data["caliboard_circle_step"] = static_cast<double>(circleStep);
    save();
}

float AppConfig::caliboardErrorThreshold() const
{
    return static_cast<float>(m_data.value("caliboard_error_threshold", 5.0).toDouble());
}

void AppConfig::setCaliboardErrorThreshold(float pct)
{
    m_data["caliboard_error_threshold"] = static_cast<double>(pct);
    save();
}

bool AppConfig::useCameraParams() const
{
    return m_data.value("use_camera_params", true).toBool();
}

void AppConfig::setUseCameraParams(bool on)
{
    m_data["use_camera_params"] = on;
    save();
}

bool AppConfig::autoDetectAfterCapture() const
{
    return m_data.value("auto_detect_after_capture", false).toBool();
}

void AppConfig::setAutoDetectAfterCapture(bool on)
{
    m_data["auto_detect_after_capture"] = on;
    save();
}

bool AppConfig::autoSaveAfterDetect() const
{
    return m_data.value("auto_save_after_detect", false).toBool();
}

void AppConfig::setAutoSaveAfterDetect(bool on)
{
    m_data["auto_save_after_detect"] = on;
    save();
}

bool AppConfig::autoReadRobotPose() const
{
    return m_data.value("auto_read_robot_pose", false).toBool();
}

void AppConfig::setAutoReadRobotPose(bool on)
{
    m_data["auto_read_robot_pose"] = on;
    save();
}

int AppConfig::idlePausePreviewSec() const
{
    const int v = m_data.value("idle_pause_preview_sec", 60).toInt();
    return v > 0 ? v : 0;   // 0 (and anything negative) disables the idle pause
}

void AppConfig::setIdlePausePreviewSec(int sec)
{
    m_data["idle_pause_preview_sec"] = sec > 0 ? sec : 0;
    save();
}

int AppConfig::healthCheckIntervalSec() const
{
    const int v = m_data.value("health_check_interval_sec", 30).toInt();
    return v > 0 ? v : 30;
}

void AppConfig::setHealthCheckIntervalSec(int sec)
{
    m_data["health_check_interval_sec"] = sec > 0 ? sec : 30;
    save();
}

int AppConfig::connectRetryCount() const
{
    const int v = m_data.value("connect_retry_count", 3).toInt();
    return v > 0 ? v : 0;
}

void AppConfig::setConnectRetryCount(int count)
{
    m_data["connect_retry_count"] = count > 0 ? count : 0;
    save();
}

int AppConfig::uiStallThresholdMs() const
{
    // Env override wins: useful when the field needs a tighter/looser report
    // than the persisted setting without editing the ini.
    bool ok = false;
    const int env = qEnvironmentVariableIntValue("HEC_UI_STALL_MS", &ok);
    if (ok && env > 0)
        return env;
    return m_data.value("ui_stall_threshold_ms", 500).toInt();
}

void AppConfig::setUiStallThresholdMs(int ms)
{
    m_data["ui_stall_threshold_ms"] = ms > 0 ? ms : 500;
    save();
}
