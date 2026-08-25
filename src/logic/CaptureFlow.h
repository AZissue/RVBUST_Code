#pragma once

#include <QObject>
#include <QImage>
#include <QString>
#include <vector>
#include <array>
#include <tuple>
#include <QFutureWatcher>
#include <QTimer>
#include "models/CalibrationMode.h"

class CameraManager;
class DataManager;

// Capture -> detect -> save workflow state machine.
//
// Owns the transient "current capture" state and all business logic of the
// pipeline.  UI concerns are communicated through signals so MainWindow can
// stay a thin adapter (views, buttons, tips, toasts, logs, card auto-fill).
class CaptureFlow : public QObject {
    Q_OBJECT
public:
    static constexpr int DETECT_TIMEOUT_MS = 30000;
    static constexpr float MAX_CALIBOARD_ERROR_PCT = 5.0f;

    explicit CaptureFlow(CameraManager* camera, DataManager* data,
                         QObject* parent = nullptr);

    // Mode / configuration (pushed by MainWindow when it changes)
    void setMode(const CalibrationMode& mode);
    void setCaliboardParams(int patternW, int patternH, float circleStep);
    // Caliboard accuracy warning threshold (%).  Warnings never block saving;
    // this only tunes when the "检测误差较大" advisory appears.
    void setErrorThreshold(float pct);
    float errorThreshold() const { return m_errorThreshold; }

    // Workflow entry points
    void beginCapture();            // sets busy and triggers camera capture
    void onCaptureReady(const QString& pngPath, const QString& plyPath,
                        const std::vector<float>& points,
                        const std::vector<float>& colors,
                        const QImage& image);
    void detect();
    void save(const QString& cameraTargetXyz, const QString& robotCapturePose,
              const QString& robotTargetXyz);
    void undo();

    // State
    bool hasUnsavedCapture() const;
    const std::vector<float>& capturedPoints() const;
    void reset();                   // discard transient capture state

    // Programmatic action-state control (e.g. camera error disables buttons)
    void setDetectEnabled(bool enabled);
    void setSaveEnabled(bool enabled);

    // Pure validation helper (unit-tested)
    static bool containsBadValue(const QString& text)
    {
        return text.contains(QStringLiteral("nan"), Qt::CaseInsensitive)
            || text.contains(QStringLiteral("inf"), Qt::CaseInsensitive);
    }

    // True when the text contains CJK / full-width characters (Chinese
    // punctuation such as ，、；（）or full-width digits).  Calibration data
    // must use ASCII numbers separated by spaces or English commas.
    static bool containsCjkFormatChars(const QString& text)
    {
        const ushort* u = text.utf16();
        const int len = text.size();
        for (int i = 0; i < len; ++i) {
            const ushort c = u[i];
            // CJK symbols/punctuation, CJK unified ideographs, full-width forms
            // (full-width comma ， is U+FF0C), and full-width digits.
            if ((c >= 0x3000 && c <= 0x303F)
                    || (c >= 0x4E00 && c <= 0x9FFF)
                    || (c >= 0xFF00 && c <= 0xFFEF))
                return true;
        }
        return false;
    }

    struct SaveIssue {
        bool ok = true;
        QString field;    // card id to highlight, empty when ok
        QString message;
    };

    // Required-field + numeric-format validation (mode aware, unit-tested).
    static SaveIssue validateSaveInputs(const QString& cameraTargetXyz,
                                        const QString& robotCapturePose,
                                        const QString& robotTargetXyz,
                                        const CalibrationMode& mode)
    {
        auto hasBad = [](const QString& s) { return containsBadValue(s); };
        if (hasBad(cameraTargetXyz) || hasBad(robotCapturePose) || hasBad(robotTargetXyz))
            return { false, {},
                     QStringLiteral("数据包含无效值(NaN/Inf)，请重新采集检测") };

        auto formatCheck = [](const QString& s) {
            return containsCjkFormatChars(s);
        };
        if (formatCheck(cameraTargetXyz) || formatCheck(robotCapturePose)
                || formatCheck(robotTargetXyz)) {
            return { false, {},
                     QStringLiteral("数据包含中文格式字符，请使用英文逗号或空格分隔数值") };
        }

        auto numericCheck = [](const QString& s, int count) {
            // Accept "1 2 3", "1,2,3" and "1, 2, 3": English commas are
            // treated as separators (normalized to spaces before splitting).
            QString normalized = s;
            normalized.replace(QLatin1Char(','), QLatin1Char(' '));
            const auto tokens = normalized.simplified().split(QLatin1Char(' '), Qt::SkipEmptyParts);
            if (tokens.size() != count) return false;
            for (const auto& t : tokens) {
                bool ok = false;
                t.toDouble(&ok);
                if (!ok) return false;
            }
            return true;
        };

        if (cameraTargetXyz.trimmed().isEmpty())
            return { false, QStringLiteral("camera_target_xyz"),
                     QStringLiteral("相机目标点坐标不能为空") };
        if (!numericCheck(cameraTargetXyz, 3))
            return { false, QStringLiteral("camera_target_xyz"),
                     QStringLiteral("相机目标点坐标应为 3 个数值（x y z）") };

        if (mode.calibType == CalibType::Marker) {
            if (robotCapturePose.trimmed().isEmpty())
                return { false, QStringLiteral("robot_capture_pose"),
                         QStringLiteral("机器人拍照位姿不能为空") };
            if (!numericCheck(robotCapturePose, 6))
                return { false, QStringLiteral("robot_capture_pose"),
                         QStringLiteral("机器人拍照位姿应为 6 个数值（x y z rx ry rz）") };
        } else {  // TCP touch
            if (robotTargetXyz.trimmed().isEmpty())
                return { false, QStringLiteral("robot_target_xyz"),
                         QStringLiteral("机器人 TCP 点坐标不能为空") };
            if (!numericCheck(robotTargetXyz, 3))
                return { false, QStringLiteral("robot_target_xyz"),
                         QStringLiteral("机器人 TCP 点坐标应为 3 个数值（x y z）") };
            if (mode.isEyeInHand()) {
                if (robotCapturePose.trimmed().isEmpty())
                    return { false, QStringLiteral("robot_capture_pose"),
                             QStringLiteral("机器人拍照位姿不能为空") };
                if (!numericCheck(robotCapturePose, 6))
                    return { false, QStringLiteral("robot_capture_pose"),
                             QStringLiteral("机器人拍照位姿应为 6 个数值（x y z rx ry rz）") };
            }
        }
        return { true, {}, {} };
    }

    // Caliboard quality advisory (unit-tested): returns a warning message when
    // the detection is partial or its accuracy metric is unusual.  Detection
    // still proceeds (points are filled, save is enabled) — the warning is
    // shown to the operator, it does not reject the result.
    static QString caliboardQualityMessage(
        int detected, int expected, float errorPct,
        float threshold = MAX_CALIBOARD_ERROR_PCT)
    {
        if (detected < expected)
            return QStringLiteral("仅检测到 %1/%2 个圆点（标定板部分缺失），请确认后保存")
                .arg(detected).arg(expected);
        if (errorPct > threshold)
            return QStringLiteral("检测误差较大 (%1%)，请确认标定板数据")
                .arg(errorPct, 0, 'f', 2);
        return {};
    }

    // Work item / result for file-based detection (runs in a worker thread).
    struct DetectJob {
        MarkerType markerType = MarkerType::ConcentricCircle;
        QString png;
        QString ply;
        int patternW = 4;
        int patternH = 11;
        float circleStep = 7.0f;
        float errorThreshold = MAX_CALIBOARD_ERROR_PCT;
        std::vector<float> intrinsic;
        std::vector<float> distortion;
    };

    struct DetectResult {
        enum class Status { Ok, EngineError, EngineCrash, NoMarkers, TooFewPoints, PoorAccuracy };
        Status status = Status::EngineError;
        std::vector<std::pair<float, float>> pts2d;
        std::vector<std::array<float, 3>> pts3d;
        std::vector<float> xyzForCard;   // first valid 3D point, empty when none
        int detectedCount = 0;
        int expectedCount = 0;
        float errorPercentage = 0.0f;
        QString errorDetail;
        QString warning;   // non-blocking advisory (partial / high error)
    };

signals:
    void busyChanged(bool busy, const QString& text);
    void detectEnabledChanged(bool enabled);
    void saveEnabledChanged(bool enabled);
    void imageCaptured(const QImage& image);
    void pointCloudReady(const std::vector<float>& points,
                         const std::vector<float>& colors);
    void markersDisplayReady(
        const std::vector<std::tuple<float, float, std::string>>& overlay2d,
        const std::vector<std::array<float, 3>>& highlights3d,
        const std::vector<int>& highlightIndices);
    void clearMarkersRequested();
    void tipRequested(const QString& text, bool isError);
    void toastRequested(const QString& text, bool success);
    void logRequested(const QString& message, const QString& level);
    void autoFillCardRequested(const QString& field, const QString& value);
    void cardInvalidRequested(const QString& field);

private:
    static DetectResult runDetectJob(const DetectJob& job);
    void applyDetectionResult(const DetectResult& result);
    void onDetectionFinished();
    void onDetectionTimeout();
    void clearCapturedState();

    CameraManager* m_camera = nullptr;
    DataManager*   m_data   = nullptr;

    CalibrationMode m_mode;
    int         m_caliboardW    = 4;
    int         m_caliboardH    = 11;
    float       m_caliboardStep = 7.0f;
    float       m_errorThreshold = MAX_CALIBOARD_ERROR_PCT;

    // Transient capture state (cleared on save/reset)
    QString m_capturedPng;
    QString m_capturedPly;
    std::vector<float> m_capturedPoints;
    QImage  m_capturedImage;

    // Detection cache: same frame + same marker type/spec -> reuse the last
    // successful file-based detection instead of re-running the engine.
    QString m_detectCacheKey;
    DetectResult m_detectCache;
    QString m_pendingCacheKey;   // key of the in-flight detection

    bool m_detectEnabled = false;
    bool m_saveEnabled   = false;

    // Async file-based detection
    DetectJob m_pendingJob;
    QFutureWatcher<DetectResult>* m_detectWatcher = nullptr;
    QTimer* m_detectWatchdog = nullptr;
    bool m_detecting = false;
    bool m_detectTimedOut = false;
    qint64 m_detectStartMs = 0;   // runtime-log timing

    // Quality of the last successful detection (persisted with the record).
    float m_lastErrorPct = -1.0f;   // -1 = not applicable (concentric)
    int   m_lastMarkerCount = 0;
};
