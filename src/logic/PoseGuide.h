#pragma once

#include <array>
#include <cmath>
#include <vector>

#include "logic/TransformTools.h"

// Pure pose-diversity helpers for the calibration capture flow (stage 8).
//
// Hand-eye calibration (AX=XB) is well-conditioned only when the collected
// robot poses are spread in both translation and orientation.  PoseGuide
// measures, for a freshly captured/read pose, how far it is from the poses
// already collected, so the operator can be nudged to "spread out" before the
// next frame.  Advisory only — it never gates capture/save/calibrate.
namespace PoseGuide {

struct Pose {
    std::array<double, 3> xyz{};     // mm
    std::array<double, 3> rpyDeg{};  // degrees, static XYZ (R = Rz·Ry·Rx)
};

constexpr double DEFAULT_MIN_POS_MM = 50.0;
constexpr double DEFAULT_MIN_ANGLE_DEG = 15.0;

// Translation distance between two poses (mm).
inline double translationMm(const Pose& a, const Pose& b)
{
    const double dx = a.xyz[0] - b.xyz[0];
    const double dy = a.xyz[1] - b.xyz[1];
    const double dz = a.xyz[2] - b.xyz[2];
    return std::sqrt(dx * dx + dy * dy + dz * dz);
}

// Minimal (geodesic) rotation angle between two orientations, in degrees.
// Uses the same static-XYZ RPY convention (R = Rz·Ry·Rx) as the calibration
// card, the robot reader and the coordinate-transform tool.
inline double rotationAngleDeg(const Pose& a, const Pose& b)
{
    constexpr double rad = 3.14159265358979323846 / 180.0;
    const TransformTools::Rot3 ra = TransformTools::eulerRpy(
        a.rpyDeg[0] * rad, a.rpyDeg[1] * rad, a.rpyDeg[2] * rad);
    const TransformTools::Rot3 rb = TransformTools::eulerRpy(
        b.rpyDeg[0] * rad, b.rpyDeg[1] * rad, b.rpyDeg[2] * rad);
    // trace(ra^T · rb) of the relative rotation -> geodesic angle.
    double trace = 0.0;
    for (int col = 0; col < 3; ++col)
        for (int row = 0; row < 3; ++row)
            trace += ra[row * 3 + col] * rb[row * 3 + col];
    const double c = 0.5 * (trace - 1.0);
    const double clamped = c > 1.0 ? 1.0 : (c < -1.0 ? -1.0 : c);
    return std::acos(clamped) / rad;
}

// Advisory verdict for one pose against the already-collected set.
struct Guide {
    bool hasReference = false;  // false when there is no collected pose yet
    double distanceMm = 0.0;    // distance to the nearest collected pose
    double angleDeg = 0.0;      // rotation angle to that nearest pose
    int refIndex = -1;          // 0-based index of the nearest pose
    bool tooClose = false;      // close in BOTH translation and orientation
};

inline Guide guide(const Pose& p, const std::vector<Pose>& collected,
                   double minPosMm = DEFAULT_MIN_POS_MM,
                   double minAngleDeg = DEFAULT_MIN_ANGLE_DEG)
{
    Guide g;
    if (collected.empty())
        return g;

    // Nearest neighbour by translation (used for the "distance vs nearest"
    // message the card shows).
    g.hasReference = true;
    g.refIndex = 0;
    g.distanceMm = translationMm(p, collected[0]);
    g.angleDeg = rotationAngleDeg(p, collected[0]);
    for (std::size_t i = 1; i < collected.size(); ++i) {
        const double d = translationMm(p, collected[i]);
        if (d < g.distanceMm) {
            g.distanceMm = d;
            g.angleDeg = rotationAngleDeg(p, collected[i]);
            g.refIndex = static_cast<int>(i);
        }
    }

    // "Too close" means some collected pose is near in BOTH dimensions.
    g.tooClose = false;
    for (const auto& other : collected) {
        if (translationMm(p, other) < minPosMm
                && rotationAngleDeg(p, other) < minAngleDeg) {
            g.tooClose = true;
            break;
        }
    }
    return g;
}

} // namespace PoseGuide
