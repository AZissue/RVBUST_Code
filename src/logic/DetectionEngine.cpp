#include "logic/DetectionEngine.h"
#include "sdk/HandEyeSDKBridge.h"

#include <RVC/RVC.h>
#include <RVC/experimental/MarkerDetection.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <sstream>
#include <iomanip>
#include <QFile>

using Vec2f = std::pair<float, float>;
using Vec3f = std::array<float, 3>;

// ═══════════════════════════════════════════════════════════════
// Public — Concentric circle detection
// ═══════════════════════════════════════════════════════════════

std::pair<std::vector<Vec2f>, std::vector<Vec3f>>
DetectionEngine::detectConcentric(const std::string& pngPath, const std::string& plyPath)
{
    // Use QFile (wide-char) so Chinese paths work; fopen() decodes as ANSI and
    // fails on UTF-8 paths even when the file exists.
    const QString png = QString::fromStdString(pngPath);
    const QString ply = QString::fromStdString(plyPath);
    if (!QFile::exists(png)) {
        fprintf(stderr, "[DetectionEngine] Cannot open PNG: %s\n", qPrintable(png));
        return {{},{}};
    }
    if (!QFile::exists(ply)) {
        fprintf(stderr, "[DetectionEngine] Cannot open PLY: %s\n", qPrintable(ply));
        return {{},{}};
    }

    // Try PyRVC native first
    try {
        auto result = detectConcentricNative(pngPath, plyPath);
        if (!result.first.empty())
            return result;
    } catch (...) {}

    // Fallback to HandEyeSDK
    fprintf(stderr, "[DetectionEngine] Falling back to HandEyeSDK concentric detection\n");
    return detectConcentricHandEye(pngPath, plyPath);
}

// ═══════════════════════════════════════════════════════════════
// Public — Caliboard detection
// ═══════════════════════════════════════════════════════════════

DetectionEngine::CaliboardResult
DetectionEngine::detectCaliboard(const std::string& pngPath, const std::string& plyPath,
                                 const std::vector<float>& intrinsic,
                                 const std::vector<float>& distortion,
                                 int patternW, int patternH, float circleStep)
{
    // QFile::exists uses wide chars; fopen() would break on Chinese paths.
    if (!QFile::exists(QString::fromStdString(pngPath)))
        return {};

    if (intrinsic.size() >= 9 && distortion.size() >= 5) {
        // Reject all-zero intrinsics (camera didn't load them properly)
        bool allZero = true;
        for (auto v : intrinsic) { if (v != 0.0f) { allZero = false; break; } }
        if (!allZero) {
            float imat[9] = {}, idist[5] = {};
            std::copy_n(intrinsic.begin(), 9, imat);
            std::copy_n(distortion.begin(), 5, idist);

            // Try RVC native TestAccuracy first (circleStep in mm, converted to m inside)
            float circleStepM = circleStep / 1000.0f;
            auto nativeR = detectCaliboardNative(pngPath, plyPath, imat, idist,
                                                  patternW, patternH, circleStepM);
            if (!nativeR.pixelXy.empty()) {
                fprintf(stderr, "[DetectionEngine] detectCaliboard: RVC native OK (%d pts)\n",
                        static_cast<int>(nativeR.pixelXy.size()) / 2);
                return nativeR;
            }
            fprintf(stderr, "[DetectionEngine] detectCaliboard: RVC native failed, falling back to HandEyeSDK\n");
            return detectCaliboardHandEye(pngPath, plyPath, intrinsic, distortion,
                                          patternW, patternH, circleStep);
        }
        fprintf(stderr, "[DetectionEngine] detectCaliboard: intrinsics are all zeros — camera may not have loaded them\n");
    } else {
        fprintf(stderr, "[DetectionEngine] detectCaliboard: intrinsics missing (I=%zu D=%zu), skipping\n",
                intrinsic.size(), distortion.size());
    }
    return {};
}

// ═══════════════════════════════════════════════════════════════
// PyRVC native concentric detection
// ═══════════════════════════════════════════════════════════════

std::pair<std::vector<Vec2f>, std::vector<Vec3f>>
DetectionEngine::detectConcentricNative(const std::string& pngPath, const std::string& plyPath)
{
    // Load captured image from temp file
    RVC::Image img = RVC::Image::CreateFromFile(pngPath.c_str());
    if (!img.IsValid()) {
        fprintf(stderr, "[RVC] detectConcentricNative: failed to load image %s\n", pngPath.c_str());
        return {{},{}};
    }

    RVC::Size sz = img.GetSize();

    // Load point map from temp file (saved in millimeters)
    RVC::PointMap pm = RVC::PointMap::CreateFromFile(plyPath.c_str(), sz, RVC::PointMapUnit::Millimeter);
    if (!pm.IsValid()) {
        fprintf(stderr, "[RVC] detectConcentricNative: failed to load PLY %s\n", plyPath.c_str());
        RVC::Image::Destroy(img);
        return {{},{}};
    }

    int num = 0;
    double pixelXy[2000] = {};
    double pointXyz[3000] = {};

    int ret = RVC::DetectConcentricCircleMarker3d(img, pm, &num, pixelXy, pointXyz);
    fprintf(stderr, "[RVC] DetectConcentricCircleMarker3d: ret=%d num=%d\n", ret, num);

    RVC::PointMap::Destroy(pm);
    RVC::Image::Destroy(img);

    if (ret < 0 || num <= 0) return {{},{}};
    num = std::min(num, 1000);  // pixelXy[2000] / pointXyz[3000] hold at most 1000 points

    // RVC returns meters, convert to mm for app
    std::vector<Vec2f> pts2d;
    std::vector<Vec3f> pts3d;
    pts2d.reserve(num);
    pts3d.reserve(num);
    for (int i = 0; i < num; ++i) {
        pts2d.emplace_back(static_cast<float>(pixelXy[i * 2]),
                           static_cast<float>(pixelXy[i * 2 + 1]));
        Vec3f p3 = {{static_cast<float>(pointXyz[i * 3] * 1000.0),
                     static_cast<float>(pointXyz[i * 3 + 1] * 1000.0),
                     static_cast<float>(pointXyz[i * 3 + 2] * 1000.0)}};
        pts3d.push_back(p3);
    }
    return {pts2d, pts3d};
}

// ═══════════════════════════════════════════════════════════════
// RVC native caliboard detection (TestAccuracy)
// ═══════════════════════════════════════════════════════════════

DetectionEngine::CaliboardResult
DetectionEngine::detectCaliboardNative(const std::string& pngPath, const std::string& plyPath,
                                       const float intrinsic[9], const float distortion[5],
                                       int patternW, int patternH, float circleStepM)
{
    RVC::Image img = RVC::Image::CreateFromFile(pngPath.c_str());
    if (!img.IsValid()) {
        fprintf(stderr, "[RVC] detectCaliboardNative: failed to load image %s\n", pngPath.c_str());
        return {};
    }

    RVC::Size sz = img.GetSize();
    RVC::PointMap pm = RVC::PointMap::CreateFromFile(plyPath.c_str(), sz, RVC::PointMapUnit::Millimeter);
    if (!pm.IsValid()) {
        fprintf(stderr, "[RVC] detectCaliboardNative: failed to load PLY %s\n", plyPath.c_str());
        RVC::Image::Destroy(img);
        return {};
    }

    int num = patternW * patternH;
    std::vector<float> circle2d(static_cast<size_t>(num) * 2, 0.0f);
    std::vector<float> circle3d(static_cast<size_t>(num) * 3, 0.0f);
    float measuringDistance = 0.0f;
    float errorPercentage = 0.0f;

    fprintf(stderr, "[RVC] TestAccuracy: img=%s ply=%s pattern=%dx%d stepM=%.4f\n",
            pngPath.c_str(), plyPath.c_str(), patternW, patternH, circleStepM);

    int err = RVC::TestAccuracy(img, pm, intrinsic, distortion,
                                patternW, patternH, circleStepM,
                                circle2d.data(), circle3d.data(),
                                measuringDistance, errorPercentage);

    fprintf(stderr, "[RVC] TestAccuracy: err=%d measDist=%.2f errPct=%.2f\n",
            err, measuringDistance, errorPercentage);

    RVC::PointMap::Destroy(pm);
    RVC::Image::Destroy(img);

    if (err != 0) return {};

    // Count valid 2D points (non-zero)
    int validCount = 0;
    for (int i = 0; i < num; ++i) {
        float x = circle2d[i * 2], y = circle2d[i * 2 + 1];
        if ((x == 0.0f && y == 0.0f) || std::isnan(x) || std::isnan(y)) break;
        ++validCount;
    }
    if (validCount == 0) return {};

    CaliboardResult result;
    result.pixelXy.assign(circle2d.begin(), circle2d.begin() + validCount * 2);

    // TestAccuracy returns 3D in meters (RVC native unit). Convert to mm.
    result.pointXyz.resize(validCount * 3);
    for (int i = 0; i < validCount; ++i) {
        result.pointXyz[i * 3 + 0] = circle3d[i * 3 + 0] * 1000.0f;
        result.pointXyz[i * 3 + 1] = circle3d[i * 3 + 1] * 1000.0f;
        result.pointXyz[i * 3 + 2] = circle3d[i * 3 + 2] * 1000.0f;
    }
    result.measuringDistance = measuringDistance;
    result.errorPercentage = errorPercentage;

    fprintf(stderr, "[RVC] TestAccuracy: validPoints=%d measDist=%.2f errPct=%.2f\n",
            validCount, measuringDistance, errorPercentage);
    for (int i = 0; i < std::min(3, validCount); ++i) {
        fprintf(stderr, "[RVC] pt[%d]: px=(%.1f,%.1f) xyz=(%.3f,%.3f,%.3f)\n",
                i, result.pixelXy[i*2], result.pixelXy[i*2+1],
                result.pointXyz[i*3], result.pointXyz[i*3+1], result.pointXyz[i*3+2]);
    }

    return result;
}

// ═══════════════════════════════════════════════════════════════
// HandEyeSDK fallback (kept for compatibility, not primary path)
// ═══════════════════════════════════════════════════════════════

std::pair<std::vector<Vec2f>, std::vector<Vec3f>>
DetectionEngine::detectConcentricHandEye(const std::string& pngPath, const std::string& plyPath)
{
    return HandEyeSDKBridge::detectConcentricCircles3D(pngPath, plyPath);
}

DetectionEngine::CaliboardResult
DetectionEngine::detectCaliboardHandEye(const std::string& pngPath, const std::string& plyPath,
                                        const std::vector<float>& intrinsic,
                                        const std::vector<float>& distortion,
                                        int patternW, int patternH, float circleStep)
{
    float imat[9] = {}, idist[5] = {};
    std::copy_n(intrinsic.begin(), 9, imat);
    std::copy_n(distortion.begin(), 5, idist);

    // PLY is saved in millimeters. Pass circleStep in mm to match.
    fprintf(stderr, "[DetectionEngine] DetectCaliboard3D (fallback): img=%s ply=%s pattern=%dx%d step=%.1f\n",
            pngPath.c_str(), plyPath.c_str(), patternW, patternH, circleStep);

    auto r = HandEyeSDKBridge::detectCaliboard3D(pngPath, plyPath, imat, idist,
                                                  patternW, patternH, circleStep);

    CaliboardResult result;
    if (r.pixelXy.empty()) return result;

    // Count valid entries (non-zero, non-NaN)
    int expected = patternW * patternH * 2;
    int validCount = 0;
    for (int i = 0; i < expected && i < static_cast<int>(r.pixelXy.size()); i += 2) {
        float x = r.pixelXy[i], y = r.pixelXy[i + 1];
        if ((x == 0.0f && y == 0.0f) || std::isnan(x) || std::isnan(y)) break;
        ++validCount;
    }
    if (validCount == 0) return result;

    result.pixelXy.assign(r.pixelXy.begin(), r.pixelXy.begin() + validCount * 2);

    // SDK returns 3D in same unit as PLY (mm)
    result.pointXyz.assign(r.pointXyz.begin(), r.pointXyz.begin() + validCount * 3);
    result.measuringDistance = r.measuringDistance;
    result.errorPercentage = r.errorPercentage;

    fprintf(stderr, "[DetectionEngine] DetectCaliboard3D: validPoints=%d measDist=%.2f errPct=%.2f\n",
            validCount, r.measuringDistance, r.errorPercentage);
    for (int i = 0; i < std::min(3, validCount); ++i) {
        fprintf(stderr, "[DetectionEngine] pt[%d]: px=(%.1f,%.1f) xyz=(%.3f,%.3f,%.3f)\n",
                i, result.pixelXy[i*2], result.pixelXy[i*2+1],
                result.pointXyz[i*3], result.pointXyz[i*3+1], result.pointXyz[i*3+2]);
    }

    return result;
}

// ═══════════════════════════════════════════════════════════════
// Image conversion utilities
// ═══════════════════════════════════════════════════════════════

QImage DetectionEngine::rvcToQImage(const RVC::Image& img)
{
    int w = img.GetSize().cols;
    int h = img.GetSize().rows;
    int channels = (img.GetType() == RVC::ImageType::BGR8) ? 3 :
                   (img.GetType() == RVC::ImageType::RGB8) ? 3 :
                   (img.GetType() == RVC::ImageType::Mono8) ? 1 : 3;
    auto* data = reinterpret_cast<const uint8_t*>(img.GetDataPtr());

    QImage qi(w, h, QImage::Format_RGB888);
    if (channels == 3) {
        for (int y = 0; y < h; ++y) {
            const uint8_t* src = data + y * w * 3;
            uint8_t* dst = qi.scanLine(y);
            for (int x = 0; x < w; ++x) {
                dst[x * 3 + 0] = src[x * 3 + 2];  // R from BGR[2]
                dst[x * 3 + 1] = src[x * 3 + 1];  // G from BGR[1]
                dst[x * 3 + 2] = src[x * 3 + 0];  // B from BGR[0]
            }
        }
    } else {
        for (int y = 0; y < h; ++y) {
            const uint8_t* src = data + y * w * channels;
            uint8_t* dst = qi.scanLine(y);
            for (int x = 0; x < w; ++x) {
                uint8_t v = src[x * channels];
                dst[x * 3 + 0] = v;
                dst[x * 3 + 1] = v;
                dst[x * 3 + 2] = v;
            }
        }
    }
    return qi;
}

void DetectionEngine::extractColors(const RVC::Image& img, std::vector<float>& rgbOut)
{
    int w = img.GetSize().cols;
    int h = img.GetSize().rows;
    int total = w * h;
    int channels = (img.GetType() == RVC::ImageType::BGR8 ||
                    img.GetType() == RVC::ImageType::RGB8) ? 3 : 1;
    auto* data = reinterpret_cast<const uint8_t*>(img.GetDataPtr());

    rgbOut.reserve(total * 3);
    for (int i = 0; i < total; ++i) {
        if (channels >= 3) {
            rgbOut.push_back(data[i * 3 + 2] / 255.0f);  // R from BGR[2]
            rgbOut.push_back(data[i * 3 + 1] / 255.0f);  // G from BGR[1]
            rgbOut.push_back(data[i * 3 + 0] / 255.0f);  // B from BGR[0]
        } else {
            float v = data[i * channels] / 255.0f;
            rgbOut.push_back(v);
            rgbOut.push_back(v);
            rgbOut.push_back(v);
        }
    }
}

// ═══════════════════════════════════════════════════════════════
// Formatting utilities
// ═══════════════════════════════════════════════════════════════

std::string DetectionEngine::formatXyzForCard(const std::vector<Vec3f>& pts3d)
{
    for (const auto& p : pts3d) {
        if (std::isnan(p[0]) || std::isnan(p[1]) || std::isnan(p[2]))
            continue;

        std::ostringstream oss;
        oss << std::fixed << std::setprecision(3)
            << p[0] << " " << p[1] << " " << p[2];
        return oss.str();
    }
    return {};
}

std::vector<float> DetectionEngine::firstValidPoint3d(const std::vector<Vec3f>& pts3d)
{
    for (const auto& p : pts3d) {
        if (std::isnan(p[0]) || std::isnan(p[1]) || std::isnan(p[2]))
            continue;
        return { p[0], p[1], p[2] };
    }
    return {};
}

MarkerOverlay
DetectionEngine::formatMarkersForOverlay(const std::vector<Vec2f>& pts2d,
                                         const std::vector<Vec3f>& pts3d)
{
    MarkerOverlay overlay;

    for (size_t i = 0; i < pts2d.size(); ++i) {
        float x = pts2d[i].first;
        float y = pts2d[i].second;
        std::string label = std::to_string(i);
        overlay.overlay2d.emplace_back(x, y, label);

        if (i < pts3d.size()) {
            const auto& p = pts3d[i];
            if (!std::isnan(p[0]) && !std::isnan(p[1]) && !std::isnan(p[2])) {
                overlay.highlights3d.push_back(p);
                overlay.highlightIndices.push_back(static_cast<int>(i));
            }
        }
    }
    return overlay;
}
