#pragma once

// 3D measurement kernels (stage 9), ported from the Python "3D 测量一体化工具"
// (源码/mcore.py) with the same numerical conventions:
//
//   * units are millimetres and degrees throughout;
//   * a fitted plane's normal is always oriented so n[2] < 0 — it points back
//     towards the camera.  A point standing proud of the plane therefore has a
//     *positive* signed deviation, which is what "凸起为正" means in the reports;
//   * outliers are rejected with the same robust rule the Python tool uses:
//     keep |v - median(v)| <= k * 1.4826 * MAD(v) (k = 3 by default).  This is
//     the same MAD-scaled sigma used by the ±3σ_MAD colour limits.
//
// No Qt, no GUI, no SDK: everything here is pure computation over point sets so
// the whole measurement path is unit-testable.
#include <array>
#include <cmath>
#include <cstddef>
#include <string>
#include <vector>

namespace MeasureTools {

using Vec3 = std::array<double, 3>;

// ── small shared helpers ───────────────────────────────────────────────

inline bool isFinite(const Vec3& p)
{
    return std::isfinite(p[0]) && std::isfinite(p[1]) && std::isfinite(p[2]);
}

// Drops non-finite points (the organized grid is full of NaN outside the
// valid measurement volume).
std::vector<Vec3> finitePoints(const std::vector<Vec3>& pts);

// Robust colour limits: lo/hi = median ∓ k * 1.4826 * MAD, i.e. a ±3σ_MAD band
// **centred on the median**, deliberately not a percentile range.
//
// The Python tool paints the deviation map this way because one flyer at the
// ROI edge would otherwise stretch a percentile range to ±1 mm and flatten
// every real deviation into the middle colour.  Percentiles are only the
// fallback for a degenerate MAD (a perfectly flat ROI); values outside the band
// are clamped to the end colours and counted in `nClipped`.
struct Limits {
    double lo = 0.0;
    double hi = 0.0;
    std::size_t nClipped = 0;
    bool robust = false;    // true when the ±3σ_MAD rule produced the band
    bool valid = false;
};
Limits robustLimits(const std::vector<double>& values, double madK = 3.0,
                    double clipLoPct = 1.0, double clipHiPct = 99.0);

// ── 1. plane + flatness ────────────────────────────────────────────────

struct Plane {
    Vec3 normal{};      // unit, oriented n[2] <= 0
    double d = 0.0;     // plane equation: normal · p + d = 0
    double rms = 0.0;   // residual RMS of the fitted point set
    std::size_t used = 0;
    bool valid = false;
    std::string message;
};

// Least-squares plane through the point set: centroid + smallest-eigenvector of
// the covariance (PCA, the same answer as the Python SVD form).
Plane fitPlane(const std::vector<Vec3>& pts);

// Signed distance of every point from the plane (positive = towards camera).
std::vector<double> deviations(const std::vector<Vec3>& pts, const Plane& plane);

struct Flatness {
    double lsqPv = 0.0;        // least-squares PV = max dev - min dev
    double lsqRms = 0.0;       // RMS of the same deviations
    double mzPv = 0.0;         // minimum-zone PV  (mzPv <= lsqPv always holds)
    double tiltDeg = 0.0;      // tilt of the minimum-zone plane vs. the LSQ plane
    std::size_t used = 0;      // points left after MAD rejection
    std::vector<double> dev;   // signed deviation of *every* input point
    Plane plane;
    bool valid = false;
    std::string message;
};

// Flatness of a ROI.
//
// LSQ PV is what a least-squares plane gives; the drawing (and a gauge) means
// minimum zone, which is smaller.  Both are reported, exactly like the Python
// tool: the MZ plane is found by a 2-DOF coordinate descent on (tiltX, tiltY)
// that minimises the residual PV, and if the descent fails to improve on the
// LSQ solution the LSQ value is kept — so mzPv <= lsqPv holds unconditionally.
Flatness flatness(const std::vector<Vec3>& pts, double madK = 3.0, int maxIter = 60);

// ── 2. height / step between two ROIs ──────────────────────────────────

struct Height {
    double value = 0.0;        // signed, robust (median) distance, positive = proud
    double rms = 0.0;          // spread of the accepted target points
    std::size_t usedRef = 0;
    std::size_t usedTarget = 0;
    Plane ref;                 // the fitted datum plane
    bool valid = false;
    std::string message;
};

// Fits a datum plane on `refPoints` and reports the robust signed height of
// `targetPoints` above it (median after MAD rejection — a step's edges and
// stray points must not drag the number around).
Height heightBetween(const std::vector<Vec3>& refPoints,
                     const std::vector<Vec3>& targetPoints,
                     double madK = 3.0);

// ── 3. plane-to-plane angle and parallel distance ──────────────────────

struct PlanePair {
    double angleDeg = 0.0;     // unsigned angle between the two planes, 0..90
    double distanceMm = 0.0;   // only meaningful when `parallel` is true
    bool parallel = false;     // angleDeg <= tolerance
    std::size_t usedA = 0;
    std::size_t usedB = 0;
    Plane planeA;
    Plane planeB;
    bool valid = false;
    std::string message;
};

// Angle always; the distance only when the two planes are parallel within
// `parallelTolDeg` (a "distance" between two tilted planes is meaningless).
PlanePair planePair(const std::vector<Vec3>& ptsA, const std::vector<Vec3>& ptsB,
                    double parallelTolDeg = 3.0, double madK = 3.0);

// Angle between two already-fitted planes (0..90 degrees).
double planeAngleDeg(const Plane& a, const Plane& b);

// Robust signed distance of `target` from `ref` (median after MAD rejection).
bool planeDistanceMm(const Plane& ref, const std::vector<Vec3>& target,
                     double* outMm, std::size_t* usedOut, double madK = 3.0);

// ── 4. circle ──────────────────────────────────────────────────────────

struct Circle {
    Vec3 center{};             // 3D centre
    Vec3 normal{};             // circle plane normal, oriented n[2] <= 0
    double radius = 0.0;
    double diameter = 0.0;
    double roundness = 0.0;    // max radius - min radius (PV)
    double rms = 0.0;
    double spanDeg = 0.0;      // angular coverage of the points
    std::size_t used = 0;
    bool valid = false;
    std::string message;
};

// Space circle: fit the plane, project, then an algebraic (Kåsa) least-squares
// circle in that plane.  `outlierIters` passes of MAD rejection drop the stray
// points a projected ROI edge always contributes (the Python tool uses the same
// iterative robust re-fit).
Circle fitCircle(const std::vector<Vec3>& pts, int outlierIters = 2, double madK = 2.5);

// ── 5. oriented bounding box ───────────────────────────────────────────

struct BoundingBox {
    double length = 0.0;       // longest side
    double width = 0.0;
    double height = 0.0;       // shortest side
    Vec3 center{};
    // Row-major 3x3, rows = the three box axes (longest first).
    std::array<double, 9> axes{};
    std::size_t used = 0;
    bool valid = false;
    std::string message;
};

// PCA oriented bounding box: extents along the three principal axes, sorted
// long -> short.  Unlike an axis-aligned box this does not inflate when the
// part sits at an angle in the field of view.
BoundingBox pcaBoundingBox(const std::vector<Vec3>& pts);

// ── 6. repeatability ───────────────────────────────────────────────────

struct Repeatability {
    std::size_t n = 0;
    double mean = 0.0;
    double stdDev = 0.0;       // sample standard deviation (n-1), as in Python
    double range = 0.0;        // max - min
    double sixSigma = 0.0;     // 6 * stdDev  (±3σ band width)
    double min = 0.0;
    double max = 0.0;
    double maxDev = 0.0;       // max |value - mean|
    bool valid = false;
};

// Multi-shot repeatability of one measurement.  Non-finite values are dropped;
// a single value yields stdDev = 0.
Repeatability repeatability(const std::vector<double>& values);

// ── ROI helpers (shared by the 2D panel and the 3D overlay) ────────────

// Organized-grid ROI extraction: the captured grid is w*h*3 doubles
// (row-major, y-major) with NaN outside the valid volume.  The rectangle is
// clamped to the grid; the result keeps only finite points.
std::vector<Vec3> pointsInRoi(const std::vector<double>& grid, int w, int h,
                              int x0, int y0, int x1, int y1);

// Same extraction, but also reporting each point's grid cell index (the
// deviation map uses it to paint every sample where it belongs in the image).
std::vector<Vec3> pointsInRoiIndexed(const std::vector<double>& grid, int w, int h,
                                     int x0, int y0, int x1, int y1,
                                     std::vector<std::size_t>* cellIndexOut);

// Section profile: project the points on the ROI's principal in-plane
// direction, bin them, and report the median height (z) of each bin.  Returns
// pairs of (distance along the section, height) — this is the polyline the
// 截面轮廓 page draws.
struct SectionProfile {
    std::vector<std::array<double, 2>> points;   // (t, z)
    double tMin = 0.0;
    double tMax = 0.0;
    double stepMm = 0.0;
    bool valid = false;
    std::string message;
};
SectionProfile sectionProfile(const std::vector<Vec3>& pts, int bins = 64);

// ── Deviation colouring (偏差图 / 3D 偏差着色) ──────────────────────────

// The Python reference's `colormap(t)` (mviz.py): coolwarm for surface
// deviations, turbo for profile/line deviations.  `t` is clamped to [0, 1].
std::array<double, 3> colormap(double t, bool coolWarm);

// Per-point RGB for the organized 3D grid — one triple per point of the *flat
// cloud*, i.e. index-aligned with PointCloudUtils::filterValidPoints' output.
// The validity rule is deliberately identical to that function's (skip NaN,
// skip exact (0,0,0), row-major) so the result can be handed to
// VisSceneView::updatePointCloud together with that same cloud.
//
// Cells listed in `highlightCells` (grid indices, e.g. the measured ROI) are
// coloured by their signed distance to `plane` mapped onto the [lo, hi] band;
// every other valid cell gets `baseRgb`, so the measured region stays readable
// in context instead of colouring the whole scene by a local plane fit.
std::vector<std::array<float, 3>> cloudDeviationColors(
    const std::vector<double>& grid, int w, int h, const Plane& plane,
    double lo, double hi, bool coolWarm,
    const std::vector<std::size_t>& highlightCells,
    const std::array<float, 3>& baseRgb = { 0.28f, 0.30f, 0.34f });

} // namespace MeasureTools
