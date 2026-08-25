#include "logic/CameraManager.h"
#include "logic/DetectionEngine.h"
#include "logic/PointCloudUtils.h"
#include "logic/RuntimeLog.h"

#include <RVC/RVC.h>
#include <RVC/experimental/MarkerDetection.h>
#include <QDir>
#include <QFileInfo>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <windows.h>
#include <QtConcurrent/QtConcurrentRun>
#include <QThread>
#include <QEventLoop>
#include <QCoreApplication>
#include <QDateTime>
#include <QElapsedTimer>
#include <chrono>

// ── PIMPL: hide RVC::X1 / RVC::X2 + CaptureOptions ──

struct CameraManager::RvcImpl {
    CameraModel model = CameraModel::None;

    RVC::X1 x1;
    RVC::X2 x2;
    RVC::X1::CaptureOptions capOptsX1;
    RVC::X2::CaptureOptions capOptsX2;

    RVC::DeviceInfo devInfo;
    // Device handles from the last scan, so connecting by serial does not
    // need a slow SystemFindDevice() bus re-lookup.
    std::vector<RVC::Device> scannedDevices;
    std::vector<RVC::DeviceInfo> scannedInfos;
    bool systemInited = false;

    bool hasCamera() const { return model != CameraModel::None; }
    bool isX1()      const { return model == CameraModel::X1; }
    bool isX2()      const { return model == CameraModel::X2; }
};

// ── Constructor / Destructor ──

CameraManager::CameraManager(QObject* parent)
    : QObject(parent)
    , m_previewTimer(new QTimer(this))
    , m_scanWatcher(new QFutureWatcher<std::vector<DeviceEntry>>(this))
    , m_captureWatcher(new QFutureWatcher<CaptureResult>(this))
    , m_captureWatchdog(new QTimer(this))
    , m_impl(std::make_unique<RvcImpl>())
{
    m_intrinsicMatrix.resize(9, 0.0f);
    m_distortion.resize(5, 0.0f);
    connect(m_previewTimer, &QTimer::timeout, this, &CameraManager::onPreviewTick);
    connect(m_scanWatcher, &QFutureWatcher<std::vector<DeviceEntry>>::finished,
            this, &CameraManager::onScanFinished);
    connect(m_captureWatcher, &QFutureWatcher<CaptureResult>::finished,
            this, &CameraManager::onCaptureFinished);
    m_captureWatchdog->setSingleShot(true);
    connect(m_captureWatchdog, &QTimer::timeout,
            this, &CameraManager::onCaptureTimeout);

    m_reconnectTimer = new QTimer(this);
    m_reconnectTimer->setSingleShot(true);
    connect(m_reconnectTimer, &QTimer::timeout,
            this, &CameraManager::onReconnectTick);

    m_healthTimer = new QTimer(this);
    m_healthTimer->setInterval(HEALTH_CHECK_INTERVAL_MS);
    connect(m_healthTimer, &QTimer::timeout,
            this, &CameraManager::onHealthTick);
}

CameraManager::~CameraManager()
{
    shutdown();
}

// ═══════════════════════════════════════════════════════════════

bool CameraManager::connectFirstAvailable()
{
    // Use plain try/catch (NOT SEH __try/__except) — nesting SEH inside RVC
    // SDK calls can interfere with the SDK's own internal exception handling
    // and cause 0xC0000005 to propagate uncaught.

    if (!m_impl->systemInited) {
        try {
            if (!RVC::SystemInit()) {
                emit cameraError(QStringLiteral("RVC 系统初始化失败"));
                return false;
            }
            m_impl->systemInited = true;
        } catch (const std::exception& e) {
            emit cameraError(QStringLiteral("RVC 系统初始化异常: %1").arg(e.what()));
            return false;
        } catch (...) {
            emit cameraError(QStringLiteral("RVC SDK 初始化时发生未知崩溃"));
            return false;
        }
    }

    RVC::Device devices[10];
    size_t count = 0;
    try {
        if (RVC::SystemListDevices(devices, 10, &count,
                                    RVC::SystemListDeviceType::All) != 0 || count == 0) {
            emit cameraError(QStringLiteral("未找到任何相机设备"));
            return false;
        }
    } catch (const std::exception& e) {
        emit cameraError(QStringLiteral("设备枚举异常: %1").arg(e.what()));
        return false;
    } catch (...) {
        emit cameraError(QStringLiteral("设备枚举时发生未知崩溃"));
        return false;
    }

    // Collect device info with try/catch protection per device
    struct Found { char sn[32] = {}; bool x1 = false; bool x2 = false; };
    Found found[10];
    int nFound = 0;

    for (size_t i = 0; i < count && nFound < 10; ++i) {
        try {
            RVC::DeviceInfo info;
            if (!devices[i].GetDeviceInfo(&info)) continue;
            strncpy(found[nFound].sn, info.sn, 31);
            found[nFound].x1 = info.support_x1;
            found[nFound].x2 = info.support_x2;
            ++nFound;
        } catch (...) {
            continue;  // skip devices that crash during enumeration
        }
    }

    auto tryConnect = [this](const char* sn) -> bool {
        return initWithDeviceSerial(QString::fromLocal8Bit(sn));
    };

    // Prefer X1 first, then fall back to X2
    for (int i = 0; i < nFound; ++i) {
        if (found[i].x1 && tryConnect(found[i].sn))
            return true;
    }
    for (int i = 0; i < nFound; ++i) {
        if (found[i].x2 && tryConnect(found[i].sn))
            return true;
    }

    emit cameraError(QStringLiteral("无法连接任何相机设备"));
    return false;
}

std::vector<DeviceEntry> CameraManager::listDevices()
{
    // Init the RVC system once.  Use plain try/catch, NOT SEH: nesting SEH
    // inside RVC SDK calls can interfere with the SDK's own exception handling
    // and let 0xC0000005 escape uncaught (see connectFirstAvailable).
    if (!m_impl->systemInited) {
        try {
            if (!RVC::SystemInit()) {
                emit cameraError(QStringLiteral("RVC 系统初始化失败"));
                return {};
            }
            m_impl->systemInited = true;
        } catch (const std::exception& e) {
            emit cameraError(QStringLiteral("RVC 系统初始化异常: %1").arg(e.what()));
            return {};
        } catch (...) {
            emit cameraError(QStringLiteral("RVC SDK 初始化时发生未知崩溃"));
            return {};
        }
    }

    RVC::Device devices[10];
    size_t count = 0;
    try {
        if (RVC::SystemListDevices(devices, 10, &count,
                                    RVC::SystemListDeviceType::All) != 0 || count == 0)
            return {};
    } catch (const std::exception& e) {
        emit cameraError(QStringLiteral("设备枚举异常: %1").arg(e.what()));
        return {};
    } catch (...) {
        emit cameraError(QStringLiteral("设备枚举时发生未知崩溃"));
        return {};
    }

    const size_t n = (count > 10) ? 10 : count;
    std::vector<DeviceEntry> result;
    result.reserve(n);
    m_impl->scannedDevices.clear();
    m_impl->scannedInfos.clear();

    for (size_t i = 0; i < n; ++i) {
        try {
            RVC::DeviceInfo info;
            if (!devices[i].GetDeviceInfo(&info))
                continue;
            if (info.name[0] == '\0' && info.sn[0] == '\0')
                continue;

            DeviceEntry entry;
            entry.name   = QString::fromLocal8Bit(info.name);
            entry.serial = QString::fromLocal8Bit(info.sn);
            entry.isX1   = info.support_x1;
            entry.isX2   = info.support_x2;

            // GigE "in use" check.  A failure here must NOT drop the device
            // from the list — report it as available instead.
            if (info.type == RVC::PortType_GIGE) {
                try {
                    int status = 0;
                    RVC::NetworkType ntype;
                    char ip[32] = {}, mask[32] = {}, gw[32] = {};
                    if (devices[i].GetNetworkConfig(RVC::NetworkDevice_LeftCamera, &ntype,
                                                    ip, mask, gw, &status) == 0)
                        entry.occupied = (status == RVC::NetworkDeviceStatus_In_Use);
                } catch (...) {
                    // ignore — keep the device listed as available
                }
            }
            m_impl->scannedDevices.push_back(devices[i]);
            m_impl->scannedInfos.push_back(info);
            result.push_back(entry);
        } catch (...) {
            continue;  // skip devices that crash during enumeration
        }
    }
    return result;
}

void CameraManager::scanDevicesAsync(std::function<void(std::vector<DeviceEntry>)> onDone)
{
    m_scanDone = std::move(onDone);
    m_scanBusy = true;
    m_scanStartMs = QDateTime::currentMSecsSinceEpoch();
    m_scanWatcher->setFuture(QtConcurrent::run([this]() { return listDevices(); }));
}

void CameraManager::prewarmSystem()
{
    if (m_impl->systemInited || m_shuttingDown)
        return;
    QElapsedTimer t;
    t.start();
    try {
        if (RVC::SystemInit()) {
            m_impl->systemInited = true;
            RuntimeLog::log("RVC::SystemInit OK (%lld ms)", t.elapsed());
        } else {
            RuntimeLog::log("RVC::SystemInit returned false");
        }
    } catch (const std::exception& e) {
        RuntimeLog::log("RVC::SystemInit exception: %s", e.what());
    } catch (...) {
        RuntimeLog::log("RVC::SystemInit unknown crash");
    }
}

void CameraManager::onScanFinished()
{
    m_scanBusy = false;
    const auto devices = m_scanWatcher->result();
    RuntimeLog::log("scan finished: %zu device(s) in %lld ms",
                    devices.size(),
                    QDateTime::currentMSecsSinceEpoch() - m_scanStartMs);
    if (!m_scanDone) return;
    auto cb = std::move(m_scanDone);
    m_scanDone = {};
    cb(devices);
}

bool CameraManager::initWithDeviceSerial(const QString& serial)
{
    QElapsedTimer connectTimer;
    connectTimer.start();
    if (!m_impl->systemInited) {
        try {
            RVC::SystemInit();
            m_impl->systemInited = true;
            RuntimeLog::log("RVC::SystemInit OK (deferred)");
        } catch (const std::exception& e) {
            RuntimeLog::log("RVC::SystemInit failed: %s", e.what());
            emit cameraError(QStringLiteral("RVC 系统初始化失败: %1").arg(e.what()));
            return false;
        } catch (...) {
            RuntimeLog::log("RVC::SystemInit crashed");
            emit cameraError(QStringLiteral("RVC 系统初始化崩溃"));
            return false;
        }
    }

    if (m_isConnected)
        shutdown();

    // Prefer the device handle cached by the last scan — SystemFindDevice()
    // re-scans the bus and is noticeably slower.
    RVC::Device device;
    bool haveDevice = false;
    for (size_t i = 0; i < m_impl->scannedInfos.size(); ++i) {
        if (QString::fromLocal8Bit(m_impl->scannedInfos[i].sn) == serial) {
            device = m_impl->scannedDevices[i];
            haveDevice = true;
            break;
        }
    }
    if (!haveDevice) {
        auto snBytes = serial.toUtf8();
        device = RVC::SystemFindDevice(snBytes.constData());
    }
    if (!device.IsValid()) {
        emit cameraError(QStringLiteral("未找到指定设备: %1").arg(serial));
        return false;
    }

    RVC::DeviceInfo info;
    if (!device.GetDeviceInfo(&info)) {
        emit cameraError(QStringLiteral("无法获取设备信息"));
        return false;
    }
    m_impl->devInfo = info;

    // Use device info to determine model — no trial-and-error.
    // For dual-mode devices (both X1 & X2), prefer X1, fall back to X2.
    bool canX1 = info.support_x1;
    bool canX2 = info.support_x2;

    if (!canX1 && !canX2) {
        emit cameraError(QStringLiteral("设备不支持 X1 或 X2 接口"));
        return false;
    }

    // Buffer per-attempt failures and emit a single message at the end, so
    // X1 -> X2 fallback does not spam the UI with intermediate errors.
    QString lastError;

    // Helper to try connecting as a specific model
    auto tryConnectX1 = [&]() -> bool {
        try {
            m_impl->x1 = RVC::X1::Create(device, RVC::CameraID_Left);
            if (!m_impl->x1.Open()) {
                lastError = QStringLiteral("打开 X1 相机失败，请检查连接");
                RVC::X1::Destroy(m_impl->x1);
                return false;
            }
            if (!m_impl->x1.LoadCaptureOptionParameters(m_impl->capOptsX1))
                m_impl->capOptsX1 = RVC::X1::CaptureOptions{};

            m_cameraId = RVC::CameraID_Left;
            m_impl->capOptsX1.transform_to_camera = true;

            float imat[9] = {}, idist[5] = {};
            if (m_impl->x1.GetIntrinsicParameters(imat, idist)) {
                m_intrinsicMatrix.assign(imat, imat + 9);
                m_distortion.assign(idist, idist + 5);
                fprintf(stderr, "[CameraManager] X1 intrinsics loaded: fx=%.2f fy=%.2f cx=%.2f cy=%.2f\n",
                        imat[0], imat[4], imat[2], imat[5]);
            } else {
                fprintf(stderr, "[CameraManager] WARNING: X1 GetIntrinsicParameters failed!\n");
            }
            m_impl->model = CameraModel::X1;
            return true;
        } catch (const std::exception& e) {
            lastError = QStringLiteral("X1 连接异常: %1").arg(e.what());
            return false;
        } catch (...) {
            lastError = QStringLiteral("X1 连接过程中发生未知崩溃");
            return false;
        }
    };

    auto tryConnectX2 = [&]() -> bool {
        try {
            m_impl->x2 = RVC::X2::Create(device);
            if (!m_impl->x2.Open()) {
                lastError = QStringLiteral("打开 X2 相机失败，请检查连接");
                RVC::X2::Destroy(m_impl->x2);
                return false;
            }
            if (!m_impl->x2.LoadCaptureOptionParameters(m_impl->capOptsX2))
                m_impl->capOptsX2 = RVC::X2::CaptureOptions{};

            // Prefer a full-frame capture mode for static calibration scenes.
            // The camera's saved mode may be a line-scan mode (SwingLineScan
            // etc.) which only produces a thin strip — or no depth at all.
            const int supported = static_cast<int>(info.support_capture_mode);
            const int preferred[] = {
                RVC::CaptureMode_Ultra,
                RVC::CaptureMode_Normal,
                RVC::CaptureMode_Fast,
                RVC::CaptureMode_AntiInterReflection,
                RVC::CaptureMode_Robust
            };
            int chosen = static_cast<int>(m_impl->capOptsX2.capture_mode);
            if ((chosen & supported) == 0)
                chosen = 0;
            for (int m : preferred) {
                if (m & supported) {
                    chosen = m;
                    break;
                }
            }
            if (chosen != static_cast<int>(m_impl->capOptsX2.capture_mode)) {
                fprintf(stderr, "[CameraManager] capture mode %d -> %d (supported=%d)\n",
                        static_cast<int>(m_impl->capOptsX2.capture_mode), chosen, supported);
                m_impl->capOptsX2.capture_mode = static_cast<RVC::CaptureMode>(chosen);
            }

            m_cameraId = info.support_extra ? RVC::CameraID_Extra : RVC::CameraID_Left;
            m_impl->capOptsX2.transform_to_camera = static_cast<RVC::CameraID>(m_cameraId);

            float imat[9] = {}, idist[5] = {};
            if (m_impl->x2.GetIntrinsicParameters(static_cast<RVC::CameraID>(m_cameraId), imat, idist)) {
                m_intrinsicMatrix.assign(imat, imat + 9);
                m_distortion.assign(idist, idist + 5);
                fprintf(stderr, "[CameraManager] X2 intrinsics loaded: fx=%.2f fy=%.2f cx=%.2f cy=%.2f\n",
                        imat[0], imat[4], imat[2], imat[5]);
            } else {
                fprintf(stderr, "[CameraManager] WARNING: X2 GetIntrinsicParameters failed!\n");
            }
            m_impl->model = CameraModel::X2;
            return true;
        } catch (const std::exception& e) {
            lastError = QStringLiteral("X2 连接异常: %1").arg(e.what());
            return false;
        } catch (...) {
            lastError = QStringLiteral("X2 连接过程中发生未知崩溃");
            return false;
        }
    };

    // Re-apply the operator's saved exposure/gain after Open() (which resets
    // capture options to the camera's stored values).  Must happen before
    // cameraConnected so the very first preview already uses them.
    auto applySavedParams = [this]() {
        for (auto it = m_paramsOnConnect.constBegin();
             it != m_paramsOnConnect.constEnd(); ++it) {
            setParameter(it.key(), it.value().toFloat());
        }
    };

    // Prefer X1 for dual-mode devices
    if (canX1 && tryConnectX1()) {
        m_isConnected = true;
        m_lastSerial = serial;
        m_reconnectAttempts = 0;
        applySavedParams();
        RuntimeLog::log("connect OK: %s (X1, %lld ms)",
                        qPrintable(serial), connectTimer.elapsed());
        // Timers must be started from their owning (UI) thread; queue it so
        // this works whether connect runs on the UI or a worker thread.
        QMetaObject::invokeMethod(this, [this]() { m_healthTimer->start(); },
                                  Qt::QueuedConnection);
        emit cameraConnected();
        return true;
    }
    if (canX2 && tryConnectX2()) {
        m_isConnected = true;
        m_lastSerial = serial;
        m_reconnectAttempts = 0;
        applySavedParams();
        RuntimeLog::log("connect OK: %s (X2, %lld ms)",
                        qPrintable(serial), connectTimer.elapsed());
        QMetaObject::invokeMethod(this, [this]() { m_healthTimer->start(); },
                                  Qt::QueuedConnection);
        emit cameraConnected();
        return true;
    }

    // Single failure message (fallback attempts are buffered in lastError).
    RuntimeLog::log("connect FAILED: %s (%lld ms) lastError=%s",
                    qPrintable(serial), connectTimer.elapsed(),
                    qPrintable(lastError));
    emit cameraError(lastError.isEmpty() ? QStringLiteral("无法连接相机设备") : lastError);
    return false;
}

void CameraManager::shutdown()
{
    if (m_shuttingDown) return;
    m_shuttingDown = true;

    stopPreview();
    // Wait for any in-flight preview frame before closing the device objects.
    const auto waitDeadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (m_previewBusy && std::chrono::steady_clock::now() < waitDeadline) {
        QThread::msleep(5);
        QCoreApplication::processEvents(QEventLoop::AllEvents, 50);
    }
    m_captureWatchdog->stop();
    m_reconnectTimer->stop();
    m_healthTimer->stop();
    m_reconnectAttempts = 0;
    m_impl->scannedDevices.clear();
    m_impl->scannedInfos.clear();

    // Let any in-flight health check finish before tearing down the RVC
    // system: SystemFindDevice (pool thread) must not run concurrently with
    // SystemShutdown (this thread).
    const auto workerDeadline = std::chrono::steady_clock::now() + std::chrono::seconds(6);
    while ((m_healthBusy.load() || m_scanBusy.load() || m_captureInProgress)
           && std::chrono::steady_clock::now() < workerDeadline) {
        QThread::msleep(10);
        QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
    }

    // If a capture worker is still running, ignore its late result and do
    // not touch the device objects concurrently below.
    if (m_captureInProgress) {
        m_captureInProgress = false;
        m_captureTimedOut = true;
    }
    m_nativeMarkerPixels.clear();
    m_nativeMarkerPoints.clear();

    if (m_isConnected) {
        try {
            if (m_impl->isX2()) {
                if (m_impl->x2.IsOpen())
                    m_impl->x2.Close();
                RVC::X2::Destroy(m_impl->x2);
            } else if (m_impl->isX1()) {
                if (m_impl->x1.IsOpen())
                    m_impl->x1.Close();
                RVC::X1::Destroy(m_impl->x1);
            }
        } catch (...) {
            fprintf(stderr, "[CameraManager] Exception during camera shutdown\n");
        }
        m_impl->model = CameraModel::None;
    }
    if (m_impl->systemInited) {
        try {
            RVC::SystemShutdown();
        } catch (...) {
            fprintf(stderr, "[CameraManager] Exception during SystemShutdown\n");
        }
        m_impl->systemInited = false;
    }
    m_isConnected = false;
    m_shuttingDown = false;
    emit cameraDisconnected();
}

bool CameraManager::isConnected() const { return m_isConnected; }

// ── Device info ──

QString CameraManager::deviceName() const
{
    return QStringLiteral("%1 - %2").arg(m_impl->devInfo.name, m_impl->devInfo.sn);
}

std::pair<std::vector<float>, std::vector<float>> CameraManager::intrinsics() const
{
    return {m_intrinsicMatrix, m_distortion};
}

bool CameraManager::lastGrid(std::vector<double>& xyzMm, int& w, int& h) const
{
    if (m_lastGrid.empty())
        return false;
    xyzMm = m_lastGrid;
    w = m_lastGridW;
    h = m_lastGridH;
    return true;
}

bool CameraManager::lastCorrespond(std::vector<double>& cmap, int& w, int& h) const
{
    if (m_lastCorrespond.empty())
        return false;
    cmap = m_lastCorrespond;
    w = m_lastCmW;
    h = m_lastCmH;
    return true;
}

bool CameraManager::lastGridAligned() const
{
    return m_lastGridAligned;
}

std::pair<std::vector<float>, std::vector<float>> CameraManager::nativeMarkerResult() const
{
    return {m_nativeMarkerPixels, m_nativeMarkerPoints};
}

// ═══════════════════════════════════════════════════════════════
// Preview
// ═══════════════════════════════════════════════════════════════

bool CameraManager::isStereo() const
{
    // X1 has no extra camera; X2 may or may not have it
    return m_impl->isX2() && m_impl->devInfo.support_extra;
}

bool CameraManager::isPreviewing() const
{
    return m_previewTimer->isActive();
}

void CameraManager::startPreview()
{
    if (!m_isConnected) return;
    m_previewPaused = false;
    // The timer is only a fallback kick for failed frames; successful frames
    // self-schedule the next capture in the completion handler.
    m_previewTimer->start(100);
}

void CameraManager::stopPreview()
{
    m_previewTimer->stop();
    ++m_previewGen;  // discard any in-flight frame from the previous session
}

void CameraManager::togglePreview()
{
    if (m_previewTimer->isActive())
        stopPreview();
    else
        startPreview();
}

void CameraManager::pausePreview()
{
    if (m_previewTimer->isActive()) {
        m_previewTimer->stop();
        m_previewPaused = true;
    }
}

void CameraManager::resumePreview()
{
    if (m_previewPaused && m_isConnected) {
        m_previewTimer->start(1000 / m_previewFps);
        m_previewPaused = false;
    }
}

void CameraManager::onPreviewTick()
{
    if (!m_isConnected || !m_impl->hasCamera() || m_previewBusy)
        return;

    m_previewBusy = true;
    const int gen = m_previewGen;

    // Capture2D runs in a pool thread so the UI event loop never blocks.
    QtConcurrent::run([this, gen]() {
        PreviewFrames frames;
        if (m_impl->isX1())
            frames = capturePreviewFrameX1();
        else if (m_impl->isX2())
            frames = capturePreviewFrameX2();

        QMetaObject::invokeMethod(this, [this, gen, frames]() {
            if (gen != m_previewGen) {
                m_previewBusy = false;  // stale frame after stop
                return;
            }
            m_previewBusy = false;
            if (!frames.left.isNull()) {
                emit previewFrameReady(frames.left);
                m_previewFailures = 0;
            } else if (++m_previewFailures >= 20) {
                // ~2 s of consecutive failures: the camera is probably gone.
                m_previewFailures = 0;
                emit cameraError(QStringLiteral("预览连续失败，相机可能已断开"));
                scheduleReconnect();
            }
            if (!frames.right.isNull())
                emit previewRightFrameReady(frames.right);
            // Self-schedule the next capture for maximum throughput; the
            // timer acts as a fallback kick when a frame fails.
            if (m_previewTimer->isActive() && !frames.left.isNull())
                onPreviewTick();
        }, Qt::QueuedConnection);
    });
}

CameraManager::PreviewFrames CameraManager::capturePreviewFrameX1()
{
    PreviewFrames out;
    try {
        if (!m_impl->x1.IsOpen()) return out;

        // Projector off: plain 2D preview is much faster than projector-aided
        // capture (the projector pattern is only needed for 3D capture).
        auto opts = m_impl->capOptsX1;
        opts.use_projector_capturing_2d_image = false;
        if (!m_impl->x1.Capture2D(opts))
            return out;

        RVC::Image img = m_impl->x1.GetImage();
        if (!img.IsValid()) return out;

        out.left = DetectionEngine::rvcToQImage(img);
        // X1 has no right camera — no stereo preview
    } catch (const std::exception& e) {
        emit cameraError(QStringLiteral("预览失败: %1").arg(e.what()));
    } catch (...) {
        emit cameraError(QStringLiteral("预览过程发生未知崩溃"));
    }
    return out;
}

CameraManager::PreviewFrames CameraManager::capturePreviewFrameX2()
{
    PreviewFrames out;
    try {
        if (!m_impl->x2.IsOpen()) return out;

        auto opts = m_impl->capOptsX2;
        opts.use_projector_capturing_2d_image = false;
        auto cid = static_cast<RVC::CameraID>(m_cameraId);
        if (!m_impl->x2.Capture2D(cid, opts))
            return out;

        RVC::Image img = m_impl->x2.GetImage(cid);
        if (!img.IsValid()) return out;

        out.left = DetectionEngine::rvcToQImage(img);

        // Stereo: also capture right camera view
        if (m_impl->devInfo.support_extra) {
            RVC::CameraID rightId = RVC::CameraID_Right;
            if (m_impl->x2.Capture2D(rightId, opts)) {
                RVC::Image rightImg = m_impl->x2.GetImage(rightId);
                if (rightImg.IsValid())
                    out.right = DetectionEngine::rvcToQImage(rightImg);
            }
        }
    } catch (const std::exception& e) {
        emit cameraError(QStringLiteral("预览失败: %1").arg(e.what()));
    } catch (...) {
        emit cameraError(QStringLiteral("预览过程发生未知崩溃"));
    }
    return out;
}

// ═══════════════════════════════════════════════════════════════
// Shared capture post-processing (called by both X1 and X2 paths).
// Runs inside the capture worker thread; results are carried back in
// CaptureResult and applied on the UI thread when the worker finishes.
static bool postProcessCapture(RVC::Image& img, RVC::PointMap& pm,
                               const QString& saveDir, int index,
                               CameraManager::CaptureResult& out,
                               bool gridAligned,
                               const std::vector<double>& correspondMap,
                               int cmW, int cmH)
{
    // Save temp files
    const QString tmpDir = QDir::tempPath() + QStringLiteral("/HandEyeCalib");
    QDir().mkpath(tmpDir);
    out.pngPath = QStringLiteral("%1/cap_%2.png").arg(tmpDir).arg(index);
    out.plyPath = QStringLiteral("%1/cap_%2.ply").arg(tmpDir).arg(index);

    if (!img.SaveImage(out.pngPath.toUtf8().constData()))
        return false;
    // Binary PLY (true): ASCII output takes seconds for 1.5M vertices.
    if (!pm.Save(out.plyPath.toUtf8().constData(), RVC::PointMapUnit::Millimeter, true))
        return false;

    // Keep the organized grid (image-ordered, mm) for pixel<->3D lookup.
    const RVC::Size pmSize = pm.GetSize();
    out.gridW = pmSize.width;
    out.gridH = pmSize.height;
    const std::size_t gridCount = static_cast<std::size_t>(out.gridW) * out.gridH;
    out.gridPoints.resize(gridCount * 3);
    if (gridCount > 0) {
        const double* pmData = pm.GetPointDataPtr();
        for (std::size_t i = 0; i < gridCount * 3; ++i)
            out.gridPoints[i] = pmData[i] * 1000.0;   // m -> mm
    }
    out.gridAligned = gridAligned;
    out.correspondMap = correspondMap;
    out.cmW = cmW;
    out.cmH = cmH;

    // In-memory native concentric circle detection (cached for the detect step)
    out.nativePixels.clear();
    out.nativePoints.clear();
    {
        int num = 0;
        double pixelXy[2000] = {};
        double pointXyz[3000] = {};
        int ret = RVC::DetectConcentricCircleMarker3d(img, pm, &num, pixelXy, pointXyz);
        if (ret == 0 && num > 0) {
            if (num > 1000) {
                num = 1000;  // clamp to fixed buffer capacity
                fprintf(stderr, "[CameraManager] WARNING: marker count clamped to 1000\n");
            }
            out.nativePixels.resize(static_cast<size_t>(num) * 2);
            out.nativePoints.resize(static_cast<size_t>(num) * 3);
            for (int i = 0; i < num; ++i) {
                out.nativePixels[i * 2]     = static_cast<float>(pixelXy[i * 2]);
                out.nativePixels[i * 2 + 1] = static_cast<float>(pixelXy[i * 2 + 1]);
                out.nativePoints[i * 3]     = static_cast<float>(pointXyz[i * 3] * 1000.0);
                out.nativePoints[i * 3 + 1] = static_cast<float>(pointXyz[i * 3 + 1] * 1000.0);
                out.nativePoints[i * 3 + 2] = static_cast<float>(pointXyz[i * 3 + 2] * 1000.0);
            }
        }
    }

    // Point cloud NaN/zero filtering + color extraction
    const int total = pm.GetSize().cols * pm.GetSize().rows;
    auto* pmData = pm.GetPointDataPtr();
    const int imgCh = (img.GetType() == RVC::ImageType::BGR8 || img.GetType() == RVC::ImageType::RGB8) ? 3 : 1;
    auto* imgData = reinterpret_cast<const uint8_t*>(img.GetDataPtr());

    PointCloudUtils::filterValidPoints(pmData, total, imgData, imgCh,
                                       out.points, out.colors);

    if (out.points.empty()) {
        fprintf(stderr, "[CameraManager] WARNING: captured point cloud is empty "
                        "(all NaN/zero) — check 3D exposure / capture mode\n");
    }

    out.image = DetectionEngine::rvcToQImage(img);
    return true;
}

// ── Full 3D capture (runs in a worker thread; UI stays responsive) ──

void CameraManager::captureFullFrame(const QString& saveDir, int index)
{
    if (!m_isConnected) {
        emit cameraError(QStringLiteral("相机未连接"));
        return;
    }
    if (m_captureInProgress)
        return;

    stopPreview();
    m_captureInProgress = true;
    m_captureTimedOut = false;
    m_captureStartMs = QDateTime::currentMSecsSinceEpoch();
    m_captureWatchdog->start(CAPTURE_TIMEOUT_MS);

    if (m_impl->isX1()) {
        m_captureWatcher->setFuture(QtConcurrent::run([this, saveDir, index]() {
            return captureFrameX1(saveDir, index);
        }));
    } else if (m_impl->isX2()) {
        m_captureWatcher->setFuture(QtConcurrent::run([this, saveDir, index]() {
            return captureFrameX2(saveDir, index);
        }));
    }
}

CameraManager::CaptureResult CameraManager::captureFrameX1(const QString& saveDir, int index)
{
    CaptureResult out;
    try {
        if (!m_impl->x1.IsOpen()) {
            out.error = QStringLiteral("X1 相机未就绪");
            return out;
        }
        // Wait for any in-flight preview frame off the UI thread (bounded).
        const auto waitDeadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
        while (m_previewBusy.load() && std::chrono::steady_clock::now() < waitDeadline)
            QThread::msleep(5);
        // Capture the 2D image with ambient lighting (no projector pattern),
        // matching what the user sees in the preview.  The projector is still
        // used for the 3D depth acquisition.
        auto opts = m_impl->capOptsX1;
        opts.use_projector_capturing_2d_image = false;
        if (!m_impl->x1.Capture(opts)) {
            out.error = QStringLiteral("3D采集失败: %1").arg(RVC::GetLastErrorMessage());
            return out;
        }
        RVC::Image img = m_impl->x1.GetImage();
        RVC::PointMap pm = m_impl->x1.GetPointMap();
        if (!img.IsValid() || !pm.IsValid()) {
            out.error = QStringLiteral("采集数据无效");
            return out;
        }
        if (!postProcessCapture(img, pm, saveDir, index, out,
                                /*gridAligned=*/true,
                                /*correspondMap=*/{}, 0, 0)) {
            out.error = QStringLiteral("PNG/PLY 临时保存失败");
            return out;
        }
        out.ok = true;
    } catch (const std::exception& e) {
        out.error = QStringLiteral("X1 采集过程异常: %1").arg(e.what());
    } catch (...) {
        out.error = QStringLiteral("X1 采集过程发生未知崩溃");
    }
    return out;
}

CameraManager::CaptureResult CameraManager::captureFrameX2(const QString& saveDir, int index)
{
    CaptureResult out;
    try {
        if (!m_impl->x2.IsOpen()) {
            out.error = QStringLiteral("X2 相机未就绪");
            return out;
        }
        // Wait for any in-flight preview frame off the UI thread (bounded).
        const auto waitDeadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
        while (m_previewBusy.load() && std::chrono::steady_clock::now() < waitDeadline)
            QThread::msleep(5);
        // Ambient-light 2D image (no projector pattern) to match the preview.
        auto opts = m_impl->capOptsX2;
        opts.use_projector_capturing_2d_image = false;
        if (!m_impl->x2.Capture(opts)) {
            out.error = QStringLiteral("3D采集失败: %1").arg(RVC::GetLastErrorMessage());
            return out;
        }
        auto cid = static_cast<RVC::CameraID>(m_cameraId);
        RVC::Image img = m_impl->x2.GetImage(cid);
        RVC::PointMap pm = m_impl->x2.GetPointMap();
        if (!img.IsValid() || !pm.IsValid()) {
            out.error = QStringLiteral("采集数据无效");
            return out;
        }
        const bool gridAligned =
            !(opts.capture_mode == RVC::CaptureMode_SwingLineScan && !opts.correspond2d);
        std::vector<double> cmap;
        int cmW = 0, cmH = 0;
        if (!gridAligned) {
            try {
                RVC::CorrespondMap cm = m_impl->x2.GetCorrespondMap();
                if (cm.IsValid()) {
                    const RVC::Size sz = cm.GetSize();
                    cmW = sz.width;
                    cmH = sz.height;
                    const double* data = cm.GetDataConstPtr();
                    if (data && cmW > 0 && cmH > 0)
                        cmap.assign(data,
                                    data + static_cast<std::size_t>(cmW) * cmH * 2);
                }
            } catch (...) {
                cmap.clear();
                cmW = cmH = 0;
            }
        }
        if (!postProcessCapture(img, pm, saveDir, index, out,
                                gridAligned, cmap, cmW, cmH)) {
            out.error = QStringLiteral("PNG/PLY 临时保存失败");
            return out;
        }
        out.ok = true;
    } catch (const std::exception& e) {
        out.error = QStringLiteral("X2 采集过程异常: %1").arg(e.what());
    } catch (...) {
        out.error = QStringLiteral("X2 采集过程发生未知崩溃");
    }
    return out;
}

void CameraManager::onCaptureFinished()
{
    m_captureWatchdog->stop();
    m_captureInProgress = false;

    if (m_captureTimedOut) {
        m_captureTimedOut = false;
        return;  // timeout already reported; late result ignored
    }

    const auto result = m_captureWatcher->result();
    const qint64 elapsed = QDateTime::currentMSecsSinceEpoch() - m_captureStartMs;
    if (!result.ok) {
        RuntimeLog::log("capture FAILED after %lld ms: %s",
                        elapsed, qPrintable(result.error));
        emit cameraError(result.error.isEmpty() ? QStringLiteral("采集失败") : result.error);
        scheduleReconnect();
        return;
    }

    // Apply native detection cache on the UI thread (written by the worker).
    m_nativeMarkerPixels = result.nativePixels;
    m_nativeMarkerPoints = result.nativePoints;
    m_lastGrid = result.gridPoints;
    m_lastGridW = result.gridW;
    m_lastGridH = result.gridH;
    m_lastCorrespond = result.correspondMap;
    m_lastCmW = result.cmW;
    m_lastCmH = result.cmH;
    m_lastGridAligned = result.gridAligned;
    RuntimeLog::log("capture OK: %zu points in %lld ms (png=%s ply=%s)",
                    result.points.size() / 3, elapsed,
                    qPrintable(QFileInfo(result.pngPath).fileName()),
                    qPrintable(QFileInfo(result.plyPath).fileName()));
    emit captureComplete(result.pngPath, result.plyPath,
                         result.points, result.colors, result.image);
}

void CameraManager::onCaptureTimeout()
{
    if (!m_captureInProgress) return;
    m_captureInProgress = false;
    m_captureTimedOut = true;
    RuntimeLog::log("capture TIMEOUT after %lld ms (SDK may be hung)",
                    QDateTime::currentMSecsSinceEpoch() - m_captureStartMs);
    // NOTE: a truly hung SDK call cannot be killed; the pool thread stays
    // blocked.  The UI recovers and late results are ignored.
    emit cameraError(QStringLiteral("采集超时（%1 秒），请检查相机状态")
                         .arg(CAPTURE_TIMEOUT_MS / 1000));
}

// ── Auto-reconnect / hot-plug ─────────────────────────────────────────

void CameraManager::scheduleReconnect()
{
    if (m_shuttingDown || !m_isConnected || m_reconnectTimer->isActive())
        return;

    if (m_reconnectAttempts >= RECONNECT_MAX_ATTEMPTS) {
        m_reconnectAttempts = 0;
        emit cameraError(QStringLiteral("自动重连失败（%1 次），请手动重新连接")
                             .arg(RECONNECT_MAX_ATTEMPTS));
        return;
    }

    m_wasPreviewing = m_previewTimer->isActive() || m_previewPaused;
    stopPreview();
    ++m_reconnectAttempts;
    emit cameraError(QStringLiteral("检测到相机异常，尝试自动重连 (%1/%2)")
                         .arg(m_reconnectAttempts).arg(RECONNECT_MAX_ATTEMPTS));
    m_reconnectTimer->start(RECONNECT_INTERVAL_MS);
}

void CameraManager::onReconnectTick()
{
    if (m_shuttingDown || !m_isConnected || m_lastSerial.isEmpty())
        return;

    // RVC camera objects must live on the UI thread (preview runs there), so
    // reconnect happens synchronously on this (UI) thread as well.
    const bool ok = initWithDeviceSerial(m_lastSerial);
    if (ok) {
        m_reconnectAttempts = 0;
        if (m_wasPreviewing)
            startPreview();
    } else {
        scheduleReconnect();
    }
}

void CameraManager::onHealthTick()
{
    if (m_shuttingDown || !m_isConnected || m_lastSerial.isEmpty())
        return;
    // SystemFindDevice re-scans the bus and can block for seconds; skip it
    // while the preview or a capture is running (a lost camera then shows up
    // as preview/capture failures), and never run it on the UI thread.
    if (m_previewTimer->isActive() || m_previewBusy || m_captureInProgress)
        return;
    if (m_healthBusy.load())
        return;
    m_healthBusy = true;

    const QString serial = m_lastSerial;
    QtConcurrent::run([this, serial]() {
        bool valid = false;
        try {
            RVC::Device dev = RVC::SystemFindDevice(serial.toUtf8().constData());
            valid = dev.IsValid();
        } catch (...) {
            // transient SDK issue — treat as unknown, keep current state
        }
        QMetaObject::invokeMethod(this, [this, valid]() {
            m_healthBusy = false;
            if (!valid && m_isConnected && !m_shuttingDown)
                scheduleReconnect();
        }, Qt::QueuedConnection);
    });
}
// Parameter setters
// ═══════════════════════════════════════════════════════════════

void CameraManager::setParamsOnConnect(const QVariantMap& params)
{
    m_paramsOnConnect = params;
}

void CameraManager::setExposure2D(float ms) {
    if (m_impl->isX1())      m_impl->capOptsX1.exposure_time_2d = static_cast<int>(ms);
    else if (m_impl->isX2()) m_impl->capOptsX2.exposure_time_2d = static_cast<int>(ms);
}

void CameraManager::setExposure3D(float ms) {
    if (m_impl->isX1())      m_impl->capOptsX1.exposure_time_3d = static_cast<int>(ms);
    else if (m_impl->isX2()) m_impl->capOptsX2.exposure_time_3d = static_cast<int>(ms);
}

void CameraManager::setGain2D(float value) {
    if (m_impl->isX1())      m_impl->capOptsX1.gain_2d = value;
    else if (m_impl->isX2()) m_impl->capOptsX2.gain_2d = value;
}

void CameraManager::setGain3D(float value) {
    if (m_impl->isX1())      m_impl->capOptsX1.gain_3d = value;
    else if (m_impl->isX2()) m_impl->capOptsX2.gain_3d = value;
}

void CameraManager::setGamma2D(float value) {
    if (m_impl->isX1())      m_impl->capOptsX1.gamma_2d = value;
    else if (m_impl->isX2()) m_impl->capOptsX2.gamma_2d = value;
}

void CameraManager::setGamma3D(float value) {
    if (m_impl->isX1())      m_impl->capOptsX1.gamma_3d = value;
    else if (m_impl->isX2()) m_impl->capOptsX2.gamma_3d = value;
}

void CameraManager::setLineScannerExposureUs(float us) {
    // Line-scan exposure only exists on X2 cameras.
    if (m_impl->isX2())
        m_impl->capOptsX2.line_scanner_exposure_time_us = static_cast<int>(us);
}

void CameraManager::setParameter(const QString& key, float value)
{
    // Clamp to the sane per-key range before applying (defense in depth).
    const auto range = cameraParamRange(key);
    if (range.first != range.second)
        value = std::clamp(value, range.first, range.second);

    if (key == "exposure_time_2d")       setExposure2D(value);
    else if (key == "exposure_time_3d")  setExposure3D(value);
    else if (key == "gain_2d")           setGain2D(value);
    else if (key == "gain_3d")           setGain3D(value);
    else if (key == "line_scanner_exposure_time_us")
        setLineScannerExposureUs(value);
}

std::pair<float, float> CameraManager::cameraParamRange(const QString& key)
{
    if (key == QStringLiteral("exposure_time_2d") || key == QStringLiteral("exposure_time_3d"))
        return { 0.1f, 200.0f };   // ms
    if (key == QStringLiteral("gain_2d") || key == QStringLiteral("gain_3d"))
        return { 0.0f, 48.0f };    // dB
    if (key == QStringLiteral("line_scanner_exposure_time_us"))
        return { 1.0f, 10000.0f }; // us
    return { 0.0f, 0.0f };         // unknown -> no clamp
}

QMap<QString, float> CameraManager::currentSettings() const
{
    if (m_impl->isX1()) {
        const auto& o = m_impl->capOptsX1;
        return {
            {"exposure_time_2d", (float)o.exposure_time_2d},
            {"exposure_time_3d", (float)o.exposure_time_3d},
            {"gain_2d", o.gain_2d},
            {"gain_3d", o.gain_3d},
        };
    } else {
        const auto& o = m_impl->capOptsX2;
        QMap<QString, float> s;
        s["exposure_time_2d"] = (float)o.exposure_time_2d;
        s["gain_2d"] = o.gain_2d;
        // In swing line-scan mode the relevant 3D exposure is the per-line
        // exposure time; otherwise it is the frame 3D exposure.
        if (o.capture_mode == RVC::CaptureMode_SwingLineScan)
            s["line_scanner_exposure_time_us"] = (float)o.line_scanner_exposure_time_us;
        else
            s["exposure_time_3d"] = (float)o.exposure_time_3d;
        s["gain_3d"] = o.gain_3d;
        return s;
    }
}
