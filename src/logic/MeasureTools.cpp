#include "logic/MeasureTools.h"

#include <algorithm>
#include <cmath>
#include <numeric>

namespace MeasureTools {

namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr double kDeg = 180.0 / kPi;
constexpr double kMadScale = 1.4826;    // MAD -> sigma for a normal distribution

double dot(const Vec3& a, const Vec3& b)
{
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

Vec3 sub(const Vec3& a, const Vec3& b)
{
    return { a[0] - b[0], a[1] - b[1], a[2] - b[2] };
}

Vec3 cross(const Vec3& a, const Vec3& b)
{
    return { a[1] * b[2] - a[2] * b[1],
             a[2] * b[0] - a[0] * b[2],
             a[0] * b[1] - a[1] * b[0] };
}

double norm(const Vec3& v)
{
    return std::sqrt(dot(v, v));
}

Vec3 normalized(const Vec3& v)
{
    const double n = norm(v);
    if (n <= 0.0 || !std::isfinite(n))
        return { 0.0, 0.0, 0.0 };
    return { v[0] / n, v[1] / n, v[2] / n };
}

// The Python tool orients every plane normal towards the camera (n[2] < 0) so
// that a point standing proud of the surface has a positive deviation.
void orientTowardsCamera(Vec3& n, double& d)
{
    if (n[2] > 0.0) {
        n = { -n[0], -n[1], -n[2] };
        d = -d;
    }
}

// Two unit vectors spanning the plane orthogonal to `n`.
void planeBasis(const Vec3& n, Vec3& u, Vec3& v)
{
    const Vec3 seed = (std::fabs(n[0]) < 0.9) ? Vec3{ 1.0, 0.0, 0.0 }
                                              : Vec3{ 0.0, 1.0, 0.0 };
    u = normalized(cross(n, seed));
    v = cross(n, u);            // already unit: |n| = |u| = 1 and n ⟂ u
}

// Cyclic Jacobi eigen-decomposition of a symmetric 3x3 matrix.  `eval` is
// ascending and `evec[i]` is the eigenvector belonging to `eval[i]`.
void symEigen3(const double in[3][3], double eval[3], Vec3 evec[3])
{
    double a[3][3];
    double v[3][3] = { { 1, 0, 0 }, { 0, 1, 0 }, { 0, 0, 1 } };
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j)
            a[i][j] = in[i][j];

    for (int sweep = 0; sweep < 64; ++sweep) {
        const double off = a[0][1] * a[0][1] + a[0][2] * a[0][2] + a[1][2] * a[1][2];
        if (off < 1e-30)
            break;
        for (int p = 0; p < 2; ++p) {
            for (int q = p + 1; q < 3; ++q) {
                if (std::fabs(a[p][q]) < 1e-300)
                    continue;
                const double theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q]);
                const double t = (theta >= 0.0 ? 1.0 : -1.0)
                    / (std::fabs(theta) + std::sqrt(theta * theta + 1.0));
                const double c = 1.0 / std::sqrt(t * t + 1.0);
                const double s = t * c;

                for (int k = 0; k < 3; ++k) {
                    const double akp = a[k][p], akq = a[k][q];
                    a[k][p] = c * akp - s * akq;
                    a[k][q] = s * akp + c * akq;
                }
                for (int k = 0; k < 3; ++k) {
                    const double apk = a[p][k], aqk = a[q][k];
                    a[p][k] = c * apk - s * aqk;
                    a[q][k] = s * apk + c * aqk;
                }
                for (int k = 0; k < 3; ++k) {
                    const double vkp = v[k][p], vkq = v[k][q];
                    v[k][p] = c * vkp - s * vkq;
                    v[k][q] = s * vkp + c * vkq;
                }
            }
        }
    }

    int order[3] = { 0, 1, 2 };
    const double diag[3] = { a[0][0], a[1][1], a[2][2] };
    std::sort(order, order + 3,
              [&diag](int l, int r) { return diag[l] < diag[r]; });
    for (int i = 0; i < 3; ++i) {
        eval[i] = diag[order[i]];
        evec[i] = { v[0][order[i]], v[1][order[i]], v[2][order[i]] };
    }
}

Vec3 centroid(const std::vector<Vec3>& pts)
{
    Vec3 c{ 0.0, 0.0, 0.0 };
    for (const Vec3& p : pts) {
        c[0] += p[0];
        c[1] += p[1];
        c[2] += p[2];
    }
    const double n = static_cast<double>(pts.size());
    return { c[0] / n, c[1] / n, c[2] / n };
}

// 3x3 symmetric covariance of `pts` (optionally about an explicit centre).
void covariance3(const std::vector<Vec3>& pts, const Vec3& c, double cov[3][3])
{
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j)
            cov[i][j] = 0.0;
    for (const Vec3& p : pts) {
        const double q[3] = { p[0] - c[0], p[1] - c[1], p[2] - c[2] };
        for (int i = 0; i < 3; ++i)
            for (int j = 0; j < 3; ++j)
                cov[i][j] += q[i] * q[j];
    }
    const double n = static_cast<double>(pts.size());
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j)
            cov[i][j] /= n;
}

double medianOf(std::vector<double> v)
{
    if (v.empty())
        return 0.0;
    const std::size_t mid = v.size() / 2;
    std::nth_element(v.begin(), v.begin() + mid, v.end());
    const double hi = v[mid];
    if (v.size() % 2 != 0)
        return hi;
    const double lo = *std::max_element(v.begin(), v.begin() + mid);
    return 0.5 * (lo + hi);
}

// Indices of the values within k * 1.4826 * MAD of the median.  When the MAD is
// zero (noise-free or fewer than 2 values) everything is kept — rejecting on a
// zero-width band would throw away every point of a perfect measurement.
std::vector<std::size_t> madInliers(const std::vector<double>& v, double k)
{
    std::vector<std::size_t> keep;
    keep.reserve(v.size());
    if (v.size() < 3) {
        for (std::size_t i = 0; i < v.size(); ++i)
            keep.push_back(i);
        return keep;
    }
    const double med = medianOf(v);
    std::vector<double> absDev(v.size());
    for (std::size_t i = 0; i < v.size(); ++i)
        absDev[i] = std::fabs(v[i] - med);
    const double mad = medianOf(absDev);
    const double sigma = k * kMadScale * mad;
    for (std::size_t i = 0; i < v.size(); ++i) {
        if (sigma <= 0.0 || std::fabs(v[i] - med) <= sigma)
            keep.push_back(i);
    }
    return keep;
}

std::vector<Vec3> pick(const std::vector<Vec3>& pts, const std::vector<std::size_t>& idx)
{
    std::vector<Vec3> out;
    out.reserve(idx.size());
    for (std::size_t i : idx)
        out.push_back(pts[i]);
    return out;
}

// Least-squares plane without any outlier handling (fitPlane() adds the
// orientation and residual reporting on top of this).
bool fitPlaneRaw(const std::vector<Vec3>& pts, Plane& out)
{
    if (pts.size() < 3) {
        out.message = "点数不足（至少需要 3 点拟合平面）";
        return false;
    }
    const Vec3 c = centroid(pts);
    double cov[3][3];
    covariance3(pts, c, cov);

    double eval[3];
    Vec3 evec[3];
    symEigen3(cov, eval, evec);
    // The normal is the direction of least spread.
    Vec3 n = normalized(evec[0]);
    if (norm(n) <= 0.0) {
        out.message = "平面拟合退化（协方差特征分解失败）";
        return false;
    }
    double d = -dot(n, c);
    orientTowardsCamera(n, d);

    double sum = 0.0;
    for (const Vec3& p : pts) {
        const double r = dot(n, p) + d;
        sum += r * r;
    }
    out.normal = n;
    out.d = d;
    out.rms = std::sqrt(sum / static_cast<double>(pts.size()));
    out.used = pts.size();
    out.valid = true;
    out.message.clear();
    return true;
}

struct Flat2D {
    double pv = 0.0;
    double a = 0.0;     // residual = z - a*x - b*y
    double b = 0.0;
};

// Minimum-zone flatness by 2-DOF coordinate descent on the residual plane.
//
// Ported from the Python implementation: start from the LSQ plane (a = b = 0)
// and only ever accept a strict improvement, so the result can never exceed the
// LSQ PV.  That is what makes `mzPv <= lsqPv` a property of the algorithm
// rather than of the data.
Flat2D minimumZone(const std::vector<std::array<double, 2>>& xy,
                   const std::vector<double>& z, int maxIter)
{
    Flat2D best;
    auto pvOf = [](const std::vector<double>& r) {
        const auto mm = std::minmax_element(r.begin(), r.end());
        return *mm.second - *mm.first;
    };
    best.pv = pvOf(z);
    if (xy.empty() || maxIter <= 0)
        return best;

    double minX = xy[0][0], maxX = xy[0][0], minY = xy[0][1], maxY = xy[0][1];
    for (const auto& p : xy) {
        minX = std::min(minX, p[0]);
        maxX = std::max(maxX, p[0]);
        minY = std::min(minY, p[1]);
        maxY = std::max(maxY, p[1]);
    }
    const double span = std::max(std::max(maxX - minX, maxY - minY), 1e-6);
    double step = std::max(best.pv, 1e-12) / span;

    std::vector<double> r(z.size());
    for (int iter = 0; iter < maxIter && step > 1e-12; ++iter) {
        bool improved = false;
        const double cand[4][2] = { { step, 0.0 }, { -step, 0.0 },
                                    { 0.0, step }, { 0.0, -step } };
        for (const auto& t : cand) {
            const double a = best.a + t[0];
            const double b = best.b + t[1];
            for (std::size_t i = 0; i < z.size(); ++i)
                r[i] = z[i] - a * xy[i][0] - b * xy[i][1];
            const double pv = pvOf(r);
            if (pv < best.pv - 1e-12) {
                best.pv = pv;
                best.a = a;
                best.b = b;
                improved = true;
            }
        }
        if (!improved)
            step *= 0.5;
    }
    return best;
}

} // namespace

std::vector<Vec3> finitePoints(const std::vector<Vec3>& pts)
{
    std::vector<Vec3> out;
    out.reserve(pts.size());
    for (const Vec3& p : pts) {
        if (isFinite(p))
            out.push_back(p);
    }
    return out;
}

Limits robustLimits(const std::vector<double>& values, double madK,
                    double clipLoPct, double clipHiPct)
{
    Limits lim;
    std::vector<double> v;
    v.reserve(values.size());
    for (double x : values) {
        if (std::isfinite(x))
            v.push_back(x);
    }
    if (v.size() < 2)
        return lim;

    const double med = medianOf(v);
    std::vector<double> absDev(v.size());
    for (std::size_t i = 0; i < v.size(); ++i)
        absDev[i] = std::fabs(v[i] - med);
    const double mad = medianOf(absDev);

    if (mad > 1e-12) {
        const double half = madK * kMadScale * mad;
        lim.lo = med - half;
        lim.hi = med + half;
        lim.robust = true;
    } else {
        // Degenerate MAD: fall back to percentiles (numpy's linear
        // interpolation), the same escape hatch the Python tool uses.
        std::vector<double> sorted = v;
        std::sort(sorted.begin(), sorted.end());
        auto pct = [&sorted](double p) {
            const double rank = p / 100.0 * static_cast<double>(sorted.size() - 1);
            const std::size_t lo = static_cast<std::size_t>(std::floor(rank));
            const std::size_t hi = std::min(lo + 1, sorted.size() - 1);
            const double frac = rank - static_cast<double>(lo);
            return sorted[lo] * (1.0 - frac) + sorted[hi] * frac;
        };
        lim.lo = pct(clipLoPct);
        lim.hi = pct(clipHiPct);
    }
    if (lim.hi - lim.lo < 1e-9) {
        lim.lo = med - 1e-3;
        lim.hi = med + 1e-3;
    }
    for (double x : v) {
        if (x < lim.lo || x > lim.hi)
            ++lim.nClipped;
    }
    lim.valid = true;
    return lim;
}

Plane fitPlane(const std::vector<Vec3>& pts)
{
    Plane p;
    const std::vector<Vec3> all = finitePoints(pts);
    fitPlaneRaw(all, p);
    return p;
}

std::vector<double> deviations(const std::vector<Vec3>& pts, const Plane& plane)
{
    std::vector<double> out;
    out.reserve(pts.size());
    for (const Vec3& p : pts)
        out.push_back(dot(plane.normal, p) + plane.d);
    return out;
}

Flatness flatness(const std::vector<Vec3>& pts, double madK, int maxIter)
{
    Flatness f;
    const std::vector<Vec3> all = finitePoints(pts);
    if (all.size() < 3) {
        f.message = "点数不足（至少需要 3 点计算平面度）";
        return f;
    }

    // LSQ fit, MAD rejection, re-fit — twice, matching the Python tool's
    // robust re-fit.  The second pass uses the plane the report is based on.
    Plane plane;
    if (!fitPlaneRaw(all, plane)) {
        f.message = plane.message;
        return f;
    }
    std::vector<double> devAll = deviations(all, plane);
    std::vector<std::size_t> idx = madInliers(devAll, madK);
    std::vector<Vec3> inliers = pick(all, idx);
    if (inliers.size() >= 3 && !fitPlaneRaw(inliers, plane)) {
        f.message = plane.message;
        return f;
    }
    devAll = deviations(all, plane);
    idx = madInliers(devAll, madK);
    if (idx.size() >= 3 && idx.size() != all.size()) {
        std::vector<Vec3> again = pick(all, idx);
        Plane refit;
        if (fitPlaneRaw(again, refit))
            plane = refit;
    }
    inliers = pick(all, idx);
    if (inliers.size() < 3) {
        f.message = "剔除离群点后剩余点数不足（至少需要 3 点）";
        return f;
    }

    const std::vector<double> dev = deviations(inliers, plane);
    const auto mm = std::minmax_element(dev.begin(), dev.end());
    f.lsqPv = *mm.second - *mm.first;
    double sum = 0.0;
    for (double d : dev)
        sum += d * d;
    f.lsqRms = std::sqrt(sum / static_cast<double>(dev.size()));

    // Minimum-zone plane, in the LSQ plane's own frame.
    Vec3 u, v;
    planeBasis(plane.normal, u, v);
    const Vec3 c = centroid(inliers);
    std::vector<std::array<double, 2>> xy(inliers.size());
    std::vector<double> z(inliers.size());
    for (std::size_t i = 0; i < inliers.size(); ++i) {
        const Vec3 q = sub(inliers[i], c);
        xy[i] = { dot(q, u), dot(q, v) };
        z[i] = dev[i];
    }
    const Flat2D mz = minimumZone(xy, z, maxIter);
    f.mzPv = std::min(mz.pv, f.lsqPv);     // the descent can only improve; clamp for safety
    f.tiltDeg = std::atan(std::sqrt(mz.a * mz.a + mz.b * mz.b)) * kDeg;

    f.dev = deviations(all, plane);
    f.plane = plane;
    f.used = inliers.size();
    f.valid = true;
    f.message.clear();
    return f;
}

Height heightBetween(const std::vector<Vec3>& refPoints,
                     const std::vector<Vec3>& targetPoints, double madK)
{
    Height h;
    const std::vector<Vec3> ref = finitePoints(refPoints);
    const std::vector<Vec3> target = finitePoints(targetPoints);
    if (ref.size() < 3) {
        h.message = "基准区点数不足（至少需要 3 点拟合基准平面）";
        return h;
    }
    if (target.size() < 1) {
        h.message = "被测区没有有效点";
        return h;
    }

    Plane plane;
    if (!fitPlaneRaw(ref, plane)) {
        h.message = plane.message;
        return h;
    }
    // Refine the datum with a MAD pass so a step edge inside the datum ROI
    // does not tilt the plane.
    const std::vector<double> refDev = deviations(ref, plane);
    const std::vector<std::size_t> refIdx = madInliers(refDev, madK);
    if (refIdx.size() >= 3 && refIdx.size() != ref.size()) {
        Plane refit;
        if (fitPlaneRaw(pick(ref, refIdx), refit))
            plane = refit;
    }

    const std::vector<double> dev = deviations(target, plane);
    const std::vector<std::size_t> idx = madInliers(dev, madK);
    if (idx.empty()) {
        h.message = "被测区所有点都被判为离群点";
        return h;
    }
    std::vector<double> kept;
    kept.reserve(idx.size());
    for (std::size_t i : idx)
        kept.push_back(dev[i]);

    const double value = medianOf(kept);
    double sum = 0.0;
    for (double d : kept)
        sum += (d - value) * (d - value);

    h.value = value;
    h.rms = std::sqrt(sum / static_cast<double>(kept.size()));
    h.usedRef = refIdx.size() >= 3 ? refIdx.size() : ref.size();
    h.usedTarget = kept.size();
    h.ref = plane;
    h.valid = true;
    h.message.clear();
    return h;
}

double planeAngleDeg(const Plane& a, const Plane& b)
{
    if (!a.valid || !b.valid)
        return 0.0;
    double c = std::fabs(dot(a.normal, b.normal));
    c = std::min(1.0, std::max(0.0, c));
    return std::acos(c) * kDeg;
}

bool planeDistanceMm(const Plane& ref, const std::vector<Vec3>& target,
                     double* outMm, std::size_t* usedOut, double madK)
{
    if (!ref.valid)
        return false;
    const std::vector<Vec3> pts = finitePoints(target);
    if (pts.empty())
        return false;
    const std::vector<double> dev = deviations(pts, ref);
    const std::vector<std::size_t> idx = madInliers(dev, madK);
    if (idx.empty())
        return false;
    std::vector<double> kept;
    kept.reserve(idx.size());
    for (std::size_t i : idx)
        kept.push_back(dev[i]);
    if (outMm)
        *outMm = medianOf(kept);
    if (usedOut)
        *usedOut = kept.size();
    return true;
}

PlanePair planePair(const std::vector<Vec3>& ptsA, const std::vector<Vec3>& ptsB,
                    double parallelTolDeg, double madK)
{
    PlanePair r;
    const std::vector<Vec3> a = finitePoints(ptsA);
    const std::vector<Vec3> b = finitePoints(ptsB);
    if (a.size() < 3 || b.size() < 3) {
        r.message = "两个区域各需要至少 3 点";
        return r;
    }
    Plane pa;
    if (!fitPlaneRaw(a, pa)) {
        r.message = pa.message;
        return r;
    }
    Plane pb;
    if (!fitPlaneRaw(b, pb)) {
        r.message = pb.message;
        return r;
    }
    // Reject outliers inside each ROI before the pair is combined.
    const std::vector<std::size_t> ia = madInliers(deviations(a, pa), madK);
    const std::vector<std::size_t> ib = madInliers(deviations(b, pb), madK);
    if (ia.size() >= 3 && ia.size() != a.size()) {
        Plane refit;
        if (fitPlaneRaw(pick(a, ia), refit))
            pa = refit;
    }
    if (ib.size() >= 3 && ib.size() != b.size()) {
        Plane refit;
        if (fitPlaneRaw(pick(b, ib), refit))
            pb = refit;
    }
    r.planeA = pa;
    r.planeB = pb;
    r.usedA = ia.size();
    r.usedB = ib.size();
    r.angleDeg = planeAngleDeg(pa, pb);
    r.parallel = r.angleDeg <= parallelTolDeg;
    if (r.parallel) {
        // Sign follows the *datum*: positive means B sits proud of A.
        std::size_t used = 0;
        planeDistanceMm(pa, b, &r.distanceMm, &used, madK);
        r.message.clear();
    } else {
        r.message = "两面不平行（夹角超过容差），不给出间距";
    }
    r.valid = true;
    return r;
}

Circle fitCircle(const std::vector<Vec3>& pts, int outlierIters, double madK)
{
    Circle circ;
    std::vector<Vec3> work = finitePoints(pts);
    if (work.size() < 5) {
        circ.message = "点数不足（至少需要 5 点拟合圆）";
        return circ;
    }

    // One pass of the algebraic fit; repeated after each rejection round.
    struct Solution {
        double cx = 0.0, cy = 0.0, r = 0.0;
        bool ok = false;
    };
    auto algebraic = [](const std::vector<double>& x, const std::vector<double>& y,
                        Solution& s) {
        // Kåsa / algebraic circle: minimise sum (x²+y² - 2cx·x - 2cy·y - k)²,
        // i.e. a plain 3-parameter linear least squares on [2x, 2y, 1].
        double a[3][3] = {};
        double rhs[3] = {};
        for (std::size_t i = 0; i < x.size(); ++i) {
            const double row[3] = { 2.0 * x[i], 2.0 * y[i], 1.0 };
            const double b = x[i] * x[i] + y[i] * y[i];
            for (int r = 0; r < 3; ++r) {
                for (int c = 0; c < 3; ++c)
                    a[r][c] += row[r] * row[c];
                rhs[r] += row[r] * b;
            }
        }
        // Gaussian elimination with partial pivoting on the 3x3 normal system.
        double m[3][4];
        for (int r = 0; r < 3; ++r) {
            for (int c = 0; c < 3; ++c)
                m[r][c] = a[r][c];
            m[r][3] = rhs[r];
        }
        for (int col = 0; col < 3; ++col) {
            int piv = col;
            for (int r = col + 1; r < 3; ++r) {
                if (std::fabs(m[r][col]) > std::fabs(m[piv][col]))
                    piv = r;
            }
            if (std::fabs(m[piv][col]) < 1e-12)
                return false;
            if (piv != col) {
                for (int c = 0; c < 4; ++c)
                    std::swap(m[col][c], m[piv][c]);
            }
            for (int r = col + 1; r < 3; ++r) {
                const double f = m[r][col] / m[col][col];
                for (int c = col; c < 4; ++c)
                    m[r][c] -= f * m[col][c];
            }
        }
        double sol[3];
        for (int r = 2; r >= 0; --r) {
            double v = m[r][3];
            for (int c = r + 1; c < 3; ++c)
                v -= m[r][c] * sol[c];
            sol[r] = v / m[r][r];
        }
        const double k = sol[2];
        const double r2 = k + sol[0] * sol[0] + sol[1] * sol[1];
        if (!(r2 > 0.0))
            return false;
        s.cx = sol[0];
        s.cy = sol[1];
        s.r = std::sqrt(r2);
        s.ok = true;
        return true;
    };

    Plane plane;
    Solution sol;
    for (int iter = 0; iter <= std::max(0, outlierIters); ++iter) {
        plane = Plane{};
        if (!fitPlaneRaw(work, plane)) {
            circ.message = plane.message;
            return circ;
        }
        Vec3 u, v;
        planeBasis(plane.normal, u, v);
        const Vec3 c = centroid(work);
        std::vector<double> x(work.size()), y(work.size());
        for (std::size_t i = 0; i < work.size(); ++i) {
            const Vec3 q = sub(work[i], c);
            x[i] = dot(q, u);
            y[i] = dot(q, v);
        }
        if (!algebraic(x, y, sol)) {
            circ.message = "圆拟合退化（点近似共线或过少）";
            return circ;
        }
        if (iter == std::max(0, outlierIters) || work.size() < 8)
            break;
        std::vector<double> res(work.size());
        for (std::size_t i = 0; i < work.size(); ++i) {
            const double dx = x[i] - sol.cx, dy = y[i] - sol.cy;
            res[i] = std::sqrt(dx * dx + dy * dy) - sol.r;
        }
        const std::vector<std::size_t> keep = madInliers(res, madK);
        if (keep.size() < 5 || keep.size() == work.size())
            break;
        work = pick(work, keep);
    }

    // Final geometry in the last fitted frame.
    plane = Plane{};
    fitPlaneRaw(work, plane);
    Vec3 u, v;
    planeBasis(plane.normal, u, v);
    const Vec3 c = centroid(work);
    std::vector<double> x(work.size()), y(work.size());
    for (std::size_t i = 0; i < work.size(); ++i) {
        const Vec3 q = sub(work[i], c);
        x[i] = dot(q, u);
        y[i] = dot(q, v);
    }
    if (!algebraic(x, y, sol)) {
        circ.message = "圆拟合退化（点近似共线或过少）";
        return circ;
    }

    std::vector<double> radii(work.size());
    std::vector<double> angles(work.size());
    double sum = 0.0;
    for (std::size_t i = 0; i < work.size(); ++i) {
        const double dx = x[i] - sol.cx, dy = y[i] - sol.cy;
        radii[i] = std::sqrt(dx * dx + dy * dy);
        angles[i] = std::atan2(dy, dx);
        const double e = radii[i] - sol.r;
        sum += e * e;
    }
    std::sort(angles.begin(), angles.end());
    double gap = angles.front() + 2.0 * kPi - angles.back();
    for (std::size_t i = 1; i < angles.size(); ++i)
        gap = std::max(gap, angles[i] - angles[i - 1]);
    const auto rr = std::minmax_element(radii.begin(), radii.end());

    circ.center = { c[0] + sol.cx * u[0] + sol.cy * v[0],
                    c[1] + sol.cx * u[1] + sol.cy * v[1],
                    c[2] + sol.cx * u[2] + sol.cy * v[2] };
    circ.normal = plane.normal;
    circ.radius = sol.r;
    circ.diameter = 2.0 * sol.r;
    circ.roundness = *rr.second - *rr.first;
    circ.rms = std::sqrt(sum / static_cast<double>(work.size()));
    circ.spanDeg = (2.0 * kPi - gap) * kDeg;
    circ.used = work.size();
    circ.valid = true;
    circ.message.clear();
    return circ;
}

BoundingBox pcaBoundingBox(const std::vector<Vec3>& pts)
{
    BoundingBox bb;
    const std::vector<Vec3> p = finitePoints(pts);
    if (p.size() < 3) {
        bb.message = "点数不足（至少需要 3 点计算包围盒）";
        return bb;
    }
    const Vec3 c = centroid(p);
    double cov[3][3];
    covariance3(p, c, cov);
    double eval[3];
    Vec3 evec[3];
    symEigen3(cov, eval, evec);
    // evec is ascending; the box axes are wanted longest first.
    Vec3 axis[3] = { evec[2], evec[1], evec[0] };
    for (int i = 0; i < 3; ++i)
        axis[i] = normalized(axis[i]);

    double lo[3] = { 1e300, 1e300, 1e300 };
    double hi[3] = { -1e300, -1e300, -1e300 };
    for (const Vec3& q : p) {
        for (int i = 0; i < 3; ++i) {
            const double t = dot(sub(q, c), axis[i]);
            lo[i] = std::min(lo[i], t);
            hi[i] = std::max(hi[i], t);
        }
    }

    Vec3 centre = c;
    double ext[3];
    for (int i = 0; i < 3; ++i) {
        ext[i] = hi[i] - lo[i];
        const double mid = 0.5 * (hi[i] + lo[i]);
        centre[0] += mid * axis[i][0];
        centre[1] += mid * axis[i][1];
        centre[2] += mid * axis[i][2];
    }
    // Extents can come out nearly equal; order them by value with a stable
    // tie-break so the same point set always reports the same l/w/h.
    int order[3] = { 0, 1, 2 };
    std::sort(order, order + 3, [&ext](int l, int r) { return ext[l] > ext[r]; });

    bb.length = ext[order[0]];
    bb.width = ext[order[1]];
    bb.height = ext[order[2]];
    for (int i = 0; i < 3; ++i) {
        for (int k = 0; k < 3; ++k)
            bb.axes[i * 3 + k] = axis[order[i]][k];
    }
    bb.center = centre;
    bb.used = p.size();
    bb.valid = true;
    bb.message.clear();
    return bb;
}

Repeatability repeatability(const std::vector<double>& values)
{
    Repeatability r;
    std::vector<double> v;
    v.reserve(values.size());
    for (double x : values) {
        if (std::isfinite(x))
            v.push_back(x);
    }
    if (v.empty())
        return r;
    r.n = v.size();
    double sum = 0.0;
    for (double x : v)
        sum += x;
    r.mean = sum / static_cast<double>(v.size());
    const auto mm = std::minmax_element(v.begin(), v.end());
    r.min = *mm.first;
    r.max = *mm.second;
    r.range = r.max - r.min;
    r.maxDev = std::max(std::fabs(r.max - r.mean), std::fabs(r.min - r.mean));
    if (v.size() >= 2) {
        double acc = 0.0;
        for (double x : v)
            acc += (x - r.mean) * (x - r.mean);
        r.stdDev = std::sqrt(acc / static_cast<double>(v.size() - 1));
    }
    r.sixSigma = 6.0 * r.stdDev;
    r.valid = true;
    return r;
}

std::vector<Vec3> pointsInRoi(const std::vector<double>& grid, int w, int h,
                              int x0, int y0, int x1, int y1)
{
    return pointsInRoiIndexed(grid, w, h, x0, y0, x1, y1, nullptr);
}

std::vector<Vec3> pointsInRoiIndexed(const std::vector<double>& grid, int w, int h,
                                     int x0, int y0, int x1, int y1,
                                     std::vector<std::size_t>* cellIndexOut)
{
    std::vector<Vec3> out;
    if (cellIndexOut)
        cellIndexOut->clear();
    if (w <= 0 || h <= 0 || grid.size() < static_cast<std::size_t>(w) * h * 3)
        return out;
    int cx0 = std::max(0, std::min(x0, x1));
    int cx1 = std::min(w - 1, std::max(x0, x1));
    int cy0 = std::max(0, std::min(y0, y1));
    int cy1 = std::min(h - 1, std::max(y0, y1));
    if (cx0 > cx1 || cy0 > cy1)
        return out;
    out.reserve(static_cast<std::size_t>(cx1 - cx0 + 1) * (cy1 - cy0 + 1));
    if (cellIndexOut)
        cellIndexOut->reserve(out.capacity());
    for (int y = cy0; y <= cy1; ++y) {
        const std::size_t row = static_cast<std::size_t>(y) * w;
        for (int x = cx0; x <= cx1; ++x) {
            const std::size_t cell = row + x;
            const std::size_t i = cell * 3;
            const Vec3 p{ grid[i], grid[i + 1], grid[i + 2] };
            if (!isFinite(p))
                continue;
            out.push_back(p);
            if (cellIndexOut)
                cellIndexOut->push_back(cell);
        }
    }
    return out;
}

GridRect roiImageToGrid(int left, int top, int right, int bottom,
                        int imageW, int imageH, int gridW, int gridH)
{
    GridRect r;
    if (imageW <= 0 || imageH <= 0 || gridW <= 0 || gridH <= 0)
        return r;
    if (right < left)
        std::swap(left, right);
    if (bottom < top)
        std::swap(top, bottom);
    const double sx = static_cast<double>(gridW) / static_cast<double>(imageW);
    const double sy = static_cast<double>(gridH) / static_cast<double>(imageH);
    r.x0 = static_cast<int>(std::floor(left * sx));
    r.y0 = static_cast<int>(std::floor(top * sy));
    r.x1 = static_cast<int>(std::ceil((right + 1) * sx)) - 1;
    r.y1 = static_cast<int>(std::ceil((bottom + 1) * sy)) - 1;
    // A rectangle that misses the grid completely stays invalid instead of being
    // clamped onto the border — clamping first would turn "outside" into a
    // one-cell measurement on the edge.
    if (r.x1 < 0 || r.y1 < 0 || r.x0 > gridW - 1 || r.y0 > gridH - 1)
        return r;
    r.x0 = std::max(0, std::min(r.x0, gridW - 1));
    r.y0 = std::max(0, std::min(r.y0, gridH - 1));
    r.x1 = std::max(0, std::min(r.x1, gridW - 1));
    r.y1 = std::max(0, std::min(r.y1, gridH - 1));
    r.cells = (r.x1 - r.x0 + 1) * (r.y1 - r.y0 + 1);
    r.valid = true;
    return r;
}

// ── 7. hole diameter (material inner boundary) ─────────────────────────

namespace {

// Nearest-neighbour distance of every point, on a uniform hash grid.  The point
// sets here are slices of an organized grid, so the search normally ends in the
// first ring or two; the ring loop is bounded by the hash size, i.e. it degrades
// into a full scan rather than ever returning a wrong answer.
void nearestNeighbourDistances(const std::vector<std::array<double, 2>>& p,
                               std::vector<double>& out)
{
    out.assign(p.size(), std::numeric_limits<double>::max());
    if (p.size() < 2)
        return;
    double minX = p[0][0], maxX = p[0][0], minY = p[0][1], maxY = p[0][1];
    for (const std::array<double, 2>& q : p) {
        minX = std::min(minX, q[0]);
        maxX = std::max(maxX, q[0]);
        minY = std::min(minY, q[1]);
        maxY = std::max(maxY, q[1]);
    }
    const double spanX = maxX - minX;
    const double spanY = maxY - minY;
    // About one point per cell on average, clamped so a degenerate input (one
    // point, or every point at the same place) still gives a usable hash.
    double cell = std::sqrt(std::max(spanX * spanY, 1e-12) / static_cast<double>(p.size()));
    if (!(cell > 0.0) || !std::isfinite(cell))
        cell = 1.0;
    const int nx = std::max(1, static_cast<int>(spanX / cell) + 1);
    const int ny = std::max(1, static_cast<int>(spanY / cell) + 1);
    std::vector<int> head(static_cast<std::size_t>(nx) * static_cast<std::size_t>(ny), -1);
    std::vector<int> next(p.size(), -1);
    auto cellIndex = [&](const std::array<double, 2>& q) {
        int cx = static_cast<int>((q[0] - minX) / cell);
        int cy = static_cast<int>((q[1] - minY) / cell);
        cx = std::max(0, std::min(cx, nx - 1));
        cy = std::max(0, std::min(cy, ny - 1));
        return cy * nx + cx;
    };
    for (std::size_t i = 0; i < p.size(); ++i) {
        const int c = cellIndex(p[i]);
        next[i] = head[c];
        head[c] = static_cast<int>(i);
    }
    const int maxRing = nx + ny;
    for (std::size_t i = 0; i < p.size(); ++i) {
        const int ci = cellIndex(p[i]);
        const int cx = ci % nx;
        const int cy = ci / nx;
        double best = std::numeric_limits<double>::max();
        for (int ring = 0; ring <= maxRing; ++ring) {
            const int x0 = cx - ring, x1 = cx + ring;
            const int y0 = cy - ring, y1 = cy + ring;
            for (int y = y0; y <= y1; ++y) {
                if (y < 0 || y >= ny)
                    continue;
                for (int x = x0; x <= x1; ++x) {
                    if (x < 0 || x >= nx)
                        continue;
                    // Only the ring's own cells are new; the interior was done.
                    if (ring > 0 && x != x0 && x != x1 && y != y0 && y != y1)
                        continue;
                    for (int j = head[y * nx + x]; j >= 0; j = next[j]) {
                        if (static_cast<std::size_t>(j) == i)
                            continue;
                        const double dx = p[j][0] - p[i][0];
                        const double dy = p[j][1] - p[i][1];
                        best = std::min(best, std::sqrt(dx * dx + dy * dy));
                    }
                }
            }
            // Anything in an unscanned ring is at least ring*cell away.
            if (best <= ring * cell)
                break;
        }
        out[i] = best;
    }
}

// Point pitch of the material = median nearest-neighbour distance.  On an
// organized grid every interior point has neighbours at exactly the pitch, so
// the median is the pitch; being a median, it ignores the edge points (which
// have fewer neighbours) and the few diagonal neighbours.
double estimatePitch(const std::vector<std::array<double, 2>>& material)
{
    if (material.size() < 5)
        return 0.0;
    std::vector<double> d;
    nearestNeighbourDistances(material, d);
    std::vector<double> fin;
    fin.reserve(d.size());
    for (double v : d) {
        if (std::isfinite(v))
            fin.push_back(v);
    }
    if (fin.size() < 5)
        return 0.0;
    return medianOf(fin);
}

} // namespace

HoleBoundary holeBoundary(const std::vector<Vec3>& roiPoints, int minSectors,
                          double bandSigmaK, double minCoverage)
{
    HoleBoundary hb;
    hb.sectors = std::max(6, minSectors);

    const std::vector<Vec3> pts = finitePoints(roiPoints);
    hb.roiPoints = pts.size();
    if (pts.size() < 12) {
        hb.message = "点数不足（孔径法至少需要 12 点）";
        return hb;
    }

    // 1. material plane: LSQ, one MAD rejection round, refit on the survivors.
    Plane plane;
    if (!fitPlaneRaw(pts, plane)) {
        hb.message = plane.message;
        return hb;
    }
    std::vector<double> dev = deviations(pts, plane);
    std::vector<Vec3> mat = pick(pts, madInliers(dev, 3.0));
    if (mat.size() >= 3)
        fitPlaneRaw(mat, plane);
    dev = deviations(mat, plane);

    // 2. plane band.  3σ of the *material* residuals, floored so that a very
    //    flat ROI still tolerates the stray points a projected edge produces.
    std::vector<double> absDev(dev.size());
    for (std::size_t i = 0; i < dev.size(); ++i)
        absDev[i] = std::fabs(dev[i]);
    const double sigma = kMadScale * medianOf(absDev);
    hb.bandMm = std::max(bandSigmaK * sigma, 0.05);
    std::vector<Vec3> band;
    band.reserve(mat.size());
    for (std::size_t i = 0; i < mat.size(); ++i) {
        if (std::fabs(dev[i]) <= hb.bandMm)
            band.push_back(mat[i]);
    }
    hb.materialPoints = band.size();
    if (band.size() < 12) {
        hb.message = "平面带内材料点不足（孔壁/背景点已排除）";
        return hb;
    }

    // 3. in-plane frame around the material centroid (see the header: a ROI
    //    drawn around a hole has no 3D point at its centre — the centre cell is
    //    the hole — so the fan origin is derived from the material itself, in
    //    plane, which is also what makes it independent of the plane's offset).
    const Vec3 origin = centroid(band);
    hb.fanOrigin = origin;
    Vec3 u, v;
    planeBasis(plane.normal, u, v);
    std::vector<std::array<double, 2>> uv(band.size());
    std::vector<double> bandR(band.size());
    for (std::size_t i = 0; i < band.size(); ++i) {
        const Vec3 q = sub(band[i], origin);
        uv[i] = { dot(q, u), dot(q, v) };
        bandR[i] = std::sqrt(uv[i][0] * uv[i][0] + uv[i][1] * uv[i][1]);
    }

    // 4. how fine the fan has to be.
    //
    // Step 5 corrects the *median of one boundary sample per sector* by half a
    // pitch, which is only right when a sector really holds one sample.  A fixed
    // 36-sector fan breaks that as soon as the pitch is coarse: a wedge wide
    // enough to hold several rim points reports the *smallest* of them, and the
    // radius comes out low by a large fraction of a pitch.  Measured on the
    // known-truth data: a 1 mm pitch with a ⌀5 hole read 6.32 mm.  The sector
    // width is therefore chosen to be about one pitch at the boundary radius, so
    // that a sector normally contains a single rim point — which is the
    // condition the half-sample correction assumes.  The radius used for that is
    // the inner tenth of the band radii, i.e. the rim itself and not the middle
    // of a band that is a couple of pitches thick.
    hb.pitch = estimatePitch(uv);
    std::vector<double> sortedR = bandR;
    std::sort(sortedR.begin(), sortedR.end());
    const double rRim = sortedR.empty()
        ? 0.0
        : sortedR[std::min(sortedR.size() - 1, sortedR.size() / 10)];
    int nWedge = hb.sectors;      // fallback when the pitch cannot be estimated
    if (hb.pitch > 0.0 && rRim > 0.0) {
        nWedge = static_cast<int>(std::lround(2.0 * kPi * rRim / hb.pitch));
        nWedge = std::max(12, std::min(nWedge, 720));
    }
    hb.sectors = nWedge;

    // 5. innermost material point per angular sector.
    const double twoPi = 2.0 * kPi;
    const std::size_t none = static_cast<std::size_t>(-1);
    std::vector<double> sectorR(static_cast<std::size_t>(nWedge),
                                std::numeric_limits<double>::max());
    std::vector<std::size_t> sectorIdx(static_cast<std::size_t>(nWedge), none);
    for (std::size_t i = 0; i < uv.size(); ++i) {
        const double angle = std::atan2(uv[i][1], uv[i][0]);
        int s = static_cast<int>((angle + kPi) / twoPi * nWedge);
        s = std::max(0, std::min(s, nWedge - 1));
        if (bandR[i] < sectorR[static_cast<std::size_t>(s)]) {
            sectorR[static_cast<std::size_t>(s)] = bandR[i];
            sectorIdx[static_cast<std::size_t>(s)] = i;
        }
    }
    std::vector<Vec3> boundary;
    std::vector<double> radii;
    for (int s = 0; s < nWedge; ++s) {
        const std::size_t k = sectorIdx[static_cast<std::size_t>(s)];
        if (k == none)
            continue;
        boundary.push_back(band[k]);
        radii.push_back(sectorR[static_cast<std::size_t>(s)]);
    }
    hb.sectorsUsed = static_cast<int>(radii.size());
    if (radii.size() < 5) {
        hb.coverage = static_cast<double>(hb.sectorsUsed) / hb.sectors;
        hb.message = "有效扇区不足（找不到孔壁）";
        return hb;
    }

    // 6. pitch and the half-sample correction.
    hb.pitchCorrection = 0.5 * hb.pitch;
    hb.medianRadius = medianOf(radii);
    // Confidence: did the fan find the rim all the way round?  The pitch only
    // allows about 2πR/pitch rim points, so that — not the sector count — is
    // what the number of boundary samples has to be compared with; a ROI that
    // clips the hole loses samples against that expectation.
    const double expect = (hb.pitch > 0.0 && hb.medianRadius > 0.0)
        ? 2.0 * kPi * hb.medianRadius / hb.pitch
        : hb.sectors;
    hb.coverage = std::min(1.0, hb.sectorsUsed / std::max(1.0, std::round(expect)));

    // 7. circle through the boundary samples.
    const Circle c = fitCircle(boundary, 0, 2.5);
    if (!c.valid) {
        hb.message = c.message;
        return hb;
    }
    hb.fitDiameter = c.diameter;
    hb.roundness = c.roundness;
    hb.rms = c.rms;
    hb.center = c.center;
    hb.normal = c.normal;
    hb.radius = c.radius - hb.pitchCorrection;
    hb.diameter = 2.0 * hb.radius;
    hb.medianDiameter = 2.0 * (hb.medianRadius - hb.pitchCorrection);
    hb.used = c.used;
    hb.valid = true;

    // 8. confidence (see step 6 for the coverage fraction).  A roundness
    //    comparable to the radius means the sectors are not sampling a common
    //    circle at all, which happens when the fan origin is not inside the
    //    hole and the sectors therefore start in the material.
    hb.reliable = hb.coverage >= minCoverage && hb.roundness <= 0.6 * hb.medianRadius;
    if (!hb.reliable) {
        hb.message = hb.coverage < minCoverage
            ? "边界样本数不足（ROI 可能没有完整覆盖孔壁），结果仅供参照"
            : "边界半径离散度过大（ROI 可能未覆盖孔壁），结果仅供参照";
    }
    return hb;
}

// ── 8. boundary circle (image-guided sub-pixel edge) ───────────────────

namespace {

// 3x3 linear system, Gaussian elimination with partial pivoting.
bool solve3(double m[3][3], const double rhs[3], double out[3])
{
    double a[3][4];
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 3; ++c)
            a[r][c] = m[r][c];
        a[r][3] = rhs[r];
    }
    for (int col = 0; col < 3; ++col) {
        int piv = col;
        for (int r = col + 1; r < 3; ++r)
            if (std::fabs(a[r][col]) > std::fabs(a[piv][col]))
                piv = r;
        if (std::fabs(a[piv][col]) < 1e-18)
            return false;
        if (piv != col)
            for (int c = 0; c < 4; ++c)
                std::swap(a[col][c], a[piv][c]);
        for (int r = col + 1; r < 3; ++r) {
            const double f = a[r][col] / a[col][col];
            for (int c = col; c < 4; ++c)
                a[r][c] -= f * a[col][c];
        }
    }
    for (int r = 2; r >= 0; --r) {
        double v = a[r][3];
        for (int c = r + 1; c < 3; ++c)
            v -= a[r][c] * out[c];
        out[r] = v / a[r][r];
    }
    return true;
}

// Image pixel -> fitted-plane coordinates: [xi, eta] = A * [u, v] + t.  On a
// plane a perspective map is locally affine, so this both removes the
// foreshortening an image-space circle fit would carry and gives the local
// mm/pixel scale (sqrt|det A|).
struct AffineMap {
    double a = 0.0, b = 0.0, c = 0.0, d = 0.0, e = 0.0, f = 0.0;
    bool ok = false;
    double det() const { return a * d - b * c; }
    void apply(double u, double v, double& xi, double& eta) const
    {
        xi = a * u + b * v + e;
        eta = c * u + d * v + f;
    }
    bool invert(double xi, double eta, double& u, double& v) const
    {
        const double D = det();
        if (std::fabs(D) < 1e-12)
            return false;
        u = (d * (xi - e) - b * (eta - f)) / D;
        v = (-c * (xi - e) + a * (eta - f)) / D;
        return true;
    }
};

bool solveAffine(const std::vector<std::array<double, 2>>& uv,
                 const std::vector<std::array<double, 2>>& xy, AffineMap& out)
{
    if (uv.size() < 3 || uv.size() != xy.size())
        return false;
    double s[3][3] = {};
    double rx[3] = {};
    double ry[3] = {};
    for (std::size_t i = 0; i < uv.size(); ++i) {
        const double p[3] = { uv[i][0], uv[i][1], 1.0 };
        for (int r = 0; r < 3; ++r) {
            for (int c = 0; c < 3; ++c)
                s[r][c] += p[r] * p[c];
            rx[r] += p[r] * xy[i][0];
            ry[r] += p[r] * xy[i][1];
        }
    }
    double sol[3];
    if (!solve3(s, rx, sol))
        return false;
    out.a = sol[0];
    out.b = sol[1];
    out.e = sol[2];
    if (!solve3(s, ry, sol))
        return false;
    out.c = sol[0];
    out.d = sol[1];
    out.f = sol[2];
    out.ok = true;
    return true;
}

double percentile(std::vector<double> v, double p)
{
    if (v.empty())
        return 0.0;
    std::sort(v.begin(), v.end());
    if (v.size() == 1)
        return v[0];
    const double rank = p * static_cast<double>(v.size() - 1);
    const std::size_t lo = static_cast<std::size_t>(std::floor(rank));
    const std::size_t hi = std::min(lo + 1, v.size() - 1);
    const double frac = rank - static_cast<double>(lo);
    return v[lo] * (1.0 - frac) + v[hi] * frac;
}

// Plane through three points, normal oriented n[2] <= 0 (towards the camera).
bool planeFrom3(const Vec3& a, const Vec3& b, const Vec3& c, Plane& p)
{
    const Vec3 ab = sub(b, a);
    const Vec3 ac = sub(c, a);
    Vec3 n{ ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0] };
    const double len = std::sqrt(dot(n, n));
    if (!(len > 1e-9))
        return false;
    n = { n[0] / len, n[1] / len, n[2] / len };
    if (n[2] > 0.0)
        n = { -n[0], -n[1], -n[2] };
    p.normal = n;
    p.d = -dot(n, a);
    return true;
}

// Dominant-plane fit (RANSAC + LSQ refit).
//
// A plain least-squares fit — even with the MAD tail rejection the other
// kernels use — cannot cope with a ROI that straddles two levels: MAD only ever
// drops a *minority* tail, so a ROI half on the disc face and half on the lower
// annulus (or on the plate behind it) fits the *average* of the two and reports
// a band wide enough to swallow everything (the ⌀63.5 ROI fitted a 29 mm band
// and then "measured" 96 mm).  Sampling triples and keeping the largest
// consensus set locks onto the surface with the most area instead.
bool fitDominantPlane(const std::vector<Vec3>& pts, double tol, Plane& out)
{
    if (pts.size() < 3)
        return false;
    const std::size_t n = pts.size();
    int best = -1;
    Vec3 bn{ 0.0, 0.0, -1.0 };
    double bd = 0.0;
    std::uint32_t rng = 0x9e3779b9u;
    const int iters = std::min(600, 40 + static_cast<int>(n) / 20);
    for (int it = 0; it < iters; ++it) {
        std::size_t idx[3];
        for (int k = 0; k < 3; ++k) {
            rng = rng * 1664525u + 1013904223u;
            idx[k] = static_cast<std::size_t>(rng) % n;
        }
        if (idx[0] == idx[1] || idx[1] == idx[2] || idx[0] == idx[2])
            continue;
        Plane cand;
        if (!planeFrom3(pts[idx[0]], pts[idx[1]], pts[idx[2]], cand))
            continue;
        int cnt = 0;
        for (const Vec3& p : pts)
            if (std::fabs(dot(cand.normal, p) + cand.d) <= tol)
                ++cnt;
        if (cnt > best) {
            best = cnt;
            bn = cand.normal;
            bd = cand.d;
        }
    }
    if (best < 3)
        return false;
    Plane seed;
    seed.normal = bn;
    seed.d = bd;
    std::vector<Vec3> inl;
    inl.reserve(static_cast<std::size_t>(best));
    for (const Vec3& p : pts)
        if (std::fabs(dot(seed.normal, p) + seed.d) <= tol)
            inl.push_back(p);
    if (!fitPlaneRaw(inl, out))
        return false;
    return true;
}

// Flood-fill the 4-connected component of `mask` (nonzero = inside) that holds
// `seed`.  Returns false when the seed is out of range or not inside the mask.
bool floodComponent(const std::vector<char>& mask, int w, int h, std::size_t seed,
                    std::vector<std::size_t>& comp)
{
    comp.clear();
    if (w <= 0 || h <= 0 || seed >= static_cast<std::size_t>(w) * h || !mask[seed])
        return false;
    std::vector<char> seen(mask.size(), 0);
    std::vector<std::size_t> stack;
    stack.push_back(seed);
    seen[seed] = 1;
    while (!stack.empty()) {
        const std::size_t cur = stack.back();
        stack.pop_back();
        comp.push_back(cur);
        const int cx = static_cast<int>(cur % static_cast<std::size_t>(w));
        const int cy = static_cast<int>(cur / static_cast<std::size_t>(w));
        const int nx[4] = { cx - 1, cx + 1, cx, cx };
        const int ny[4] = { cy, cy, cy - 1, cy + 1 };
        for (int k = 0; k < 4; ++k) {
            if (nx[k] < 0 || nx[k] >= w || ny[k] < 0 || ny[k] >= h)
                continue;
            const std::size_t nb = static_cast<std::size_t>(ny[k]) * w + nx[k];
            if (mask[nb] && !seen[nb]) {
                seen[nb] = 1;
                stack.push_back(nb);
            }
        }
    }
    return true;
}

double bilinear(const GrayImage& img, double u, double v)
{
    if (!img.valid())
        return 0.0;
    const double maxU = img.width - 1.0;
    const double maxV = img.height - 1.0;
    u = std::min(maxU, std::max(0.0, u));
    v = std::min(maxV, std::max(0.0, v));
    const int x0 = static_cast<int>(u);
    const int y0 = static_cast<int>(v);
    const int x1 = std::min(x0 + 1, img.width - 1);
    const int y1 = std::min(y0 + 1, img.height - 1);
    const double fx = u - x0;
    const double fy = v - y0;
    const double a = img.at(x0, y0), b = img.at(x1, y0);
    const double c = img.at(x0, y1), d = img.at(x1, y1);
    return (a * (1.0 - fx) + b * fx) * (1.0 - fy) + (c * (1.0 - fx) + d * fx) * fy;
}

// Radial sub-pixel edge scan around (u0, v0): for every ray, sample the
// intensity outward over [r0-window, r0+window], take the *first* location
// where |dI/dr| reaches half its peak (walking out of the material that is the
// boundary), and refine it to the gradient's parabola vertex — the intensity
// inflection point, i.e. the sub-pixel edge.
void scanEdgeRays(const GrayImage& img, double u0, double v0, double r0,
                  double window, std::vector<std::array<double, 2>>& out)
{
    out.clear();
    if (!img.valid() || window <= 0.0)
        return;
    const int rays = 360;
    const double step = 0.5;
    const int m = std::max(7, static_cast<int>(2.0 * window / step) + 1);
    std::vector<double> prof(static_cast<std::size_t>(m));
    std::vector<double> grad(static_cast<std::size_t>(m), 0.0);
    const double twoPi = 2.0 * kPi;
    for (int k = 0; k < rays; ++k) {
        const double ang = twoPi * static_cast<double>(k) / rays;
        const double dx = std::cos(ang), dy = std::sin(ang);
        double lo = 1e300, hi = -1e300;
        for (int j = 0; j < m; ++j) {
            const double r = r0 - window + static_cast<double>(j) * step;
            const double x = u0 + r * dx, y = v0 + r * dy;
            if (x < 0.0 || y < 0.0 || x > img.width - 1 || y > img.height - 1) {
                prof[static_cast<std::size_t>(j)] =
                    std::numeric_limits<double>::quiet_NaN();
                continue;
            }
            const double val = bilinear(img, x, y);
            prof[static_cast<std::size_t>(j)] = val;
            lo = std::min(lo, val);
            hi = std::max(hi, val);
        }
        if (!(hi - lo >= 12.0))
            continue;                       // flat profile: no edge to trust
        for (int j = 1; j + 1 < m; ++j) {
            const double p0 = prof[static_cast<std::size_t>(j - 1)];
            const double p2 = prof[static_cast<std::size_t>(j + 1)];
            grad[static_cast<std::size_t>(j)] =
                (std::isfinite(p0) && std::isfinite(p2)) ? 0.5 * (p2 - p0) : 0.0;
        }
        grad[0] = 0.0;
        grad[static_cast<std::size_t>(m - 1)] = 0.0;
        double peak = 0.0;
        for (int j = 0; j < m; ++j)
            peak = std::max(peak, std::fabs(grad[static_cast<std::size_t>(j)]));
        if (peak < std::max(3.0, 0.15 * (hi - lo)))
            continue;
        // The edge we are after is where the *material* ends.  On the ⌀26 hub
        // the material is followed by a dark groove (the step down to the base
        // plate) and then more material, so the boundary is the interior
        // intensity *minimum*: the strongest gradient alone sits a few px
        // inside it (23.54 mm where the step is really at 172 px).  A hole, by
        // contrast, is a single dark→bright ramp with no interior minimum, so
        // there we fall back to the strongest intensity step (its inflection
        // point).
        int best = -1;
        double bestG = 0.0;
        for (int j = 1; j + 1 < m; ++j) {
            if (std::isfinite(grad[static_cast<std::size_t>(j)])
                && std::fabs(grad[static_cast<std::size_t>(j)]) > bestG) {
                bestG = std::fabs(grad[static_cast<std::size_t>(j)]);
                best = j;
            }
        }
        const double p1 = prof[1];
        const double pN = prof[static_cast<std::size_t>(m - 2)];
        int dip = -1;
        double dipV = 1e300;
        if (std::isfinite(p1) && std::isfinite(pN)) {
            const double endLevel = std::min(p1, pN);
            for (int j = 2; j + 2 < m; ++j) {
                const double pj = prof[static_cast<std::size_t>(j)];
                if (!std::isfinite(pj))
                    continue;
                if (pj < prof[static_cast<std::size_t>(j - 1)]
                    && pj <= prof[static_cast<std::size_t>(j + 1)]
                    && pj <= endLevel - 0.35 * (hi - lo) && pj < dipV) {
                    dipV = pj;
                    dip = j;
                }
            }
        }
        if (dip > 0) {
            const double q0 = prof[static_cast<std::size_t>(dip - 1)];
            const double q1 = prof[static_cast<std::size_t>(dip)];
            const double q2 = prof[static_cast<std::size_t>(dip + 1)];
            const double den = q0 - 2.0 * q1 + q2;
            double delta = (std::fabs(den) > 1e-12) ? 0.5 * (q0 - q2) / den : 0.0;
            if (delta < -1.0 || delta > 1.0)
                delta = 0.0;
            const double r = r0 - window + (static_cast<double>(dip) + delta) * step;
            out.push_back({ u0 + r * dx, v0 + r * dy });
            continue;
        }
        if (best <= 0 || best >= m - 1)
            continue;                       // edge runs off the window
        const double g0 = grad[static_cast<std::size_t>(best - 1)];
        const double g1 = grad[static_cast<std::size_t>(best)];
        const double g2 = grad[static_cast<std::size_t>(best + 1)];
        const double den = g0 - 2.0 * g1 + g2;
        double delta = (std::fabs(den) > 1e-12) ? 0.5 * (g0 - g2) / den : 0.0;
        if (delta < -1.0 || delta > 1.0)
            delta = 0.0;
        const double r = r0 - window + (static_cast<double>(best) + delta) * step;
        out.push_back({ u0 + r * dx, v0 + r * dy });
    }
}

} // namespace

BoundaryCircle measureBoundaryCircle(
    const std::vector<Vec3>& roiPoints,
    const std::vector<std::size_t>& roiCells,
    int gridW, int gridH,
    const std::vector<double>& grid,
    int imageW, int imageH,
    const GrayImage& img,
    bool materialInside)
{
    BoundaryCircle bc;
    const std::size_t n = std::min(roiPoints.size(), roiCells.size());
    std::vector<Vec3> pts;
    std::vector<std::size_t> cells;
    pts.reserve(n);
    cells.reserve(n);
    for (std::size_t i = 0; i < n; ++i) {
        if (isFinite(roiPoints[i])) {
            pts.push_back(roiPoints[i]);
            cells.push_back(roiCells[i]);
        }
    }
    if (pts.size() < 12) {
        bc.message = "点数不足（边界圆法至少需要 12 点）";
        return bc;
    }

    // 1. dominant material plane + narrow band (a ROI drawn around a hole is
    //    mostly material; a ROI drawn inside a solid part is all material).
    //    RANSAC, not plain LSQ: the ⌀63.5 ROI covers the whole disc and the
    //    plate behind it, and a LSQ plane through all of that is the average of
    //    every level ("measured" 96 mm with a 29 mm band).
    Plane plane;
    const double tol = 0.08;            // ≈ one grid pitch (0.0755 mm)
    if (!fitDominantPlane(pts, tol, plane)) {
        bc.message = plane.message.empty() ? std::string("平面拟合失败") : plane.message;
        return bc;
    }
    std::vector<double> dev = deviations(pts, plane);
    std::vector<std::size_t> keep;
    keep.reserve(pts.size());
    for (std::size_t i = 0; i < pts.size(); ++i)
        if (std::fabs(dev[i]) <= tol)
            keep.push_back(i);
    std::vector<Vec3> mat;
    std::vector<std::size_t> matCells;
    mat.reserve(keep.size());
    matCells.reserve(keep.size());
    for (std::size_t i : keep) {
        mat.push_back(pts[i]);
        matCells.push_back(cells[i]);
    }
    if (mat.size() >= 3)
        fitPlaneRaw(mat, plane);
    dev = deviations(mat, plane);
    std::vector<double> absDev(dev.size());
    for (std::size_t i = 0; i < dev.size(); ++i)
        absDev[i] = std::fabs(dev[i]);
    const double sigma = kMadScale * medianOf(absDev);
    const double band = std::max(3.0 * sigma, 0.05);

    std::vector<Vec3> bpts;
    std::vector<std::size_t> bcells;
    for (std::size_t i = 0; i < mat.size(); ++i) {
        if (std::fabs(dev[i]) <= band) {
            bpts.push_back(mat[i]);
            bcells.push_back(matCells[i]);
        }
    }
    if (bpts.size() < 12) {
        bc.message = "平面带内材料点不足（孔壁/背景点已排除）";
        return bc;
    }
    bc.debug = "DBG pts=" + std::to_string(pts.size())
        + " mat=" + std::to_string(mat.size())
        + " band=" + std::to_string(bpts.size())
        + " bandMm=" + std::to_string(band)
        + " n=(" + std::to_string(plane.normal[0]) + "," + std::to_string(plane.normal[1])
        + "," + std::to_string(plane.normal[2]) + ")";

    // 2. in-plane frame around the material centroid.
    Vec3 u, v;
    planeBasis(plane.normal, u, v);
    const Vec3 c3 = centroid(bpts);

    const bool haveGrid = gridW > 0 && gridH > 0
        && grid.size() >= static_cast<std::size_t>(gridW) * gridH * 3;
    const bool haveImage = imageW > 0 && imageH > 0 && img.valid();
    const double sx = (haveGrid && imageW > 0) ? static_cast<double>(imageW) / gridW : 1.0;
    const double sy = (haveGrid && imageH > 0) ? static_cast<double>(imageH) / gridH : 1.0;
    auto cellToPx = [&](std::size_t cell, double& pu, double& pv) {
        const int cx = static_cast<int>(cell % static_cast<std::size_t>(gridW));
        const int cy = static_cast<int>(cell / static_cast<std::size_t>(gridW));
        pu = (cx + 0.5) * sx;
        pv = (cy + 0.5) * sy;
    };

    std::vector<std::array<double, 2>> px(bpts.size());
    std::vector<std::array<double, 2>> planeXY(bpts.size());
    std::vector<double> planeR(bpts.size());
    double su = 0.0, sv = 0.0;
    for (std::size_t i = 0; i < bpts.size(); ++i) {
        const Vec3 q = sub(bpts[i], c3);
        const double xi = dot(q, u), eta = dot(q, v);
        planeXY[i] = { xi, eta };
        planeR[i] = std::sqrt(xi * xi + eta * eta);
        double pu = 0.0, pv = 0.0;
        if (haveGrid)
            cellToPx(bcells[i], pu, pv);
        px[i] = { pu, pv };
        su += pu;
        sv += pv;
    }
    const double bandCu = su / static_cast<double>(bpts.size());
    const double bandCv = sv / static_cast<double>(bpts.size());
    {
        double uLo = 1e300, uHi = -1e300, vLo = 1e300, vHi = -1e300;
        for (const auto& q : px) {
            uLo = std::min(uLo, q[0]); uHi = std::max(uHi, q[0]);
            vLo = std::min(vLo, q[1]); vHi = std::max(vHi, q[1]);
        }
        std::vector<double> srt = planeR;
        std::sort(srt.begin(), srt.end());
        auto q = [&](double f) {
            return srt[std::min(srt.size() - 1, static_cast<std::size_t>(f * srt.size()))];
        };
        bc.debug += " pxBox=(" + std::to_string(uLo) + "," + std::to_string(vLo) + ")-("
            + std::to_string(uHi) + "," + std::to_string(vHi) + ")"
            + " bandC=(" + std::to_string(bandCu) + "," + std::to_string(bandCv) + ")"
            + " Rq=" + std::to_string(q(0.05)) + "/" + std::to_string(q(0.25)) + "/"
            + std::to_string(q(0.50)) + "/" + std::to_string(q(0.75)) + "/"
            + std::to_string(q(0.95));
    }

    // 3. seed centre / radius.
    double u0 = bandCu, v0 = bandCv, r0px = 0.0;
    AffineMap map;
    std::vector<Vec3> contour3d;        // 3-D points of the outer contour (ring only)
    if (haveGrid && haveImage)
        solveAffine(px, planeXY, map);

    if (map.ok) {
        const double s = std::sqrt(std::fabs(map.det()));
        if (s > 0.0)
            bc.mmPerPx = s;
        if (!materialInside) {
            // Hole.  The centre must come from where the *material is absent*,
            // not from the material centroid: an operator drags the rectangle
            // around a hole, but "around" is not "centred on".  On the real ⌀6
            // ROI the hole sits right-of-centre (the material is a crescent on
            // the left), so the material centroid lands ~2 mm off the hole axis;
            // the inner tenth of the band radii is then a point *inside* the
            // hole (1.5 mm instead of 3.0 mm) and the image scan hunts texture
            // inside the hole — that is the 2.06 mm of the first attempt.
            //
            // So: build the material mask over the whole grid (a cell is material
            // when it holds a point inside the plane band), flood the *complement*
            // from the ROI centre, and read the hole centre and its equivalent
            // radius off that component.  The complement is the hole for a real
            // hole (the sensor returns nothing, or only the wall/floor outside the
            // band), and it is enclosed by material so the flood cannot leak into
            // the background.
            const std::size_t total = static_cast<std::size_t>(gridW) * gridH;
            std::vector<char> matMask(total, 0);
            const Vec3 nn = plane.normal;
            for (std::size_t i = 0; i < total; ++i) {
                const double x = grid[i * 3], y = grid[i * 3 + 1], z = grid[i * 3 + 2];
                if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z))
                    continue;
                if (x == 0.0 && y == 0.0 && z == 0.0)
                    continue;
                const double d = nn[0] * x + nn[1] * y + nn[2] * z + plane.d;
                if (std::fabs(d) <= band)
                    matMask[i] = 1;
            }
            std::vector<char> emptyMask(total);
            for (std::size_t i = 0; i < total; ++i)
                emptyMask[i] = matMask[i] ? 0 : 1;
            // Seed: the middle of the ROI's own cell rectangle (the operator's
            // "centre" of the drag), not the material centroid.
            std::size_t cxLo = cells[0] % static_cast<std::size_t>(gridW), cxHi = cxLo;
            std::size_t cyLo = cells[0] / static_cast<std::size_t>(gridW), cyHi = cyLo;
            for (std::size_t c : cells) {
                const std::size_t cx = c % static_cast<std::size_t>(gridW);
                const std::size_t cy = c / static_cast<std::size_t>(gridW);
                cxLo = std::min(cxLo, cx); cxHi = std::max(cxHi, cx);
                cyLo = std::min(cyLo, cy); cyHi = std::max(cyHi, cy);
            }
            const std::size_t roiSeed =
                static_cast<std::size_t>((cyLo + cyHi) / 2) * gridW + (cxLo + cxHi) / 2;
            std::vector<std::size_t> hole;
            const bool gotHole = floodComponent(emptyMask, gridW, gridH, roiSeed, hole)
                && hole.size() >= 50 && hole.size() < total / 2;
            std::size_t hxLo = total, hxHi = 0, hyLo = total, hyHi = 0;
            for (std::size_t c : hole) {
                const std::size_t cx = c % static_cast<std::size_t>(gridW);
                const std::size_t cy = c / static_cast<std::size_t>(gridW);
                hxLo = std::min(hxLo, cx); hxHi = std::max(hxHi, cx);
                hyLo = std::min(hyLo, cy); hyHi = std::max(hyHi, cy);
            }
            const bool enclosed = gotHole && hxLo > 0 && hyLo > 0 && hxHi + 1 < gridW
                && hyHi + 1 < gridH;
            if (enclosed) {
                double su = 0.0, sv = 0.0;
                for (std::size_t c : hole) {
                    double pu = 0.0, pv = 0.0;
                    cellToPx(c, pu, pv);
                    su += pu;
                    sv += pv;
                }
                u0 = su / static_cast<double>(hole.size());
                v0 = sv / static_cast<double>(hole.size());
                r0px = std::sqrt(static_cast<double>(hole.size()) * sx * sy / kPi);
                bc.debug += " holeFlood=" + std::to_string(hole.size())
                    + " c=(" + std::to_string(u0) + "," + std::to_string(v0) + ")"
                    + " r=" + std::to_string(r0px);
                // T-012 debug: the 3-D material inner boundary about that centre
                // (per-sector innermost band point, median) — tells the bore apart
                // from the chamfered opening the image shows.
                std::vector<double> innerR(360, -1.0);
                for (std::size_t i = 0; i < bpts.size(); ++i) {
                    const double du = px[i][0] - u0, dv = px[i][1] - v0;
                    const double rr = std::sqrt(du * du + dv * dv);
                    int sg = static_cast<int>((std::atan2(dv, du) + kPi) / (2.0 * kPi) * 360.0);
                    sg = std::max(0, std::min(sg, 359));
                    if (innerR[static_cast<std::size_t>(sg)] < 0.0
                        || rr < innerR[static_cast<std::size_t>(sg)])
                        innerR[static_cast<std::size_t>(sg)] = rr;
                }
                std::vector<double> valid;
                for (double v : innerR)
                    if (v >= 0.0)
                        valid.push_back(v);
                if (!valid.empty()) {
                    std::sort(valid.begin(), valid.end());
                    bc.debug += " inner3d_med=" + std::to_string(valid[valid.size() / 2])
                        + " min=" + std::to_string(valid.front())
                        + " max=" + std::to_string(valid.back())
                        + " n=" + std::to_string(valid.size());
                }
            } else {
                // No enclosed void to seed from: fall back to the inner tenth of
                // the band radii (the ROI really is a ring of material).
                const double rRim = percentile(planeR, 0.10);
                if (s > 0.0)
                    r0px = rRim / s;
                bc.debug += " holeFlood=none(" + std::to_string(hole.size()) + ")";
            }
        } else {
            // Outer edge: grow the material region out of the ROI over the whole
            // grid (|plane deviation| <= band) and keep the component that holds
            // the ROI — the capability that did not exist before.
            const std::size_t total = static_cast<std::size_t>(gridW) * gridH;
            std::vector<char> inRegion(total, 0);
            const Vec3 nn = plane.normal;
            for (std::size_t i = 0; i < total; ++i) {
                const double x = grid[i * 3], y = grid[i * 3 + 1], z = grid[i * 3 + 2];
                if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z))
                    continue;
                if (x == 0.0 && y == 0.0 && z == 0.0)
                    continue;
                const double d = nn[0] * x + nn[1] * y + nn[2] * z + plane.d;
                if (std::fabs(d) <= band)
                    inRegion[i] = 1;
            }
            const std::size_t seed = bcells[bcells.size() / 2];
            std::vector<std::size_t> stack;
            std::vector<char> vis(total, 0);
            std::vector<std::size_t> comp;
            if (seed < total && inRegion[seed]) {
                stack.push_back(seed);
                vis[seed] = 1;
                while (!stack.empty()) {
                    const std::size_t cur = stack.back();
                    stack.pop_back();
                    comp.push_back(cur);
                    const int cx = static_cast<int>(cur % static_cast<std::size_t>(gridW));
                    const int cy = static_cast<int>(cur / static_cast<std::size_t>(gridW));
                    const int nx[4] = { cx - 1, cx + 1, cx, cx };
                    const int ny[4] = { cy, cy, cy - 1, cy + 1 };
                    for (int k = 0; k < 4; ++k) {
                        if (nx[k] < 0 || nx[k] >= gridW || ny[k] < 0 || ny[k] >= gridH)
                            continue;
                        const std::size_t nb = static_cast<std::size_t>(ny[k]) * gridW + nx[k];
                        if (inRegion[nb] && !vis[nb]) {
                            vis[nb] = 1;
                            stack.push_back(nb);
                        }
                    }
                }
            }
            if (!comp.empty()) {
                std::vector<char> inComp(total, 0);
                for (std::size_t c : comp)
                    inComp[c] = 1;
                // Outer contour: per angular sector about the ROI centre, the
                // region cell with the largest in-plane radius (this skips the
                // relief slots, which are interior boundaries).
                const int sectors = 720;
                std::vector<double> bestR(static_cast<std::size_t>(sectors), -1.0);
                std::vector<std::array<double, 3>> bestP(static_cast<std::size_t>(sectors));
                for (std::size_t c : comp) {
                    const int cx = static_cast<int>(c % static_cast<std::size_t>(gridW));
                    const int cy = static_cast<int>(c / static_cast<std::size_t>(gridW));
                    bool boundary = false;
                    const int nx[4] = { cx - 1, cx + 1, cx, cx };
                    const int ny[4] = { cy, cy, cy - 1, cy + 1 };
                    for (int k = 0; k < 4 && !boundary; ++k) {
                        if (nx[k] < 0 || nx[k] >= gridW || ny[k] < 0 || ny[k] >= gridH) {
                            boundary = true;
                            break;
                        }
                        const std::size_t nb =
                            static_cast<std::size_t>(ny[k]) * gridW + nx[k];
                        if (!inComp[nb])
                            boundary = true;
                    }
                    if (!boundary)
                        continue;
                    const double x = grid[c * 3], y = grid[c * 3 + 1], z = grid[c * 3 + 2];
                    const Vec3 q = sub(Vec3{ x, y, z }, c3);
                    const double xi = dot(q, u), eta = dot(q, v);
                    const double rr = std::sqrt(xi * xi + eta * eta);
                    const double ang = std::atan2(eta, xi);
                    int s = static_cast<int>((ang + kPi) / (2.0 * kPi) * sectors);
                    s = std::max(0, std::min(s, sectors - 1));
                    if (rr > bestR[static_cast<std::size_t>(s)]) {
                        bestR[static_cast<std::size_t>(s)] = rr;
                        bestP[static_cast<std::size_t>(s)] = { x, y, z };
                    }
                }
                std::vector<std::array<double, 2>> cxy;
                for (int s = 0; s < sectors; ++s) {
                    if (bestR[static_cast<std::size_t>(s)] < 0.0)
                        continue;
                    const Vec3& p = bestP[static_cast<std::size_t>(s)];
                    contour3d.push_back(p);
                    const Vec3 q = sub(p, c3);
                    cxy.push_back({ dot(q, u), dot(q, v) });
                }
                if (!cxy.empty()) {
                    std::vector<Vec3> flat;
                    flat.reserve(cxy.size());
                    for (const auto& q : cxy)
                        flat.push_back({ q[0], q[1], 0.0 });
                    const Circle cs = fitCircle(flat, 1, 2.5);
                    if (cs.valid) {
                        if (map.invert(cs.center[0], cs.center[1], u0, v0)) {
                            const double s2 = std::sqrt(std::fabs(map.det()));
                            if (s2 > 0.0)
                                r0px = cs.radius / s2;
                        }
                    }
                }
            }
            // Grow the affine map over the whole region for a better-conditioned
            // (and better-extrapolating) fit than the ROI-only version.
            if (!comp.empty()) {
                std::vector<std::array<double, 2>> ruv;
                std::vector<std::array<double, 2>> rxy;
                const std::size_t stride = comp.size() > 40000 ? comp.size() / 40000 + 1 : 1;
                for (std::size_t idx = 0; idx < comp.size(); idx += stride) {
                    const std::size_t c = comp[idx];
                    const int cx = static_cast<int>(c % static_cast<std::size_t>(gridW));
                    const int cy = static_cast<int>(c / static_cast<std::size_t>(gridW));
                    const double x = grid[c * 3], y = grid[c * 3 + 1], z = grid[c * 3 + 2];
                    const Vec3 q = sub(Vec3{ x, y, z }, c3);
                    ruv.push_back({ (cx + 0.5) * sx, (cy + 0.5) * sy });
                    rxy.push_back({ dot(q, u), dot(q, v) });
                }
                AffineMap wide;
                if (solveAffine(ruv, rxy, wide)) {
                    map = wide;
                    const double s2 = std::sqrt(std::fabs(map.det()));
                    if (s2 > 0.0)
                        bc.mmPerPx = s2;
                }
            }
        }
    }
    bc.centerU = u0;
    bc.centerV = v0;
    if (img.valid()) {
        std::string hx, vy;
        for (int dx = -64; dx <= 64; dx += 2)
            hx += " " + std::to_string(static_cast<int>(bilinear(img, u0 + dx, v0)));
        for (int dy = -64; dy <= 64; dy += 2)
            vy += " " + std::to_string(static_cast<int>(bilinear(img, u0, v0 + dy)));
        bc.debug += " HX" + hx + " VY" + vy;
        std::string prof;
        for (int r = 0; r <= 224; r += 4) {
            std::vector<double> vals;
            for (int k = 0; k < 90; ++k) {
                const double a = 2.0 * kPi * k / 90.0;
                const double x = u0 + r * std::cos(a), y = v0 + r * std::sin(a);
                if (x < 0.0 || y < 0.0 || x > img.width - 1 || y > img.height - 1)
                    continue;
                vals.push_back(bilinear(img, x, y));
            }
            if (vals.empty())
                continue;
            std::sort(vals.begin(), vals.end());
            prof += " " + std::to_string(r) + ":"
                + std::to_string(static_cast<int>(vals[vals.size() / 2]));
        }
        bc.debug += " RAD" + prof;
    }
    bc.debug += " | rRimMm=" + std::to_string(percentile(planeR, 0.10))
        + " rMaxMm=" + std::to_string(*std::max_element(planeR.begin(), planeR.end()))
        + " rMinMm=" + std::to_string(*std::min_element(planeR.begin(), planeR.end()))
        + " mmPerPx=" + std::to_string(bc.mmPerPx)
        + " u0=" + std::to_string(u0) + " v0=" + std::to_string(v0)
        + " r0px=" + std::to_string(r0px)
        + " mapOK=" + std::to_string(map.ok ? 1 : 0)
        + " imgWH=" + std::to_string(img.width) + "x" + std::to_string(img.height)
        + " gridWH=" + std::to_string(gridW) + "x" + std::to_string(gridH);

    // 4. sub-pixel scan + iterated circle fit in the plane frame.
    Circle final;
    if (haveImage && map.ok && r0px > 2.0) {
        const double window = materialInside ? 10.0 : 6.0;
        std::vector<std::array<double, 2>> edge;
        for (int iter = 0; iter < 3; ++iter) {
            scanEdgeRays(img, u0, v0, r0px, window, edge);
            bc.debug += " | it" + std::to_string(iter) + " r0px=" + std::to_string(r0px)
                + " edges=" + std::to_string(edge.size());
            if (edge.size() < 24)
                break;
            std::vector<Vec3> flat;
            flat.reserve(edge.size());
            for (const auto& e : edge) {
                double xi = 0.0, eta = 0.0;
                map.apply(e[0], e[1], xi, eta);
                flat.push_back({ xi, eta, 0.0 });
            }
            const Circle c = fitCircle(flat, 1, 2.5);
            if (!c.valid)
                break;
            bc.debug += " fitRpx=" + std::to_string(c.radius / (bc.mmPerPx > 0 ? bc.mmPerPx : 1.0))
                + " fitRnd=" + std::to_string(c.roundness);
            final = c;
            double nu = 0.0, nv = 0.0;
            const double s = std::sqrt(std::fabs(map.det()));
            if (map.invert(c.center[0], c.center[1], nu, nv)) {
                u0 = nu;
                v0 = nv;
                if (s > 0.0)
                    r0px = c.radius / s;
                bc.centerU = u0;
                bc.centerV = v0;
            }
        }
    }

    if (final.valid && final.used >= 24) {
        bc.radius = final.radius;
        bc.diameter = 2.0 * final.radius;
        bc.roundness = final.roundness;
        bc.rms = final.rms;
        bc.used = static_cast<int>(final.used);
        bc.center = { c3[0] + final.center[0] * u[0] + final.center[1] * v[0],
                      c3[1] + final.center[0] * u[1] + final.center[1] * v[1],
                      c3[2] + final.center[0] * u[2] + final.center[1] * v[2] };
        bc.normal = plane.normal;
        bc.sectors = 360;
        bc.coverage = static_cast<double>(final.used) / 360.0;
        bc.subpixel = true;
        bc.reliable = bc.coverage >= 0.5 && bc.radius > 0.0
            && bc.roundness <= 0.2 * bc.radius;
        bc.valid = true;
        if (!bc.reliable)
            bc.message = "图像边缘样本不足或离散度过大，结果仅供参照";
        return bc;
    }

    // 5. fall back to the 3-D boundary (no image, or no usable edge).
    if (!materialInside) {
        const HoleBoundary hb = holeBoundary(pts);
        if (!hb.valid) {
            bc.message = hb.message;
            return bc;
        }
        bc.diameter = hb.diameter;
        bc.radius = hb.radius;
        bc.center = hb.center;
        bc.normal = hb.normal;
        bc.roundness = hb.roundness;
        bc.rms = hb.rms;
        bc.used = static_cast<int>(hb.used);
        bc.sectors = hb.sectors;
        bc.coverage = hb.coverage;
        bc.reliable = hb.reliable;
        bc.valid = true;
        bc.message = "图像不可用，退回 3D 孔壁边界（粗）";
        return bc;
    }

    if (contour3d.size() >= 5) {
        const Circle c = fitCircle(contour3d, 1, 2.5);
        if (c.valid) {
            const double pitch = estimatePitch(planeXY);
            bc.radius = c.radius + 0.5 * pitch;   // contour cells sit inside the edge
            bc.diameter = 2.0 * bc.radius;
            bc.center = c.center;
            bc.normal = c.normal;
            bc.roundness = c.roundness;
            bc.rms = c.rms;
            bc.used = static_cast<int>(c.used);
            bc.sectors = static_cast<int>(contour3d.size());
            bc.coverage = 1.0;
            bc.reliable = false;
            bc.valid = true;
            bc.message = "图像不可用，退回 3D 外缘边界（粗）";
            return bc;
        }
    }

    bc.message = "找不到材料边界（ROI 内没有可用的边缘）";
    return bc;
}

SectionProfile sectionProfile(const std::vector<Vec3>& pts, int bins)
{
    SectionProfile sp;
    const std::vector<Vec3> p = finitePoints(pts);
    if (p.size() < 4) {
        sp.message = "点数不足（至少需要 4 点生成截面）";
        return sp;
    }
    if (bins < 2)
        bins = 2;

    // Principal direction of the ROI in the XY plane (2x2 symmetric
    // eigen-problem, closed form).
    const Vec3 c = centroid(p);
    double sxx = 0.0, sxy = 0.0, syy = 0.0;
    for (const Vec3& q : p) {
        const double dx = q[0] - c[0], dy = q[1] - c[1];
        sxx += dx * dx;
        sxy += dx * dy;
        syy += dy * dy;
    }
    const double dirAngle = 0.5 * std::atan2(2.0 * sxy, sxx - syy);
    const double dx = std::cos(dirAngle), dy = std::sin(dirAngle);

    std::vector<double> t(p.size());
    double tMin = 1e300, tMax = -1e300;
    for (std::size_t i = 0; i < p.size(); ++i) {
        t[i] = (p[i][0] - c[0]) * dx + (p[i][1] - c[1]) * dy;
        tMin = std::min(tMin, t[i]);
        tMax = std::max(tMax, t[i]);
    }
    const double span = tMax - tMin;
    if (span <= 1e-9) {
        sp.message = "ROI 主方向长度过小，无法生成截面";
        return sp;
    }
    const double step = span / static_cast<double>(bins);
    std::vector<std::vector<double>> bucket(static_cast<std::size_t>(bins));
    for (std::size_t i = 0; i < p.size(); ++i) {
        int b = static_cast<int>((t[i] - tMin) / step);
        b = std::max(0, std::min(bins - 1, b));
        bucket[static_cast<std::size_t>(b)].push_back(p[i][2]);
    }
    sp.points.reserve(static_cast<std::size_t>(bins));
    for (int b = 0; b < bins; ++b) {
        if (bucket[static_cast<std::size_t>(b)].empty())
            continue;
        const double tb = tMin + (static_cast<double>(b) + 0.5) * step;
        sp.points.push_back({ tb, medianOf(bucket[static_cast<std::size_t>(b)]) });
    }
    sp.tMin = tMin;
    sp.tMax = tMax;
    sp.stepMm = step;
    sp.valid = sp.points.size() >= 2;
    if (!sp.valid)
        sp.message = "有效分箱过少，无法生成截面";
    return sp;
}

std::array<double, 3> colormap(double t, bool coolWarm)
{
    auto clip01 = [](double v) { return v < 0.0 ? 0.0 : (v > 1.0 ? 1.0 : v); };
    // t is clamped here rather than trusted: the reference's green channel is
    // not clipped by its own formula (1 - |2t-1| * 0.85 goes negative below
    // t = 0), so an out-of-range t would otherwise produce a channel outside
    // [0, 1] and overflow the 8-bit conversion in the views.
    t = clip01(t);
    if (coolWarm) {
        return { clip01(1.6 * t + 0.1), 1.0 - std::fabs(2.0 * t - 1.0) * 0.85,
                 clip01(1.7 - 1.6 * t) };
    }
    return { clip01(1.5 - std::fabs(4.0 * t - 3.0)),
             clip01(1.5 - std::fabs(4.0 * t - 2.0)),
             clip01(1.5 - std::fabs(4.0 * t - 1.0)) };
}

std::vector<std::array<float, 3>> cloudDeviationColors(
    const std::vector<double>& grid, int w, int h, const Plane& plane,
    double lo, double hi, bool coolWarm,
    const std::vector<std::size_t>& highlightCells,
    const std::array<float, 3>& baseRgb)
{
    std::vector<std::array<float, 3>> out;
    if (w <= 0 || h <= 0 || grid.size() < 3)
        return out;

    const std::size_t cells = static_cast<std::size_t>(w) * static_cast<std::size_t>(h);
    const std::size_t n = std::min(cells, grid.size() / 3);

    std::vector<char> highlight(n, 0);
    for (std::size_t k : highlightCells)
        if (k < n)
            highlight[k] = 1;

    const double span = (hi - lo) > 1e-12 ? (hi - lo) : 1e-12;
    out.reserve(n);
    for (std::size_t i = 0; i < n; ++i) {
        const double x = grid[i * 3], y = grid[i * 3 + 1], z = grid[i * 3 + 2];
        // Same rule (and same order) as PointCloudUtils::filterValidPoints.
        if (std::isnan(x) || std::isnan(y) || std::isnan(z))
            continue;
        if (x == 0.0 && y == 0.0 && z == 0.0)
            continue;
        if (highlight[i] && plane.valid) {
            const double dev = plane.normal[0] * x + plane.normal[1] * y
                               + plane.normal[2] * z + plane.d;
            const double t = std::min(1.0, std::max(0.0, (dev - lo) / span));
            const std::array<double, 3> c = colormap(t, coolWarm);
            out.push_back({ static_cast<float>(c[0]), static_cast<float>(c[1]),
                            static_cast<float>(c[2]) });
        } else {
            out.push_back(baseRgb);
        }
    }
    return out;
}

} // namespace MeasureTools
