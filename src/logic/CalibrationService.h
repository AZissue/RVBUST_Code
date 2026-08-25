#pragma once

#include <QString>
#include <array>
#include <vector>

// Hand-eye calibration computation backed by the RVC HandEyeSDK.
//
// The SDK's HandEyeCalibrationMarker() takes a folder with .ply + .png files
// and one robot pose per frame.  This service stages the session files into a
// temp folder with zero-padded names (so file order == record order), writes a
// normalized comma-separated pose file, runs the SDK, and maps its return code
// to a user-facing message.
namespace CalibrationService {

struct Params {
    bool eyeInHand = true;          // camera mounted on the robot flange
    int markerType = 1;             // 0 = asymmetric circle grid, 1 = concentric
    bool isPoseMm = true;           // pose position unit
    bool isPoseDegree = true;       // pose angle unit
    bool autoRemoveLargeError = true;
};

struct Result {
    bool ok = false;
    QString error;
    int retCode = -1;
    std::array<double, 16> matrix{};
    std::vector<double> errors;      // per-frame error from the SDK
    std::vector<int> success2D;
    std::vector<int> success3D;
    double totalMeanError = 0.0;
    int usedCount = 0;               // frames the SDK actually used
};

// Normalize one robot-pose line ("x y z rx ry rz", spaces or English commas)
// into the SDK's comma-separated format.  Returns empty on invalid input.
QString normalizePoseLine(const QString& raw);

// SDK return code -> Chinese message.
QString errorText(int retCode);

// Run marker calibration.  folder contains 1.png..N.png / 1.ply..N.ply and
// poseLines must have N entries matching record order.
Result calibrateMarker(const QString& folder,
                       const std::vector<QString>& poseLines,
                       const Params& params);

} // namespace CalibrationService
