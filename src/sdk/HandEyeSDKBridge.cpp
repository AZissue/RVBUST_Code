#include "sdk/HandEyeSDKBridge.h"
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <cmath>
#include <cstdio>
#include <algorithm>

namespace HandEyeSDKBridge {

using Vec2f = std::pair<float, float>;
using Vec3f = std::array<float, 3>;

// ── SEH-safe wrappers ──

template<typename F>
static bool safeCall(F&& fn) {
    __try {
        fn();
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        fprintf(stderr, "[HandEyeSDK] SEH exception caught — DLL may have crashed\n");
        return false;
    }
}

// ── Concentric circles ──

std::vector<Vec2f> detectConcentricCircles2D(const std::string& imagePath)
{
    int num = 0;
    float pixelXy[200] = {};

    bool ok = safeCall([&]() {
        DetectConcentricCircles2D(imagePath.c_str(), &num, pixelXy);
    });
    if (!ok || num <= 0) return {};
    num = std::min(num, 100);  // pixelXy[200] holds at most 100 points

    std::vector<Vec2f> result;
    result.reserve(num);
    for (int i = 0; i < num; ++i)
        result.emplace_back(pixelXy[i * 2], pixelXy[i * 2 + 1]);
    return result;
}

std::pair<std::vector<Vec2f>, std::vector<Vec3f>>
detectConcentricCircles3D(const std::string& imagePath, const std::string& plyPath)
{
    int num = 0;
    float pixelXy[200] = {};
    float pointXyz[300] = {};

    fprintf(stderr, "[HandEyeSDK] DetectConcentricCircles3D: img=%s ply=%s\n",
            imagePath.c_str(), plyPath.c_str());

    bool ok = safeCall([&]() {
        DetectConcentricCircles3D(imagePath.c_str(), plyPath.c_str(), &num, pixelXy, pointXyz);
    });
    fprintf(stderr, "[HandEyeSDK] DetectConcentricCircles3D: ok=%d num=%d\n", ok, num);
    if (!ok || num <= 0) return {{},{}};
    num = std::min(num, 100);  // pixelXy[200] / pointXyz[300] hold at most 100 points

    std::vector<Vec2f> pts2d;
    std::vector<Vec3f> pts3d;
    pts2d.reserve(num);
    pts3d.reserve(num);
    for (int i = 0; i < num; ++i) {
        pts2d.emplace_back(pixelXy[i * 2], pixelXy[i * 2 + 1]);
        Vec3f p3 = {{pointXyz[i * 3], pointXyz[i * 3 + 1], pointXyz[i * 3 + 2]}};
        if (std::isnan(p3[0]) || std::isnan(p3[1]) || std::isnan(p3[2]))
            p3 = {{NAN, NAN, NAN}};
        pts3d.push_back(p3);
    }
    return {pts2d, pts3d};
}

// ── Caliboard ──

std::vector<float>
detectCaliboard2D(const std::string& imagePath,
                  const float intrinsic[9], const float distortion[5],
                  int patternW, int patternH)
{
    float pixelXy[200] = {};
    const int expected = patternW * patternH;
    if (expected <= 0 || expected > 100) {
        fprintf(stderr, "[HandEyeSDK] DetectCaliboard2D: pattern %dx%d exceeds buffer (max 100 points)\n",
                patternW, patternH);
        return {};
    }

    bool ok = safeCall([&]() {
        DetectCaliboard2D(imagePath.c_str(), intrinsic, distortion,
                         patternW, patternH, pixelXy);
    });
    if (!ok) return {};

    std::vector<float> result;
    result.reserve(expected * 2);
    for (int i = 0; i < expected; ++i) {
        float x = pixelXy[i * 2];
        float y = pixelXy[i * 2 + 1];
        if (x == 0.0f && y == 0.0f) break;
        result.push_back(x);
        result.push_back(y);
    }
    return result;
}

Caliboard3DResult
detectCaliboard3D(const std::string& imagePath, const std::string& plyPath,
                  const float intrinsic[9], const float distortion[5],
                  int patternW, int patternH, float circleStep)
{
    if (patternW <= 0 || patternH <= 0 || patternW * patternH > 100) {
        fprintf(stderr, "[HandEyeSDK] DetectCaliboard3D: pattern %dx%d exceeds buffer (max 100 points)\n",
                patternW, patternH);
        return {};
    }

    fprintf(stderr, "[HandEyeSDK] DetectCaliboard3D: img=%s ply=%s pattern=%dx%d step=%.4f\n",
            imagePath.c_str(), plyPath.c_str(), patternW, patternH, circleStep);
    fprintf(stderr, "[HandEyeSDK] intrinsic: %.3f %.3f %.3f %.3f %.3f %.3f %.3f %.3f %.3f\n",
            intrinsic[0], intrinsic[1], intrinsic[2],
            intrinsic[3], intrinsic[4], intrinsic[5],
            intrinsic[6], intrinsic[7], intrinsic[8]);
    fprintf(stderr, "[HandEyeSDK] distortion: %.5f %.5f %.5f %.5f %.5f\n",
            distortion[0], distortion[1], distortion[2], distortion[3], distortion[4]);

    Caliboard3DResult r;
    float pixelXy[200] = {};
    float pointXyz[300] = {};

    bool ok = safeCall([&]() {
        DetectCaliboard3D(imagePath.c_str(), plyPath.c_str(), intrinsic, distortion,
                         patternW, patternH, circleStep,
                         pixelXy, pointXyz, r.measuringDistance, r.errorPercentage);
    });
    fprintf(stderr, "[HandEyeSDK] DetectCaliboard3D: ok=%d measDist=%.2f errPct=%.2f\n",
            (int)ok, r.measuringDistance, r.errorPercentage);

    if (!ok) return r;

    // Count non-zero pixel coordinates
    int validCount = 0;
    for (int i = 0; i < 100; ++i) {
        if (pixelXy[i * 2] != 0.0f || pixelXy[i * 2 + 1] != 0.0f)
            ++validCount;
    }
    fprintf(stderr, "[HandEyeSDK] DetectCaliboard3D: validPoints=%d\n", validCount);

    r.pixelXy.assign(pixelXy, pixelXy + 200);
    r.pointXyz.assign(pointXyz, pointXyz + 300);
    return r;
}

// ── Calibration ──

int handEyeCalibrationMarker(const std::string& folder,
                             const std::string& robotPoseFile,
                             const HandEyeParam& params, HandEyeResult& result)
{
    int ret = -1;
    safeCall([&]() {
        ret = HandEyeCalibrationMarker(folder.c_str(), robotPoseFile.c_str(), params, result);
    });
    return ret;
}

int handEyeCalibrationTcpTouch(const std::string& cameraXyzFile,
                               const std::string& robotPoseFile,
                               const std::string& tcpXyzFile,
                               const HandEyeParam& params, HandEyeResult& result)
{
    int ret = -1;
    safeCall([&]() {
        ret = HandEyeCalibrationTcpTouch(cameraXyzFile.c_str(), robotPoseFile.c_str(),
                                         tcpXyzFile.c_str(), params, result);
    });
    return ret;
}

int transformPointCloudsToRobotBase(const std::string& folder,
                                    const std::string& robotPoseFile,
                                    int poseType, bool isMm,
                                    bool isPoseMm, bool isPoseDegree,
                                    bool isEyeInHand,
                                    const double matrix[16])
{
    int ret = -1;
    safeCall([&]() {
        ret = TransformPointCloudsToRobotBase(folder.c_str(), robotPoseFile.c_str(),
                                              poseType, isMm, isPoseMm,
                                              isPoseDegree, isEyeInHand, matrix);
    });
    return ret;
}

} // namespace HandEyeSDKBridge
