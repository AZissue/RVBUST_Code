#pragma once

#include <QString>
#include <array>
#include <vector>

#include "models/CalibrationMode.h"

// Hand-eye calibration computation backed by the RVC HandEyeSDK.
//
// Two SDK entry points, two data layouts:
//   * 标定板（同心圆 / 黑底白圆）— HandEyeCalibrationMarker(folder, poseFile, …):
//     a folder of .ply + .png, one robot pose per frame.
//   * 戳点标定 — HandEyeCalibrationTcpTouch(cameraFile, poseFile, tcpFile, …):
//     相机目标点 / 机器人目标点（戳点）各一列，眼在手上再加一列机器人拍照位姿；
//     眼在手外没有拍照位姿，SDK 要的是 nullptr（不是空字符串）。
//
// `calibrate()` 是唯一入口，按 Params::calibType 分派 —— 两个界面页都只调它，
// 避免"某个页面没有跟着标定方式改"这类分叉（原来两个页面都无条件走
// calibrateMarker，于是戳点标定必然失败在"第 1 组机器人拍照位姿格式无效"）。
namespace CalibrationService {

struct Params {
    CalibType calibType = CalibType::Marker;
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
    std::vector<int> success2D;      // empty = 本接口不报告（戳点标定）
    std::vector<int> success3D;
    double totalMeanError = 0.0;
    int usedCount = 0;               // frames the SDK actually used
};

// Normalize one robot-pose line ("x y z rx ry rz", spaces or English commas)
// into the SDK's comma-separated format.  Returns empty on invalid input.
QString normalizePoseLine(const QString& raw);

// Normalize a 3-number line ("x y z") the same way.
QString normalizeXyzLine(const QString& raw);

// SDK return code -> Chinese message (HandEyeCalibrationMarker code space).
QString errorText(int retCode);

// SDK return code -> Chinese message (HandEyeCalibrationTcpTouch code space;
// the two tables do NOT agree — e.g. -2 is "有效数据不足 6 组" for Marker but
// "相机点位数据无效" for TcpTouch).
QString tcpErrorText(int retCode);

// Render a Result as the user-facing body shown in both GUIs (main window's
// calculate view and the tools panel's hand-eye page): the success summary
// with the matrix and per-frame errors, or the failure line.  Single source of
// truth so the wording lives in one place.
QString formatResult(const Result& r);

// Run marker (标定板) calibration.  folder contains 1.png..N.png / 1.ply..N.ply
// and poseLines must have N entries matching record order.
Result calibrateMarker(const QString& folder,
                       const std::vector<QString>& poseLines,
                       const Params& params);

// Run TCP-touch calibration.  cameraLines / tcpLines are one "x y z" line per
// frame; poseLines is the robot capture pose, used only for eye-in-hand (ignored
// for eye-to-hand, where the SDK is handed a null pose file).
Result calibrateTcpTouch(const std::vector<QString>& cameraLines,
                         const std::vector<QString>& poseLines,
                         const std::vector<QString>& tcpLines,
                         const Params& params);

// Single entry point: dispatches on params.calibType.  `folder` is only used by
// the marker path (the TCP-touch path works entirely from the in-memory columns).
Result calibrate(const QString& folder,
                 const std::vector<QString>& cameraLines,
                 const std::vector<QString>& poseLines,
                 const std::vector<QString>& tcpLines,
                 const Params& params);

} // namespace CalibrationService
