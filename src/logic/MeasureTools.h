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

// ── measurement methods ────────────────────────────────────────────────
//
// One entry per tool in the panel's left list.  The enum lives here (and not in
// the UI header) because the *ROI requirement* of a method is a fact the tests
// check, not a cosmetic detail: asking for one ROI when the algorithm needs two
// is a silent wrong answer, not a layout problem.
enum class Method {
    Flatness = 0,      // 平面度
    StepHeight,        // 高度段差（面到面高度）
    PlanePair,         // 面面距离/夹角
    RingCircle,        // 圆环拟合（ROI 必须是环形材料）
    HoleDiameter,      // 孔径（孔洞边界法）
    BoundingBox,       // 包围盒
    Section,           // 截面轮廓
    Repeatability,     // 重复性统计
    Count
};

// 2 = datum + measured region, 1 = one region, 0 = works on a stored value.
inline int roiCountFor(Method m)
{
    switch (m) {
    case Method::StepHeight:
    case Method::PlanePair:      return 2;
    case Method::Repeatability:  return 0;
    case Method::Count:          return 0;
    default:                     return 1;
    }
}

// Stable ASCII id (logs, manifests, test data).  Never localized.
inline const char* methodId(Method m)
{
    switch (m) {
    case Method::Flatness:      return "flatness";
    case Method::StepHeight:    return "step_height";
    case Method::PlanePair:     return "plane_pair";
    case Method::RingCircle:    return "ring_circle";
    case Method::HoleDiameter:  return "hole_diameter";
    case Method::BoundingBox:   return "bounding_box";
    case Method::Section:       return "section";
    case Method::Repeatability: return "repeatability";
    case Method::Count:         break;
    }
    return "unknown";
}

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

// ── 7. hole diameter (material inner boundary, sector method) ──────────
//
// A rectangular ROI dragged around a hole is *mostly material* — only the rim
// crosses it.  Fitting one circle through all of those points (fitCircle)
// answers a different question than "how big is the hole": it measures the
// shape of the ROI.  This method measures what the operator means:
//
//   1. fit the material plane robustly over the ROI points;
//   2. keep only points inside a narrow band around that plane, so the hole's
//      inner wall, its floor and the background behind a through-hole cannot
//      act as material;
//   3. cut the ROI into angular sectors around the ROI centre, with the sector
//      width chosen so that one sector holds one rim point (see below);
//   4. take the *innermost* material point of every sector — the material
//      boundary;
//   5. a boundary sample sits somewhere in [0, pitch) outside the true edge, so
//      the median radius is corrected by half the estimated point pitch (the
//      usual half-sample correction);
//   6. fit a circle through the boundary samples for the centre, the roundness
//      and the confidence, and report the corrected diameter/radius.
//
// The *median* (step 5) is what makes the answer insensitive to a ROI that is
// not exactly centred on the hole: an origin offset e shifts a sector radius by
// -e·cos(theta), and the median of a full cosine cycle is 0 — the residual error
// is only second order, e²/2R.
//
// **How many sectors.**  Step 5 corrects "one boundary sample per sector" by
// half a pitch, so a sector must hold one rim point.  A sector wide enough to
// hold several reports the smallest of them, and the radius comes out low by a
// large fraction of a pitch — on the known-truth data a fixed 36-sector fan over
// a 1 mm pitch read 6.32 mm for a ⌀5 hole.  The sector count is therefore
// derived from the data: about 2πR/pitch sectors (bounded to 12..720), i.e. one
// pitch of arc at the boundary radius.  `minSectors` is the fallback used when
// no point pitch can be estimated at all.
//
// **Where the fan origin comes from.**  The sectors must radiate from a point
// *inside* the hole; the ROI's own centre cell is a hole cell and has no 3D
// point at all (NaN), so there is nothing for the caller to hand in — asking the
// caller for a "centre point" is how a ROI-centre lookup ends up on the rim, and
// a fan centred on the rim reports nothing but its own offset (the radii spread
// from 0 to 2R and the "diameter" comes out with an error of the order of R).
// The origin is therefore computed here, and only in-plane: the centroid of the
// material points surviving the plane band.  For the ROI this method is defined
// for — a rectangle drawn tightly around a hole — the material is a ring and its
// centroid *is* the hole centre.  A ROI drawn so lopsidedly that the centroid
// leaves the hole makes step 3 pick up the ROI's own edge instead of the rim;
// that shows up as a roundness comparable to the radius and an empty coverage
// fraction, and `reliable` goes false rather than the method returning a
// confident wrong number.
struct HoleBoundary {
    double diameter = 0.0;        // primary: 2 * (fitted radius - pitch/2)
    double radius = 0.0;          // fitted radius - pitch/2
    double fitDiameter = 0.0;     // uncorrected fit (raw boundary points)
    double medianDiameter = 0.0;  // 2 * (median sector radius - pitch/2)
    Vec3 center{};                // fitted centre (corrected radius kept)
    Vec3 fanOrigin{};             // the sector fan origin actually used (material centroid)
    Vec3 normal{};                // plane normal, oriented n[2] <= 0
    double pitch = 0.0;           // estimated material point pitch, mm
    double pitchCorrection = 0.0; // pitch / 2
    double roundness = 0.0;       // max - min of the boundary samples
    double rms = 0.0;             // RMS of the boundary samples about the fit
    double medianRadius = 0.0;    // median of the per-sector radii
    int sectors = 0;              // sectors actually used (derived from the pitch)
    int sectorsUsed = 0;          // sectors that found material
    // sectorsUsed over the number of rim samples the pitch allows (2πR/pitch),
    // not over `sectors`: a coarse pitch cannot deliver more samples than that,
    // and a ROI that clips the hole loses samples against this expectation.
    double coverage = 0.0;
    double bandMm = 0.0;          // plane band actually used
    std::size_t roiPoints = 0;    // finite points handed in
    std::size_t materialPoints = 0;  // points left inside the band
    std::size_t used = 0;         // boundary samples fed to the circle fit
    bool reliable = false;        // coverage and roundness checks passed
    bool valid = false;
    std::string message;
};

HoleBoundary holeBoundary(const std::vector<Vec3>& roiPoints, int minSectors = 36,
                          double bandSigmaK = 3.0, double minCoverage = 0.75);

// ── 8. boundary circle (image-guided sub-pixel edge) ───────────────────
//
// T-012.  The two tools above answer "what does the *point set* look like",
// which is not the same question as "where is the edge of the part": on a
// ⌀63.5 solid disc the Kåsa fit returns the material's statistical radius
// (√(2/3)·R for a uniform disc, less with the relief slots) — 48 mm instead of
// 63.5 — and the 3-D grid's own pitch (0.0755 mm) is already 0.6 % of a ⌀6
// hole, an order of magnitude coarser than the 0.2 % the drawing demands.
//
// This kernel keeps the *geometry* in the 3-D cloud and takes the *sub-pixel
// position of the edge* from the captured grayscale image:
//
//   * the boundary is defined by material, not by the ROI.  A hole is
//     material-outside; an outer edge (a solid disc, a step's outer rim) is
//     material-inside and is found by growing the material region outwards
//     from the ROI, which is exactly the capability that did not exist;
//   * the edge itself is the intensity inflection point along a ray, located
//     to ~0.1 px by parabolic interpolation of the radial gradient — at
//     0.075 mm/px that is ~0.008 mm, inside the 0.2 % budget;
//   * pixels are mapped into the fitted plane by a least-squares affine fit
//     (the local approximation of the perspective map), so the circle is
//     fitted without the foreshortening an image-space fit would carry.
//
// When no image is handed in (or no edge can be found) the result falls back
// to the 3-D boundary and says so (`subpixel = false`) rather than returning a
// confident wrong number.

// 8-bit grayscale view of the captured 2-D image.  Borrowed, never owned.
struct GrayImage {
    const unsigned char* data = nullptr;
    int width = 0;
    int height = 0;
    int stride = 0;                 // bytes per row (>= width)
    bool valid() const
    {
        return data != nullptr && width > 0 && height > 0 && stride >= width;
    }
    int at(int x, int y) const { return data[y * stride + x]; }
};

struct BoundaryCircle {
    double diameter = 0.0;      // primary: 2 * radius
    double radius = 0.0;        // mm, in the fitted material plane
    Vec3 center{};              // 3-D centre on that plane
    double centerU = 0.0;       // centre in image pixels
    double centerV = 0.0;
    Vec3 normal{};              // plane normal, oriented n[2] <= 0
    double roundness = 0.0;     // radius PV of the edge samples (mm)
    double rms = 0.0;           // RMS of the edge samples about the fit (mm)
    double mmPerPx = 0.0;       // local image scale actually used (mm / pixel)
    double coverage = 0.0;      // good rays / rays scanned
    int sectors = 0;            // rays scanned
    int used = 0;               // edge samples in the final fit
    bool subpixel = false;      // true when the edge came from the image
    bool reliable = false;
    bool valid = false;
    std::string message;
    std::string debug;          // T-012 临时：中间量，交回前删
};

// Material-boundary circle: found in the 3-D grid, refined to sub-pixel on the
// image.  `materialInside = false` measures a hole (material outside, hole
// inside); `true` measures the outer edge of a solid / raised step (material
// inside, background outside).  `roiCells[i]` is the grid cell of `roiPoints[i]`
// (index w*y + x); the grid is w*h*3 doubles, NaN outside the valid volume, and
// is used to grow the material region for the outer-edge case.  `img` may be
// invalid, in which case the 3-D boundary is reported with subpixel = false.
BoundaryCircle measureBoundaryCircle(
    const std::vector<Vec3>& roiPoints,
    const std::vector<std::size_t>& roiCells,
    int gridW, int gridH,
    const std::vector<double>& grid,
    int imageW, int imageH,
    const GrayImage& img,
    bool materialInside);

// ── ROI helpers (shared by the 2D panel and the 3D overlay) ────────────

// Image pixel rectangle -> grid cell rectangle.
//
// The operator drags in *image* pixels while the point map may live on its own
// resolution (an X2 delivers a 1440×1080 image with a down-sampled point map),
// so the rectangle is scaled into cells.  A pixel rect covers the continuous
// interval [left, right+1) × [top, bottom+1); a cell is taken as soon as it is
// covered at all, so the mapping is a conservative "cover" and never silently
// drops a cell the operator dragged over.  Returns the cell rectangle
// (inclusive) and the cell count; `valid` is false when the inputs are
// degenerate or the result misses the grid.
struct GridRect {
    int x0 = 0, y0 = 0, x1 = -1, y1 = -1;
    int cells = 0;
    bool valid = false;
};
GridRect roiImageToGrid(int left, int top, int right, int bottom,
                        int imageW, int imageH, int gridW, int gridH);

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
