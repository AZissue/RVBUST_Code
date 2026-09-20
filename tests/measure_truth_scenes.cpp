// Known-truth scene generator (round 7, P1).  See measure_truth.h for the data
// contract.  Everything here is deterministic — no clock, no platform RNG.
#include "measure_truth.h"

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <random>

namespace MeasureTruth {
namespace {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();
constexpr double kPi = 3.14159265358979323846;
constexpr double kDegPerRad = 180.0 / kPi;
constexpr std::uint64_t kSeed = 20260920ULL;

// Deterministic Gaussian noise: raw std::mt19937_64 output (the engine's own
// sequence is standardized) through explicit Box-Muller math.  The distribution
// adaptors in <random> are NOT portable, so the same seed would otherwise give
// different bytes with a different standard library.
struct Rng {
    explicit Rng(std::uint64_t seed) : engine(seed) {}
    std::mt19937_64 engine;

    double uniform()
    {
        return static_cast<double>(engine() >> 11) * (1.0 / 9007199254740992.0);
    }
    double gauss()
    {
        double u1 = uniform();
        if (u1 < 1e-300)
            u1 = 1e-300;
        const double u2 = uniform();
        return std::sqrt(-2.0 * std::log(u1)) * std::cos(2.0 * kPi * u2);
    }
};

double pvOf(const std::vector<double>& v)
{
    if (v.empty())
        return 0.0;
    double lo = v[0], hi = v[0];
    for (double x : v) {
        lo = std::min(lo, x);
        hi = std::max(hi, x);
    }
    return hi - lo;
}

double meanOf(const std::vector<double>& v)
{
    if (v.empty())
        return 0.0;
    double s = 0.0;
    for (double x : v)
        s += x;
    return s / static_cast<double>(v.size());
}

// Reported flatness PV of a noisy ROI.
//
// flatness() drops outliers with |v - median| <= 3 * 1.4826 * MAD before
// reporting, and for Gaussian noise MAD ~ 0.6745σ, so the kept band is ~±3σ and
// the reported PV saturates at ~6σ no matter how many samples are fitted — the
// raw PV of the sample (which grows with n) is *not* what the panel prints.
// Asserting against 6σ is what makes the check independent of the sample count;
// the raw PV is only recorded for the human reader.
double madClippedPv(double sigma)
{
    return 6.0 * sigma;
}

// Sample standard deviation (n-1), the same convention as MeasureTools::repeatability.
double sigmaOf(const std::vector<double>& v)
{
    if (v.size() < 2)
        return 0.0;
    const double m = meanOf(v);
    double s = 0.0;
    for (double x : v)
        s += (x - m) * (x - m);
    return std::sqrt(s / static_cast<double>(v.size() - 1));
}

// Grid under construction: NaN until set (NaN is the "no measurement" cell).
struct GridBuilder {
    int w = 0;
    int h = 0;
    std::vector<double> data;

    GridBuilder(int w_, int h_) : w(w_), h(h_), data(static_cast<std::size_t>(w_) * h_ * 3, kNaN) {}

    void set(int x, int y, double px, double py, double pz)
    {
        if (x < 0 || y < 0 || x >= w || y >= h)
            return;
        const std::size_t i = (static_cast<std::size_t>(y) * w + x) * 3;
        data[i] = px;
        data[i + 1] = py;
        data[i + 2] = pz;
    }
};

Check mkCheck(const std::string& id, const std::string& title, const std::string& unit,
              double truth, double tol, const std::vector<int>& roi,
              const std::string& criterion)
{
    Check c;
    c.id = id;
    c.title = title;
    c.unit = unit;
    c.truth = truth;
    c.tol = tol;
    c.roi = roi;
    c.criterion = criterion;
    return c;
}

std::vector<int> rect(int x0, int y0, int x1, int y1)
{
    return { x0, y0, x1, y1 };
}

// ── plane_flat ─────────────────────────────────────────────────────────
Scene scenePlaneFlat()
{
    Scene s;
    s.name = "plane_flat";
    s.method = "flatness";
    s.roiHint = "选「平面度」，在 2D 视图上拖一个框盖住整块平面（ROI A = 被测面）";
    const int n = 200;          // 200 x 200 cells
    const double pitch = 0.5;   // 100 x 100 mm
    const double sigma = 0.005;
    s.gridW = s.gridH = n;
    s.imageW = s.imageH = n;
    s.files = { "plane_flat.grid" };

    Rng rng(kSeed + 1);
    GridBuilder g(n, n);
    std::vector<double> noise;
    noise.reserve(static_cast<std::size_t>(n) * n);
    for (int y = 0; y < n; ++y) {
        for (int x = 0; x < n; ++x) {
            const double e = rng.gauss() * sigma;
            noise.push_back(e);
            g.set(x, y, x * pitch, y * pitch, e);
        }
    }
    const double pv = pvOf(noise);
    s.frames.push_back(std::move(g.data));
    char note[256];
    std::snprintf(note, sizeof(note),
                  "100 x 100 mm 平面，σ = 0.005 mm 高斯噪声。PV 真值取 MAD 剔除后的"
                  "饱和值 6σ（本次原始噪声 PV 为 %.4f mm，仅供参考），RMS 真值取 σ。",
                  pv);
    s.notes = note;

    s.checks.push_back(mkCheck("roi_point_count", "ROI 取点数", "点",
                               static_cast<double>(n) * n, 0.0, rect(0, 0, n - 1, n - 1),
                               "全网格取点，数目必须精确相等（映射的覆盖性）"));
    s.checks.push_back(mkCheck("flatness_pv", "平面度 LSQ PV", "mm", madClippedPv(sigma),
                               0.35 * sigma, rect(0, 0, n - 1, n - 1),
                               "MAD 剔除把报告 PV 限制在 ±3σ 内，故 |实测-6σ| <= 0.35σ"));
    s.checks.push_back(mkCheck("flatness_rms", "平面度 LSQ RMS", "mm", sigma, 0.0008,
                               rect(0, 0, n - 1, n - 1),
                               "|实测-噪声σ| <= 0.0008 mm"));
    s.checks.push_back(mkCheck("mz_le_pv", "最小区域 PV <= LSQ PV", "mm", 0.0, 1e-4,
                               rect(0, 0, n - 1, n - 1),
                               "断言 LSQ PV - MZ PV >= -0.0001 mm（收敛失败时 MZ 保留 LSQ 值）"));
    s.checks.push_back(mkCheck("plane_tilt_x", "平面法向倾角 X", "°", 0.0, 0.02,
                               rect(0, 0, n - 1, n - 1), "|实测-真值| <= 0.02°"));
    s.checks.push_back(mkCheck("plane_tilt_y", "平面法向倾角 Y", "°", 0.0, 0.02,
                               rect(0, 0, n - 1, n - 1), "|实测-真值| <= 0.02°"));
    return s;
}

// ── plane_tilt ─────────────────────────────────────────────────────────
Scene scenePlaneTilt()
{
    Scene s;
    s.name = "plane_tilt";
    s.method = "flatness";
    s.roiHint = "选「平面度」，框住整块倾斜平面（ROI A = 被测面）；倾角看「倾斜角」那一行";
    const int n = 200;
    const double pitch = 0.5;
    const double sigma = 0.02;
    const double tiltDeg = 8.0;
    s.gridW = s.gridH = n;
    s.imageW = s.imageH = n;
    s.files = { "plane_tilt.grid" };

    Rng rng(kSeed + 2);
    GridBuilder g(n, n);
    std::vector<double> noise;
    const double slope = std::tan(tiltDeg / kDegPerRad);
    for (int y = 0; y < n; ++y) {
        for (int x = 0; x < n; ++x) {
            const double e = rng.gauss() * sigma;
            noise.push_back(e);
            // z = y * tan(8°) -> the true normal is (0, sin 8°, -cos 8°).
            g.set(x, y, x * pitch, y * pitch, y * pitch * slope + e);
        }
    }
    const double pv = pvOf(noise);
    s.frames.push_back(std::move(g.data));
    char note[256];
    std::snprintf(note, sizeof(note),
                  "100 x 100 mm 平面绕 X 轴倾斜 8.000°，σ = 0.02 mm（本次原始 PV %.4f mm）。"
                  "倾角定义：tilt_x = atan2(nx, -nz)，tilt_y = atan2(ny, -nz)。",
                  pv);
    s.notes = note;

    s.checks.push_back(mkCheck("plane_tilt_y", "平面法向倾角 Y", "°", tiltDeg, 0.05,
                               rect(0, 0, n - 1, n - 1), "|实测-真值| <= 0.05°"));
    s.checks.push_back(mkCheck("plane_tilt_x", "平面法向倾角 X", "°", 0.0, 0.05,
                               rect(0, 0, n - 1, n - 1), "|实测-真值| <= 0.05°"));
    s.checks.push_back(mkCheck("flatness_pv", "平面度 LSQ PV", "mm", madClippedPv(sigma),
                               0.35 * sigma, rect(0, 0, n - 1, n - 1),
                               "倾斜被拟合掉，只剩噪声，PV 取 MAD 剔除后的 6σ"));
    s.checks.push_back(mkCheck("flatness_rms", "平面度 LSQ RMS", "mm", sigma, 0.002,
                               rect(0, 0, n - 1, n - 1), "|实测-噪声σ| <= 0.002 mm"));
    return s;
}

// ── step_3mm ───────────────────────────────────────────────────────────
Scene sceneStep()
{
    Scene s;
    s.name = "step_3mm";
    s.method = "step_height";
    s.roiHint = "选「高度段差」：第一次拖框 = ROI A（基准面，x <= 60 mm），"
                "第二次拖框 = ROI B（被测面，x > 60 mm）";
    const double pitch = 0.5;
    const int w = 241;    // 120 mm
    const int h = 161;    // 80 mm
    const double stepMm = 3.0;
    const double stepAt = 60.0;   // mm
    const double sigma = 0.004;
    s.gridW = w;
    s.gridH = h;
    s.imageW = w;
    s.imageH = h;
    s.files = { "step_3mm.grid" };

    // The camera looks along +z, so "towards the camera" is *smaller* z: the
    // measured face stands 3 mm proud of the datum at z = -3.000 — the sign
    // convention the panel's "凸起为正" and test_measure_tools.cpp both use.
    Rng rng(kSeed + 3);
    GridBuilder g(w, h);
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            const double xm = x * pitch;
            const double z = (xm > stepAt ? -stepMm : 0.0) + rng.gauss() * sigma;
            g.set(x, y, xm, y * pitch, z);
        }
    }
    s.frames.push_back(std::move(g.data));
    s.notes = "120 x 80 mm 台阶：x <= 60 mm 为基准面 z = 0，x > 60 mm 为被测面 "
              "z = -3.000 mm（朝向相机 3 mm，凸起为正），σ = 0.004 mm。";

    // The datum ROI must not touch the step edge (cell 120 = 60 mm): a datum ROI
    // straddling the edge fits a plane through both levels and the height comes
    // out meaningless — which is what an earlier revision of this scene did.
    const std::vector<int> roiA = rect(10, 20, 100, 140);   // 基准面，全部 x <= 50 mm
    const std::vector<int> roiB = rect(140, 20, 220, 140);  // 被测面，全部 x >= 70 mm
    Check up = mkCheck("height_signed", "面到面高度 B-A", "mm", stepMm, 0.01, roiA,
                       "|实测-真值| <= 0.01 mm");
    up.roi2 = roiB;
    s.checks.push_back(up);
    Check down = mkCheck("height_signed", "面到面高度 A-B（对调，符号反）", "mm", -stepMm, 0.01,
                         roiB, "|实测-(-真值)| <= 0.01 mm");
    down.roi2 = roiA;
    s.checks.push_back(down);
    s.checks.push_back(mkCheck("roi_point_count", "基准 ROI 取点数", "点",
                               static_cast<double>((100 - 10 + 1) * (140 - 20 + 1)), 0.0,
                               roiA, "取点数必须精确相等"));
    return s;
}

// ── angle_89_613 ───────────────────────────────────────────────────────
Scene sceneAngle()
{
    Scene s;
    s.name = "angle_89_613";
    s.method = "plane_pair";
    s.roiHint = "选「面面距离夹角」：ROI A 框水平面，ROI B 框近竖直墙；"
                "两面夹角 89.613° > 3°，所以不报「平行面间距」是正常的";
    const double pitch = 0.5;
    const int w = 181;
    const int h = 81;
    const double alphaDeg = 89.613;
    const double alpha = alphaDeg / kDegPerRad;
    const double cot = std::cos(alpha) / std::sin(alpha);   // 0.006756
    const double sigma = 0.003;
    s.gridW = w;
    s.gridH = h;
    s.imageW = w;
    s.imageH = h;
    s.files = { "angle_89_613.grid" };

    Rng rng(kSeed + 4);
    GridBuilder g(w, h);
    // A: plane z = 0 (normal (0,0,-1)).
    for (int y = 0; y <= 80; ++y) {
        for (int x = 0; x <= 80; ++x) {
            g.set(x, y, x * pitch, y * pitch, rng.gauss() * sigma);
        }
    }
    // B: near-vertical wall.  True normal (sin α, 0, -cos α) => angle to A = α.
    // Surface: x = x0 + z * cot(α), so the wall leans almost exactly upright.
    for (int j = 0; j <= 80; ++j) {
        const double z = j * pitch;
        for (int i = 0; i <= 80; ++i) {
            const double x = 60.0 + (z - 0.0) * cot;
            const double y = i * pitch;
            g.set(100 + i, j,
                  x + rng.gauss() * sigma, y + rng.gauss() * sigma, z + rng.gauss() * sigma);
        }
    }
    s.frames.push_back(std::move(g.data));
    s.notes = "两块面：A 为 z = 0 水平面（40 x 40 mm），B 为近竖直墙（40 x 40 mm），"
              "两面夹角 89.613°。法向按 n[2] <= 0 定向。";

    Check ang = mkCheck("angle_deg", "面面夹角 A-B", "°", alphaDeg, 0.05, rect(0, 0, 80, 80),
                        "|实测-真值| <= 0.05°");
    ang.roi2 = rect(100, 0, 180, 80);
    s.checks.push_back(ang);
    s.checks.push_back(mkCheck("roi_point_count", "A 面 ROI 取点数", "点", 81.0 * 81.0, 0.0,
                               rect(0, 0, 80, 80), "取点数必须精确相等"));
    return s;
}

// ── holes ──────────────────────────────────────────────────────────────
struct HoleSpec {
    double diameter;
    double cx, cy;
};

Scene sceneHoles(double pitch)
{
    Scene s;
    const double plateW = 120.0, plateH = 80.0;
    const int w = static_cast<int>(plateW / pitch) + 1;
    const int h = static_cast<int>(plateH / pitch) + 1;
    const double sigma = 0.003;
    const HoleSpec holes[3] = { { 5.0, 30.0, 40.0 }, { 10.0, 60.0, 40.0 }, { 20.0, 95.0, 40.0 } };
    // Diameter tolerance = the resolution the *data* allows, not just the
    // estimator's: the hole wall is only sampled once per pitch, so the
    // innermost material cell of a direction sits between 0 and one pitch
    // outside the true edge.  0.25 mm is a camera-realistic pitch and there the
    // tolerance is the Python-parity target ±0.05 mm; coarser pitches hold fewer
    // rim samples per hole (a ⌀5 hole at a 1 mm pitch is five samples across)
    // and the floor grows with the pitch — measured, not assumed:
    //   0.25 mm -> 0.035 / 0.024 / 0.014   (within 0.05 ✓)
    //   0.50 mm -> 0.165 / 0.089 / 0.029   (within 0.20)
    //   1.00 mm -> 0.541 / 0.242 / 0.198   (within 0.60)
    const double tolMm = pitch <= 0.25 ? 0.05 : (pitch <= 0.5 ? 0.2 : 0.6);
    const double tolCentre = std::max(0.2, pitch);

    s.name = pitch <= 0.25 ? "holes_p025" : (pitch <= 0.5 ? "holes_p050" : "holes_p100");
    s.method = "hole_diameter";
    s.roiHint = "选「孔径(孔洞边界法)」，紧贴每个孔各拖一个近正方形 ROI"
                "（ROI A = 孔 + 孔外约 2 个点距的材料，别框进别的孔）；"
                "不要用「圆环拟合」测孔——它是给环形材料用的";
    s.gridW = w;
    s.gridH = h;
    s.imageW = w;
    s.imageH = h;
    s.files = { s.name + ".grid" };

    Rng rng(kSeed + 5 + static_cast<std::uint64_t>(pitch * 1000.0));
    GridBuilder g(w, h);
    std::vector<std::size_t> holeCells[3];
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            const double xm = x * pitch;
            const double ym = y * pitch;
            bool inside = false;
            for (int k = 0; k < 3; ++k) {
                const double dx = xm - holes[k].cx;
                const double dy = ym - holes[k].cy;
                if (dx * dx + dy * dy < (holes[k].diameter / 2.0) * (holes[k].diameter / 2.0)) {
                    inside = true;
                    holeCells[k].push_back(static_cast<std::size_t>(y) * w + x);
                }
            }
            if (inside)
                continue;               // through hole -> no return -> NaN
            g.set(x, y, xm, ym, rng.gauss() * sigma);
        }
    }
    s.frames.push_back(std::move(g.data));

    char notes[512];
    std::snprintf(notes, sizeof(notes),
                  "120 x 80 mm 板，通孔 ⌀5 / ⌀10 / ⌀20 位于 (30,40) / (60,40) / (95,40) mm；"
                  "材料点距 %.3f mm，σ = %.3f mm。孔径公差 ±%.3f mm（该点距下 %s），"
                  "孔心公差 ±%.2f mm。",
                  pitch, sigma, tolMm,
                  pitch <= 0.25 ? "达到 Python 一致性目标" : "公差按点距量化极限放宽",
                  tolCentre);
    s.notes = notes;

    for (int k = 0; k < 3; ++k) {
        const HoleSpec& hs = holes[k];
        const int cx = static_cast<int>(std::lround(hs.cx / pitch));
        const int cy = static_cast<int>(std::lround(hs.cy / pitch));
        // ROI = hole + exactly 2 cells of material.  A tight ROI is the method's
        // documented operating condition: the innermost material point of each
        // sector is then a rim point, which is what the half-pitch correction
        // assumes.  A wide ROI whose annulus is many cells thick would instead
        // measure an order statistic of the 2-D fill (see README).
        const int half = static_cast<int>(std::lround(hs.diameter / 2.0 / pitch)) + 2;
        const int x0 = std::max(0, cx - half);
        const int x1 = std::min(w - 1, cx + half);
        const int y0 = std::max(0, cy - half);
        const int y1 = std::min(h - 1, cy + half);
        char title[64];
        std::snprintf(title, sizeof(title), "孔径 ⌀%g（孔洞边界法）", hs.diameter);
        s.checks.push_back(mkCheck("hole_diameter", title, "mm", hs.diameter, tolMm,
                                   rect(x0, y0, x1, y1),
                                   "|实测-真值| <= 公差，且新法偏差 <= 旧法偏差的一半"));
        std::snprintf(title, sizeof(title), "孔心 ⌀%g", hs.diameter);
        Check cc = mkCheck("hole_center", title, "mm", hs.cx, tolCentre,
                           rect(x0, y0, x1, y1), "|实测-真值| <= 孔心公差（x / y 各一行）");
        cc.truth2 = hs.cy;
        cc.tol2 = tolCentre;
        s.checks.push_back(cc);
        // How many cells of this ROI are material: the ROI crosses the hole, so
        // this doubles as a mapping check that survives a NaN region.
        const std::size_t cells = static_cast<std::size_t>(x1 - x0 + 1) * (y1 - y0 + 1);
        std::size_t inside = 0;
        for (std::size_t c : holeCells[k]) {
            const int hx = static_cast<int>(c % w);
            const int hy = static_cast<int>(c / w);
            if (hx >= x0 && hx <= x1 && hy >= y0 && hy <= y1)
                ++inside;
        }
        if (k == 0) {
            std::snprintf(title, sizeof(title), "⌀5 ROI 材料点数");
            s.checks.push_back(mkCheck("roi_point_count", title, "点",
                                       static_cast<double>(cells - inside), 0.0,
                                       rect(x0, y0, x1, y1),
                                       "ROI 内有效点（材料）数必须精确相等"));
        }
    }
    return s;
}

// ── box ────────────────────────────────────────────────────────────────
Scene sceneBox(bool rotated)
{
    Scene s;
    s.name = rotated ? "box_rot_30_20" : "box_100_60_20";
    s.method = "bounding_box";
    s.roiHint = "选「包围盒」，一个框盖住整个物体（ROI A = 整个物体，六个面尽量都在里面）";
    const double pitch = 0.5;
    const double sigma = 0.002;
    // Face sample counts (both edges included, so the extents are exact).
    const int n100 = 201, n60 = 121, n20 = 41;
    // Unrolled layout: two 100x60 faces, two 100x20, two 60x20.
    const int blkW = 210;
    s.gridW = blkW + n100;
    s.gridH = 130 + 50 + n20;
    s.imageW = s.gridW;
    s.imageH = s.gridH;
    s.files = { s.name + ".grid" };

    Rng rng(kSeed + (rotated ? 7 : 6));
    GridBuilder g(s.gridW, s.gridH);
    // Rotation for the second variant: Rz(30°) then Rx(20°).
    const double a = 30.0 / kDegPerRad, b = 20.0 / kDegPerRad;
    auto place = [&](int x, int y, double px, double py, double pz) {
        double X = px, Y = py, Z = pz;
        if (rotated) {
            // Rx(20°) about X, then Rz(30°) about Z.
            const double y1 = py * std::cos(b) - pz * std::sin(b);
            const double z1 = py * std::sin(b) + pz * std::cos(b);
            X = px * std::cos(a) - y1 * std::sin(a);
            Y = px * std::sin(a) + y1 * std::cos(a);
            Z = z1;
        }
        g.set(x, y, X + rng.gauss() * sigma, Y + rng.gauss() * sigma, Z + rng.gauss() * sigma);
    };
    // z = +-10 faces (100 x 60).
    for (int j = 0; j < n60; ++j)
        for (int i = 0; i < n100; ++i) {
            const double px = -50.0 + i * pitch;
            const double py = -30.0 + j * pitch;
            place(i, j, px, py, +10.0);
            place(blkW + i, j, px, py, -10.0);
        }
    // y = +-30 faces (100 x 20).
    for (int j = 0; j < n20; ++j)
        for (int i = 0; i < n100; ++i) {
            const double px = -50.0 + i * pitch;
            const double pz = -10.0 + j * pitch;
            place(i, 130 + j, px, +30.0, pz);
            place(blkW + i, 130 + j, px, -30.0, pz);
        }
    // x = +-50 faces (60 x 20).
    for (int j = 0; j < n20; ++j)
        for (int i = 0; i < n60; ++i) {
            const double py = -30.0 + i * pitch;
            const double pz = -10.0 + j * pitch;
            place(i, 180 + j, +50.0, py, pz);
            place(140 + i, 180 + j, -50.0, py, pz);
        }
    const std::size_t points = 2u * n100 * n60 + 2u * n100 * n20 + 2u * n60 * n20;
    s.frames.push_back(std::move(g.data));
    char notes[512];
    std::snprintf(notes, sizeof(notes),
                  "100 x 60 x 20 mm 盒子的六个面全部采样（点距 %.1f mm，表面展开成网格），"
                  "%s。σ = %.3f mm。真值 = 三个主方向的真实长度，取向盒的长/宽/高。",
                  pitch,
                  rotated ? "整体先绕 X 轴转 20°、再绕 Z 轴转 30°" : "轴对齐",
                  sigma);
    s.notes = notes;

    const std::vector<int> all = rect(0, 0, s.gridW - 1, s.gridH - 1);
    s.checks.push_back(mkCheck("roi_point_count", "表面总点数", "点",
                               static_cast<double>(points), 0.0, all,
                               "六个面点数和，NaN 缝不计"));
    s.checks.push_back(mkCheck("box_length", "取向盒 长", "mm", 100.0, 0.5, all,
                               "|实测-真值| <= 0.5 mm"));
    s.checks.push_back(mkCheck("box_width", "取向盒 宽", "mm", 60.0, 0.5, all,
                               "|实测-真值| <= 0.5 mm"));
    s.checks.push_back(mkCheck("box_height", "取向盒 高", "mm", 20.0, 0.5, all,
                               "|实测-真值| <= 0.5 mm"));
    return s;
}

// ── repeat_series ──────────────────────────────────────────────────────
Scene sceneRepeat()
{
    Scene s;
    s.name = "repeat_series";
    s.method = "repeatability";
    s.roiHint = "先选「平面度」或「高度段差」逐帧测量并点「加入重复性」，"
                "再选「重复性」看 n / 均值 / σ / 极差（本方法自己不需要 ROI）";
    const int n = 100;          // 50 x 50 mm at 0.5 mm pitch
    const double pitch = 0.5;
    const double sigma = 0.002;
    const double offsets[10] = { 0.0, 0.020, 0.050, 0.030, -0.010,
                                 0.040, 0.010, -0.020, 0.020, 0.030 };
    s.gridW = s.gridH = n;
    s.imageW = s.imageH = n;

    Rng rng(kSeed + 8);
    std::vector<double> realized;
    for (int f = 0; f < 10; ++f) {
        GridBuilder g(n, n);
        double sum = 0.0;
        for (int y = 0; y < n; ++y) {
            for (int x = 0; x < n; ++x) {
                const double e = offsets[f] + rng.gauss() * sigma;
                sum += e;
                g.set(x, y, x * pitch, y * pitch, e);
            }
        }
        // The harness measures the mean height of the ROI per frame, so the
        // truth is the *realized* mean of this frame's noise, not the offset.
        realized.push_back(sum / (static_cast<double>(n) * n));
        char fn[48];
        std::snprintf(fn, sizeof(fn), "repeat_series_%02d.grid", f);
        s.files.push_back(fn);
        s.frames.push_back(std::move(g.data));
    }
    s.notes = "10 帧同一平面的小视场（50 x 50 mm，σ = 0.002 mm），高度偏移已知："
              "0/20/50/30/-10/40/10/-20/20/30 μm。真值取各帧实际生成的均值高度，"
              "统计量按 n-1 标准差计算。";

    const double mean = meanOf(realized);
    const double sigmaStat = sigmaOf(realized);
    const double range = pvOf(realized);
    const std::vector<int> all = rect(0, 0, n - 1, n - 1);
    char crit[256];
    std::snprintf(crit, sizeof(crit),
                  "对 10 帧 ROI 分别取平均高度，再做重复性统计：|实测-真值| <= 0.002 mm");
    Check c1 = mkCheck("repeat_mean", "重复性 均值", "mm", mean, 0.002, all, crit);
    c1.perFrame = true;
    s.checks.push_back(c1);
    Check c2 = mkCheck("repeat_sigma", "重复性 标准差 σ", "mm", sigmaStat, 0.002, all, crit);
    c2.perFrame = true;
    s.checks.push_back(c2);
    Check c3 = mkCheck("repeat_range", "重复性 极差", "mm", range, 0.002, all, crit);
    c3.perFrame = true;
    s.checks.push_back(c3);
    return s;
}

// ── roi_map_boss ───────────────────────────────────────────────────────
Scene sceneRoiMap()
{
    Scene s;
    s.name = "roi_map_boss";
    // 本场景不测某个具体量：它校验的是 ROI 像素矩形 → 网格取点这条映射本身，
    // 所以"该用哪个方法"只是"用哪个页都能看见取点结果"的意思。
    s.method = "section";
    s.roiHint = "本场景校验的是框选本身（图像 400x300 是点图 200x150 的两倍）："
                "选「截面轮廓」（或任一方法页），把框拖在方台上/旁边，"
                "看「取点数」与偏差图是否落在正确位置";
    const double pitch = 0.5;
    const int w = 200, h = 150;          // 100 x 75 mm
    const int bx0 = 120, bx1 = 139;      // boss cells: 10 x 10 mm at (60..69.5, 40..49.5)
    const int by0 = 80, by1 = 99;
    // Proud of the base means *towards the camera*, and the camera looks along
    // +z in this module's convention, so a raised boss sits at negative z.
    const double bossZ = -2.0;
    const double sigma = 0.002;
    const double scale = 2.0;            // image is 2x the point map
    s.gridW = w;
    s.gridH = h;
    s.imageW = static_cast<int>(w * scale);
    s.imageH = static_cast<int>(h * scale);
    s.files = { "roi_map_boss.grid" };

    Rng rng(kSeed + 9);
    GridBuilder g(w, h);
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            const bool boss = (x >= bx0 && x <= bx1 && y >= by0 && y <= by1);
            g.set(x, y, x * pitch, y * pitch, (boss ? bossZ : 0.0) + rng.gauss() * sigma);
        }
    }
    s.frames.push_back(std::move(g.data));
    s.notes = "100 x 75 mm 底板（z = 0）上有一个 10 x 10 mm、高 2 mm 的方台（z = -2，"
              "朝向相机为凸起），"
              "占网格 x[120,139] y[80,99]。图像故意做成点图的 2 倍（400 x 300），"
              "这样「像素矩形 -> 网格格子」的缩放/偏移一错就会取错点。";

    // Cell rect -> image px for the ROI fields of the checks.
    auto toImage = [&](int x0, int y0, int x1, int y1) {
        return rect(static_cast<int>(x0 * scale), static_cast<int>(y0 * scale),
                    static_cast<int>(x1 * scale), static_cast<int>(y1 * scale));
    };
    // 1. four cells inside the boss must all be boss cells (z = -2 exactly).
    s.checks.push_back(mkCheck("roi_point_count", "方台 2x2 格取点数", "点", 4.0, 0.0,
                               toImage(120, 80, 121, 81), "取点数精确相等"));
    s.checks.push_back(mkCheck("roi_min_z", "方台 2x2 格最小 z", "mm", bossZ, 0.01,
                               toImage(120, 80, 121, 81), "|实测-真值| <= 0.01 mm"));
    // 2. the whole boss block: no base point may leak in.
    s.checks.push_back(mkCheck("roi_point_count", "方台整块取点数", "点", 400.0, 0.0,
                               toImage(bx0, by0, bx1, by1), "取点数精确相等"));
    s.checks.push_back(mkCheck("roi_min_z", "方台整块最小 z", "mm", bossZ, 0.01,
                               toImage(bx0, by0, bx1, by1), "混入底板点即为映射偏移"));
    s.checks.push_back(mkCheck("roi_span_x", "方台整块 x 跨度", "mm", 9.5, 0.05,
                               toImage(bx0, by0, bx1, by1), "|实测-真值| <= 0.05 mm"));
    // 3. one cell to the left / above the boss must be pure base.
    s.checks.push_back(mkCheck("roi_max_z", "方台左侧 2x2 格最大 z", "mm", 0.0, 0.01,
                               toImage(118, 80, 119, 81), "取到方台点即为映射偏移"));
    s.checks.push_back(mkCheck("roi_point_count", "方台左侧 2x2 格取点数", "点", 4.0, 0.0,
                               toImage(118, 80, 119, 81), "取点数精确相等"));
    s.checks.push_back(mkCheck("roi_max_z", "方台下方 2x2 格最大 z", "mm", 0.0, 0.01,
                               toImage(120, 100, 121, 101), "取到方台点即为映射偏移"));
    // 4. a wide ROI over boss + base: the z range must be the full step.
    s.checks.push_back(mkCheck("roi_z_range", "方台+底板整块 z 极差", "mm", 2.0, 0.02,
                               toImage(118, 78, 141, 101), "|实测-真值| <= 0.02 mm"));
    return s;
}

} // namespace

std::vector<std::string> sceneNames()
{
    std::vector<std::string> names = { "plane_flat", "plane_tilt", "step_3mm", "angle_89_613",
                                       "holes_p025", "holes_p050", "holes_p100",
                                       "box_100_60_20", "box_rot_30_20",
                                       "repeat_series", "roi_map_boss" };
    return names;
}

Scene buildScene(const std::string& name)
{
    if (name == "plane_flat")
        return scenePlaneFlat();
    if (name == "plane_tilt")
        return scenePlaneTilt();
    if (name == "step_3mm")
        return sceneStep();
    if (name == "angle_89_613")
        return sceneAngle();
    if (name == "holes_p025")
        return sceneHoles(0.25);
    if (name == "holes_p050")
        return sceneHoles(0.50);
    if (name == "holes_p100")
        return sceneHoles(1.00);
    if (name == "box_100_60_20")
        return sceneBox(false);
    if (name == "box_rot_30_20")
        return sceneBox(true);
    if (name == "repeat_series")
        return sceneRepeat();
    if (name == "roi_map_boss")
        return sceneRoiMap();
    Scene unknown;
    unknown.name = name;
    unknown.notes = "未知场景名（生成器没有这个场景）";
    return unknown;
}

bool writeGrid(const std::string& path, const std::vector<double>& grid, int w, int h)
{
    std::FILE* f = std::fopen(path.c_str(), "wb");
    if (!f)
        return false;
    const std::string header = std::to_string(w) + " " + std::to_string(h) + "\n";
    bool ok = std::fwrite(header.data(), 1, header.size(), f) == header.size();
    if (ok && !grid.empty()) {
        // float32 little-endian on every Windows/x86 target; the header and the
        // row-major order are what the reader relies on.
        std::vector<float> out(grid.size());
        for (std::size_t i = 0; i < grid.size(); ++i)
            out[i] = static_cast<float>(grid[i]);
        ok = std::fwrite(out.data(), sizeof(float), out.size(), f) == out.size();
    }
    std::fclose(f);
    return ok;
}

bool writePly(const std::string& path, const std::vector<double>& grid, int w, int h)
{
    std::vector<float> verts;
    if (!grid.empty()) {
        const std::size_t cells = static_cast<std::size_t>(w) * h;
        verts.reserve(cells / 3);
        for (std::size_t c = 0; c < cells && c * 3 + 2 < grid.size(); ++c) {
            const double x = grid[c * 3], y = grid[c * 3 + 1], z = grid[c * 3 + 2];
            if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z))
                continue;
            verts.push_back(static_cast<float>(x));
            verts.push_back(static_cast<float>(y));
            verts.push_back(static_cast<float>(z));
        }
    }
    const std::size_t n = verts.size() / 3;
    std::FILE* f = std::fopen(path.c_str(), "wb");
    if (!f)
        return false;
    std::string header = "ply\nformat binary_little_endian 1.0\n";
    header += "comment generated by tests/measure_truth (organized " + std::to_string(w) + "x"
              + std::to_string(h) + " grid, mm, NaN cells dropped)\n";
    header += "element vertex " + std::to_string(n) + "\n";
    header += "property float x\nproperty float y\nproperty float z\nend_header\n";
    bool ok = std::fwrite(header.data(), 1, header.size(), f) == header.size();
    if (ok && n > 0)
        ok = std::fwrite(verts.data(), sizeof(float), verts.size(), f) == verts.size();
    std::fclose(f);
    return ok;
}

} // namespace MeasureTruth
