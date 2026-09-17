#include "test_measure_tools.h"

#include <QtTest>

#include <algorithm>
#include <cmath>
#include <limits>

#include "logic/MeasureTools.h"

using namespace MeasureTools;

namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr double kDeg = 180.0 / kPi;

// Deterministic noise source.  std::uniform_real_distribution is
// implementation-defined, so a hand-rolled LCG is used instead: the same
// numbers must come out on every platform the suite runs on.
class Lcg
{
public:
    explicit Lcg(quint32 seed) : m_s(seed) {}

    double next()   // [-1, 1)
    {
        m_s = m_s * 1103515245u + 12345u;
        const quint32 v = (m_s >> 8) & 0xFFFFFFu;
        return static_cast<double>(v) / 8388608.0 - 1.0;
    }

private:
    quint32 m_s;
};

// A grid laid out on z = tiltX*x + tiltY*y with uniform noise.
std::vector<Vec3> tiltedPlane(int n, double tiltX, double tiltY, double noiseAmp,
                              quint32 seed)
{
    Lcg rng(seed);
    std::vector<Vec3> pts;
    pts.reserve(static_cast<std::size_t>(n) * n);
    const double c = (n - 1) / 2.0;
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j < n; ++j) {
            const double x = (i - c) * 2.0;
            const double y = (j - c) * 2.0;
            pts.push_back({ x, y, tiltX * x + tiltY * y + noiseAmp * rng.next() });
        }
    }
    return pts;
}

std::vector<Vec3> flatGrid(int n, double z, double noiseAmp, double spacing, quint32 seed)
{
    Lcg rng(seed);
    std::vector<Vec3> pts;
    pts.reserve(static_cast<std::size_t>(n) * n);
    const double c = (n - 1) / 2.0;
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j < n; ++j) {
            pts.push_back({ (i - c) * spacing, (j - c) * spacing,
                            z + noiseAmp * rng.next() });
        }
    }
    return pts;
}

// Rotate about Y by `deg` — used to build the plane pair at a known angle.
Vec3 rotY(const Vec3& p, double deg)
{
    const double t = deg / kDeg;
    const double c = std::cos(t), s = std::sin(t);
    return { p[0] * c + p[2] * s, p[1], -p[0] * s + p[2] * c };
}

Vec3 rotZ(const Vec3& p, double deg)
{
    const double t = deg / kDeg;
    const double c = std::cos(t), s = std::sin(t);
    return { p[0] * c - p[1] * s, p[0] * s + p[1] * c, p[2] };
}

Vec3 rotX(const Vec3& p, double deg)
{
    const double t = deg / kDeg;
    const double c = std::cos(t), s = std::sin(t);
    return { p[0], p[1] * c - p[2] * s, p[1] * s + p[2] * c };
}

std::vector<Vec3> circlePoints(int n, double radius, double radialNoise, double zNoise,
                               quint32 seed)
{
    Lcg rng(seed);
    std::vector<Vec3> pts;
    pts.reserve(n);
    for (int i = 0; i < n; ++i) {
        const double a = 2.0 * kPi * i / n;
        const double r = radius + radialNoise * rng.next();
        pts.push_back({ r * std::cos(a), r * std::sin(a), zNoise * rng.next() });
    }
    return pts;
}

// A densely sampled solid box of exactly L x W x H, then rotated rigidly.
std::vector<Vec3> boxLattice(int nx, int ny, int nz, double L, double W, double H,
                             double rotZDeg, double rotXDeg)
{
    std::vector<Vec3> pts;
    pts.reserve(static_cast<std::size_t>(nx) * ny * nz);
    for (int i = 0; i < nx; ++i) {
        for (int j = 0; j < ny; ++j) {
            for (int k = 0; k < nz; ++k) {
                Vec3 p{ -L / 2.0 + L * i / (nx - 1.0),
                        -W / 2.0 + W * j / (ny - 1.0),
                        -H / 2.0 + H * k / (nz - 1.0) };
                p = rotZ(p, rotZDeg);
                p = rotX(p, rotXDeg);
                pts.push_back(p);
            }
        }
    }
    return pts;
}

} // namespace

// ── flatness ───────────────────────────────────────────────────────────

void TestMeasureTools::flatnessPvRmsAndMinimumZone()
{
    // A plane tilted by 0.05 / 0.03 rad with +-0.01 mm of noise.  The LSQ fit
    // must remove the tilt, leaving a PV of roughly the noise band; the
    // minimum-zone plane can only do better.
    const std::vector<Vec3> pts = tiltedPlane(41, 0.05, 0.03, 0.01, 12345u);
    const Flatness f = flatness(pts);

    QVERIFY2(f.valid, qPrintable(QString::fromStdString(f.message)));
    QCOMPARE(f.used, pts.size());
    // The deviation vector the heat map colours keeps every input point
    // (Python parity: the flatness `dev` is the un-trimmed vector).
    QCOMPARE(f.dev.size(), pts.size());

    QVERIFY2(f.mzPv <= f.lsqPv + 1e-12,
             qPrintable(QStringLiteral("MZ %1 > LSQ PV %2").arg(f.mzPv).arg(f.lsqPv)));
    QVERIFY2(f.lsqRms <= f.lsqPv,
             qPrintable(QStringLiteral("RMS %1 > PV %2").arg(f.lsqRms).arg(f.lsqPv)));
    QVERIFY(f.mzPv > 0.0);
    QVERIFY2(f.lsqPv < 0.05, qPrintable(QStringLiteral("PV %1").arg(f.lsqPv)));
    QVERIFY2(f.lsqRms < 0.01, qPrintable(QStringLiteral("RMS %1").arg(f.lsqRms)));

    // The fitted normal must point back towards the camera and reproduce the
    // constructed tilt: normal ∝ (0.05, 0.03, -1) after orientation.
    QVERIFY(f.plane.normal[2] < 0.0);
    const Vec3 want = { 0.05, 0.03, -1.0 };
    const double wn = std::sqrt(want[0] * want[0] + want[1] * want[1] + want[2] * want[2]);
    const double d = f.plane.normal[0] * want[0] / wn
        + f.plane.normal[1] * want[1] / wn
        + f.plane.normal[2] * want[2] / wn;
    const double angErr = std::acos(std::min(1.0, std::fabs(d))) * kDeg;
    QVERIFY2(angErr < 0.1,
             qPrintable(QStringLiteral("normal off by %1 deg").arg(angErr)));
}

void TestMeasureTools::flatnessRejectsFlyers()
{
    std::vector<Vec3> pts = tiltedPlane(41, 0.0, 0.0, 0.01, 999u);
    const std::size_t clean = pts.size();
    // Six flight points 5 mm off the surface; a non-robust fit would report a
    // PV near 5 mm.
    pts.push_back({ 0.0, 0.0, 5.0 });
    pts.push_back({ 2.0, 2.0, -5.0 });
    pts.push_back({ -2.0, 4.0, 5.0 });
    pts.push_back({ 4.0, -6.0, -5.0 });
    pts.push_back({ 6.0, 6.0, 5.0 });
    pts.push_back({ -8.0, 0.0, -5.0 });

    const Flatness f = flatness(pts);
    QVERIFY2(f.valid, qPrintable(QString::fromStdString(f.message)));
    QVERIFY2(f.used < pts.size(),
             qPrintable(QStringLiteral("no point was rejected (used %1 of %2)")
                            .arg(f.used).arg(pts.size())));
    QVERIFY2(f.used >= clean * 9 / 10,
             qPrintable(QStringLiteral("rejected too much: %1 of %2")
                            .arg(f.used).arg(pts.size())));
    QVERIFY2(f.lsqPv < 0.1,
             qPrintable(QStringLiteral("PV %1 still carries the flyers").arg(f.lsqPv)));
    QVERIFY(f.mzPv <= f.lsqPv + 1e-12);
}

void TestMeasureTools::deviationIsPositiveTowardsCamera()
{
    // The camera looks along +z, so a bump towards it sits at negative z and
    // must still read as a *positive* deviation ("凸起为正").
    const std::vector<Vec3> ref = flatGrid(31, 0.0, 0.0, 1.0, 7u);
    const std::vector<Vec3> target = { { 0.0, 0.0, -0.5 }, { 1.0, 1.0, -0.5 } };
    const Height h = heightBetween(ref, target);
    QVERIFY2(h.valid, qPrintable(QString::fromStdString(h.message)));
    QVERIFY(h.ref.normal[2] < 0.0);
    QVERIFY2(h.value > 0.0, qPrintable(QStringLiteral("value %1").arg(h.value)));
    QVERIFY2(std::fabs(h.value - 0.5) < 1e-9,
             qPrintable(QStringLiteral("value %1, want 0.5").arg(h.value)));
}

// ── height / step ──────────────────────────────────────────────────────

void TestMeasureTools::heightStepIsThreeMillimetres()
{
    // Datum at z = 0, measured face exactly 3.000 mm towards the camera
    // (z = -3), 0.005 mm of noise on both.
    const std::vector<Vec3> ref = flatGrid(31, 0.0, 0.005, 1.0, 2024u);
    const std::vector<Vec3> target = flatGrid(21, -3.0, 0.005, 1.0, 2025u);
    const Height h = heightBetween(ref, target);
    QVERIFY2(h.valid, qPrintable(QString::fromStdString(h.message)));
    QVERIFY2(std::fabs(h.value - 3.000) <= 0.001,
             qPrintable(QStringLiteral("step %1 mm, want 3.000").arg(h.value, 0, 'f', 6)));
    QVERIFY(h.rms <= 0.01);
    QCOMPARE(h.usedTarget, target.size());
    QCOMPARE(h.usedRef, ref.size());
}

void TestMeasureTools::heightIsSigned()
{
    // Swapping datum and measured face flips the sign: 3.000 mm below the
    // datum (z = +3, away from the camera) must read as -3.000.
    const std::vector<Vec3> ref = flatGrid(21, 0.0, 0.005, 1.0, 11u);
    const std::vector<Vec3> lower = flatGrid(21, 3.0, 0.005, 1.0, 12u);
    const Height h = heightBetween(ref, lower);
    QVERIFY2(h.valid, qPrintable(QString::fromStdString(h.message)));
    QVERIFY2(std::fabs(h.value + 3.000) <= 0.001,
             qPrintable(QStringLiteral("step %1 mm, want -3.000").arg(h.value, 0, 'f', 6)));
}

// ── plane pair ─────────────────────────────────────────────────────────

void TestMeasureTools::planeAngleMatchesConstructedTilt()
{
    // Plane B is plane A rotated about Y by exactly 89.613°, so the plane
    // angle itself is 89.613° by construction.
    const std::vector<Vec3> a = flatGrid(21, 0.0, 0.0, 1.0, 3u);
    std::vector<Vec3> b;
    b.reserve(a.size());
    for (const Vec3& p : a)
        b.push_back(rotY(p, 89.613));

    const PlanePair r = planePair(a, b, 3.0);
    QVERIFY2(r.valid, qPrintable(QString::fromStdString(r.message)));
    QVERIFY2(std::fabs(r.angleDeg - 89.613) < 1e-6,
             qPrintable(QStringLiteral("angle %1, want 89.613").arg(r.angleDeg, 0, 'f', 9)));
    QVERIFY(!r.parallel);
    QVERIFY(!r.message.empty());
}

void TestMeasureTools::parallelPlaneDistance()
{
    const std::vector<Vec3> a = flatGrid(21, 0.0, 0.0, 1.0, 4u);
    std::vector<Vec3> b = flatGrid(21, -3.0, 0.0, 1.0, 5u);

    const PlanePair r = planePair(a, b, 3.0);
    QVERIFY2(r.valid, qPrintable(QString::fromStdString(r.message)));
    QVERIFY(r.parallel);
    // Exactly parallel: acos() is ill-conditioned near 1 (an error of 1e-16 in
    // the dot product already shows up as ~1e-6 deg), so the gate here is the
    // conditioning limit rather than an exact zero.
    QVERIFY2(r.angleDeg < 1e-4,
             qPrintable(QStringLiteral("angle %1").arg(r.angleDeg, 0, 'f', 12)));
    // B is 3.000 mm proud of A, so the distance is +3.000 with the datum's
    // sign convention.
    QVERIFY2(std::fabs(r.distanceMm - 3.000) < 1e-9,
             qPrintable(QStringLiteral("distance %1").arg(r.distanceMm, 0, 'f', 9)));

    // The same pair with 5° of tilt is not parallel at the default 3° gate,
    // but becomes "parallel" once the tolerance is opened up.
    std::vector<Vec3> tilted;
    tilted.reserve(a.size());
    for (const Vec3& p : a)
        tilted.push_back(rotY(p, 5.0));
    const PlanePair t = planePair(a, tilted, 3.0);
    QVERIFY(!t.parallel);
    QVERIFY2(std::fabs(t.angleDeg - 5.0) < 1e-6,
             qPrintable(QStringLiteral("angle %1").arg(t.angleDeg, 0, 'f', 9)));
    const PlanePair t2 = planePair(a, tilted, 10.0);
    QVERIFY(t2.parallel);
}

void TestMeasureTools::nonParallelPairHasNoDistance()
{
    const std::vector<Vec3> a = flatGrid(21, 0.0, 0.0, 1.0, 6u);
    std::vector<Vec3> perp;
    perp.reserve(a.size());
    for (const Vec3& p : a)
        perp.push_back(rotY(p, 45.0));

    const PlanePair r = planePair(a, perp, 3.0);
    QVERIFY2(r.valid, qPrintable(QString::fromStdString(r.message)));
    QVERIFY2(std::fabs(r.angleDeg - 45.0) < 1e-6,
             qPrintable(QStringLiteral("angle %1").arg(r.angleDeg, 0, 'f', 9)));
    QVERIFY(!r.parallel);
    QVERIFY2(!r.message.empty(), "a tilted pair must explain why there is no distance");
}

// ── circle ─────────────────────────────────────────────────────────────

void TestMeasureTools::circleDiameterWithinTolerance()
{
    // Ø10 with +-0.02 mm of radial noise: the fit must land within 0.02 mm.
    const std::vector<Vec3> pts = circlePoints(720, 5.0, 0.02, 0.005, 77u);
    const Circle c = fitCircle(pts, 2);
    QVERIFY2(c.valid, qPrintable(QString::fromStdString(c.message)));
    QVERIFY2(std::fabs(c.diameter - 10.0) <= 0.02,
             qPrintable(QStringLiteral("diameter %1, want 10 +-0.02")
                            .arg(c.diameter, 0, 'f', 6)));
    QVERIFY2(std::fabs(c.radius - 5.0) <= 0.02, qPrintable(QStringLiteral("radius %1").arg(c.radius)));
    QVERIFY2(std::fabs(c.center[0]) < 0.02, qPrintable(QStringLiteral("cx %1").arg(c.center[0])));
    QVERIFY2(std::fabs(c.center[1]) < 0.02, qPrintable(QStringLiteral("cy %1").arg(c.center[1])));
    // Roundness is a peak-to-valley over the same noise band.
    QVERIFY2(c.roundness <= 0.06,
             qPrintable(QStringLiteral("roundness %1").arg(c.roundness)));
    QVERIFY(c.normal[2] < 0.0);
    QVERIFY2(c.spanDeg > 359.0, qPrintable(QStringLiteral("span %1").arg(c.spanDeg)));
    QCOMPARE(c.used, pts.size());
}

void TestMeasureTools::circleRejectsOutliers()
{
    std::vector<Vec3> pts = circlePoints(720, 5.0, 0.02, 0.005, 78u);
    // 15 points on a larger radius: a plain algebraic fit would report a
    // diameter well above 10.
    for (int i = 0; i < 15; ++i) {
        const double a = 2.0 * kPi * i / 15.0;
        pts.push_back({ 8.0 * std::cos(a), 8.0 * std::sin(a), 0.0 });
    }
    const Circle c = fitCircle(pts, 2);
    QVERIFY2(c.valid, qPrintable(QString::fromStdString(c.message)));
    QVERIFY2(std::fabs(c.diameter - 10.0) <= 0.02,
             qPrintable(QStringLiteral("diameter %1, want 10 +-0.02")
                            .arg(c.diameter, 0, 'f', 6)));
    QVERIFY2(c.used < pts.size(),
             qPrintable(QStringLiteral("outliers kept (used %1 of %2)")
                            .arg(c.used).arg(pts.size())));
}

// ── bounding box ───────────────────────────────────────────────────────

void TestMeasureTools::boundingBoxExtents()
{
    const std::vector<Vec3> pts = boxLattice(41, 25, 9, 100.0, 60.0, 20.0, 0.0, 0.0);
    const BoundingBox b = pcaBoundingBox(pts);
    QVERIFY2(b.valid, qPrintable(QString::fromStdString(b.message)));
    QVERIFY2(std::fabs(b.length - 100.0) < 1e-6,
             qPrintable(QStringLiteral("length %1").arg(b.length, 0, 'f', 9)));
    QVERIFY2(std::fabs(b.width - 60.0) < 1e-6,
             qPrintable(QStringLiteral("width %1").arg(b.width, 0, 'f', 9)));
    QVERIFY2(std::fabs(b.height - 20.0) < 1e-6,
             qPrintable(QStringLiteral("height %1").arg(b.height, 0, 'f', 9)));
    QVERIFY2(std::fabs(b.center[0]) < 1e-9 && std::fabs(b.center[1]) < 1e-9
                 && std::fabs(b.center[2]) < 1e-9,
             qPrintable(QStringLiteral("center %1 %2 %3")
                            .arg(b.center[0]).arg(b.center[1]).arg(b.center[2])));
}

void TestMeasureTools::boundingBoxIsOriented()
{
    // The same box rotated 30° about Z and 20° about X: an axis-aligned box
    // would inflate, an oriented one must still report 100 x 60 x 20.
    const std::vector<Vec3> pts = boxLattice(41, 25, 9, 100.0, 60.0, 20.0, 30.0, 20.0);
    const BoundingBox b = pcaBoundingBox(pts);
    QVERIFY2(b.valid, qPrintable(QString::fromStdString(b.message)));
    QVERIFY2(std::fabs(b.length - 100.0) < 1e-6,
             qPrintable(QStringLiteral("length %1").arg(b.length, 0, 'f', 9)));
    QVERIFY2(std::fabs(b.width - 60.0) < 1e-6,
             qPrintable(QStringLiteral("width %1").arg(b.width, 0, 'f', 9)));
    QVERIFY2(std::fabs(b.height - 20.0) < 1e-6,
             qPrintable(QStringLiteral("height %1").arg(b.height, 0, 'f', 9)));
}

// ── repeatability ──────────────────────────────────────────────────────

void TestMeasureTools::repeatabilityHandComputed()
{
    // {10.0, 10.5, 11.0}: mean 10.5, sample sigma 0.5, range 1.0, 6σ 3.0.
    const Repeatability r = repeatability({ 10.0, 10.5, 11.0 });
    QVERIFY(r.valid);
    QCOMPARE(r.n, std::size_t(3));
    QVERIFY2(std::fabs(r.mean - 10.5) <= 1e-9, qPrintable(QStringLiteral("mean %1").arg(r.mean)));
    QVERIFY2(std::fabs(r.stdDev - 0.5) <= 1e-9,
             qPrintable(QStringLiteral("sigma %1").arg(r.stdDev, 0, 'f', 12)));
    QVERIFY2(std::fabs(r.range - 1.0) <= 1e-9, qPrintable(QStringLiteral("range %1").arg(r.range)));
    QVERIFY2(std::fabs(r.sixSigma - 3.0) <= 1e-9,
             qPrintable(QStringLiteral("6 sigma %1").arg(r.sixSigma, 0, 'f', 12)));
    QVERIFY2(std::fabs(r.min - 10.0) <= 1e-9, qPrintable(QStringLiteral("min %1").arg(r.min)));
    QVERIFY2(std::fabs(r.max - 11.0) <= 1e-9, qPrintable(QStringLiteral("max %1").arg(r.max)));
    QVERIFY2(std::fabs(r.maxDev - 0.5) <= 1e-9,
             qPrintable(QStringLiteral("maxdev %1").arg(r.maxDev)));

    // {1,2,3,4,5}: mean 3, sample sigma sqrt(2.5), range 4.
    const Repeatability q = repeatability({ 1.0, 2.0, 3.0, 4.0, 5.0 });
    QVERIFY(q.valid);
    QCOMPARE(q.n, std::size_t(5));
    QVERIFY2(std::fabs(q.mean - 3.0) <= 1e-9, qPrintable(QStringLiteral("mean %1").arg(q.mean)));
    const double want = std::sqrt(2.5);
    QVERIFY2(std::fabs(q.stdDev - want) <= 1e-9,
             qPrintable(QStringLiteral("sigma %1 want %2")
                            .arg(q.stdDev, 0, 'f', 12).arg(want, 0, 'f', 12)));
    QVERIFY2(std::fabs(q.range - 4.0) <= 1e-9, qPrintable(QStringLiteral("range %1").arg(q.range)));
    QVERIFY2(std::fabs(q.sixSigma - 6.0 * want) <= 1e-9,
             qPrintable(QStringLiteral("6 sigma %1").arg(q.sixSigma, 0, 'f', 12)));

    // Degenerate inputs stay readable instead of producing NaN.
    const Repeatability one = repeatability({ 2.5 });
    QVERIFY(one.valid);
    QCOMPARE(one.n, std::size_t(1));
    QCOMPARE(one.stdDev, 0.0);
    QVERIFY(!repeatability({}).valid);
    // Non-finite values are dropped rather than poisoning the statistics.
    const Repeatability dropped = repeatability({ std::nan(""), 1.0, 2.0 });
    QVERIFY(dropped.valid);
    QCOMPARE(dropped.n, std::size_t(2));
    QVERIFY2(std::fabs(dropped.mean - 1.5) <= 1e-9,
             qPrintable(QStringLiteral("mean %1").arg(dropped.mean)));
}

// ── colour limits ──────────────────────────────────────────────────────

void TestMeasureTools::robustLimitsResistFlyer()
{
    // 21 inliers spanning +-0.01 mm plus one 1.0 mm flyer.  The ±3σ_MAD band
    // must stay near the inliers; a percentile range would be dragged to ~0.8
    // by the single flyer — that difference is the whole point of the rule.
    std::vector<double> v;
    for (int i = 0; i < 7; ++i) {
        v.push_back(-0.01);
        v.push_back(0.0);
        v.push_back(0.01);
    }
    v.push_back(1.0);

    const Limits lim = robustLimits(v);
    QVERIFY(lim.valid);
    QVERIFY2(lim.robust, "a non-degenerate MAD must select the ±3σ_MAD rule");
    QVERIFY2(lim.hi < 0.1,
             qPrintable(QStringLiteral("hi %1 looks percentile-driven").arg(lim.hi)));
    QVERIFY2(lim.lo > -0.1, qPrintable(QStringLiteral("lo %1").arg(lim.lo)));
    QVERIFY2(std::fabs(lim.hi - 3.0 * 1.4826 * 0.01) < 1e-12,
             qPrintable(QStringLiteral("hi %1").arg(lim.hi, 0, 'f', 12)));
    QCOMPARE(lim.nClipped, std::size_t(1));

    // A perfectly flat set has a zero MAD: the percentile fallback kicks in
    // and the band is widened so the colour map cannot divide by zero.
    const Limits flat = robustLimits({ 1.0, 1.0, 1.0, 1.0 });
    QVERIFY(flat.valid);
    QVERIFY(!flat.robust);
    QVERIFY(flat.hi - flat.lo >= 1e-9);
    QVERIFY(!robustLimits({ 1.0 }).valid);
}

// ── ROI / section helpers ──────────────────────────────────────────────

void TestMeasureTools::roiExtractionSkipsNan()
{
    // 4x3 grid, z = x + y, with one invalid cell inside the ROI.
    const int w = 4, h = 3;
    std::vector<double> grid(static_cast<std::size_t>(w) * h * 3, 0.0);
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            const std::size_t i = (static_cast<std::size_t>(y) * w + x) * 3;
            grid[i] = x;
            grid[i + 1] = y;
            grid[i + 2] = x + y;
        }
    }
    grid[(static_cast<std::size_t>(1) * w + 2) * 3 + 2] = std::nan("");

    const std::vector<Vec3> roi = pointsInRoi(grid, w, h, 1, 0, 2, 1);
    QCOMPARE(roi.size(), std::size_t(3));
    for (const Vec3& p : roi) {
        QVERIFY(std::fabs(p[2] - (p[0] + p[1])) < 1e-12);
        QVERIFY(p[0] >= 1.0 && p[0] <= 2.0 && p[1] >= 0.0 && p[1] <= 1.0);
    }

    // A rectangle dragged outside the grid is clamped, not read out of bounds:
    // the whole 4x3 grid less the one invalid cell.
    QCOMPARE(pointsInRoi(grid, w, h, -5, -5, 99, 99).size(), std::size_t(11));
    // Dragging bottom-right to top-left must select the same rectangle as the
    // forward drag (1,0)-(3,2): 3x3 cells less the NaN = 8.
    QCOMPARE(pointsInRoi(grid, w, h, 3, 2, 1, 0).size(), std::size_t(8));
    QCOMPARE(pointsInRoi(grid, w, h, 1, 0, 3, 2).size(), std::size_t(8));
    // A single-cell rectangle is one point.
    QCOMPARE(pointsInRoi(grid, w, h, 0, 0, 0, 0).size(), std::size_t(1));
    // A grid whose buffer is too small for the stated size yields nothing.
    QVERIFY(pointsInRoi({}, w, h, 0, 0, 1, 1).empty());
}

void TestMeasureTools::sectionProfileFollowsStep()
{
    // Left half at z = 0, right half at z = -1: the profile must show both
    // levels and span the ROI's principal (x) direction.
    std::vector<Vec3> pts;
    for (int x = 0; x < 40; ++x) {
        for (int y = 0; y < 10; ++y) {
            pts.push_back({ static_cast<double>(x) - 20.0, static_cast<double>(y) - 5.0,
                            x < 20 ? 0.0 : -1.0 });
        }
    }
    const SectionProfile sp = sectionProfile(pts, 20);
    QVERIFY2(sp.valid, qPrintable(QString::fromStdString(sp.message)));
    QVERIFY(sp.points.size() >= 10);
    QVERIFY2(std::fabs((sp.tMax - sp.tMin) - 39.0) < 0.5,
             qPrintable(QStringLiteral("span %1").arg(sp.tMax - sp.tMin)));
    QVERIFY(sp.stepMm > 0.0);

    double lo = 1e300, hi = -1e300;
    for (const auto& p : sp.points) {
        lo = std::min(lo, p[1]);
        hi = std::max(hi, p[1]);
    }
    QVERIFY2(std::fabs(hi) < 1e-9, qPrintable(QStringLiteral("high %1").arg(hi)));
    QVERIFY2(std::fabs(lo + 1.0) < 1e-9, qPrintable(QStringLiteral("low %1").arg(lo)));

    // Too few points / a degenerate direction are reported, not guessed at.
    QVERIFY(!sectionProfile({ { 0, 0, 0 }, { 1, 1, 0 } }).valid);
    QVERIFY(!sectionProfile({ { 0, 0, 0 }, { 0, 0, 1 }, { 0, 0, 2 }, { 0, 0, 3 } }).valid);
}

void TestMeasureTools::colormapMatchesReferenceFormula()
{
    // mviz.py's colormap() written out longhand — the 2D deviation page and the
    // 3D colouring must agree with it bit for bit.
    auto clip01 = [](double v) { return std::min(1.0, std::max(0.0, v)); };
    for (int i = 0; i <= 20; ++i) {
        const double t = i / 20.0;
        const std::array<double, 3> cw = colormap(t, true);
        QVERIFY(std::fabs(cw[0] - clip01(1.6 * t + 0.1)) < 1e-12);
        QVERIFY(std::fabs(cw[1] - (1.0 - std::fabs(2.0 * t - 1.0) * 0.85)) < 1e-12);
        QVERIFY(std::fabs(cw[2] - clip01(1.7 - 1.6 * t)) < 1e-12);

        const std::array<double, 3> tb = colormap(t, false);
        QVERIFY(std::fabs(tb[0] - clip01(1.5 - std::fabs(4.0 * t - 3.0))) < 1e-12);
        QVERIFY(std::fabs(tb[1] - clip01(1.5 - std::fabs(4.0 * t - 2.0))) < 1e-12);
        QVERIFY(std::fabs(tb[2] - clip01(1.5 - std::fabs(4.0 * t - 1.0))) < 1e-12);
    }
    // End points are the cool/warm extremes and every channel stays in [0, 1]
    // — a colour outside the range would overflow the 8-bit conversion.
    const std::array<double, 3> lo = colormap(0.0, true);
    const std::array<double, 3> hi = colormap(1.0, true);
    QVERIFY(lo[0] < hi[0]);            // cool -> warm
    QVERIFY(lo[2] > hi[2]);            // blue -> red
    for (int i = -3; i <= 23; ++i) {   // includes out-of-range t
        const std::array<double, 3> c = colormap(i / 20.0, i % 2 == 0);
        for (double ch : c)
            QVERIFY(ch >= 0.0 && ch <= 1.0);
    }
}

void TestMeasureTools::cloudColorsAlignWithFilteredCloud()
{
    // A 6x4 grid with four kinds of cell: valid, NaN, exact zero, and one with
    // a non-finite value.  The colour array must contain exactly one triple per
    // point that PointCloudUtils::filterValidPoints would keep, in the same
    // order — that is the whole contract with VisSceneView::updatePointCloud.
    const int w = 6, h = 4;
    std::vector<double> grid(static_cast<std::size_t>(w) * h * 3, 0.0);
    std::vector<std::size_t> expectedValid;
    for (std::size_t i = 0; i < static_cast<std::size_t>(w) * h; ++i) {
        // x starts at 1 so that cell 0 is *not* an accidental (0,0,0): the two
        // exact-zero cells below are deliberate.
        const double x = static_cast<double>(i % w) + 1.0;
        const double y = static_cast<double>(i / w);
        const double z = 0.001 * static_cast<double>(i);
        grid[i * 3] = x;
        grid[i * 3 + 1] = y;
        grid[i * 3 + 2] = z;
        if (i == 7) {                       // NaN cell
            grid[i * 3 + 2] = std::nan("");
        } else if (i == 11) {               // exact (0,0,0) cell
            grid[i * 3] = grid[i * 3 + 1] = grid[i * 3 + 2] = 0.0;
        } else if (i == 19) {               // +inf cell (non-finite, not NaN)
            grid[i * 3 + 2] = std::numeric_limits<double>::infinity();
        } else {
            expectedValid.push_back(i);
        }
    }

    const Plane plane = fitPlane({ { 0, 0, 0 }, { 1, 0, 0 }, { 0, 1, 0 }, { 1, 1, 0 } });
    QVERIFY(plane.valid);

    const std::vector<std::array<float, 3>> colors =
        cloudDeviationColors(grid, w, h, plane, -0.01, 0.01, true, expectedValid);

    // filterValidPoints skips NaN but keeps +inf, so it is counted as valid.
    QCOMPARE(colors.size(), expectedValid.size() + 1);

    // Every highlighted cell that survives carries its deviation colour, so the
    // array cannot simply be the base colour repeated.
    bool sawDeviationColor = false;
    for (const std::array<float, 3>& c : colors) {
        if (std::fabs(c[0] - 0.28f) > 1e-6f || std::fabs(c[1] - 0.30f) > 1e-6f)
            sawDeviationColor = true;
        for (float ch : c)
            QVERIFY(ch >= 0.0f && ch <= 1.0f);
    }
    QVERIFY(sawDeviationColor);

    // Degenerate inputs are empty, never a half-filled array.
    QVERIFY(cloudDeviationColors(grid, 0, h, plane, 0, 1, true, {}).empty());
    QVERIFY(cloudDeviationColors({}, w, h, plane, 0, 1, true, {}).empty());
}

void TestMeasureTools::cloudColorsHighlightOnlyTheRoi()
{
    // 21x1 grid on z = 0.001*i, coloured against the hand-built plane z = 0
    // (deviation = -z, so the deviation decreases along the row).  Only the
    // cells listed as the ROI may take a deviation colour — the measured region
    // has to stay recognisable inside the rest of the scene — and the colour it
    // takes must follow the sign of its deviation.
    const int w = 21, h = 1;
    std::vector<double> grid(static_cast<std::size_t>(w) * 3, 0.0);
    for (int i = 0; i < w; ++i) {
        // x from 1 so no cell is an accidental (0,0,0) — every cell must end up
        // in the colour array for the index alignment below to mean anything.
        grid[i * 3] = i + 1.0;
        grid[i * 3 + 1] = 0.0;
        grid[i * 3 + 2] = 0.001 * i;
    }

    Plane plane;
    plane.normal = { 0.0, 0.0, -1.0 };   // same convention as fitPlane: n[2] < 0
    plane.d = 0.0;
    plane.valid = true;

    // Band [-0.016, 0.004] keeps the two ROI cells used below at t ≈ 0.55 and
    // 0.45 — mid-map, where no coolwarm channel is clipped, so the comparison
    // is about the mapping and not about a saturated end point.
    const std::vector<std::size_t> roi = { 5, 6, 7 };
    const std::vector<std::array<float, 3>> colors =
        cloudDeviationColors(grid, w, h, plane, -0.016, 0.004, true, roi);
    QCOMPARE(static_cast<int>(colors.size()), w);

    auto isBase = [](const std::array<float, 3>& c) {
        return std::fabs(c[0] - 0.28f) < 1e-6f && std::fabs(c[1] - 0.30f) < 1e-6f
               && std::fabs(c[2] - 0.34f) < 1e-6f;
    };
    for (int i = 0; i < w; ++i) {
        const bool inRoi = i >= 5 && i <= 7;
        QCOMPARE(isBase(colors[static_cast<std::size_t>(i)]), !inRoi);
    }
    // Cell 5 has the larger (less negative) deviation, so it must read warmer
    // than cell 7: more red, less blue.
    QVERIFY(colors[5][0] > colors[7][0]);
    QVERIFY(colors[5][2] < colors[7][2]);
}
