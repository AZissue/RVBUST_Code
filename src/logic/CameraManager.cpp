#include "logic/CameraManager.h"
#include "logic/CameraParamPolicy.h"
#include "logic/CameraRelease.h"
#include "logic/CrashInject.h"
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
#define PSAPI_VERSION 2   // K32GetProcessMemoryInfo lives in kernel32
#include <psapi.h>
#include <QtConcurrent/QtConcurrentRun>
#include <QCoreApplication>
#include <QDateTime>
#include <QElapsedTimer>
#include <QThread>
#include <QTimer>
#include <chrono>

// ── In-process memory trace (D2) ──
//
// The acceptance criterion for the buffer work is a working-set delta over a
// fixed operation sequence, so log the process figures next to the payload
// sizes at each hand-off.  That gives the before/after comparison directly
// from the runtime log.
static void logMemoryTrace(const char* tag, std::size_t payloadBytes)
{
    PROCESS_MEMORY_COUNTERS pmc{};
    DWORD handles = 0;
    const bool haveMem =
        GetProcessMemoryInfo(GetCurrentProcess(), &pmc, sizeof(pmc)) != 0;
    GetProcessHandleCount(GetCurrentProcess(), &handles);
    if (haveMem) {
        RuntimeLog::log("[MEM] %s: working_set=%.1f MB peak=%.1f MB handles=%lu payload=%.1f MB",
                        tag,
                        pmc.WorkingSetSize / 1048576.0,
                        pmc.PeakWorkingSetSize / 1048576.0,
                        static_cast<unsigned long>(handles),
                        payloadBytes / 1048576.0);
    } else {
        RuntimeLog::log("[MEM] %s: handles=%lu payload=%.1f MB (working set unavailable)",
                        tag, static_cast<unsigned long>(handles),
                        payloadBytes / 1048576.0);
    }
}

// QVariantMap (config / QVariant storage) -> the plain float map the pure
// parameter policy works on.
static QMap<QString, float> toFloatMap(const QVariantMap& in)
{
    QMap<QString, float> out;
    for (auto it = in.constBegin(); it != in.constEnd(); ++it)
        out.insert(it.key(), it.value().toFloat());
    return out;
}

// GigE "In Use" flag — the hard evidence for "上一次没释放干净 / 被别的程序占着",
// which is what decides whether a connect retry can help (任务 3.3).
static bool deviceInUse(RVC::Device& dev, const RVC::DeviceInfo& info)
{
    if (info.type != RVC::PortType_GIGE)
        return false;
    try {
        int status = 0;
        RVC::NetworkType ntype;
        char ip[32] = {}, mask[32] = {}, gw[32] = {};
        if (dev.GetNetworkConfig(RVC::NetworkDevice_LeftCamera, &ntype,
                                 ip, mask, gw, &status) == 0)
            return status == RVC::NetworkDeviceStatus_In_Use;
    } catch (...) {
        // unknown — treat as not occupied rather than blocking a retry
    }
    return false;
}

// ── PIMPL: hide RVC::X1 / RVC::X2 + CaptureOptions ──

struct CameraManager::RvcImpl {
    CameraModel model = CameraModel::None;

    RVC::X1 x1;
    RVC::X2 x2;
    RVC::X1::CaptureOptions capOptsX1;
    RVC::X2::CaptureOptions capOptsX2;

    // Set once by ~CameraManager().  shutdown() refuses to re-arm the worker
    // token afterwards, so a late worker can never touch a half-destroyed
    // CameraManager.
    bool destroying = false;

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

// ── D1: the one gate every RVC call goes through ──
//
// `who`       : static tag for the runtime log ("capture", "preview-x2", ...)
// `previewGen`: >= 0 marks a preview round.  The round remembers the yield
//               generation it started with; if a capture has bumped it by the
//               time the lock is granted, the round gives the device up again
//               instead of finishing its frame (that is the "让位" the D1 fix
//               requires).  < 0 marks the capturing/shutdown side, which never
//               abandons.
// `timeout`   : zero = wait indefinitely (deterministic); non-zero = bounded
//               try, used only by shutdown(), which must not hang the close
//               path.  When the try fails the caller MUST NOT touch the device.
class CameraManager::DeviceLock {
public:
    DeviceLock(CameraManager* mgr, const char* who, int previewGen = -1,
               std::chrono::milliseconds timeout = std::chrono::milliseconds(0))
        : m_mgr(mgr), m_who(who), m_lock(mgr->m_rvcMutex, std::defer_lock)
    {
        const auto t0 = std::chrono::steady_clock::now();
        if (timeout.count() > 0) {
            m_ok = m_lock.try_lock_for(timeout);
        } else {
            m_lock.lock();
            m_ok = true;
        }
        const qint64 waited = std::chrono::duration_cast<std::chrono::milliseconds>(
                                  std::chrono::steady_clock::now() - t0).count();

        if (!m_ok) {
            RuntimeLog::log("[DEV] %s: device still busy after %lld ms — "
                            "NOT entering (no concurrent device access)",
                            m_who, waited);
            return;
        }

        if (previewGen >= 0 && previewGen != m_mgr->m_deviceYieldGen.load()) {
            // A capture requested the device while this preview round was
            // waiting for the lock: abandon the round and release immediately.
            m_mgr->m_previewAbandonCount.fetch_add(1);
            m_lock.unlock();
            m_ok = false;
            m_abandoned = true;
            return;
        }

        m_mgr->m_lastDeviceWaitMs = waited;
        // Preview rounds run ~20x/s — only log the ones that actually had to
        // wait, so the log stays readable.  Capture/shutdown always log.
        if (previewGen < 0 || waited >= 50) {
            RuntimeLog::log("[DEV] %s acquired device after %lld ms "
                            "(preview yields so far=%d, was_previewing=%d)",
                            m_who, waited, m_mgr->m_previewAbandonCount.load(),
                            previewGen >= 0 ? 1 : 0);
        }
    }

    ~DeviceLock()
    {
        if (m_ok && m_lock.owns_lock())
            m_lock.unlock();
    }

    bool ok() const { return m_ok; }
    bool abandoned() const { return m_abandoned; }

private:
    CameraManager* m_mgr;
    const char* m_who;
    std::unique_lock<std::recursive_timed_mutex> m_lock;
    bool m_ok = false;
    bool m_abandoned = false;
};

// ── Constructor / Destructor ──

CameraManager::CameraManager(QObject* parent)
    : QObject(parent)
    , m_previewTimer(new QTimer(this))
    , m_scanWatcher(new QFutureWatcher<std::vector<DeviceEntry>>(this))
    , m_captureWatcher(new QFutureWatcher<CaptureResult>(this))
    , m_captureWatchdog(new QTimer(this))
    , m_impl(std::make_unique<RvcImpl>())
    , m_workerToken(std::make_shared<WorkerToken>())
{
    qRegisterMetaType<FrameBuffer::FloatBuf>("FrameBuffer::FloatBuf");
    qRegisterMetaType<FrameBuffer::DoubleBuf>("FrameBuffer::DoubleBuf");
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
    // Order matters: flag the destruction first so shutdown() does not re-arm
    // the worker token and so a worker that is queued-but-not-started bails out
    // before it dereferences `this`.
    m_impl->destroying = true;
    if (m_workerToken)
        m_workerToken->cancelRequested = true;
    shutdown();
    m_impl.reset();
}

// ═══════════════════════════════════════════════════════════════

bool CameraManager::connectFirstAvailable()
{
    // Use plain try/catch (NOT SEH __try/__except) — nesting SEH inside RVC
    // SDK calls can interfere with the SDK's own internal exception handling
    // and cause 0xC0000005 to propagate uncaught.

    // Enumerating and opening a device are RVC calls too: serialize them.
    DeviceLock lk(this, "connect-first");
    if (!lk.ok())
        return false;

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
    // Runs on a pool thread (scanDevicesAsync); the enumeration and the
    // GetDeviceInfo/GetNetworkConfig calls below are RVC calls and must not
    // overlap a preview or capture transaction on another thread.
    DeviceLock lk(this, "scan");
    if (!lk.ok())
        return {};

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
    DeviceLock lk(this, "prewarm");
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

    // Create/Open/Close/Destroy plus the intrinsic read are device calls.  The
    // lock is recursive because this function re-enters through shutdown()
    // when a device is already connected.
    DeviceLock lk(this, "connect");
    if (!lk.ok()) {
        emit cameraError(QStringLiteral("相机设备忙，请稍后重试"));
        return false;
    }

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
            // 任务 1: remember the values the *camera* holds, before anything can
            // overwrite the capture options.
            m_cameraRead = currentSettings();
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
            applyPreferredCaptureMode(static_cast<int>(info.support_capture_mode));

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
            // 任务 1: the device's own values, read after the capture-mode fix so
            // the reported 3D exposure key matches the mode actually in use.
            m_cameraRead = currentSettings();
            return true;
        } catch (const std::exception& e) {
            lastError = QStringLiteral("X2 连接异常: %1").arg(e.what());
            return false;
        } catch (...) {
            lastError = QStringLiteral("X2 连接过程中发生未知崩溃");
            return false;
        }
    };

    // One full connect attempt: X1 first for dual-mode devices, then X2.  The
    // winning model name is handed back so the caller can finish the session
    // with it — before the retry loop was introduced this was the `if (canX1 &&
    // tryConnectX1()) { ... }` body, and dropping the call here left a
    // successfully opened device without ever entering the connected state.
    auto attemptConnect = [&](const char*& model) -> bool {
        if (canX1 && tryConnectX1()) { model = "X1"; return true; }
        if (canX2 && tryConnectX2()) { model = "X2"; return true; }
        return false;
    };

    auto finishConnect = [&](const char* model) -> bool {
        m_isConnected = true;
        m_released = false;            // a new session must be releasable again
        m_lastSerial = serial;
        m_reconnectAttempts = 0;
        applyConnectParams();
        RuntimeLog::log("connect OK: %s (%s, %lld ms)",
                        qPrintable(serial), model, connectTimer.elapsed());
        // Timers must be started from their owning (UI) thread; queue it so
        // this works whether connect runs on the UI or a worker thread.
        QMetaObject::invokeMethod(this, [this]() { m_healthTimer->start(); },
                                  Qt::QueuedConnection);
        emit cameraConnected();
        // 崩溃注入 (TEST ONLY): HEC_CRASH_INJECT=after-connect.  Placed after the
        // emit so the acceptance test crashes with a fully "connected" GUI.
        CrashInject::hitIfEnabled(CrashInject::Point::AfterConnect);
        return true;
    };

    // ── Bounded connect retry (任务 3.3) ──
    // A device that is still held by a previous, not-quite-released process is
    // the common field failure, and it clears by itself after a moment.  Retry
    // only when that can actually help: an unplugged camera or an unsupported
    // model will not come back after 3 s of waiting.
    int retriesTried = 0;
    const std::vector<int> retryDelays =
        CameraRelease::connectRetryDelaysMs(m_connectRetryCount);
    for (;;) {
        const char* model = nullptr;
        if (attemptConnect(model))
            return finishConnect(model);

        const auto failure = CameraRelease::classify(
            lastError, /*deviceFound=*/true, deviceInUse(device, info));
        if (retriesTried >= static_cast<int>(retryDelays.size())
                || !CameraRelease::shouldRetry(failure)) {
            RuntimeLog::log("connect FAILED: %s (%lld ms, %d retr%s, failure=%d) lastError=%s",
                            qPrintable(serial), connectTimer.elapsed(),
                            retriesTried, retriesTried == 1 ? "y" : "ies",
                            static_cast<int>(failure), qPrintable(lastError));
            // Readable recovery advice instead of a bare SDK string.
            emit cameraError(CameraRelease::operatorHint(failure, retriesTried, lastError));
            return false;
        }

        const int waitMs = retryDelays[retriesTried];
        ++retriesTried;
        // Bounded: at most 1+2+3 s with the default count, and only on failure.
        RuntimeLog::log("[DEV] connect attempt failed (%s) — retry %d/%d in %d ms",
                        qPrintable(lastError), retriesTried,
                        static_cast<int>(retryDelays.size()), waitMs);
        QThread::msleep(waitMs);
    }
}

void CameraManager::applyPreferredCaptureMode(int supportedModes)
{
    const int preferred[] = {
        RVC::CaptureMode_Ultra,
        RVC::CaptureMode_Normal,
        RVC::CaptureMode_Fast,
        RVC::CaptureMode_AntiInterReflection,
        RVC::CaptureMode_Robust
    };
    int chosen = static_cast<int>(m_impl->capOptsX2.capture_mode);
    if ((chosen & supportedModes) == 0)
        chosen = 0;
    for (int m : preferred) {
        if (m & supportedModes) {
            chosen = m;
            break;
        }
    }
    if (chosen != static_cast<int>(m_impl->capOptsX2.capture_mode)) {
        fprintf(stderr, "[CameraManager] capture mode %d -> %d (supported=%d)\n",
                static_cast<int>(m_impl->capOptsX2.capture_mode), chosen, supportedModes);
        m_impl->capOptsX2.capture_mode = static_cast<RVC::CaptureMode>(chosen);
    }
}

void CameraManager::applySavedParams()
{
    for (auto it = m_paramsOnConnect.constBegin();
         it != m_paramsOnConnect.constEnd(); ++it) {
        setParameter(it.key(), it.value().toFloat());
    }
}

void CameraManager::applyConnectParams()
{
    // 任务 1: the single place that decides whether the saved exposure/gain is
    // pushed over what the camera itself holds.  With use_camera_params=true the
    // decision applies nothing at all, which is exactly the requested behaviour
    // ("不应下发任何参数") and is what the runtime log line below records.
    const auto decision = CameraParamPolicy::decide(
        m_useCameraParams, toFloatMap(m_paramsOnConnect), m_cameraRead,
        /*userEdited=*/false);
    for (const QString& key : decision.appliedKeys)
        setParameter(key, m_paramsOnConnect.value(key).toFloat());
    RuntimeLog::log("%s", qPrintable(decision.logLine));

    // Also log the values that will really be used, so "本次连接用的是相机内部值
    // 还是保存值" is verifiable from the log alone.
    const auto effective = currentSettings();
    QStringList parts;
    for (auto it = effective.constBegin(); it != effective.constEnd(); ++it)
        parts << QStringLiteral("%1=%2").arg(it.key()).arg(it.value());
    // The source is taken from the decision, not from the checkbox, so an
    // operator edit (which overrides the checkbox) cannot be mislabelled here.
    RuntimeLog::log("[CAM] effective params (%s): %s",
                    decision.source == CameraParamPolicy::Source::CameraInternal
                        ? "camera-internal" : "saved-config",
                    qPrintable(parts.join(QStringLiteral(", "))));
}

void CameraManager::setUseCameraParams(bool on)
{
    m_useCameraParams = on;
}

void CameraManager::setHealthCheckInterval(int ms)
{
    m_healthTimer->setInterval(ms > 0 ? ms : HEALTH_CHECK_INTERVAL_MS);
}

int CameraManager::healthCheckInterval() const
{
    return m_healthTimer->interval();
}

bool CameraManager::reloadCameraParamsFromDevice()
{
    if (!m_isConnected || !m_impl->hasCamera())
        return false;

    DeviceLock lk(this, "reload-params");
    if (!lk.ok())
        return false;

    bool ok = false;
    try {
        if (m_impl->isX1()) {
            ok = m_impl->x1.LoadCaptureOptionParameters(m_impl->capOptsX1);
        } else if (m_impl->isX2()) {
            ok = m_impl->x2.LoadCaptureOptionParameters(m_impl->capOptsX2);
            if (ok)
                applyPreferredCaptureMode(
                    static_cast<int>(m_impl->devInfo.support_capture_mode));
        }
    } catch (...) {
        ok = false;
    }
    if (!ok) {
        RuntimeLog::log("[CAM] reload params FAILED (device did not report)");
        return false;
    }

    m_cameraRead = currentSettings();
    // The reload replaced the capture options with the device's values, so if
    // the operator is on the saved-parameter setting, put those back on top —
    // otherwise "从相机读取" would silently change what the next capture uses.
    if (!m_useCameraParams)
        applySavedParams();

    RuntimeLog::log("[CAM] reload params OK: %d key(s) read from device, source=%s",
                    m_cameraRead.size(),
                    m_useCameraParams ? "camera-internal" : "saved-config");
    return true;
}

bool CameraManager::waitForCaptureIdle(int timeoutMs)
{
    if (!m_captureInProgress || !m_captureWatcher->isRunning())
        return true;

    QElapsedTimer t;
    t.start();
    // Deliberately polls instead of pumping the event loop: processEvents() here
    // would let the capture-completion slot re-enter the window while it is
    // already closing.  isRunning() flips as soon as the worker leaves the
    // device, which is all the teardown below needs — the queued `finished`
    // delivery stays queued and is discarded by shutdown()'s timeout flag.
    while (m_captureWatcher->isRunning() && t.elapsed() < timeoutMs)
        QThread::msleep(10);

    const bool idle = !m_captureWatcher->isRunning();
    if (!idle) {
        RuntimeLog::log("[CAM] capture worker still inside the device after %d ms — "
                        "teardown will run anyway", timeoutMs);
    }
    return idle;
}

void CameraManager::shutdown(int deviceWaitMs)
{
    if (m_shuttingDown) return;

    // Idempotency (任务 3.1): decide from the *state* whether there is anything
    // left to release.  A repeat call (aboutToQuit after closeEvent,
    // WM_QUERYENDSESSION after an explicit 断开) must not repeat Close/Destroy,
    // must not call SystemShutdown twice and must not emit a second
    // cameraDisconnected.
    CameraRelease::State st;
    // "deviceOpen" must describe the *object*, not our bookkeeping: the field
    // is documented in CameraRelease.h as "an X1/X2 object is open", and
    // m_isConnected is a UI-facing flag that can lag behind it.  Asking the
    // impl keeps Close/Destroy from being skipped for a device that exists —
    // which would leave the object open and let SystemShutdown() run underneath
    // it.
    st.deviceOpen = m_impl->hasCamera();
    st.systemInited = m_impl->systemInited;
    st.released = m_released;
    const CameraRelease::Actions act = CameraRelease::plan(st);
    if (act.noop) {
        RuntimeLog::log("[CAM] shutdown: already released — no-op "
                        "(no Close/Destroy, no SystemShutdown, no signal)");
        return;
    }

    m_shuttingDown = true;
    m_lastRelease = ReleaseReport{};
    m_lastRelease.attempted = true;

    // 1. Stop scheduling new frames and ask any queued/running worker to bail
    //    out before it touches the device (or `this`, when destroying).
    if (m_workerToken && !m_impl->destroying)
        m_workerToken->cancelRequested = true;
    stopPreview();
    m_captureWatchdog->stop();
    m_reconnectTimer->stop();
    m_healthTimer->stop();
    m_reconnectAttempts = 0;

    // 2. Drop the previous frame's caches now, not when the next capture
    //    happens to overwrite them — nothing reads them after a teardown.
    releaseFrameCaches();
    m_impl->scannedDevices.clear();
    m_impl->scannedInfos.clear();

    // A capture worker may still be inside the SDK.  Its result must not be
    // applied after teardown.
    if (m_captureInProgress)
        m_captureTimedOut = true;

    // 3. Deterministically wait for the worker to leave the device.  This is a
    //    plain lock wait — no nested processEvents, so no slot can re-enter
    //    this object while it is being torn down.  Bounded so a truly hung SDK
    //    call cannot hang the close path.
    QString detail;
    {
        DeviceLock lk(this, "shutdown", -1, std::chrono::milliseconds(deviceWaitMs));
        if (lk.ok()) {
            if (act.closeDevice) {
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
                } catch (const std::exception& e) {
                    detail = QStringLiteral("关闭设备异常: %1").arg(e.what());
                } catch (...) {
                    detail = QStringLiteral("关闭设备时发生未知异常");
                }
                m_impl->model = CameraModel::None;
            }
            if (act.systemShutdown) {
                try {
                    RVC::SystemShutdown();
                } catch (const std::exception& e) {
                    if (detail.isEmpty())
                        detail = QStringLiteral("SystemShutdown 异常: %1").arg(e.what());
                } catch (...) {
                    if (detail.isEmpty())
                        detail = QStringLiteral("SystemShutdown 时发生未知异常");
                }
                m_impl->systemInited = false;
            }
        } else {
            // Deliberately leaking the device handle beats tearing it down while
            // a worker is inside it.  The process exit reclaims it.
            detail = QStringLiteral("等待设备锁超时(%1 ms)：采集/预览线程仍在相机内，"
                                    "已跳过 Close/Destroy/SystemShutdown")
                         .arg(deviceWaitMs);
            m_impl->model = CameraModel::None;
        }
    }

    m_lastRelease.released = detail.isEmpty();
    m_lastRelease.detail = detail;
    if (m_lastRelease.released) {
        RuntimeLog::log("[CAM] release OK: close=%d systemShutdown=%d (device wait <=%d ms)",
                        act.closeDevice ? 1 : 0, act.systemShutdown ? 1 : 0, deviceWaitMs);
    } else {
        // Never silent: without this line an incomplete release just looks like
        // "the camera is occupied again next time".
        RuntimeLog::log("[CAM] release INCOMPLETE: %s", qPrintable(detail));
    }

    m_isConnected = false;
    m_released = true;
    m_shuttingDown = false;
    if (m_workerToken && !m_impl->destroying)
        m_workerToken->cancelRequested = false;
    if (act.emitDisconnected)
        emit cameraDisconnected();
}

bool CameraManager::isConnected() const { return m_isConnected; }

void CameraManager::emergencyRelease()
{
    // 任务 3.3 — crash-only path.  Rules for code that runs after an access
    // violation:
    //   * no per-device call (the X1/X2 objects may point at corrupt state, and
    //     Close() would walk driver structures the fault may have half-updated);
    //   * no lock (a fault inside the device lock would make a second wait on it
    //     deadlock — the caller's bound would then be the only way out, and we
    //     would rather spend that budget on the SDK call);
    //   * no RuntimeLog::log (its mutex may be exactly what the crashing thread
    //     held).  stderr is redirected to the same runtime log, unbuffered, and
    //     needs no lock — see openEarlyLog() in main.cpp.
    // The TerminateProcess that follows this call is what really frees the
    // device: the OS closes the GigE/USB handles.  This function only gives the
    // SDK a chance to drop system-wide state cleanly first.
    fprintf(stderr, "[CRASH] emergencyRelease: RVC::SystemShutdown() begin\n");
    try {
        RVC::SystemShutdown();
        fprintf(stderr, "[CRASH] emergencyRelease: RVC::SystemShutdown() returned\n");
    } catch (const std::exception& e) {
        fprintf(stderr, "[CRASH] emergencyRelease: SystemShutdown threw: %s\n", e.what());
    } catch (...) {
        fprintf(stderr, "[CRASH] emergencyRelease: SystemShutdown threw (unknown)\n");
    }
    fflush(stderr);
}

// ── Device info ──

QString CameraManager::deviceName() const
{
    return QStringLiteral("%1 - %2").arg(m_impl->devInfo.name, m_impl->devInfo.sn);
}

std::pair<std::vector<float>, std::vector<float>> CameraManager::intrinsics() const
{
    return {m_intrinsicMatrix, m_distortion};
}

bool CameraManager::lastGrid(FrameBuffer::DoubleBuf& xyzMm, int& w, int& h) const
{
    if (!m_lastGrid.valid())
        return false;
    xyzMm = m_lastGrid.get();   // refcount bump, not a 37 MB copy
    w = m_lastGridW;
    h = m_lastGridH;
    return true;
}

bool CameraManager::lastCorrespond(FrameBuffer::DoubleBuf& cmap, int& w, int& h) const
{
    if (!m_lastCorrespond.valid())
        return false;
    cmap = m_lastCorrespond.get();
    w = m_lastCmW;
    h = m_lastCmH;
    return true;
}

std::size_t CameraManager::cachedBufferBytes() const
{
    return m_lastGrid.bytes() + m_lastCorrespond.bytes()
         + FrameBuffer::bytes(m_nativeMarkerPixels)
         + FrameBuffer::bytes(m_nativeMarkerPoints);
}

void CameraManager::releaseFrameCaches()
{
    m_lastGrid.clear();
    m_lastGridW = m_lastGridH = 0;
    m_lastCorrespond.clear();
    m_lastCmW = m_lastCmH = 0;
    m_nativeMarkerPixels.clear();
    m_nativeMarkerPixels.shrink_to_fit();
    m_nativeMarkerPoints.clear();
    m_nativeMarkerPoints.shrink_to_fit();
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

    // The worker captures this token by value; reading it is the very first
    // thing it does, so a worker that starts after ~CameraManager() exits
    // without ever touching `this`.
    auto token = m_workerToken;

    // Capture2D runs in a pool thread so the UI event loop never blocks.
    QtConcurrent::run([this, gen, token]() {
        if (!token || token->cancelRequested.load())
            return;

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
            if (frames.abandoned) {
                // The round was dropped on purpose so a capture could own the
                // device.  Not a failure: do not count it and do not
                // self-schedule (the capture has already stopped preview).
                return;
            }
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
    // Device transaction: one thread at a time.  If a capture bumped the yield
    // generation while we were waiting for the lock, we hand the device over
    // instead of driving it — that is the deterministic "preview 让位".
    const int gen = m_deviceYieldGen.load();
    DeviceLock lk(this, "preview-x1", gen);
    if (!lk.ok()) {
        out.abandoned = lk.abandoned();
        return out;
    }
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
    const int gen = m_deviceYieldGen.load();
    DeviceLock lk(this, "preview-x2", gen);
    if (!lk.ok()) {
        out.abandoned = lk.abandoned();
        return out;
    }
    try {
        if (!m_impl->x2.IsOpen()) return out;

        // A capture may have asked for the device after this round started;
        // bail before the first Capture2D rather than after it.
        if (gen != m_deviceYieldGen.load()) {
            ++m_previewAbandonCount;
            out.abandoned = true;
            return out;
        }

        auto opts = m_impl->capOptsX2;
        opts.use_projector_capturing_2d_image = false;
        auto cid = static_cast<RVC::CameraID>(m_cameraId);
        if (!m_impl->x2.Capture2D(cid, opts))
            return out;

        RVC::Image img = m_impl->x2.GetImage(cid);
        if (!img.IsValid()) return out;

        out.left = DetectionEngine::rvcToQImage(img);

        // Stereo: also capture right camera view.  Re-check the yield request
        // first so the second frame does not delay the waiting capture.
        if (m_impl->devInfo.support_extra && gen == m_deviceYieldGen.load()) {
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
                               FrameBuffer::DoubleBuf correspondMap,
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
    {
        // Fill a local vector, then hand ownership to a shared immutable
        // buffer (a move — no element copy).  ~37 MB at 1440x1080.
        std::vector<double> grid(gridCount * 3);
        if (gridCount > 0) {
            const double* pmData = pm.GetPointDataPtr();
            for (std::size_t i = 0; i < gridCount * 3; ++i)
                grid[i] = pmData[i] * 1000.0;   // m -> mm
        }
        out.gridPoints = FrameBuffer::makeDouble(std::move(grid));
    }
    out.gridAligned = gridAligned;
    out.correspondMap = std::move(correspondMap);
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

    {
        // The filter writes into plain vectors; wrap them afterwards so the
        // payload is handed on by pointer instead of being copied again.
        std::vector<float> pts, cols;
        PointCloudUtils::filterValidPoints(pmData, total, imgData, imgCh, pts, cols);
        out.points = FrameBuffer::makeFloat(std::move(pts));
        out.colors = FrameBuffer::makeFloat(std::move(cols));
    }

    if (!out.points || out.points->empty()) {
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

    // See onPreviewTick: the token is read before anything else, so a capture
    // worker that starts after ~CameraManager() never touches `this`.
    auto token = m_workerToken;
    if (m_impl->isX1()) {
        m_captureWatcher->setFuture(QtConcurrent::run([this, saveDir, index, token]() {
            if (token && token->cancelRequested.load())
                return CaptureResult{};
            return captureFrameX1(saveDir, index);
        }));
    } else if (m_impl->isX2()) {
        m_captureWatcher->setFuture(QtConcurrent::run([this, saveDir, index, token]() {
            if (token && token->cancelRequested.load())
                return CaptureResult{};
            return captureFrameX2(saveDir, index);
        }));
    }
}

CameraManager::CaptureResult CameraManager::captureFrameX1(const QString& saveDir, int index)
{
    CaptureResult out;
    // Ask any in-flight preview round to give the device up, then wait for it.
    // There is deliberately no "wait N seconds then enter anyway": the lock is
    // granted only once the preview thread has actually left the device.
    const int abandonBefore = m_previewAbandonCount.load();
    m_deviceYieldGen.fetch_add(1);
    DeviceLock lk(this, "capture-x1");
    RuntimeLog::log("[DEV] capture-x1: device acquired after %lld ms "
                    "(preview rounds yielded=%d)",
                    m_lastDeviceWaitMs,
                    m_previewAbandonCount.load() - abandonBefore);
    if (!lk.ok()) {
        out.error = QStringLiteral("相机设备忙，未开始采集");
        return out;
    }
    try {
        if (!m_impl->x1.IsOpen()) {
            out.error = QStringLiteral("X1 相机未就绪");
            return out;
        }
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
    const int abandonBefore = m_previewAbandonCount.load();
    m_deviceYieldGen.fetch_add(1);
    DeviceLock lk(this, "capture-x2");
    RuntimeLog::log("[DEV] capture-x2: device acquired after %lld ms "
                    "(preview rounds yielded=%d)",
                    m_lastDeviceWaitMs,
                    m_previewAbandonCount.load() - abandonBefore);
    if (!lk.ok()) {
        out.error = QStringLiteral("相机设备忙，未开始采集");
        return out;
    }
    try {
        if (!m_impl->x2.IsOpen()) {
            out.error = QStringLiteral("X2 相机未就绪");
            return out;
        }
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
        // Built once at the SDK boundary and then shared by pointer: the map is
        // ~25 MB and used to be copied into the result, the cache and the flow.
        FrameBuffer::DoubleBuf cmap;
        int cmW = 0, cmH = 0;
        if (!gridAligned) {
            try {
                RVC::CorrespondMap cm = m_impl->x2.GetCorrespondMap();
                if (cm.IsValid()) {
                    const RVC::Size sz = cm.GetSize();
                    cmW = sz.width;
                    cmH = sz.height;
                    const double* data = cm.GetDataConstPtr();
                    if (data && cmW > 0 && cmH > 0) {
                        std::vector<double> cmapVec(
                            static_cast<std::size_t>(cmW) * cmH * 2);
                        std::copy(data, data + cmapVec.size(), cmapVec.begin());
                        cmap = FrameBuffer::makeDouble(std::move(cmapVec));
                    }
                }
            } catch (...) {
                cmap.reset();
                cmW = cmH = 0;
            }
        }
        if (!postProcessCapture(img, pm, saveDir, index, out,
                                gridAligned, std::move(cmap), cmW, cmH)) {
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

    // The worker's CaptureResult stays inside the QFuture until the next capture
    // replaces it — see captureFullFrame(), which calls setFuture() with the new
    // run and thereby drops the previous result.  That is the release point.
    //
    // Do NOT reset the watcher here, and not on a deferred event-loop turn
    // either: setFuture() disconnects the watcher's call-out interface, and Qt
    // may still be delivering this completion's QFutureCallOutEvent, so the
    // callback lands on a torn-down interface (SEH 0xC0000005 right after
    // "setFuture returned").  One retained CaptureResult costs a few refcounts
    // plus the frame's QImage; the heavy blocks are already shared with
    // m_lastGrid/m_lastCorrespond and are freed by BufferSlot::publish().
    if (m_captureTimedOut) {
        m_captureTimedOut = false;
        return;  // timeout already reported; late result ignored
    }

    // QFutureWatcher<T>::result() returns T by value; CaptureResult is cheap to
    // copy now that its heavy members are shared_ptr.
    const CaptureResult result = m_captureWatcher->result();
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

    // Publish the new frame's lookup buffers.  This also drops the previous
    // frame's grid/correspond block (tens of MB) right here instead of leaving
    // it to linger until the next capture overwrote it.
    m_lastGrid.publish(result.gridPoints);
    m_lastGridW = result.gridW;
    m_lastGridH = result.gridH;
    m_lastCorrespond.publish(result.correspondMap);
    m_lastCmW = result.cmW;
    m_lastCmH = result.cmH;
    m_lastGridAligned = result.gridAligned;

    RuntimeLog::log("capture OK: %zu points in %lld ms (png=%s ply=%s)",
                    result.points ? result.points->size() / 3 : 0, elapsed,
                    qPrintable(QFileInfo(result.pngPath).fileName()),
                    qPrintable(QFileInfo(result.plyPath).fileName()));
    logMemoryTrace("after capture (before upload)", cachedBufferBytes()
                   + FrameBuffer::bytes(result.points) + FrameBuffer::bytes(result.colors));
    emit captureComplete(result.pngPath, result.plyPath,
                         result.points, result.colors, result.image);
    // 崩溃注入 (TEST ONLY): HEC_CRASH_INJECT=after-capture.  Last statement on
    // purpose: the frame has already reached the UI, so the acceptance test
    // crashes with the camera holding a fully delivered capture.
    CrashInject::hitIfEnabled(CrashInject::Point::AfterCapture);
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
    auto token = m_workerToken;
    QtConcurrent::run([this, serial, token]() {
        if (!token || token->cancelRequested.load())
            return;
        bool valid = false;
        try {
            // SystemFindDevice re-scans the bus; it is an RVC call like any
            // other and must not overlap SystemShutdown or a device
            // transaction on another thread.
            DeviceLock lk(this, "health-scan");
            if (!lk.ok()) {
                QMetaObject::invokeMethod(this, [this]() {
                    m_healthBusy = false;
                }, Qt::QueuedConnection);
                return;
            }
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
