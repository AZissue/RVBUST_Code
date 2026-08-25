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
        m_data["caliboard_pattern_w"] = 11;
    }
    if (!m_data.contains("caliboard_pattern_h")) {
        m_data["caliboard_pattern_h"] = 4;
    }
    if (!m_data.contains("caliboard_circle_step")) {
        m_data["caliboard_circle_step"] = 15.0;
    }
    if (!m_data.contains("caliboard_error_threshold")) {
        m_data["caliboard_error_threshold"] = 5.0;
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
