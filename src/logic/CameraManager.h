#pragma once
#include <QObject>
#include <QTimer>
#include <QImage>
#include <QMap>
#include <QString>
#include <QVariantMap>
#include <vector>
#include <memory>
#include <functional>
#include <atomic>
#include <QFutureWatcher>

// Forward-declare RVC types to avoid leaking RVC headers into all consumers
namespace RVC {
struct Device;
struct DeviceInfo;
enum CameraID : int;
struct Image;
struct PointMap;
struct X1;
struct X2;
}

// Device entry for list dialog (name/sn/status only — type info used internally)
struct DeviceEntry {
    QString name;
    QString serial;
    bool isX1 = false;
    bool isX2 = false;
    bool occupied = false;
};

class CameraManager : public QObject {
    Q_OBJECT
public:
    explicit CameraManager(QObject* parent = nullptr);
    ~CameraManager() override;

    // Lifecycle
    std::vector<DeviceEntry> listDevices();
    void scanDevicesAsync(std::function<void(std::vector<DeviceEntry>)> onDone);
    void prewarmSystem();   // RVC::SystemInit on the calling (UI) thread
    bool initWithDeviceSerial(const QString& serial);
    bool connectFirstAvailable();   // scan + connect (SEH-safe), prefers X1
    void shutdown();
    bool isConnected() const;

    // Saved camera parameters (exposure/gain) to re-apply every time a device
    // connects.  Connect resets capture options to the camera's stored values,
    // so this is applied after Open() and before cameraConnected is emitted.
    void setParamsOnConnect(const QVariantMap& params);

    // Device info
    QString deviceName() const;
    std::pair<std::vector<float>, std::vector<float>> intrinsics() const;

    // Last capture's organized grid (image-ordered, mm) for pixel<->3D lookup
    // and, for SwingLineScan + correspond2d=false captures, the SDK
    // CorrespondMap (3D point index -> 2D pixel).  lastGridAligned() is false
    // exactly when correspond data is available.
    bool lastGrid(std::vector<double>& xyzMm, int& w, int& h) const;
    bool lastCorrespond(std::vector<double>& cmap, int& w, int& h) const;
    bool lastGridAligned() const;

    // Native concentric circle detection results (from last capture)
    std::pair<std::vector<float>, std::vector<float>> nativeMarkerResult() const;

    // Preview stream
    bool isStereo() const;
    bool isPreviewing() const;
    void startPreview();
    void stopPreview();
    void togglePreview();
    void pausePreview();
    void resumePreview();

    // Full 3D capture — emits captureComplete on success
    void captureFullFrame(const QString& saveDir, int index);

    // Camera parameter setters
    void setExposure2D(float ms);
    void setExposure3D(float ms);
    void setGain2D(float value);
    void setGain3D(float value);
    void setGamma2D(float value);
    void setGamma3D(float value);
    void setLineScannerExposureUs(float us);
    void setParameter(const QString& key, float value);

    QMap<QString, float> currentSettings() const;

    // Per-key clamp range; returns {0,0} for unknown keys.
    static std::pair<float, float> cameraParamRange(const QString& key);

signals:
    void previewFrameReady(const QImage& image);
    void previewRightFrameReady(const QImage& image);
    void captureComplete(const QString& pngPath, const QString& plyPath,
                         const std::vector<float>& points,       // filtered N*3 flat
                         const std::vector<float>& colors,       // N*3 flat [0,1]
                         const QImage& image);
    void cameraError(const QString& message);
    void cameraConnected();
    void cameraDisconnected();

private slots:
    void onPreviewTick();
    void onScanFinished();
    void onCaptureFinished();
    void onCaptureTimeout();
    void onReconnectTick();
    void onHealthTick();

private:
    // ── X1/X2 dedicated flow methods (guard + return isolates each code path) ──
public:
    struct CaptureResult {
        bool ok = false;
        QString pngPath;
        QString plyPath;
        QString error;
        std::vector<float> points;
        std::vector<float> colors;
        std::vector<float> nativePixels;
        std::vector<float> nativePoints;
        // Organized grid (image-ordered, mm) for pixel<->3D lookup.
        std::vector<double> gridPoints;   // w*h*3
        int gridW = 0;
        int gridH = 0;
        // SwingLineScan + correspond2d=false only: point index -> 2D pixel.
        std::vector<double> correspondMap;  // w*h*2
        int cmW = 0;
        int cmH = 0;
        bool gridAligned = true;
        QImage image;
    };

private:
    CaptureResult captureFrameX1(const QString& saveDir, int index);
    CaptureResult captureFrameX2(const QString& saveDir, int index);

    // Preview frame capture (runs in a worker thread; projector disabled so
    // the 2D stream is as fast as the camera allows).
    struct PreviewFrames {
        QImage left;
        QImage right;   // stereo X2 only
    };
    PreviewFrames capturePreviewFrameX1();
    PreviewFrames capturePreviewFrameX2();

    // ── Camera model discriminator ──
    enum class CameraModel : uint8_t { None, X1, X2 };

    // PIMPL: hide RVC types behind opaque pointer to keep header clean
    struct RvcImpl;
    std::unique_ptr<RvcImpl> m_impl;

    int m_cameraId = 0;   // X2: left/extra; X1: always Left
    QTimer* m_previewTimer = nullptr;
    QFutureWatcher<std::vector<DeviceEntry>>* m_scanWatcher = nullptr;
    QFutureWatcher<CaptureResult>* m_captureWatcher = nullptr;
    QTimer* m_captureWatchdog = nullptr;
    QTimer* m_reconnectTimer = nullptr;
    QTimer* m_healthTimer = nullptr;
    int m_previewFps = 20;
    bool m_isConnected = false;
    bool m_previewPaused = false;
    bool m_shuttingDown = false;
    bool m_captureInProgress = false;
    bool m_captureTimedOut = false;
    QVariantMap m_paramsOnConnect;
    std::atomic<bool> m_previewBusy{false};
    int  m_previewGen = 0;
    std::atomic<int> m_previewFailures{0};
    std::atomic<bool> m_healthBusy{false};
    std::atomic<bool> m_scanBusy{false};
    int  m_reconnectAttempts = 0;
    bool m_wasPreviewing = false;
    QString m_lastSerial;
    qint64 m_scanStartMs = 0;    // runtime-log timing
    qint64 m_captureStartMs = 0;

    std::function<void(std::vector<DeviceEntry>)> m_scanDone;

    std::vector<float> m_intrinsicMatrix;   // 9 elements
    std::vector<float> m_distortion;        // 5 elements

    // Last capture's pixel<->3D lookup data (UI thread, filled on success).
    std::vector<double> m_lastGrid;
    int m_lastGridW = 0;
    int m_lastGridH = 0;
    std::vector<double> m_lastCorrespond;
    int m_lastCmW = 0;
    int m_lastCmH = 0;
    bool m_lastGridAligned = true;

    // Cached native concentric circle detection from last capture
    std::vector<float> m_nativeMarkerPixels;   // flat [x0,y0,...] in px
    std::vector<float> m_nativeMarkerPoints;   // flat [x0,y0,z0,...] in mm

    void scheduleReconnect();

public:
    static constexpr int CAPTURE_TIMEOUT_MS = 60000;  // 5M-point GigE captures are slow
    static constexpr int RECONNECT_MAX_ATTEMPTS = 3;
    static constexpr int RECONNECT_INTERVAL_MS = 3000;
    static constexpr int HEALTH_CHECK_INTERVAL_MS = 5000;
};
