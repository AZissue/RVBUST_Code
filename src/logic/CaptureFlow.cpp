#include "logic/CaptureFlow.h"

#include "logic/CameraManager.h"
#include "logic/DataManager.h"
#include "logic/DetectionEngine.h"
#include "logic/RuntimeLog.h"

#include <QtConcurrent/QtConcurrentRun>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QDateTime>
#include <cmath>

namespace {

void emitLog(CaptureFlow* flow, const QString& level, const QString& message)
{
    emit flow->logRequested(message, level);
}

} // namespace

CaptureFlow::CaptureFlow(CameraManager* camera, DataManager* data, QObject* parent)
    : QObject(parent)
    , m_camera(camera)
    , m_data(data)
{
    m_detectWatcher = new QFutureWatcher<DetectResult>(this);
    m_detectWatchdog = new QTimer(this);
    m_detectWatchdog->setSingleShot(true);

    connect(m_detectWatcher, &QFutureWatcher<DetectResult>::finished,
            this, &CaptureFlow::onDetectionFinished);
    connect(m_detectWatchdog, &QTimer::timeout,
            this, &CaptureFlow::onDetectionTimeout);
}

// ── Mode / configuration ──────────────────────────────────────────────

void CaptureFlow::setMode(const CalibrationMode& mode)
{
    m_mode = mode;
}

void CaptureFlow::setCaliboardParams(int patternW, int patternH, float circleStep)
{
    m_caliboardW = patternW;
    m_caliboardH = patternH;
    m_caliboardStep = circleStep;
}

void CaptureFlow::setErrorThreshold(float pct)
{
    m_errorThreshold = pct;
}

// ── Capture ───────────────────────────────────────────────────────────

void CaptureFlow::beginCapture()
{
    if (!m_camera || !m_camera->isConnected()) {
        emit toastRequested(QStringLiteral("请先连接相机"), false);
        return;
    }

    emit busyChanged(true, QStringLiteral("采集中..."));
    m_camera->captureFullFrame(m_data->saveDir(), m_data->count() + 1);
}

void CaptureFlow::onCaptureReady(const QString& pngPath, const QString& plyPath,
                                 const std::vector<float>& points,
                                 const std::vector<float>& colors,
                                 const QImage& image)
{
    emit busyChanged(false, {});

    m_capturedPng = pngPath;
    m_capturedPly = plyPath;
    m_capturedPoints = points;
    m_capturedImage = image;

    // A new frame invalidates any cached detection from the previous one.
    m_detectCacheKey.clear();
    m_detectCache = DetectResult{};

    emit imageCaptured(image);
    emit pointCloudReady(points, colors);

    setDetectEnabled(true);
    setSaveEnabled(false);
    emit tipRequested(QStringLiteral("采集完成，请点击识别检测标记物"), false);
    emitLog(this, QStringLiteral("success"),
            QStringLiteral("第 %1 组数据采集完成").arg(m_data->count() + 1));
}

// ── Detect ────────────────────────────────────────────────────────────

void CaptureFlow::detect()
{
    const qint64 detectStartMs = QDateTime::currentMSecsSinceEpoch();
    if (m_capturedPng.isEmpty()) {
        RuntimeLog::log("detect skipped: no captured frame");
        emit toastRequested(QStringLiteral("请先拍照采集数据"), false);
        emitLog(this, QStringLiteral("warning"), QStringLiteral("识别失败: 未采集数据"));
        return;
    }
    if (m_detecting)
        return;

    // Same frame + same marker type/spec -> reuse the last successful result
    // instead of re-running the detection engine (repeat clicks are instant).
    const QString cacheKey = QStringLiteral("%1|%2|%3x%4|%5")
        .arg(m_capturedPng)
        .arg(static_cast<int>(m_mode.markerType))
        .arg(m_caliboardW).arg(m_caliboardH)
        .arg(m_caliboardStep);
    if (cacheKey == m_detectCacheKey
            && m_detectCache.status == DetectResult::Status::Ok) {
        emit clearMarkersRequested();
        // The warning depends on the *current* operator threshold — re-evaluate
        // it so a threshold change takes effect even on a cached result.
        if (m_mode.markerType == MarkerType::AsymmetricGrid) {
            m_detectCache.warning = caliboardQualityMessage(
                m_detectCache.detectedCount, m_detectCache.expectedCount,
                m_detectCache.errorPercentage, m_errorThreshold);
        }
        emitLog(this, QStringLiteral("info"),
                QStringLiteral("同帧重复识别，复用缓存结果 (%1 点)")
                    .arg(m_detectCache.detectedCount));
        applyDetectionResult(m_detectCache);
        return;
    }

    emit busyChanged(true, QStringLiteral("识别中..."));
    emit clearMarkersRequested();

    const auto markerName = (m_mode.markerType == MarkerType::ConcentricCircle)
        ? QStringLiteral("同心圆") : QStringLiteral("黑底白圆");
    emitLog(this, QStringLiteral("info"), QStringLiteral("使用%1检测").arg(markerName));

    // Concentric: prefer the in-memory cache captured with the frame
    // (instant, no file round-trip, no worker needed).
    if (m_mode.markerType == MarkerType::ConcentricCircle) {
        auto [nativePixels, nativePoints] = m_camera->nativeMarkerResult();
        if (!nativePixels.empty() && !nativePoints.empty()) {
            DetectResult r;
            r.status = DetectResult::Status::Ok;
            const int num = static_cast<int>(nativePixels.size()) / 2;
            r.detectedCount = num;
            r.pts2d.reserve(num);
            r.pts3d.reserve(num);
            for (int i = 0; i < num; ++i) {
                r.pts2d.emplace_back(nativePixels[i * 2], nativePixels[i * 2 + 1]);
                r.pts3d.push_back({{
                    nativePoints[i * 3], nativePoints[i * 3 + 1], nativePoints[i * 3 + 2]
                }});
            }
            // SDK convention: first returned point == calibration reference origin
            r.xyzForCard = DetectionEngine::firstValidPoint3d(r.pts3d);
            emitLog(this, QStringLiteral("info"),
                    QStringLiteral("使用采集时缓存的原生检测结果 (%1 点)").arg(num));
            RuntimeLog::log("detect OK (cached native): %d markers in %lld ms",
                            num, QDateTime::currentMSecsSinceEpoch() - detectStartMs);
            applyDetectionResult(r);
            emit busyChanged(false, {});
            return;
        }
    }

    // File-based detection runs in a worker thread so the UI stays responsive.
    DetectJob job;
    job.markerType = m_mode.markerType;
    job.png = m_capturedPng;
    job.ply = m_capturedPly;
    job.patternW = m_caliboardW;
    job.patternH = m_caliboardH;
    job.circleStep = m_caliboardStep;
    job.errorThreshold = m_errorThreshold;
    if (m_mode.markerType == MarkerType::AsymmetricGrid) {
        auto imat = m_camera->intrinsics();
        job.intrinsic = imat.first;
        job.distortion = imat.second;
    }
    m_pendingJob = job;
    m_pendingCacheKey = cacheKey;

    m_detecting = true;
    m_detectTimedOut = false;
    m_detectStartMs = QDateTime::currentMSecsSinceEpoch();
    m_detectWatchdog->start(DETECT_TIMEOUT_MS);
    m_detectWatcher->setFuture(QtConcurrent::run([job]() { return runDetectJob(job); }));
}

// Runs off the UI thread: pure file-based detection, no camera/device access.
CaptureFlow::DetectResult CaptureFlow::runDetectJob(const DetectJob& job)
{
    DetectResult r;

    if (job.markerType == MarkerType::AsymmetricGrid) {
        r.expectedCount = job.patternW * job.patternH;
        try {
            const auto res = DetectionEngine::detectCaliboard(
                job.png.toStdString(), job.ply.toStdString(),
                job.intrinsic, job.distortion,
                job.patternW, job.patternH, job.circleStep);

            if (res.pixelXy.empty() || (res.pixelXy.size() % 2) != 0) {
                r.status = DetectResult::Status::NoMarkers;
                return r;
            }

            r.detectedCount = static_cast<int>(res.pixelXy.size()) / 2;
            r.errorPercentage = res.errorPercentage;

            r.pts2d.reserve(r.detectedCount);
            r.pts3d.reserve(r.detectedCount);
            for (int i = 0; i < r.detectedCount; ++i) {
                r.pts2d.emplace_back(res.pixelXy[i * 2], res.pixelXy[i * 2 + 1]);
                if (i * 3 + 2 < static_cast<int>(res.pointXyz.size())) {
                    std::array<float, 3> p3 = {{
                        res.pointXyz[i * 3],
                        res.pointXyz[i * 3 + 1],
                        res.pointXyz[i * 3 + 2]
                    }};
                    if (!std::isnan(p3[0]) && !std::isnan(p3[1]) && !std::isnan(p3[2]))
                        r.pts3d.push_back(p3);
                }
            }

            // SDK convention: first returned point == calibration reference origin
            // (the origin corner of the asymmetric board).
            r.xyzForCard = DetectionEngine::firstValidPoint3d(r.pts3d);
            r.warning = caliboardQualityMessage(
                r.detectedCount, r.expectedCount, res.errorPercentage,
                job.errorThreshold);
            r.status = DetectResult::Status::Ok;
        } catch (const std::exception& e) {
            r.status = DetectResult::Status::EngineError;
            r.errorDetail = QString::fromUtf8(e.what());
        } catch (...) {
            r.status = DetectResult::Status::EngineCrash;
        }
        return r;
    }

    // Concentric (file-based fallback)
    try {
        auto res = DetectionEngine::detectConcentric(
            job.png.toStdString(), job.ply.toStdString());
        if (res.first.empty()) {
            r.status = DetectResult::Status::NoMarkers;
            return r;
        }
        r.detectedCount = static_cast<int>(res.first.size());
        r.pts2d = std::move(res.first);
        r.pts3d = std::move(res.second);
        // SDK convention: first returned point == calibration reference origin
        // (the shared center of the concentric marker).
        r.xyzForCard = DetectionEngine::firstValidPoint3d(r.pts3d);
        r.status = DetectResult::Status::Ok;
    } catch (const std::exception& e) {
        r.status = DetectResult::Status::EngineError;
        r.errorDetail = QString::fromUtf8(e.what());
    } catch (...) {
        r.status = DetectResult::Status::EngineCrash;
    }
    return r;
}

void CaptureFlow::onDetectionFinished()
{
    m_detectWatchdog->stop();
    m_detecting = false;

    if (m_detectTimedOut) {
        m_detectTimedOut = false;
        return;  // timeout already handled; late result ignored
    }

    const auto result = m_detectWatcher->result();
    RuntimeLog::log("detect finished: status=%d markers=%d/%d errorPct=%.2f in %lld ms",
                    static_cast<int>(result.status),
                    result.detectedCount, result.expectedCount,
                    result.errorPercentage,
                    QDateTime::currentMSecsSinceEpoch() - m_detectStartMs);
    applyDetectionResult(result);
    if (result.status == DetectResult::Status::Ok) {
        m_detectCacheKey = m_pendingCacheKey;
        m_detectCache = result;
    }
    emit busyChanged(false, {});
}

void CaptureFlow::onDetectionTimeout()
{
    if (!m_detecting) return;
    m_detecting = false;
    m_detectTimedOut = true;
    RuntimeLog::log("detect TIMEOUT after %lld ms",
                    QDateTime::currentMSecsSinceEpoch() - m_detectStartMs);

    emit busyChanged(false, {});
    setSaveEnabled(false);
    emit tipRequested(QStringLiteral("识别超时，请重新采集"), true);
    emit toastRequested(QStringLiteral("识别超时，请重试"), false);
    emitLog(this, QStringLiteral("error"),
            QStringLiteral("识别超时（%1 秒）").arg(DETECT_TIMEOUT_MS / 1000));
}

void CaptureFlow::applyDetectionResult(const DetectResult& result)
{
    const bool concentric = (m_mode.markerType == MarkerType::ConcentricCircle);

    if (result.status != DetectResult::Status::Ok) {
        setSaveEnabled(false);
        switch (result.status) {
        case DetectResult::Status::NoMarkers:
            if (concentric) {
                emit tipRequested(QStringLiteral("未检测到同心圆标记物，请重新采集"), true);
                emitLog(this, QStringLiteral("warning"),
                        QStringLiteral("同心圆检测: 未找到标记物，请确认标定板在视野内且光照良好"));
                emit toastRequested(QStringLiteral("未检测到标记物，请重新采集"), false);
            } else {
                emit tipRequested(QStringLiteral("未检测到黑底白圆标定板，请重新采集"), true);
                emitLog(this, QStringLiteral("warning"), QStringLiteral("黑底白圆检测: 未找到标定板"));
                emit toastRequested(QStringLiteral("未检测到标定板，请重新采集"), false);
            }
            break;
        case DetectResult::Status::EngineError:
            emit tipRequested(QStringLiteral("检测引擎异常，请重新采集"), true);
            emit toastRequested(QStringLiteral("检测异常，请重新采集"), false);
            emitLog(this, QStringLiteral("error"),
                    concentric
                        ? QStringLiteral("同心圆检测异常: %1").arg(result.errorDetail)
                        : QStringLiteral("黑底白圆检测异常: %1").arg(result.errorDetail));
            break;
        case DetectResult::Status::EngineCrash:
            emit tipRequested(QStringLiteral("检测引擎崩溃，请重新采集"), true);
            emit toastRequested(QStringLiteral("检测崩溃，请重新采集"), false);
            emitLog(this, QStringLiteral("error"),
                    concentric ? QStringLiteral("同心圆检测崩溃")
                               : QStringLiteral("黑底白圆检测崩溃"));
            break;
        default:
            break;
        }
        return;
    }

    const auto overlay = DetectionEngine::formatMarkersForOverlay(result.pts2d, result.pts3d);
    emit markersDisplayReady(overlay.overlay2d, overlay.highlights3d,
                             overlay.highlightIndices);

    if (result.xyzForCard.size() >= 3) {
        emit autoFillCardRequested("camera_target_xyz",
            QStringLiteral("%1 %2 %3")
                .arg(result.xyzForCard[0], 0, 'f', 3)
                .arg(result.xyzForCard[1], 0, 'f', 3)
                .arg(result.xyzForCard[2], 0, 'f', 3));
    }

    setSaveEnabled(true);
    m_lastMarkerCount = result.detectedCount;
    m_lastErrorPct = concentric ? -1.0f : result.errorPercentage;
    if (concentric) {
        emit tipRequested(QStringLiteral("检测到 %1 个标记物，请确认数据后点击保存")
                              .arg(result.detectedCount), false);
        emitLog(this, QStringLiteral("success"),
                QStringLiteral("检测到 %1 个同心圆").arg(result.detectedCount));
        emit toastRequested(QStringLiteral("识别成功: %1 个同心圆").arg(result.detectedCount), true);
    } else {
        if (!result.warning.isEmpty()) {
            emit tipRequested(result.warning, true);
            emitLog(this, QStringLiteral("warning"),
                    QStringLiteral("黑底白圆检测告警: %1").arg(result.warning));
        } else {
            emit tipRequested(QStringLiteral("检测到 %1 个圆点，请确认数据后点击保存")
                                  .arg(result.detectedCount), false);
        }
        emitLog(this, QStringLiteral("success"),
                QStringLiteral("黑底白圆检测成功 (%1 点)").arg(result.detectedCount));
        emit toastRequested(QStringLiteral("识别成功: %1 个圆点").arg(result.detectedCount), true);
    }
}

// ── Save ──────────────────────────────────────────────────────────────

void CaptureFlow::save(const QString& cameraTargetXyz, const QString& robotCapturePose,
                       const QString& robotTargetXyz)
{
    RuntimeLog::log("save requested");
    const auto issue = validateSaveInputs(
        cameraTargetXyz, robotCapturePose, robotTargetXyz, m_mode);
    if (!issue.ok) {
        RuntimeLog::log("save REJECTED: %s", qPrintable(issue.message));
        if (!issue.field.isEmpty())
            emit cardInvalidRequested(issue.field);
        emit tipRequested(issue.message, true);
        emit toastRequested(issue.message, false);
        emitLog(this, QStringLiteral("warning"),
                QStringLiteral("保存被拒绝: %1").arg(issue.message));
        return;
    }

    // Copy PNG/PLY from temp to permanent save directory
    const int newIdx = m_data->count() + 1;
    const QString saveDir = m_data->saveDir();
    const QString permPng = QStringLiteral("%1/%2.png").arg(saveDir).arg(newIdx);
    const QString permPly = QStringLiteral("%1/%2.ply").arg(saveDir).arg(newIdx);
    RuntimeLog::log("save: index=%d dir=%s", newIdx, qPrintable(saveDir));

    if (!QDir().mkpath(saveDir)) {
        RuntimeLog::log("save FAILED: cannot create dir %s", qPrintable(saveDir));
        emitLog(this, QStringLiteral("error"),
                QStringLiteral("无法创建保存目录: %1").arg(saveDir));
        emit toastRequested(QStringLiteral("保存失败: 无法创建目录"), false);
        return;
    }

    // Remove stale target files first (overwrite safety)
    if (QFile::exists(permPng)) QFile::remove(permPng);
    if (QFile::exists(permPly)) QFile::remove(permPly);

    const bool pngOk = QFile::copy(m_capturedPng, permPng);
    const bool plyOk = QFile::copy(m_capturedPly, permPly);
    RuntimeLog::log("save: copy png=%d ply=%d (tmp=%s -> %s)",
                    pngOk ? 1 : 0, plyOk ? 1 : 0,
                    qPrintable(QFileInfo(m_capturedPng).fileName()),
                    qPrintable(QFileInfo(permPng).fileName()));

    if (!pngOk || !plyOk) {
        if (pngOk) QFile::remove(permPng);
        if (plyOk) QFile::remove(permPly);
        emitLog(this, QStringLiteral("error"),
                QStringLiteral("文件拷贝失败: PNG=%1 PLY=%2")
                    .arg(pngOk ? "OK" : "FAIL", plyOk ? "OK" : "FAIL"));
        emit toastRequested(QStringLiteral("保存失败: 文件写入错误"), false);
        return;
    }

    m_data->addRecord(permPng, permPly, cameraTargetXyz, robotCapturePose, robotTargetXyz,
                      m_lastErrorPct, m_lastMarkerCount);
    m_data->writeHandEyeOutput();
    RuntimeLog::log("save OK: record %d (%s)", m_data->count(),
                    qPrintable(QFileInfo(saveDir).fileName()));

    const int n = m_data->count();
    emit toastRequested(QStringLiteral("第 %1 组数据保存成功").arg(n), true);
    emitLog(this, QStringLiteral("success"), QStringLiteral("第 %1 组数据已保存").arg(n));

    clearCapturedState();
    setDetectEnabled(false);
    setSaveEnabled(false);
    emit tipRequested(QStringLiteral("请移动机器人到下一个位姿并点击拍照"), false);
}

// ── Undo ──────────────────────────────────────────────────────────────

void CaptureFlow::undo()
{
    RuntimeLog::log("undo requested (count=%d)", m_data->count());
    if (m_data->removeLast()) {
        m_data->writeHandEyeOutput();
        RuntimeLog::log("undo OK: removed record, count=%d", m_data->count());
        emit toastRequested(QStringLiteral("已撤销上一次保存"), true);
        emitLog(this, QStringLiteral("info"),
                QStringLiteral("撤销: 第 %1 组数据已删除").arg(m_data->count() + 1));
    } else {
        emit toastRequested(QStringLiteral("没有可撤销的数据"), false);
    }
}

// ── State ─────────────────────────────────────────────────────────────

bool CaptureFlow::hasUnsavedCapture() const
{
    return !m_capturedPng.isEmpty();
}

const std::vector<float>& CaptureFlow::capturedPoints() const
{
    return m_capturedPoints;
}

void CaptureFlow::reset()
{
    clearCapturedState();
}

void CaptureFlow::setDetectEnabled(bool enabled)
{
    if (m_detectEnabled == enabled) return;
    m_detectEnabled = enabled;
    emit detectEnabledChanged(enabled);
}

void CaptureFlow::setSaveEnabled(bool enabled)
{
    if (m_saveEnabled == enabled) return;
    m_saveEnabled = enabled;
    emit saveEnabledChanged(enabled);
}

void CaptureFlow::clearCapturedState()
{
    m_capturedPng.clear();
    m_capturedPly.clear();
    m_capturedPoints.clear();
    m_capturedPoints.shrink_to_fit();
    m_capturedImage = QImage();
    m_lastErrorPct = -1.0f;
    m_lastMarkerCount = 0;
    m_detectCacheKey.clear();
    m_detectCache = DetectResult{};
}
