#pragma once

#include <array>
#include <cmath>
#include <cstddef>
#include <vector>

// Pure pixel<->3D helpers for the "2D 像素点 → 3D 点" tool (unit-tested,
// no Qt / RVC dependency).
//
// Two data layouts are supported:
//   1. Aligned (default): the point cloud is organized as an image grid and
//      pixel (px, py) maps to point index py*width + px.
//   2. Non-aligned (SwingLineScan + correspond2d=false): points do not line up
//      with the image grid.  A pixel -> point index is built either by
//      projecting every point through camera intrinsics (+ optional
//      extrinsics) or from an RVC CorrespondMap (3D point index -> 2D pixel).
//
// Extrinsics are a 4x4 row-major transform mapping the point-cloud frame into
// the camera/image frame; null / identity when the cloud is already in the
// camera frame.  Projection uses the pinhole model (distortion is not
// modeled).
namespace PixelTo3DTools {

struct Intrinsics {
    double fx = 0.0;
    double fy = 0.0;
    double cx = 0.0;
    double cy = 0.0;
};

inline bool alignedIndex(int px, int py, int w, int h, std::size_t& idx)
{
    if (w <= 0 || h <= 0 || px < 0 || py < 0 || px >= w || py >= h)
        return false;
    idx = static_cast<std::size_t>(py) * static_cast<std::size_t>(w)
        + static_cast<std::size_t>(px);
    return true;
}

inline bool pointAt(const std::vector<double>& xyzMm, std::size_t idx,
                    std::array<double, 3>& out)
{
    if (idx * 3 + 2 >= xyzMm.size())
        return false;
    const double x = xyzMm[idx * 3 + 0];
    const double y = xyzMm[idx * 3 + 1];
    const double z = xyzMm[idx * 3 + 2];
    if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z))
        return false;
    out = { x, y, z };
    return true;
}

// Project a 3D point (point-cloud frame, any linear unit) into pixel coords.
inline bool projectPoint(const std::array<double, 3>& p,
                         const double* ext16,  // nullable
                         const Intrinsics& k,
                         double& u, double& v)
{
    double x = p[0], y = p[1], z = p[2];
    if (ext16) {
        const double xw = x, yw = y, zw = z;
        x = ext16[0] * xw + ext16[1] * yw + ext16[2] * zw + ext16[3];
        y = ext16[4] * xw + ext16[5] * yw + ext16[6] * zw + ext16[7];
        z = ext16[8] * xw + ext16[9] * yw + ext16[10] * zw + ext16[11];
    }
    if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z))
        return false;
    if (z <= 1e-9)
        return false;   // at/behind the camera
    if (k.fx <= 0.0 || k.fy <= 0.0)
        return false;
    u = k.fx * x / z + k.cx;
    v = k.fy * y / z + k.cy;
    return true;
}

// Build pixel -> point index by projecting every point into the image.
// outIndex: w*h entries, -1 = empty.  First point per pixel wins.
inline int buildProjectedIndex(const std::vector<double>& xyz,  // n*3
                               const double* ext16,            // nullable
                               const Intrinsics& k,
                               int w, int h,
                               std::vector<int>& outIndex)
{
    outIndex.clear();
    if (w <= 0 || h <= 0 || xyz.size() < 3 || k.fx <= 0.0 || k.fy <= 0.0)
        return 0;
    outIndex.assign(static_cast<std::size_t>(w) * static_cast<std::size_t>(h), -1);
    int filled = 0;
    const std::size_t n = xyz.size() / 3;
    for (std::size_t i = 0; i < n; ++i) {
        const std::array<double, 3> p = { xyz[i * 3], xyz[i * 3 + 1], xyz[i * 3 + 2] };
        double u, v;
        if (!projectPoint(p, ext16, k, u, v))
            continue;
        const int px = static_cast<int>(std::lround(u));
        const int py = static_cast<int>(std::lround(v));
        if (px < 0 || py < 0 || px >= w || py >= h)
            continue;
        const std::size_t pix = static_cast<std::size_t>(py) * w + px;
        if (outIndex[pix] < 0) {
            outIndex[pix] = static_cast<int>(i);
            ++filled;
        }
    }
    return filled;
}

// Build pixel -> point index from an SDK CorrespondMap (3D point index -> 2D
// pixel).  cmap: n*2 doubles (x, y pixel coordinates).
inline int buildCorrespondIndex(const std::vector<double>& cmap,
                                int w, int h,
                                std::vector<int>& outIndex)
{
    outIndex.clear();
    if (w <= 0 || h <= 0 || cmap.size() < 2)
        return 0;
    outIndex.assign(static_cast<std::size_t>(w) * static_cast<std::size_t>(h), -1);
    int filled = 0;
    const std::size_t n = cmap.size() / 2;
    for (std::size_t i = 0; i < n; ++i) {
        const double u = cmap[i * 2];
        const double v = cmap[i * 2 + 1];
        if (!std::isfinite(u) || !std::isfinite(v))
            continue;
        const int px = static_cast<int>(std::lround(u));
        const int py = static_cast<int>(std::lround(v));
        if (px < 0 || py < 0 || px >= w || py >= h)
            continue;
        const std::size_t pix = static_cast<std::size_t>(py) * w + px;
        if (outIndex[pix] < 0) {
            outIndex[pix] = static_cast<int>(i);
            ++filled;
        }
    }
    return filled;
}

// Look up a pixel in a previously built index (projected or correspond).
inline bool queryIndex(const std::vector<int>& index, int w, int h,
                       int px, int py,
                       const std::vector<double>& xyz,  // n*3
                       std::array<double, 3>& out)
{
    std::size_t idx = 0;
    if (!alignedIndex(px, py, w, h, idx))
        return false;
    if (idx >= index.size())
        return false;
    const int pt = index[idx];
    if (pt < 0)
        return false;
    return pointAt(xyz, static_cast<std::size_t>(pt), out);
}

} // namespace PixelTo3DTools
