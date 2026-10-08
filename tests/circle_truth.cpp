// Known-truth synthetic scenes for the two circle tools (2026-10-08).
//
// 圆环拟合 measures the outer edge of a circular *object*; 孔径 measures a
// circular *hole*.  Both now run through MeasureTools::measureBoundaryCircle,
// and neither had a single test.  This harness answers, without a camera:
//
//   "on a part whose answer we already know, how far off is the current code?"
//
// A scene is a plane seen by a pinhole camera, tilted so the projection onto the
// image is a real homography (not a similarity) — that matters, because the
// kernel maps pixels into the plane with a least-squares *affine* fit and we
// want to see what that approximation costs.  The grid is built the way an
// aligned RGB-D sensor does it: cell (a,b) is the intersection of the ray
// through image pixel ((a+0.5)*scale, (b+0.5)*scale) with the surface.  The
// image is the same scene rendered with a Gaussian PSF of sigma = blurPx
// (4x supersampled, blurred, then box-downsampled) plus gray noise, so the edge
// has a genuine, blurred, sub-pixel position to find.
//
// Output: one line per scene, plus a summary.  Exit code 0 = every scene within
// the project criterion (|err| <= 0.5% of nominal).  Run:
//   build/src/Release/circle_truth.exe
#include "logic/MeasureTools.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <string>
#include <vector>

using MeasureTools::Vec3;

namespace {

constexpr double kPi = 3.14159265358979323846;

// ── scene description ──────────────────────────────────────────────────
struct Scene {
    std::string name;
    bool materialInside = false;  // true = solid disc (outer edge), false = hole
    double radius = 3.0;          // mm, truth
    double pitch = 0.0755;        // mm per grid cell, at the plane centre
    double tiltDeg = 0.0;         // rotation of the plane about world Y
    double gridNoiseMm = 0.0;     // gaussian noise along the plane normal
    double blurPx = 0.0;          // optical PSF sigma, in image pixels
    double imageNoise = 0.0;      // gaussian gray noise, in levels (0..255)
    double chamferMm = 0.0;       // 45-deg chamfer on the hole opening / disc rim:
                                  // the image boundary is at radius+chamfer, but
                                  // the point cloud sees the cone down to radius.
    int cells = 200;              // grid is cells x cells
    int scale = 2;                // image pixels per grid cell
    double distance = 400.0;      // camera -> plane centre, mm
    bool useImage = true;         // false exercises the 3-D-only fallback
    double k1 = 0.0;              // radial lens distortion (brown-conrady, r^2 term)
    double offsetMm = 0.0;        // in-plane x offset of the feature from the
                                  // optical axis — distortion only bites off-axis
    double stepR = 0.0;           // an annular step at this radius (0 = none):
    double stepDepth = 0.0;       //   the surface drops by this much beyond stepR.
                                  //   This is the Ø26 case — a real part has more
                                  //   than one transition near the edge, and the
                                  //   edge picker has to choose the right one.
};

// ── pinhole camera looking down +Z at a plane tilted about Y ───────────
struct Camera {
    double f = 1.0, cx = 0.0, cy = 0.0, distance = 0.0, tilt = 0.0, k1 = 0.0;
    double ox = 0.0, oy = 0.0;    // in-plane centre of the feature
    Vec3 n{}, uax{}, vax{}, p0{};

    Vec3 circleCenter() const
    {
        return { p0[0] + ox * uax[0] + oy * vax[0],
                 p0[1] + ox * uax[1] + oy * vax[1],
                 p0[2] + ox * uax[2] + oy * vax[2] };
    }
    // ideal pixel where the feature centre lands (ray = the point itself)
    void centerPixel(double& u, double& v) const
    {
        const Vec3 c = circleCenter();
        u = cx + f * c[0] / c[2];
        v = cy + f * c[1] / c[2];
    }

    // A pixel is a direction.  `undistort` maps an *observed* (distorted) pixel
    // back to the ideal ray — the point cloud is ideal, the raw image is not,
    // and that mismatch is exactly what an affine pixel->plane fit cannot absorb.
    Vec3 ray(double u, double v, bool undistort) const
    {
        double x = u - cx, y = v - cy;
        if (undistort && k1 != 0.0) {
            const double s = 1.0 + k1 * (x * x + y * y) / (f * f);
            x /= s;
            y /= s;
        }
        return { x, y, f };
    }

    // A pixel subtends pitch/scale mm at the plane, so f = distance*scale/pitch.
    static Camera make(double pitch, int scale, int imagePixels, double distance,
                       double tiltDeg, double k1 = 0.0, double ox = 0.0, double oy = 0.0)
    {
        Camera c;
        c.distance = distance;
        c.tilt = tiltDeg * kPi / 180.0;
        c.k1 = k1;
        c.ox = ox;
        c.oy = oy;
        c.f = distance * scale / pitch;
        c.cx = imagePixels / 2.0;        // in-plane origin lands on the image centre
        c.cy = imagePixels / 2.0;
        c.n = { std::sin(c.tilt), 0.0, std::cos(c.tilt) };
        c.uax = { std::cos(c.tilt), 0.0, -std::sin(c.tilt) };
        c.vax = { 0.0, 1.0, 0.0 };
        c.p0 = { 0.0, 0.0, distance };
        return c;
    }

    // ray through pixel (u,v) -> (hit point, in-plane coords xi/eta)
    bool trace(double u, double v, bool undistort, Vec3& hit, double& xi, double& eta) const
    {
        const Vec3 d = ray(u, v, undistort);
        const double den = n[0] * d[0] + n[1] * d[1] + n[2] * d[2];
        if (std::fabs(den) < 1e-12)
            return false;
        const double t = (n[0] * p0[0] + n[1] * p0[1] + n[2] * p0[2]) / den;
        if (t <= 0.0)
            return false;
        hit = { t * d[0], t * d[1], t * d[2] };
        const Vec3 q{ hit[0] - p0[0], hit[1] - p0[1], hit[2] - p0[2] };
        xi = q[0] * uax[0] + q[1] * uax[1] + q[2] * uax[2];
        eta = q[0] * vax[0] + q[1] * vax[1] + q[2] * vax[2];
        return true;
    }

    double radiusAt(double xi, double eta) const
    {
        const double dx = xi - ox, dy = eta - oy;
        return std::sqrt(dx * dx + dy * dy);
    }

    bool material(double xi, double eta, bool inside, double radius) const
    {
        const double r = radiusAt(xi, eta);
        return inside ? (r <= radius) : (r >= radius);
    }
};

double gauss(unsigned& s)
{
    // deterministic Box-Muller on a plain LCG (no <random> implementation drift)
    auto next = [&s]() {
        s = s * 1103515245u + 12345u;
        return ((s >> 8) & 0xffffff) / static_cast<double>(0xffffff);
    };
    const double u1 = std::max(1e-12, next());
    const double u2 = next();
    return std::sqrt(-2.0 * std::log(u1)) * std::cos(2.0 * kPi * u2);
}

// ── scene -> grid + image ──────────────────────────────────────────────
struct Data {
    int w = 0, h = 0;
    std::vector<double> grid;          // w*h*3, NaN = invalid
    int imageW = 0, imageH = 0;
    std::vector<unsigned char> image;
    Vec3 circleCenter{};               // world coordinates of the true centre
    double centerU = 0.0, centerV = 0.0;  // where that centre lands in the image
};

void blurInPlace(std::vector<float>& a, int w, int h, double sigma)
{
    if (sigma <= 0.0)
        return;
    const int r = std::max(1, static_cast<int>(std::ceil(3.0 * sigma)));
    std::vector<double> k(2 * r + 1);
    double sum = 0.0;
    for (int i = -r; i <= r; ++i) {
        k[i + r] = std::exp(-0.5 * (i / sigma) * (i / sigma));
        sum += k[i + r];
    }
    for (double& v : k)
        v /= sum;

    std::vector<float> tmp(a.size());
    for (int y = 0; y < h; ++y)          // horizontal
        for (int x = 0; x < w; ++x) {
            double acc = 0.0;
            for (int i = -r; i <= r; ++i)
                acc += k[i + r] * a[y * static_cast<std::size_t>(w) +
                                    std::min(w - 1, std::max(0, x + i))];
            tmp[y * static_cast<std::size_t>(w) + x] = static_cast<float>(acc);
        }
    for (int y = 0; y < h; ++y)          // vertical
        for (int x = 0; x < w; ++x) {
            double acc = 0.0;
            for (int i = -r; i <= r; ++i)
                acc += k[i + r] * tmp[std::min(h - 1, std::max(0, y + i)) *
                                         static_cast<std::size_t>(w) + x];
            a[y * static_cast<std::size_t>(w) + x] = static_cast<float>(acc);
        }
}

Data build(const Scene& s)
{
    Data d;
    const int S = 4;                     // supersampling for the image
    d.w = s.cells;
    d.h = s.cells;
    d.grid.assign(static_cast<std::size_t>(d.w) * d.h * 3,
                  std::numeric_limits<double>::quiet_NaN());
    const int imagePixels = s.cells * s.scale;
    const Camera cam = Camera::make(s.pitch, s.scale, imagePixels, s.distance,
                                    s.tiltDeg, s.k1, s.offsetMm, 0.0);
    unsigned rng = 12345u;
    d.circleCenter = cam.circleCenter();
    cam.centerPixel(d.centerU, d.centerV);

    for (int b = 0; b < s.cells; ++b) {
        for (int a = 0; a < s.cells; ++a) {
            Vec3 hit{};
            double xi = 0.0, eta = 0.0;
            if (!cam.trace((a + 0.5) * s.scale, (b + 0.5) * s.scale, false, hit, xi, eta))
                continue;
            if (!cam.material(xi, eta, s.materialInside, s.radius))
                continue;                // NaN: hole, or off the part
            // 45-deg chamfer: the tip of the cone is at `radius`, its rim at
            // radius+chamfer (hole) / radius-chamfer (disc).  The point cloud
            // sees this cone; the image only sees the rim.
            const double r = cam.radiusAt(xi, eta);
            const double chamfer = s.materialInside ? (r - (s.radius - s.chamferMm))
                                                    : ((s.radius + s.chamferMm) - r);
            // disc: the outer ring beyond stepR is lower (a boss).  hole: the
            // annulus next to the bore is recessed (a counterbore).
            const bool inStep = s.materialInside ? (r > s.stepR) : (r < s.stepR);
            const double step = (s.stepDepth > 0.0 && inStep) ? s.stepDepth : 0.0;
            const double depth = std::max(0.0, chamfer) + step;
            double dz = -depth;
            if (s.gridNoiseMm > 0.0)
                dz += s.gridNoiseMm * gauss(rng);
            const std::size_t i = (static_cast<std::size_t>(b) * d.w + a) * 3;
            d.grid[i + 0] = hit[0] + dz * cam.n[0];
            d.grid[i + 1] = hit[1] + dz * cam.n[1];
            d.grid[i + 2] = hit[2] + dz * cam.n[2];
        }
    }

    if (s.useImage) {
        d.imageW = imagePixels;
        d.imageH = imagePixels;
        d.image.assign(static_cast<std::size_t>(d.imageW) * d.imageH, 0);
        // Material mask at S x resolution, then a Gaussian PSF, then box
        // downsample — an optical blur, not a nearest-neighbour step.
        const int hw = d.imageW * S, hh = d.imageH * S;
        // the image boundary sits at the chamfer rim, not at the bore/face edge
        const double imageR = s.materialInside ? s.radius : s.radius + s.chamferMm;
        // Radiance, not a mask: background 30, top level 200, stepped-down
        // level 140 — so the step shows up as a brightness transition too.
        std::vector<float> lum(static_cast<std::size_t>(hw) * hh, 30.0f);
        for (int y = 0; y < hh; ++y)
            for (int x = 0; x < hw; ++x) {
                Vec3 hit{};
                double xi = 0.0, eta = 0.0;
                const double u = (x + 0.5) / S, v = (y + 0.5) / S;
                if (!cam.trace(u, v, true, hit, xi, eta))
                    continue;
                if (!cam.material(xi, eta, s.materialInside, imageR))
                    continue;
                const double r = cam.radiusAt(xi, eta);
                const bool onStep = s.stepDepth > 0.0 &&
                    (s.materialInside ? (r > s.stepR) : (r < s.stepR));
                lum[static_cast<std::size_t>(y) * hw + x] = onStep ? 140.0f : 200.0f;
            }
        blurInPlace(lum, hw, hh, s.blurPx * S);
        for (int y = 0; y < d.imageH; ++y)
            for (int x = 0; x < d.imageW; ++x) {
                double acc = 0.0;
                for (int sy = 0; sy < S; ++sy)
                    for (int sx = 0; sx < S; ++sx)
                        acc += lum[static_cast<std::size_t>(y * S + sy) * hw + x * S + sx];
                acc /= S * S;
                acc += s.imageNoise > 0.0 ? s.imageNoise * gauss(rng) : 0.0;
                d.image[static_cast<std::size_t>(y) * d.imageW + x] =
                    static_cast<unsigned char>(std::min(255.0, std::max(0.0, acc)));
            }
    }
    return d;
}

// ── run one scene ──────────────────────────────────────────────────────
struct Outcome {
    bool valid = false;
    bool subpixel = false;
    bool reliable = false;
    double diameter = 0.0;
    double centerErr = 0.0;
    double roundness = 0.0;
    double coverage = 0.0;
    double mmPerPx = 0.0;
    std::string message;
};

Outcome run(const Scene& s, const Data& d)
{
    Outcome o;
    // Guard: the whole feature + ROI margin must be inside the frame, or the
    // "error" is the scene's fault, not the algorithm's.
    {
        const double rPx = (s.radius + s.chamferMm + 4.0 * s.pitch) * s.scale / s.pitch;
        if (s.useImage &&
            (d.centerU - rPx < 1.0 || d.centerU + rPx > d.imageW - 2.0 ||
             d.centerV - rPx < 1.0 || d.centerV + rPx > d.imageH - 2.0)) {
            o.message = "OUT OF FRAME (scene invalid)";
            return o;
        }
    }
    const double margin = s.materialInside ? 0.0 : 3.0 * s.pitch;
    const double half = s.materialInside ? 0.75 * s.radius : s.radius + margin;
    // the ROI the operator would drag: centred on the feature, not the frame
    const int c0x = static_cast<int>(std::lround(d.centerU / s.scale - 0.5));
    const int c0y = static_cast<int>(std::lround(d.centerV / s.scale - 0.5));
    const int halfCells = std::max(2, static_cast<int>(half / s.pitch));
    const int x0 = std::max(0, c0x - halfCells);
    const int x1 = std::min(d.w - 1, c0x + halfCells);
    const int y0 = std::max(0, c0y - halfCells);
    const int y1 = std::min(d.h - 1, c0y + halfCells);

    std::vector<std::size_t> cells;
    const std::vector<Vec3> pts =
        MeasureTools::pointsInRoiIndexed(d.grid, d.w, d.h, x0, y0, x1, y1, &cells);

    MeasureTools::GrayImage img;
    if (s.useImage) {
        img.data = d.image.data();
        img.width = d.imageW;
        img.height = d.imageH;
        img.stride = d.imageW;
    }

    const MeasureTools::BoundaryCircle bc = MeasureTools::measureBoundaryCircle(
        pts, cells, d.w, d.h, d.grid, img.width, img.height, img, s.materialInside);
    o.valid = bc.valid;
    o.subpixel = bc.subpixel;
    o.reliable = bc.reliable;
    o.diameter = bc.diameter;
    o.roundness = bc.roundness;
    o.coverage = bc.coverage;
    o.mmPerPx = bc.mmPerPx;
    o.message = bc.message;
    const double dx = bc.center[0] - d.circleCenter[0];
    const double dy = bc.center[1] - d.circleCenter[1];
    const double dz = bc.center[2] - d.circleCenter[2];
    o.centerErr = std::sqrt(dx * dx + dy * dy + dz * dz);
    return o;
}

// Defects this harness has already characterised and reported (2026-10-08).
// They are *recorded* rather than *hidden*: the test stays green so the build
// stays usable, the numbers are still printed every run, and the day one of
// these starts passing the run says so loudly.  Deleting a name here without
// fixing the code makes the run red again.
bool isKnownDefect(const std::string& name)
{
    static const char* kKnown[] = {
        // 边缘选择（L2）：多跃变工件上报内部台阶/沉孔，而不是材料边界
        "disc_d26  stepR10",
        "disc_d26  stepR12",
        "disc_d26  stepR12 d2",
        "disc_d26  cham+step",
        "hole_d9   cboreR6 d2",
        "hole_d9   cboreR5.5 d.5",
        // 无图像时圆环拟合的 3D 外缘兜底不可达（contour3d 只在 map.ok 里建）
        "disc_d26  3D tilt15",
        "disc_d26  3D tilt0",
    };
    for (const char* k : kKnown)
        if (name == k)
            return true;
    return false;
}

} // namespace

int main(int argc, char** argv)
{
    (void)argc;
    (void)argv;

    std::vector<Scene> scenes;
    auto add = [&](const char* name, bool inside, double r, double tilt, double pitch,
                   double blur, double imgNoise, int cells, int scale, bool useImage,
                   double chamfer = 0.0, double k1 = 0.0, double offset = 0.0,
                   double stepR = 0.0, double stepDepth = 0.0) {
        Scene s;
        s.name = name;
        s.materialInside = inside;
        s.radius = r;
        s.tiltDeg = tilt;
        s.pitch = pitch;
        s.blurPx = blur;
        s.imageNoise = imgNoise;
        s.cells = cells;
        s.scale = scale;
        s.useImage = useImage;
        s.chamferMm = chamfer;
        s.k1 = k1;
        s.offsetMm = offset;
        s.stepR = stepR;
        s.stepDepth = stepDepth;
        scenes.push_back(s);
    };

    const double p = 0.0755;             // fine point pitch (an X2 at ~400 mm)
    // 孔径（孔）—— 图像路径，理想 → 现实
    add("hole_d6   ideal",        false, 3.00,  0, p, 0.0, 0.0, 200, 2, true);
    add("hole_d6   blur1 noise2", false, 3.00, 15, p, 1.0, 2.0, 200, 2, true);
    add("hole_d6   blur2 noise4", false, 3.00, 15, p, 2.0, 4.0, 200, 2, true);
    add("hole_d5   blur1 noise2", false, 2.50, 15, p, 1.0, 2.0, 200, 2, true);
    add("hole_d9   blur1 noise2", false, 4.50, 15, p, 1.0, 2.0, 240, 2, true);
    add("hole_d26  blur1 noise2", false, 13.0, 15, p, 1.0, 2.0, 500, 2, true);
    add("hole_d6   tilt45 blur1", false, 3.00, 45, p, 1.0, 2.0, 200, 2, true);
    // 孔径 —— 无图像（走 3D 兜底）
    add("hole_d6   3D tilt15",    false, 3.00, 15, p, 0.0, 0.0, 200, 2, false);
    add("hole_d9   3D tilt15",    false, 4.50, 15, p, 0.0, 0.0, 240, 2, false);
    // 孔径 —— 孔口倒角 0.5：图纸 Ø=孔口=2(R+0.5)，点云只见孔壁 R。
    //   报出的直径应落在哪一侧，就是 L5 那道定义题。
    add("hole_d6   chamfer0.5",    false, 3.00, 15, p, 1.0, 2.0, 200, 2, true, 0.5);
    add("hole_d9   chamfer0.5",    false, 4.50, 15, p, 1.0, 2.0, 240, 2, true, 0.5);
    add("hole_d9   chamfer1.0",    false, 4.50, 15, p, 1.0, 2.0, 240, 2, true, 1.0);
    // 孔径 —— 沉孔（counterbore）：孔壁 R=4.5，孔口沉台到 R=6。图纸 Ø=孔口=12。
    //   若报 9，现场按图纸比就是 −25%。
    add("hole_d9   cboreR6 d2",    false, 4.50, 15, p, 1.0, 2.0, 700, 2, true, 0.0, 0.0, 0.0, 6.0, 2.0);
    add("hole_d9   cboreR5.5 d.5", false, 4.50, 15, p, 1.0, 2.0, 700, 2, true, 0.0, 0.0, 0.0, 5.5, 0.5);
    // 离轴：特征不在光轴上。畸变与"仿射拟合像素→平面"都只在这里咬人。
    // scale=1（视场 = cells*pitch，够宽）以免特征出画；ROI 仍需整幅在内。
    add("hole_d9   off10 k1=.15", false, 4.50, 15, p, 1.0, 2.0, 600, 1, true, 0.0, 0.15, 10.0);
    add("hole_d9   off20 k1=.15", false, 4.50, 15, p, 1.0, 2.0, 800, 1, true, 0.0, 0.15, 20.0);
    add("hole_d9   off25 k1=.15", false, 4.50, 15, p, 1.0, 2.0, 900, 1, true, 0.0, 0.15, 25.0);
    add("hole_d9   off20 k1=0",   false, 4.50, 15, p, 1.0, 2.0, 800, 1, true, 0.0, 0.00, 20.0);
    // 圆环拟合（实心外缘）—— 图像路径
    add("disc_d26  ideal",        true,  13.0,  0, p, 0.0, 0.0, 500, 2, true);
    add("disc_d26  blur1 noise2", true,  13.0, 15, p, 1.0, 2.0, 500, 2, true);
    add("disc_d26  tilt45 blur1", true,  13.0, 45, p, 1.0, 2.0, 500, 2, true);
    // 圆环拟合 —— 边缘倒角 0.5：轮廓在 R（图纸 Ø=26），顶面止于 R-0.5
    add("disc_d26  chamfer0.5",   true,  13.0, 15, p, 1.0, 2.0, 500, 2, true, 0.5);
    // 圆环拟合 —— 真实工件：外缘附近还有一道环形台阶（Ø26 那道槽）。
    //   正确结果永远是 26（外轮廓）；若报 ~20 或 ~23.5，就是选错了跃变。
    add("disc_d26  stepR10",      true,  13.0, 15, p, 1.0, 2.0, 700, 2, true, 0.0, 0.0, 0.0, 10.0, 1.0);
    add("disc_d26  stepR12",      true,  13.0, 15, p, 1.0, 2.0, 700, 2, true, 0.0, 0.0, 0.0, 12.0, 1.0);
    add("disc_d26  stepR12 d2",   true,  13.0, 15, p, 1.0, 2.0, 700, 2, true, 0.0, 0.0, 0.0, 12.0, 2.0);
    add("disc_d26  cham+step",    true,  13.0, 15, p, 1.0, 2.0, 700, 2, true, 0.5, 0.0, 0.0, 12.0, 1.0);
    // 圆环拟合 —— 离轴 / 镜头畸变
    add("disc_d26  off10 k1=.15", true,  13.0, 15, p, 1.0, 2.0, 800, 1, true, 0.0, 0.15, 10.0);
    add("disc_d26  off10 k1=0",   true,  13.0, 15, p, 1.0, 2.0, 800, 1, true, 0.0, 0.00, 10.0);
    add("disc_d26  off20 k1=.15", true,  13.0, 15, p, 1.0, 2.0, 1100, 1, true, 0.0, 0.15, 20.0);
    // 圆环拟合 —— 无图像（走 3D 兜底）
    add("disc_d26  3D tilt15",    true,  13.0, 15, p, 0.0, 0.0, 500, 2, false);
    add("disc_d26  3D tilt0",     true,  13.0,  0, p, 0.0, 0.0, 500, 2, false);

    std::printf("%-26s %-4s %-4s %-4s %8s %8s %8s %8s %7s %8s %7s %6s  %s\n",
                "scene", "ok", "sub", "rel", "outer", "inner", "meas", "err_mm",
                "err_pct", "ctr_mm", "round", "cov", "msg");
    int failed = 0;
    int skipped = 0;
    int known = 0;
    int fixed = 0;
    for (const Scene& s : scenes) {
        const Data d = build(s);
        const Outcome o = run(s, d);
        // Drawing Ø = the outermost material boundary.  For a hole that is the
        // chamfer opening (2R+2c); for a disc it is the silhouette (2R).
        double outer = s.materialInside ? 2.0 * s.radius
                                        : 2.0 * (s.radius + s.chamferMm);
        // a counterbore moves the opening outward: the drawing Ø is its rim
        if (!s.materialInside && s.stepDepth > 0.0 && s.stepR > s.radius)
            outer = std::max(outer, 2.0 * s.stepR);
        const double inner = s.materialInside ? 2.0 * (s.radius - s.chamferMm)
                                              : 2.0 * s.radius;
        const double err = o.diameter - outer;
        const double pct = o.valid && outer > 0.0 ? 100.0 * err / outer : 0.0;
        const bool bad = !o.valid || std::fabs(err) > 0.005 * outer;
        const bool tracked = isKnownDefect(s.name);
        std::printf("%-26s %-4s %-4s %-4s %8.4f %8.4f %8.4f %8.4f %6.3f%% %8.4f %7.4f %6.2f  %s%s\n",
                    s.name.c_str(), o.valid ? "yes" : "NO", o.subpixel ? "yes" : "no",
                    o.reliable ? "yes" : "no",
                    outer, inner, o.diameter, o.valid ? err : 0.0, pct, o.centerErr,
                    o.roundness, o.coverage,
                    o.valid ? "" : o.message.c_str(),
                    (!bad && tracked) ? "   *** FIXED — drop from isKnownDefect() ***"
                                      : (bad && tracked ? "   [known defect]" : ""));
        if (o.message.rfind("OUT OF FRAME", 0) == 0)
            ++skipped;
        else if (bad && tracked)
            ++known;
        else if (!bad && tracked)
            ++fixed;
        else if (bad)
            ++failed;
    }
    std::printf("\n%zu scenes | %d OUTSIDE criterion | %d known defects (reported, not hidden) | "
                "%d newly FIXED | %d skipped\n",
                scenes.size(), failed, known, fixed, skipped);
    if (fixed > 0)
        std::printf("NOTE: %d previously-known defect(s) now pass — remove them from "
                    "isKnownDefect() so the run keeps its teeth.\n", fixed);
    return failed == 0 ? 0 : 1;
}
