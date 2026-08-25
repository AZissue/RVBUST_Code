#pragma once
#include <HandEye.h>
#include <vector>
#include <string>
#include <cstdint>
#include <array>

namespace HandEyeSDKBridge {

// ── Detection wrappers ──

std::vector<std::pair<float, float>>
detectConcentricCircles2D(const std::string& imagePath);

std::pair<std::vector<std::pair<float, float>>,
          std::vector<std::array<float, 3>>>
detectConcentricCircles3D(const std::string& imagePath,
                          const std::string& plyPath);

// "flat" variant for caliboard-style output: [x0,y0,x1,y1,...]
std::vector<float>
detectCaliboard2D(const std::string& imagePath,
                  const float intrinsic[9],
                  const float distortion[5],
                  int patternW, int patternH);

struct Caliboard3DResult {
    std::vector<float> pixelXy;       // flat [x0,y0,x1,y1,...]
    std::vector<float> pointXyz;      // flat [x0,y0,z0,x1,y1,z1,...]
    float measuringDistance = 0.0f;
    float errorPercentage = 0.0f;
};

Caliboard3DResult
detectCaliboard3D(const std::string& imagePath,
                  const std::string& plyPath,
                  const float intrinsic[9],
                  const float distortion[5],
                  int patternW, int patternH,
                  float circleStep);

// ── Calibration wrappers (not called from this app, declared for completeness) ──

int handEyeCalibrationMarker(const std::string& folder,
                             const std::string& robotPoseFile,
                             const HandEyeParam& params,
                             HandEyeResult& result);

int handEyeCalibrationTcpTouch(const std::string& cameraXyzFile,
                               const std::string& robotPoseFile,
                               const std::string& tcpXyzFile,
                               const HandEyeParam& params,
                               HandEyeResult& result);

int transformPointCloudsToRobotBase(const std::string& folder,
                                    const std::string& robotPoseFile,
                                    int poseType, bool isMm,
                                    bool isPoseMm, bool isPoseDegree,
                                    bool isEyeInHand,
                                    const double matrix[16]);

} // namespace HandEyeSDKBridge
