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
#include <chrono>
#include <mutex>
#include <QFutureWatcher>

#include "logic/FrameBuffer.h"

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
    //
    // Both hand out a shared, immutable buffer instead of copying: the grid is
    // w*h*3 doubles (~37 MB at 1440x1080) and the correspond map ~25 MB, which
    // used to be deep-copied on every 2D pixel pick.
    bool lastGrid(FrameBuffer::DoubleBuf& xyzMm, int& w, int& h) const;
    bool lastCorrespond(FrameBuffer::DoubleBuf& cmap, int& w, int& h) const;
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
    // Point/colour payload is handed over as shared immutable buffers: emitting
    // the signal (and every slot that keeps a reference) costs a refcount bump
    // instead of an 8 MB copy each.
    void captureComplete(const QString& pngPath, const QString& plyPath,
                         const FrameBuffer::FloatBuf& points,   // filtered N*3 flat
                         const FrameBuffer::FloatBuf& colors,   // N*3 flat [0,1]
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
    // One 3D capture produces ~70 MB of payload.  Every heavy member is a
    // shared immutable buffer so this struct can be copied cheaply — which
    // matters because QFutureWatcher<T>::result() returns T *by value*, so the
    // whole struct used to be deep-copied once per capture.
    struct CaptureResult {
        bool ok = false;
        QString pngPath;
        QString plyPath;
        QString error;
        FrameBuffer::FloatBuf points;         // filtered N*3 flat
        FrameBuffer::FloatBuf colors;         // N*3 flat [0,1]
        std::vector<float> nativePixels;      // <=1000 markers, kept by value
        std::vector<float> nativePoints;
        // Organized grid (image-ordered, mm) for pixel<->3D lookup.
        FrameBuffer::DoubleBuf gridPoints;    // w*h*3
        int gridW = 0;
        int gridH = 0;
        // SwingLineScan + correspond2d=false only: point index -> 2D pixel.
        FrameBuffer::DoubleBuf correspondMap; // w*h*2
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
        QImage right;      // stereo X2 only
        bool abandoned = false;   // round dropped to hand the device to a capture
    };
    PreviewFrames capturePreviewFrameX1();
    PreviewFrames capturePreviewFrameX2();

    // ── Camera model discriminator ──
    enum class CameraModel : uint8_t { None, X1, X2 };

    // ── D1: RVC device access serialization ──────────────────────────────
    //
    // The RVC GenICam layer is not thread-safe: driving one device from the
    // preview worker and the capture worker at the same time corrupts device
    // state (black 2D frames, num=0 detections, internal deadlocks).  Every RVC
    // entry point therefore runs under m_rvcMutex, so at most one thread is
    // ever inside the SDK.
    //
    // A capture cannot simply wait for "preview idle" with a timeout and then
    // barge in anyway — that was the bug.  Instead the capturing side bumps
    // m_deviceYieldGen before it blocks; a preview round that observes a newer
    // generation drops its remaining device calls and releases.  The capture
    // then acquires the lock deterministically, however long that takes.
    //
    // std::recursive_timed_mutex (not std::mutex) because initWithDeviceSerial()
    // legitimately re-enters via shutdown() on the same thread, and because the
    // close path needs a bounded try_lock_for instead of an unbounded wait.
    std::recursive_timed_mutex m_rvcMutex;
    std::atomic<int>  m_deviceYieldGen{0};       // bumped by the capturing side
    std::atomic<int>  m_previewAbandonCount{0};  // preview rounds that yielded
    qint64 m_lastDeviceWaitMs = 0;               // for the runtime log/tests

    // Class definition lives in the .cpp; only ever used there.
    class DeviceLock;

    // Lifetime token shared with every worker we hand to the thread pool.  A
    // worker's first action is to read this token, so a worker that starts
    // after ~CameraManager() is a no-op instead of a use-after-free on `this`.
    struct WorkerToken {
        std::atomic<bool> cancelRequested{false};
    };
    std::shared_ptr<WorkerToken> m_workerToken;


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
    // Slots, not vectors: publishing the shared buffer from the capture result
    // and releasing the previous frame's block are both refcount operations.
    FrameBuffer::BufferSlot<std::vector<double>> m_lastGrid;
    int m_lastGridW = 0;
    int m_lastGridH = 0;
    FrameBuffer::BufferSlot<std::vector<double>> m_lastCorrespond;
    int m_lastCmW = 0;
    int m_lastCmH = 0;
    bool m_lastGridAligned = true;

    // Cached native concentric circle detection from last capture
    std::vector<float> m_nativeMarkerPixels;   // flat [x0,y0,...] in px
    std::vector<float> m_nativeMarkerPoints;   // flat [x0,y0,z0,...] in mm

    void scheduleReconnect();
    // Drop the last-frame lookup buffers / native detection cache.  Called when
    // a newer frame replaces them and on shutdown, so the previous ~60 MB goes
    // away at a defined point instead of lingering until the next capture.
    void releaseFrameCaches();

public:
    static constexpr int CAPTURE_TIMEOUT_MS = 60000;  // 5M-point GigE captures are slow
    static constexpr int RECONNECT_MAX_ATTEMPTS = 3;
    static constexpr int RECONNECT_INTERVAL_MS = 3000;
    static constexpr int HEALTH_CHECK_INTERVAL_MS = 5000;
    // Bounded wait for the device lock on the close path.  If a worker is still
    // inside a hung SDK call we skip teardown instead of hanging the UI or
    // racing the device (see shutdown()).
    static constexpr int SHUTDOWN_DEVICE_WAIT_MS = 3000;

    // Bytes held by the last-frame caches (grid + correspond map), for the
    // [MEM] runtime trace.
    std::size_t cachedBufferBytes() const;
    // Diagnostics for the D1 log line and the unit tests.
    qint64 lastDeviceWaitMs() const { return m_lastDeviceWaitMs; }
    int previewAbandonCount() const { return m_previewAbandonCount.load(); }
};

// Registered so the shared-buffer signal arguments stay usable if any
// connection is ever changed to Qt::QueuedConnection.
Q_DECLARE_METATYPE(FrameBuffer::FloatBuf)
Q_DECLARE_METATYPE(FrameBuffer::DoubleBuf)
