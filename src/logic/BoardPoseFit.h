#pragma once

#include <array>
#include <cmath>
#include <vector>

// Fit a calibration board's pose (center + orientation) from its detected 3D
// points, in the camera frame (stage 8 board-pose visualization).
//
// PCA of the point set yields the plane normal (smallest-variance direction)
// and the two in-plane principal axes; the in-plane x-axis is oriented from
// the first to the last point so the recovered frame is deterministic.  The
// quaternion uses the same (x, y, z, w) convention as TransformTools::quatToRot
// and RVBUST Vis (identity = {0,0,0,1}).  Invalid/zero-padded points are
// skipped; fewer than 3 valid points -> valid == false.
namespace BoardPoseFit {

struct Pose {
    bool valid = false;
    std::array<float, 3> center{};  // mm
    std::array<float, 3> normal{};  // unit normal (positive-z preferred)
    std::array<float, 4> quat{};    // (x, y, z, w)
    float extentX = 0.0f;           // mm, along in-plane x
    float extentY = 0.0f;           // mm, along in-plane y
};

// Jacobi eigen-decomposition of a 3x3 symmetric matrix (Numerical-Recipes
// style).  On return `a` holds the eigenvalues on its diagonal and `v` holds
// the eigenvectors as columns (v[col*3+row]).
inline void jacobi3(std::array<double, 9>& a, std::array<double, 9>& v)
{
    v = { 1, 0, 0, 0, 1, 0, 0, 0, 1 };
    for (int sweep = 0; sweep < 50; ++sweep) {
        double offsum = 0.0;
        for (int p = 0; p < 3; ++p)
            for (int q = p + 1; q < 3; ++q)
                offsum += std::fabs(a[static_cast<std::size_t>(p * 3 + q)]);
        if (offsum < 1e-12) break;

        for (int p = 0; p < 3; ++p) {
            for (int q = p + 1; q < 3; ++q) {
                const double apq = a[static_cast<std::size_t>(p * 3 + q)];
                if (std::fabs(apq) < 1e-14) continue;
                const double theta = (a[static_cast<std::size_t>(q * 3 + q)]
                                      - a[static_cast<std::size_t>(p * 3 + p)])
                                   / (2.0 * apq);
                const double t = (theta >= 0.0 ? 1.0 : -1.0)
                               / (std::fabs(theta) + std::sqrt(theta * theta + 1.0));
                const double c = 1.0 / std::sqrt(t * t + 1.0);
                const double s = t * c;
                const double tau = s / (1.0 + c);

                const double app = a[static_cast<std::size_t>(p * 3 + p)];
                const double aqq = a[static_cast<std::size_t>(q * 3 + q)];
                a[static_cast<std::size_t>(p * 3 + p)] = app - t * apq;
                a[static_cast<std::size_t>(q * 3 + q)] = aqq + t * apq;
                a[static_cast<std::size_t>(p * 3 + q)] = 0.0;
                a[static_cast<std::size_t>(q * 3 + p)] = 0.0;

                for (int k = 0; k < 3; ++k) {
                    if (k == p || k == q) continue;
                    const double akp = a[static_cast<std::size_t>(k * 3 + p)];
                    const double akq = a[static_cast<std::size_t>(k * 3 + q)];
                    a[static_cast<std::size_t>(k * 3 + p)] = akp - s * (akq + tau * akp);
                    a[static_cast<std::size_t>(p * 3 + k)] = a[static_cast<std::size_t>(k * 3 + p)];
                    a[static_cast<std::size_t>(k * 3 + q)] = akq + s * (akp - tau * akq);
                    a[static_cast<std::size_t>(q * 3 + k)] = a[static_cast<std::size_t>(k * 3 + q)];
                }
                for (int k = 0; k < 3; ++k) {
                    const double vkp = v[static_cast<std::size_t>(k * 3 + p)];
                    const double vkq = v[static_cast<std::size_t>(k * 3 + q)];
                    v[static_cast<std::size_t>(k * 3 + p)] = vkp - s * (vkq + tau * vkp);
                    v[static_cast<std::size_t>(k * 3 + q)] = vkq + s * (vkp - tau * vkq);
                }
            }
        }
    }
}

// Rotation matrix (columns x, y, z) -> unit quaternion (x, y, z, w).
inline std::array<double, 4> rotToQuat(const std::array<double, 3>& x,
                                       const std::array<double, 3>& y,
                                       const std::array<double, 3>& z)
{
    const double m00 = x[0], m10 = x[1], m20 = x[2];
    const double m01 = y[0], m11 = y[1], m21 = y[2];
    const double m02 = z[0], m12 = z[1], m22 = z[2];
    const double tr = m00 + m11 + m22;

    double qx, qy, qz, qw;
    if (tr > 0.0) {
        const double s = std::sqrt(tr + 1.0) * 2.0;
        qw = 0.25 * s;
        qx = (m21 - m12) / s;
        qy = (m02 - m20) / s;
        qz = (m10 - m01) / s;
    } else if (m00 > m11 && m00 > m22) {
        const double s = std::sqrt(1.0 + m00 - m11 - m22) * 2.0;
        qw = (m21 - m12) / s;
        qx = 0.25 * s;
        qy = (m01 + m10) / s;
        qz = (m02 + m20) / s;
    } else if (m11 > m22) {
        const double s = std::sqrt(1.0 + m11 - m00 - m22) * 2.0;
        qw = (m02 - m20) / s;
        qx = (m01 + m10) / s;
        qy = 0.25 * s;
        qz = (m12 + m21) / s;
    } else {
        const double s = std::sqrt(1.0 + m22 - m00 - m11) * 2.0;
        qw = (m10 - m01) / s;
        qx = (m02 + m20) / s;
        qy = (m12 + m21) / s;
        qz = 0.25 * s;
    }
    const double norm = std::sqrt(qx * qx + qy * qy + qz * qz + qw * qw);
    return { qx / norm, qy / norm, qz / norm, qw / norm };
}

inline Pose fit(const std::vector<std::array<float, 3>>& pts)
{
    Pose out;

    // Gather valid points (skip NaN and zero-padded detection tail).
    std::vector<std::array<double, 3>> p;
    p.reserve(pts.size());
    for (const auto& q : pts) {
        if (std::isnan(q[0]) || std::isnan(q[1]) || std::isnan(q[2]))
            continue;
        if (q[0] == 0.0f && q[1] == 0.0f && q[2] == 0.0f)
            continue;
        p.push_back({ static_cast<double>(q[0]),
                      static_cast<double>(q[1]),
                      static_cast<double>(q[2]) });
    }
    if (p.size() < 3)
        return out;

    // Centroid.
    std::array<double, 3> c{ 0.0, 0.0, 0.0 };
    for (const auto& q : p) { c[0] += q[0]; c[1] += q[1]; c[2] += q[2]; }
    const double invN = 1.0 / static_cast<double>(p.size());
    c[0] *= invN; c[1] *= invN; c[2] *= invN;

    // Covariance (sum of outer products; scale irrelevant to eigenvectors).
    std::array<double, 9> cov{};
    for (const auto& q : p) {
        const double dx = q[0] - c[0], dy = q[1] - c[1], dz = q[2] - c[2];
        cov[0] += dx * dx; cov[1] += dx * dy; cov[2] += dx * dz;
        cov[4] += dy * dy; cov[5] += dy * dz;
        cov[8] += dz * dz;
    }
    cov[3] = cov[1]; cov[6] = cov[2]; cov[7] = cov[5];

    std::array<double, 9> evec;
    jacobi3(cov, evec);
    const std::array<double, 3> eval = { cov[0], cov[4], cov[8] };

    // Sort eigenvectors by eigenvalue ascending (smallest first = normal).
    int idx[3] = { 0, 1, 2 };
    for (int i = 0; i < 3; ++i)
        for (int j = i + 1; j < 3; ++j)
            if (eval[idx[j]] < eval[idx[i]]) { const int t = idx[i]; idx[i] = idx[j]; idx[j] = t; }

    auto col = [&](int axis) -> std::array<double, 3> {
        return { evec[static_cast<std::size_t>(0 * 3 + axis)],
                 evec[static_cast<std::size_t>(1 * 3 + axis)],
                 evec[static_cast<std::size_t>(2 * 3 + axis)] };
    };

    std::array<double, 3> n = col(idx[0]);        // normal (smallest variance)
    std::array<double, 3> a = col(idx[2]);        // long axis (largest variance)
    std::array<double, 3> b = col(idx[1]);        // short axis

    // Orient normal to positive z (camera-forward / outward) when possible.
    if (n[2] < 0.0) { n[0] = -n[0]; n[1] = -n[1]; n[2] = -n[2]; }

    // Orient x-axis (long axis) from the first point toward the last point.
    const std::array<double, 3> fwd = { p.back()[0] - p.front()[0],
                                        p.back()[1] - p.front()[1],
                                        p.back()[2] - p.front()[2] };
    const double dot = a[0] * fwd[0] + a[1] * fwd[1] + a[2] * fwd[2];
    if (dot < 0.0) { a[0] = -a[0]; a[1] = -a[1]; a[2] = -a[2]; }

    const std::array<double, 3> x = a;
    // Right-handed y = n × x (perpendicular to n and to the long axis).
    const std::array<double, 3> y = {
        n[1] * x[2] - n[2] * x[1],
        n[2] * x[0] - n[0] * x[2],
        n[0] * x[1] - n[1] * x[0]
    };

    // In-plane extents (project all points onto x and y).
    double minX = 0.0, maxX = 0.0, minY = 0.0, maxY = 0.0;
    for (const auto& q : p) {
        const double dx = q[0] - c[0], dy = q[1] - c[1], dz = q[2] - c[2];
        const double px = dx * x[0] + dy * x[1] + dz * x[2];
        const double py = dx * y[0] + dy * y[1] + dz * y[2];
        // Parenthesized to dodge the min/max macros some TUs pull in via
        // <windows.h> before this header (function-like macros only expand when
        // the name is immediately followed by '(').
        minX = (std::min)(minX, px); maxX = (std::max)(maxX, px);
        minY = (std::min)(minY, py); maxY = (std::max)(maxY, py);
    }

    const std::array<double, 4> q = rotToQuat(x, y, n);

    out.valid = true;
    out.center = { static_cast<float>(c[0]), static_cast<float>(c[1]), static_cast<float>(c[2]) };
    out.normal = { static_cast<float>(n[0]), static_cast<float>(n[1]), static_cast<float>(n[2]) };
    out.quat = { static_cast<float>(q[0]), static_cast<float>(q[1]),
                 static_cast<float>(q[2]), static_cast<float>(q[3]) };
    out.extentX = static_cast<float>(maxX - minX);
    out.extentY = static_cast<float>(maxY - minY);
    return out;
}

} // namespace BoardPoseFit
