// Known-truth verification harness for the measurement tools (round 7, P1+P2).
//
//   measure_truth --data-dir <dir> [--no-generate] [--verbose]
//
// 1. generates every scene of MeasureTruth::sceneNames() into <dir> (*.grid,
//    *.ply) plus manifest.json, unless --no-generate is given;
// 2. re-reads the data *from disk* and runs every check listed in the manifest
//    through the full application chain
//
//        ROI 像素矩形 -> MeasureTools::roiImageToGrid
//                     -> MeasureTools::pointsInRoiIndexed
//                     -> the measurement algorithm itself
//
//    so a mapping error (the ROI lands on the wrong cells) and an algorithm
//    error (the maths is wrong) can be told apart: the harness prints the ROI
//    mapping, the point counts and the measured/truth/deviation of every
//    assertion;
// 3. prints a before/after table for the holes (the old ring fit vs the new
//    material-boundary method on the same points) and a failure summary.
//
// Exit code 0 = every assertion held.  Nothing here touches Qt GUI, the SDK or
// the camera: it is pure computation on files, so ctest can run it headless.
#include "measure_truth.h"

#include "logic/MeasureMethods.h"   // 方法目录：manifest 的"该用哪个方法"
#include "logic/MeasureTools.h"

#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>

#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>
#include <map>
#include <string>
#include <vector>

#ifdef _WIN32
// windows.h would otherwise define min/max as macros and break std::min.
#define NOMINMAX
#include <windows.h>
#endif

using MeasureTruth::Check;
using MeasureTools::BoundingBox;
using MeasureTools::Circle;
using MeasureTools::Flatness;
using MeasureTools::GridRect;
using MeasureTools::Height;
using MeasureTools::HoleBoundary;
using MeasureTools::Plane;
using MeasureTools::PlanePair;
using MeasureTools::Vec3;

namespace {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

// ── console formatting ─────────────────────────────────────────────────
// Chinese glyphs occupy two terminal columns; counting them as one would make
// every table crooked.
int codepointWidth(const std::string& s, std::size_t i, std::size_t* bytes)
{
    const unsigned char c = static_cast<unsigned char>(s[i]);
    if (c < 0x80) {
        *bytes = 1;
        return 1;
    }
    if ((c & 0xE0) == 0xC0) {
        *bytes = 2;
        return 1;
    }
    if ((c & 0xF0) == 0xE0) {
        *bytes = 3;
        return 2;
    }
    *bytes = 4;
    return 2;
}

int displayWidth(const std::string& s)
{
    int w = 0;
    for (std::size_t i = 0; i < s.size();) {
        std::size_t n = 1;
        w += codepointWidth(s, i, &n);
        i += n;
    }
    return w;
}

std::string pad(const std::string& s, int width)
{
    std::string out = s;
    const int w = displayWidth(s);
    for (int i = w; i < width; ++i)
        out += ' ';
    return out;
}

std::string fmt(double v, int prec = 4)
{
    if (!std::isfinite(v))
        return "—";
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.*f", prec, v);
    return buf;
}

// Counts are exact integers; printing them with four decimals reads as noise.
std::string fmtValue(double v, const std::string& unit)
{
    return fmt(v, unit == "点" ? 0 : 4);
}

// ── data loading ───────────────────────────────────────────────────────
struct GridFile {
    int w = 0;
    int h = 0;
    std::vector<double> data;
    bool ok = false;
    std::string error;
};

GridFile readGrid(const std::string& path)
{
    GridFile g;
    std::FILE* f = std::fopen(path.c_str(), "rb");
    if (!f) {
        g.error = "打不开文件";
        return g;
    }
    // Header: "<w> <h>\n" (the same text form the generator writes).
    std::string header;
    int c = 0;
    while ((c = std::fgetc(f)) != EOF && c != '\n' && header.size() < 64)
        header.push_back(static_cast<char>(c));
    if (std::sscanf(header.c_str(), "%d %d", &g.w, &g.h) != 2 || g.w <= 0 || g.h <= 0) {
        g.error = "网格头非法: " + header;
        std::fclose(f);
        return g;
    }
    const std::size_t n = static_cast<std::size_t>(g.w) * g.h * 3;
    std::vector<float> raw(n);
    const std::size_t got = std::fread(raw.data(), sizeof(float), n, f);
    std::fclose(f);
    if (got != n) {
        g.error = "点数据长度不符";
        return g;
    }
    g.data.resize(n);
    for (std::size_t i = 0; i < n; ++i)
        g.data[i] = raw[i];
    g.ok = true;
    return g;
}

// ── the ROI extraction that both sides share ───────────────────────────
struct RoiPoints {
    bool ok = false;
    std::string error;
    GridRect rect;
    std::vector<Vec3> pts;
    std::vector<std::size_t> cells;
};

RoiPoints extractRoi(const GridFile& g, const std::vector<int>& roi, int imageW, int imageH)
{
    RoiPoints r;
    if (!g.ok) {
        r.error = g.error;
        return r;
    }
    if (roi.size() != 4) {
        r.error = "ROI 未定义";
        return r;
    }
    r.rect = MeasureTools::roiImageToGrid(roi[0], roi[1], roi[2], roi[3], imageW, imageH,
                                          g.w, g.h);
    if (!r.rect.valid) {
        r.error = "ROI 与网格没有交集";
        return r;
    }
    r.pts = MeasureTools::pointsInRoiIndexed(g.data, g.w, g.h, r.rect.x0, r.rect.y0,
                                             r.rect.x1, r.rect.y1, &r.cells);
    r.ok = true;
    return r;
}

// ── measurement dispatch (the full chain, algorithm included) ──────────
struct Measured {
    bool ok = false;
    std::string error;
    double v1 = 0.0;
    bool hasV2 = false;
    double v2 = 0.0;
    // Hole checks: the old ring fit on the very same points (the "before").
    bool hasRing = false;
    double ring = 0.0;
    bool ringValid = false;
    // Extra assertion: the new method must be at least twice as close as the old.
    bool hasExtra = false;
    bool extraOk = true;
    std::string extraLabel;
    std::string info;
};

// value of the primary number of every check kind
bool measure(const std::string& id, const std::vector<RoiPoints>& rois,
             const std::vector<GridFile>& frames, int imageW, int imageH, const Check& c,
             Measured& m)
{
    auto fail = [&](const std::string& why) {
        m.ok = false;
        m.error = why;
        return false;
    };

    if (id == "flatness_pv" || id == "flatness_rms" || id == "mz_le_pv"
        || id == "plane_tilt_x" || id == "plane_tilt_y") {
        if (rois.empty() || !rois[0].ok)
            return fail(rois.empty() ? "ROI 缺失" : rois[0].error);
        const Flatness f = MeasureTools::flatness(rois[0].pts, 3.0);
        if (!f.valid)
            return fail(f.message);
        if (id == "flatness_pv")
            m.v1 = f.lsqPv;
        else if (id == "flatness_rms")
            m.v1 = f.lsqRms;
        else if (id == "mz_le_pv")
            m.v1 = f.lsqPv - f.mzPv;     // must be >= 0
        else {
            const Vec3& n = f.plane.normal;
            const double tiltX = std::atan2(n[0], -n[2]) * 180.0 / 3.14159265358979323846;
            const double tiltY = std::atan2(n[1], -n[2]) * 180.0 / 3.14159265358979323846;
            m.v1 = (id == "plane_tilt_x") ? tiltX : tiltY;
        }
        char buf[256];
        std::snprintf(buf, sizeof(buf),
                      "点数 %zu（剔除后），LSQ PV %.4f，MZ PV %.4f，RMS %.4f，LSQ-MZ "
                      "%.9f",
                      f.used, f.lsqPv, f.mzPv, f.lsqRms, f.lsqPv - f.mzPv);
        m.info = buf;
        m.ok = true;
        return true;
    }

    if (id == "height_signed") {
        if (rois.size() < 2 || !rois[0].ok || !rois[1].ok)
            return fail("需要两个 ROI");
        const Height h = MeasureTools::heightBetween(rois[0].pts, rois[1].pts, 3.0);
        if (!h.valid)
            return fail(h.message);
        m.v1 = h.value;
        char buf[256];
        std::snprintf(buf, sizeof(buf), "基准 %zu 点 / 被测 %zu 点，被测面 RMS %.4f mm",
                      h.usedRef, h.usedTarget, h.rms);
        m.info = buf;
        m.ok = true;
        return true;
    }

    if (id == "angle_deg") {
        if (rois.size() < 2 || !rois[0].ok || !rois[1].ok)
            return fail("需要两个 ROI");
        const PlanePair pp = MeasureTools::planePair(rois[0].pts, rois[1].pts, 3.0, 3.0);
        if (!pp.valid)
            return fail(pp.message);
        m.v1 = pp.angleDeg;
        char buf[256];
        std::snprintf(buf, sizeof(buf), "A %zu 点 / B %zu 点，平行=%s，A 面 RMS %.4f",
                      pp.usedA, pp.usedB, pp.parallel ? "是" : "否", pp.planeA.rms);
        m.info = buf;
        m.ok = true;
        return true;
    }

    if (id == "hole_diameter" || id == "hole_center") {
        if (rois.empty() || !rois[0].ok)
            return fail(rois.empty() ? "ROI 缺失" : rois[0].error);
        const HoleBoundary hb = MeasureTools::holeBoundary(rois[0].pts);
        if (!hb.valid)
            return fail(hb.message);
        char buf[512];
        std::snprintf(buf, sizeof(buf),
                      "扇区 %d/%d（覆盖 %.0f%%）%s，点距 %.3f mm，半径修正 %.3f mm，"
                      "圆度 %.4f，材料点 %zu，边界点 %zu，扇心 (%.3f, %.3f)",
                      hb.sectorsUsed, hb.sectors, hb.coverage * 100.0,
                      hb.reliable ? "可信" : "参考", hb.pitch, hb.pitchCorrection,
                      hb.roundness, hb.materialPoints, hb.used,
                      hb.fanOrigin[0], hb.fanOrigin[1]);
        m.info = buf;
        if (id == "hole_diameter") {
            m.v1 = hb.diameter;
            m.hasRing = true;
            // The old method, on exactly the same points: one circle through
            // every ROI point (the 圆环拟合 / 孔径 path as it shipped before).
            const Circle circ = MeasureTools::fitCircle(rois[0].pts, 2, 2.5);
            m.ringValid = circ.valid;
            m.ring = circ.diameter;
            if (circ.valid) {
                const double devNew = std::fabs(hb.diameter - c.truth);
                const double devOld = std::fabs(circ.diameter - c.truth);
                m.hasExtra = true;
                m.extraOk = devNew <= 0.5 * devOld;
                char eb[192];
                std::snprintf(eb, sizeof(eb), "偏差比 新/旧 = %.4f / %.4f = %.3f（要求 <= 0.5）",
                              devNew, devOld, devOld > 0 ? devNew / devOld : 0.0);
                m.extraLabel = eb;
            }
        } else {
            m.v1 = hb.center[0];
            m.hasV2 = true;
            m.v2 = hb.center[1];
        }
        m.ok = true;
        return true;
    }

    if (id == "box_length" || id == "box_width" || id == "box_height") {
        if (rois.empty() || !rois[0].ok)
            return fail(rois.empty() ? "ROI 缺失" : rois[0].error);
        const BoundingBox b = MeasureTools::pcaBoundingBox(rois[0].pts);
        if (!b.valid)
            return fail(b.message);
        m.v1 = (id == "box_length") ? b.length : (id == "box_width" ? b.width : b.height);
        char buf[256];
        std::snprintf(buf, sizeof(buf), "长/宽/高 = %.4f / %.4f / %.4f，%zu 点",
                      b.length, b.width, b.height, b.used);
        m.info = buf;
        m.ok = true;
        return true;
    }

    if (id == "repeat_mean" || id == "repeat_sigma" || id == "repeat_range") {
        std::vector<double> perFrame;
        for (const GridFile& g : frames) {
            const RoiPoints r = extractRoi(g, c.roi, imageW, imageH);
            if (!r.ok)
                return fail("帧取点失败: " + r.error);
            if (r.pts.empty())
                return fail("帧内没有有效点");
            double sum = 0.0;
            for (const Vec3& p : r.pts)
                sum += p[2];
            perFrame.push_back(sum / static_cast<double>(r.pts.size()));
        }
        const MeasureTools::Repeatability rep = MeasureTools::repeatability(perFrame);
        if (!rep.valid)
            return fail("重复性统计无效");
        m.v1 = (id == "repeat_mean") ? rep.mean
                                     : (id == "repeat_sigma" ? rep.stdDev : rep.range);
        char buf[256];
        std::snprintf(buf, sizeof(buf),
                      "n=%zu，均值 %.4f，σ %.4f，极差 %.4f（每帧取 ROI 平均高度）",
                      rep.n, rep.mean, rep.stdDev, rep.range);
        m.info = buf;
        m.ok = true;
        return true;
    }

    if (id == "roi_point_count" || id == "roi_mean_z" || id == "roi_min_z" || id == "roi_max_z"
        || id == "roi_span_x" || id == "roi_z_range") {
        if (rois.empty() || !rois[0].ok)
            return fail(rois.empty() ? "ROI 缺失" : rois[0].error);
        const std::vector<Vec3>& p = rois[0].pts;
        if (p.empty())
            return fail("ROI 内没有有效点");
        if (id == "roi_point_count") {
            m.v1 = static_cast<double>(p.size());
        } else if (id == "roi_span_x") {
            double lo = p[0][0], hi = p[0][0];
            for (const Vec3& q : p) {
                lo = std::min(lo, q[0]);
                hi = std::max(hi, q[0]);
            }
            m.v1 = hi - lo;
        } else {
            double lo = p[0][2], hi = p[0][2], sum = 0.0;
            for (const Vec3& q : p) {
                lo = std::min(lo, q[2]);
                hi = std::max(hi, q[2]);
                sum += q[2];
            }
            if (id == "roi_mean_z")
                m.v1 = sum / static_cast<double>(p.size());
            else if (id == "roi_min_z")
                m.v1 = lo;
            else if (id == "roi_max_z")
                m.v1 = hi;
            else
                m.v1 = hi - lo;
        }
        m.ok = true;
        return true;
    }

    return fail("未知检查类型: " + id);
}

// ── manifest I/O ───────────────────────────────────────────────────────
QJsonObject checkToJson(const Check& c)
{
    QJsonObject o;
    o["id"] = QString::fromStdString(c.id);
    o["title"] = QString::fromStdString(c.title);
    o["unit"] = QString::fromStdString(c.unit);
    o["truth"] = c.truth;
    o["tol"] = c.tol;
    if (c.tol2 > 0.0) {
        o["truth2"] = c.truth2;
        o["tol2"] = c.tol2;
    }
    if (c.perFrame)
        o["perFrame"] = true;
    if (!c.roi.empty()) {
        QJsonArray a;
        for (int v : c.roi)
            a.append(v);
        o["roi"] = a;
    }
    if (!c.roi2.empty()) {
        QJsonArray a;
        for (int v : c.roi2)
            a.append(v);
        o["roi2"] = a;
    }
    o["criterion"] = QString::fromStdString(c.criterion);
    return o;
}

Check checkFromJson(const QJsonObject& o)
{
    Check c;
    c.id = o["id"].toString().toStdString();
    c.title = o["title"].toString().toStdString();
    c.unit = o["unit"].toString().toStdString();
    c.truth = o["truth"].toDouble();
    c.tol = o["tol"].toDouble();
    c.truth2 = o["truth2"].toDouble(0.0);
    c.tol2 = o["tol2"].toDouble(0.0);
    c.perFrame = o["perFrame"].toBool(false);
    for (const QJsonValue& v : o["roi"].toArray())
        c.roi.push_back(v.toInt());
    for (const QJsonValue& v : o["roi2"].toArray())
        c.roi2.push_back(v.toInt());
    c.criterion = o["criterion"].toString().toStdString();
    return c;
}

std::vector<int> intsFromJson(const QJsonObject& o, const char* key)
{
    std::vector<int> out;
    for (const QJsonValue& v : o[key].toArray())
        out.push_back(v.toInt());
    return out;
}

QJsonObject sceneToJson(const MeasureTruth::Scene& s)
{
    QJsonObject o;
    o["name"] = QString::fromStdString(s.name);
    o["gridWidth"] = s.gridW;
    o["gridHeight"] = s.gridH;
    o["imageWidth"] = s.imageW;
    o["imageHeight"] = s.imageH;
    QJsonArray files;
    for (const std::string& f : s.files)
        files.append(QString::fromStdString(f));
    o["files"] = files;
    o["notes"] = QString::fromStdString(s.notes);
    // 该用哪个方法（界面左列表里的条目 id）/ 该怎么画 ROI。
    o["method"] = QString::fromStdString(s.method);
    o["roiHint"] = QString::fromStdString(s.roiHint);
    QJsonArray checks;
    for (const Check& c : s.checks)
        checks.append(checkToJson(c));
    o["checks"] = checks;
    return o;
}

MeasureTruth::Scene sceneFromJson(const QJsonObject& o)
{
    MeasureTruth::Scene s;
    s.name = o["name"].toString().toStdString();
    s.gridW = o["gridWidth"].toInt();
    s.gridH = o["gridHeight"].toInt();
    s.imageW = o["imageWidth"].toInt();
    s.imageH = o["imageHeight"].toInt();
    for (const QJsonValue& v : o["files"].toArray())
        s.files.push_back(v.toString().toStdString());
    s.notes = o["notes"].toString().toStdString();
    s.method = o["method"].toString().toStdString();
    s.roiHint = o["roiHint"].toString().toStdString();
    for (const QJsonValue& v : o["checks"].toArray())
        s.checks.push_back(checkFromJson(v.toObject()));
    return s;
}

std::string manifestText(const std::vector<MeasureTruth::Scene>& scenes)
{
    QJsonObject root;
    root["format"] = QStringLiteral("measure_truth/1");
    root["generator"] = QStringLiteral(
        "tests/measure_truth.cpp (C++17, std::mt19937_64 seed 20260920, Box-Muller)");
    QJsonObject units;
    units["length"] = QStringLiteral("mm");
    units["angle"] = QStringLiteral("deg");
    root["units"] = units;
    QJsonObject grid;
    grid["layout"] = QStringLiteral(
        "ASCII 头 \"<w> <h>\\n\"，随后 w*h*3 个小端 float32 (x,y,z)，单位 mm，"
        "行主序 cell = y*w + x");
    grid["invalid"] = QStringLiteral("NaN（无效体积之外 / 通孔内）");
    grid["isomorphic"] = QStringLiteral(
        "与 CameraManager::lastGrid() 交给测量面板的内存布局一致");
    root["grid"] = grid;
    root["toleranceRule"] = QStringLiteral(
        "每条检查都按 |实测 - 真值| <= 公差 判定；真值由生成器在写入数据时一并算出");

    // 每个场景的 method 都必须是这张目录里的 id（工装会断言），所以 manifest 里
    // 的"该用哪个方法"不会跟界面上的工具条目脱节。
    QJsonObject methodUsage;
    methodUsage["field"] = QStringLiteral(
        "scenes[].method = 界面左侧工具列表里的条目 id（== MeasureTools::methodId()）；"
        "scenes[].roiHint = 这一框该框哪儿的操作说明");
    methodUsage["catalogue"] = QStringLiteral("src/logic/MeasureMethods.h (methodSpecs())");
    root["methodUsage"] = methodUsage;
    QJsonArray methods;
    {
        int n = 0;
        const MeasureTools::MethodSpec* specs = MeasureTools::methodSpecs(n);
        for (int i = 0; i < n; ++i) {
            QJsonObject m;
            m["id"] = QString::fromStdString(specs[i].id);
            m["name"] = QString::fromUtf8(specs[i].name);
            m["roiCount"] = specs[i].roiCount;
            m["roiRequirement"] = QString::fromStdString(
                MeasureTools::roiRequirementText(specs[i].method));
            methods.append(m);
        }
    }
    root["methods"] = methods;
    QJsonArray arr;
    for (const MeasureTruth::Scene& s : scenes)
        arr.append(sceneToJson(s));
    root["scenes"] = arr;
    const QJsonDocument doc(root);
    return std::string(doc.toJson(QJsonDocument::Indented).constData());
}

// ── check bookkeeping ──────────────────────────────────────────────────
struct Row {
    std::string scene;
    std::string title;
    std::string unit;
    double measured = 0.0;
    double truth = 0.0;
    double dev = 0.0;
    double tol = 0.0;
    bool pass = false;
    std::string note;
};

struct Summary {
    int checks = 0;
    int failed = 0;
    int scenes = 0;
    int files = 0;
    int ledger = 0;   // 「该用哪个方法 / 该画哪个 ROI」台账检查（不带数值）
    std::vector<std::string> failures;
};

} // namespace

int main(int argc, char** argv)
{
#ifdef _WIN32
    SetConsoleOutputCP(CP_UTF8);
#endif
    // The report is long and a crash must not swallow what was already measured.
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    std::string dataDir;
    bool generate = true;
    bool verbose = false;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        if (a == "--data-dir" && i + 1 < argc)
            dataDir = argv[++i];
        else if (a == "--no-generate")
            generate = false;
        else if (a == "--verbose" || a == "-v")
            verbose = true;
        else if (a == "--help" || a == "-h") {
            std::printf("用法: measure_truth [--data-dir <目录>] [--no-generate] [-v]\n"
                        "  默认: 生成 -> <目录> 并立即校验；-v 打印每条检查的 ROI 映射\n");
            return 0;
        }
    }
    if (dataDir.empty())
        dataDir = "codex_testData";
    QDir().mkpath(QString::fromStdString(dataDir));

    // ── 1. generate ────────────────────────────────────────────────────
    std::vector<MeasureTruth::Scene> scenes;
    for (const std::string& name : MeasureTruth::sceneNames()) {
        MeasureTruth::Scene s = MeasureTruth::buildScene(name);
        scenes.push_back(s);
    }
    if (generate) {
        for (MeasureTruth::Scene& s : scenes) {
            if (s.files.empty()) {
                std::printf("[生成] 跳过 %s（无数据）\n", s.name.c_str());
                continue;
            }
            if (s.files.size() != s.frames.size()) {
                std::printf("[生成] %s 文件数与数据块数不一致\n", s.name.c_str());
                return 2;
            }
            for (std::size_t i = 0; i < s.files.size(); ++i) {
                const std::string base = dataDir + "/" + s.files[i];
                if (!MeasureTruth::writeGrid(base, s.frames[i], s.gridW, s.gridH)) {
                    std::printf("[生成] 写入失败: %s\n", base.c_str());
                    return 2;
                }
                std::string ply = base;
                ply.replace(ply.size() - 5, 5, ".ply");
                MeasureTruth::writePly(ply, s.frames[i], s.gridW, s.gridH);
            }
        }
        const std::string manifestPath = dataDir + "/manifest.json";
        const std::string text = manifestText(scenes);
        QFile f(QString::fromStdString(manifestPath));
        if (!f.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
            std::printf("[生成] 无法写入 %s\n", manifestPath.c_str());
            return 2;
        }
        f.write(text.data(), static_cast<qint64>(text.size()));
        f.close();
        std::printf("[生成] %zu 个场景 + manifest.json -> %s\n\n", scenes.size(),
                    dataDir.c_str());
    } else {
        // Verify-only: the manifest on disk is the source of truth (so a user can
        // edit tolerances and re-run without regenerating the data).
        QFile f(QString::fromStdString(dataDir + "/manifest.json"));
        if (!f.open(QIODevice::ReadOnly)) {
            std::printf("读不到 %s/manifest.json（先不带 --no-generate 跑一次）\n",
                        dataDir.c_str());
            return 2;
        }
        const QJsonDocument doc = QJsonDocument::fromJson(f.readAll());
        f.close();
        scenes.clear();
        for (const QJsonValue& v : doc.object()["scenes"].toArray())
            scenes.push_back(sceneFromJson(v.toObject()));
    }

    // ── 2. verify, re-reading the data from disk ───────────────────────
    Summary sum;
    std::vector<Row> rows;
    std::map<std::string, bool> printedMapping;

    for (const MeasureTruth::Scene& s : scenes) {
        std::vector<GridFile> frames;
        bool dataOk = true;
        for (const std::string& fn : s.files) {
            GridFile g = readGrid(dataDir + "/" + fn);
            if (!g.ok) {
                std::printf("!! %s/%s: %s\n", s.name.c_str(), fn.c_str(), g.error.c_str());
                dataOk = false;
                ++sum.failed;
                sum.failures.push_back(s.name + "/" + fn + ": " + g.error);
            }
            frames.push_back(std::move(g));
            ++sum.files;
        }
        if (!dataOk)
            continue;

        ++sum.scenes;

        // "该用哪个方法 / 该画哪个 ROI"必须是真的：manifest 里的 method 必须能在
        // src/logic/MeasureMethods.h 的目录里找到（也就是界面上确实有这一项），
        // 并且需要 ROI 的方法必须写出该怎么画。这两条各算一条检查。
        const MeasureTools::MethodSpec* mspec = nullptr;
        if (!s.method.empty()) {
            int n = 0;
            const MeasureTools::MethodSpec* specs = MeasureTools::methodSpecs(n);
            for (int i = 0; i < n; ++i) {
                if (s.method == specs[i].id) {
                    mspec = &specs[i];
                    break;
                }
            }
        }
        ++sum.checks;
        ++sum.ledger;
        if (!s.method.empty() && !mspec) {
            ++sum.failed;
            sum.failures.push_back(s.name + " / method -> manifest 里写的方法 id「" + s.method
                                   + "」不在方法目录（MeasureMethods.h）里");
        }
        if (mspec) {
            ++sum.checks;
            ++sum.ledger;
            if (mspec->roiCount > 0 && s.roiHint.empty()) {
                ++sum.failed;
                sum.failures.push_back(s.name + " / roiHint -> 方法「" + s.method
                                       + "」需要 ROI，却没有写该怎么画");
            }
        }

        std::printf("══ 场景 %s  %d×%d 网格，图像 %d×%d，%zu 个文件\n", s.name.c_str(), s.gridW,
                    s.gridH, s.imageW, s.imageH, s.files.size());
        if (!s.notes.empty())
            std::printf("   说明: %s\n", s.notes.c_str());
        if (mspec) {
            std::printf("   该用哪个方法: %s（id %s，%s）\n", mspec->name, mspec->id,
                        MeasureTools::roiRequirementText(mspec->method).c_str());
            std::printf("   该画哪个 ROI: %s\n", s.roiHint.c_str());
        } else if (s.method.empty()) {
            std::printf("   该用哪个方法: —（本场景不针对某个方法）\n");
            std::printf("   该画哪个 ROI: %s\n", s.roiHint.c_str());
        } else {
            std::printf("   该用哪个方法: !!「%s」不在方法目录里\n", s.method.c_str());
        }
        std::printf("   %s%s%s%s%s%s%s\n", pad("检查项", 34).c_str(), pad("实测", 12).c_str(),
                    pad("单位", 6).c_str(), pad("真值", 12).c_str(), pad("偏差", 12).c_str(),
                    pad("公差", 10).c_str(), "判定");

        const GridFile& g0 = frames[0];
        for (const Check& c : s.checks) {
            ++sum.checks;

            // ROI mapping trace: printed once per distinct (scene, roi) so a
            // mapping error is visible instead of being inferred from a number.
            std::vector<RoiPoints> rois;
            std::vector<std::vector<int>> roiList;
            if (!c.roi.empty())
                roiList.push_back(c.roi);
            if (!c.roi2.empty())
                roiList.push_back(c.roi2);
            for (const std::vector<int>& r : roiList) {
                RoiPoints rp = extractRoi(g0, r, s.imageW, s.imageH);
                rois.push_back(rp);
                char key[256];
                std::snprintf(key, sizeof(key), "%s|%d,%d,%d,%d|%d", s.name.c_str(), r[0], r[1],
                              r[2], r[3], static_cast<int>(r.size()));
                if (!printedMapping[key]) {
                    printedMapping[key] = true;
                    if (verbose || !rp.ok) {
                        if (rp.ok) {
                            std::printf("   [映射] ROI[px]=(%d,%d)-(%d,%d) 图像 %d×%d -> 网格 "
                                        "(%d,%d)-(%d,%d) 共 %d 格，取到 %zu 点\n",
                                        r[0], r[1], r[2], r[3], s.imageW, s.imageH, rp.rect.x0,
                                        rp.rect.y0, rp.rect.x1, rp.rect.y1, rp.rect.cells,
                                        rp.pts.size());
                        } else {
                            std::printf("   [映射] ROI[px]=(%d,%d)-(%d,%d) 取点失败: %s\n", r[0],
                                        r[1], r[2], r[3], rp.error.c_str());
                        }
                    }
                }
            }

            Measured m;
            measure(c.id, rois, frames, s.imageW, s.imageH, c, m);

            auto failRow = [&](const std::string& why) {
                Row row;
                row.scene = s.name;
                row.title = c.title;
                row.unit = c.unit;
                row.measured = kNaN;
                row.truth = c.truth;
                row.dev = kNaN;
                row.tol = c.tol;
                row.pass = false;
                row.note = why;
                rows.push_back(row);
                ++sum.failed;
                sum.failures.push_back(s.name + " / " + c.title + " -> " + why);
                std::printf("   %s%s%s%s%s%s%s\n", pad(c.title, 34).c_str(),
                            pad("—", 12).c_str(), pad(c.unit, 6).c_str(),
                            pad(fmtValue(c.truth, c.unit), 12).c_str(),
                            pad("—", 12).c_str(), pad(fmt(c.tol), 10).c_str(), "FAIL");
            };

            if (!m.ok) {
                failRow(m.error);
                continue;
            }
            const bool pass = std::fabs(m.v1 - c.truth) <= c.tol + 1e-9;
            {
                Row row;
                row.scene = s.name;
                row.title = c.title;
                row.unit = c.unit;
                row.measured = m.v1;
                row.truth = c.truth;
                row.dev = m.v1 - c.truth;
                row.tol = c.tol;
                row.pass = pass;
                rows.push_back(row);
            }
            if (!pass) {
                ++sum.failed;
                char fb[256];
                std::snprintf(fb, sizeof(fb), "%s/%s: 实测 %s，真值 %s，偏差 %s，公差 %s",
                              s.name.c_str(), c.title.c_str(), fmt(m.v1).c_str(),
                              fmt(c.truth).c_str(), fmt(m.v1 - c.truth).c_str(),
                              fmt(c.tol).c_str());
                sum.failures.push_back(fb);
            }
            std::printf("   %s%s%s%s%s%s%s\n", pad(c.title, 34).c_str(),
                        pad(fmtValue(m.v1, c.unit), 12).c_str(), pad(c.unit, 6).c_str(),
                        pad(fmtValue(c.truth, c.unit), 12).c_str(),
                        pad(fmt(m.v1 - c.truth), 12).c_str(),
                        pad(fmt(c.tol), 10).c_str(), pass ? "PASS" : "FAIL");
            if (!m.info.empty())
                std::printf("      ├ %s\n", m.info.c_str());
            if (m.hasV2) {
                const bool pass2 = std::fabs(m.v2 - c.truth2) <= c.tol2 + 1e-9;
                if (!pass2) {
                    ++sum.failed;
                    char fb[256];
                    std::snprintf(fb, sizeof(fb), "%s/%s(y): 实测 %s，真值 %s，公差 %s",
                                  s.name.c_str(), c.title.c_str(), fmt(m.v2).c_str(),
                                  fmt(c.truth2).c_str(), fmt(c.tol2).c_str());
                    sum.failures.push_back(fb);
                }
                const std::string title2 = c.title + " y";
                std::printf("   %s%s%s%s%s%s%s\n", pad(title2, 34).c_str(),
                            pad(fmtValue(m.v2, c.unit), 12).c_str(), pad(c.unit, 6).c_str(),
                            pad(fmtValue(c.truth2, c.unit), 12).c_str(),
                            pad(fmt(m.v2 - c.truth2), 12).c_str(), pad(fmt(c.tol2), 10).c_str(),
                            pass2 ? "PASS" : "FAIL");
            }
            if (m.hasRing) {
                std::printf("   %s%s%s%s%s%s\n", pad("  旧法 圆环拟合(同一批点)", 34).c_str(),
                            pad(m.ringValid ? fmt(m.ring) : std::string("—"), 12).c_str(),
                            pad(fmt(c.truth), 12).c_str(),
                            pad(m.ringValid ? fmt(m.ring - c.truth) : std::string("—"), 12).c_str(),
                            pad(std::string("—"), 10).c_str(), "参考（修复前的结果）");
                if (!m.ringValid) {
                    ++sum.failed;
                    sum.failures.push_back(s.name + " / " + c.title + " -> 旧法圆拟合失败");
                }
            }
            if (m.hasExtra) {
                std::printf("   %s%s\n", pad("  新法偏差 <= 旧法一半", 34).c_str(),
                            m.extraOk ? "PASS" : "FAIL");
                if (!m.extraOk) {
                    ++sum.failed;
                    sum.failures.push_back(s.name + " / " + c.title + " -> " + m.extraLabel);
                }
                std::printf("      └ %s\n", m.extraLabel.c_str());
            }
        }
        std::printf("\n");
    }

    // ── 3. summary ─────────────────────────────────────────────────────
    std::printf("════ 汇总\n");
    std::printf("  场景 %d 个，文件 %d 个，检查 %d 条，失败 %d 条\n", sum.scenes, sum.files,
                sum.checks, sum.failed);
    // 每个场景有 2 条不带数值的台账检查（manifest 里的「该用哪个方法」必须是合法
    // 方法 id、需要 ROI 的方法必须写了 roiHint），它们不在下面的数值表里。
    std::printf("  （其中 %d 条是「该用哪个方法 / 该画哪个 ROI」的台账检查，无数值；"
                "数值检查 %d 条）\n", sum.ledger, sum.checks - sum.ledger);
    if (!sum.failures.empty()) {
        std::printf("  失败明细:\n");
        for (const std::string& f : sum.failures)
            std::printf("    - %s\n", f.c_str());
    }
    // The deviation table the round-7 report quotes: every row that was measured,
    // scene by scene, in one place.
    std::printf("\n════ 实测 vs 真值（全部检查）\n");
    std::printf("  %s%s%s%s%s\n", pad("场景", 18).c_str(), pad("检查项", 34).c_str(),
                pad("实测", 12).c_str(), pad("真值", 12).c_str(), "偏差");
    for (const Row& r : rows) {
        std::printf("  %s%s%s%s%s%s\n", pad(r.scene, 18).c_str(), pad(r.title, 34).c_str(),
                    pad(fmtValue(r.measured, r.unit), 12).c_str(),
                    pad(fmtValue(r.truth, r.unit), 12).c_str(), pad(fmt(r.dev), 12).c_str(),
                    r.pass ? "" : "FAIL");
    }
    std::printf("\n%s\n", sum.failed == 0 ? "全部通过（exit 0）" : "存在失败（exit 1）");
    return sum.failed == 0 ? 0 : 1;
}
