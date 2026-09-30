#pragma once
#include <QObject>
#include <QTimer>
#include <QImage>
#include <QMap>
#include <QString>
#include <vector>
#include <memory>
#include <functional>
#include <atomic>
#include <chrono>
#include <mutex>
#include <QFuture>
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
    // Bounded, idempotent teardown.  `deviceWaitMs` is how long the device lock
    // is waited for; the OS-session path passes a shorter one.  A repeat call
    // performs no SDK work and emits no second cameraDisconnected (see
    // CameraRelease::plan).
    void shutdown(int deviceWaitMs = SHUTDOWN_DEVICE_WAIT_MS);
    bool isConnected() const;

    // What the last shutdown() actually did (3.1: a failed/timed-out release
    // must be visible in the log, never silent).
    struct ReleaseReport {
        bool attempted = false;    // a release path with work to do ran
        bool released = false;     // Close/Destroy/SystemShutdown completed
        QString detail;            // error text when !released
    };
    ReleaseReport lastRelease() const { return m_lastRelease; }

    // Crash path only (called from the SEH filter's release thread, never from
    // the normal workflow).  Drops the SDK-wide resources with no per-device
    // call — after an access violation the X1/X2 objects may point at corrupt
    // state, so Close()/Destroy() are deliberately NOT attempted here; the
    // TerminateProcess that follows is what actually frees the device.
    // Never throws, never blocks on the device lock.
    static void emergencyRelease();

    // Bounded wait for an in-flight capture worker to leave the device.  True
    // when nothing was running (or it finished in time).  Used by the close
    // path so the teardown below it does not race a live worker; it does NOT
    // pump the event loop, so no slot can re-enter the window mid-close.
    bool waitForCaptureIdle(int timeoutMs);

    // ── Capture parameters (第 12 回合 任务 1) ──
    //
    // The app owns none of them any more.  预览和拍照 call the SDK's no-arg
    // Capture()/Capture2D(), which load whatever the device has stored — the
    // operator tunes exposure/gain/mode in the camera vendor's own tool and the
    // app never pushes a value over it.  What is left here is a *read-only*
    // mirror of the camera's values, kept for one reason: the runtime log has to
    // be able to say what the camera was actually set to, which is the first
    // thing to check when a capture comes back dark, pattern-lit or depth-less.
    QMap<QString, float> cameraCaptureSummary() const;

    // ── Camera lifetime tuning (任务 3.4) ──
    void setHealthCheckInterval(int ms);
    // The interval actually in effect (default 30 s — the 5 s scan took the
    // device lock often enough to be felt as "the camera keeps getting grabbed").
    int  healthCheckInterval() const;
    void setConnectRetryCount(int count) { m_connectRetryCount = count > 0 ? count : 0; }
    int  connectRetryCount() const { return m_connectRetryCount; }

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
    // The one preview round currently in flight.  onPreviewTick() runs at most
    // one at a time (m_previewBusy), and stores its future here so
    // ~CameraManager() can wait that round out before it tears `m_impl` down
    // (a worker that has passed its token check is inside
    // capturePreviewFrameX1()/X2(), i.e. driving `this` / `m_impl`).
    // Only ever written on the UI thread, which also runs the destructor, so no
    // lock is needed.
    QFuture<void> m_previewFuture;
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
    // 任务 3: set once a teardown has completed, cleared by a successful
    // connect, so a repeat shutdown() is a no-op (and a shutdown after a
    // *reconnect* still tears the new session down).
    bool m_released = false;
    ReleaseReport m_lastRelease;
    int m_connectRetryCount = 3;
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

    // Read the device's stored capture options into `m_impl->capOpts*` (the
    // read-only mirror).  Must be called with the device lock held; returns false
    // when the device reports nothing, in which case the previous mirror stands.
    bool loadCameraOptionsLocked(const char* who);
    // One runtime-log line naming the camera's own exposure/gain *and* the
    // options that decide the shape of a capture (mode / correspond2d / 2D 开关
    // / 投影 / 坐标系).  This is the only place those are visible to us now.
    void logCameraOptions(const char* when);

    void scheduleReconnect();
    // Drop the last-frame lookup buffers / native detection cache.  Called when
    // a newer frame replaces them and on shutdown, so the previous ~60 MB goes
    // away at a defined point instead of lingering until the next capture.
    void releaseFrameCaches();

public:
    static constexpr int CAPTURE_TIMEOUT_MS = 60000;  // 5M-point GigE captures are slow
    static constexpr int RECONNECT_MAX_ATTEMPTS = 3;
    static constexpr int RECONNECT_INTERVAL_MS = 3000;
    // 任务 3.4: was 5 s, which took the device lock (SystemFindDevice) 12x per
    // minute and wrote a "[DEV] health-scan acquired device" line each time.
    // 30 s is plenty for hot-plug detection; AppConfig can tune it.
    static constexpr int HEALTH_CHECK_INTERVAL_MS = 30000;
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
