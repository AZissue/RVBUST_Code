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

    // Caliboard pattern
    int caliboardPatternW() const;
    int caliboardPatternH() const;
    float caliboardCircleStep() const;
    void setCaliboardParams(int patternW, int patternH, float circleStep);

    // Caliboard quality warning threshold (%)
    float caliboardErrorThreshold() const;
    void setCaliboardErrorThreshold(float pct);

    // Direct access to QSettings (for dialogs)
    QSettings& settings() { return m_settings; }

private:
    QSettings m_settings;
    QVariantMap m_data;
};
