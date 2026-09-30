#include "ui/MeasurePages.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <string>
#include <vector>

// ── 8 个方法页 ─────────────────────────────────────────────────────────
//
// 每个类的 compute() 就是旧面板 runMeasurement() 里对应 case 的算法部分，数值
// 口径一行未改（同样的稳健剔除、同样的 minOutliers、同样的单位）。搬出来只是
// 为了让"这一页需要几个 ROI、要显示哪些行、跑不出来时说什么"集中在一个类里。
namespace {

using MeasureTools::Vec3;

QString fromStd(const std::string& s)
{
    return QString::fromStdString(s);
}

// 结果表一行的简写（值必须已经格式化好）。
void row(MeasureContext& ctx, const QString& label, const QString& value,
         const QString& unit, int points, const QString& confidence)
{
    ctx.rows.push_back({ label, value, unit, points, confidence });
}

// 3D 标记的落点（旧面板的 roiCenter lambda）。
Vec3 centroidOf(const std::vector<Vec3>& pts)
{
    Vec3 c{ 0.0, 0.0, 0.0 };
    if (pts.empty())
        return c;
    for (const Vec3& v : pts)
        for (int k = 0; k < 3; ++k)
            c[k] += v[k];
    for (int k = 0; k < 3; ++k)
        c[k] /= static_cast<double>(pts.size());
    return c;
}

// ── 1. 平面度 ──────────────────────────────────────────────────────────
class FlatnessPage : public MeasurePage {
public:
    explicit FlatnessPage(QWidget* parent)
        : MeasurePage(MeasureTools::Method::Flatness, parent) {}

protected:
    void compute(MeasureContext& ctx) override
    {
        const std::vector<Vec3>& pts = ctx.roi[0];
        if (pts.size() < 3) {
            ctx.refusal = QStringLiteral("平面度需要在 ROI A（被测面）内至少 3 个点，当前 %1 个。")
                              .arg(static_cast<qulonglong>(pts.size()));
            return;
        }
        const MeasureTools::Flatness f = MeasureTools::flatness(pts, 3.0);
        if (!f.valid) {
            ctx.refusal = fromStd(f.message);
            return;
        }
        const int used = static_cast<int>(f.used);
        row(ctx, QStringLiteral("平面度 最小区域 PV"), fmt4(f.mzPv), QStringLiteral("mm"),
            used, confidenceFor(used, f.lsqRms));
        row(ctx, QStringLiteral("平面度 LSQ PV"), fmt4(f.lsqPv), QStringLiteral("mm"),
            used, confidenceFor(used, f.lsqRms));
        row(ctx, QStringLiteral("平面度 LSQ RMS"), fmt4(f.lsqRms), QStringLiteral("mm"),
            used, confidenceFor(used, f.lsqRms));
        row(ctx, QStringLiteral("倾斜角"), fmt4(f.tiltDeg), QStringLiteral("°"),
            used, confidenceFor(used, f.lsqRms));
        ctx.primaryKey = QStringLiteral("平面度 最小区域 PV");
        ctx.primaryValue = f.mzPv;
        ctx.hasPrimary = true;

        ctx.hasDeviation = true;
        ctx.devValues = f.dev;
        ctx.devCells = ctx.roiCells[0];
        ctx.devCoolWarm = true;
        ctx.plane = f.plane;
        ctx.hasPlane = true;
        ctx.planePoint = centroidOf(pts);
        ctx.planeNormal = f.plane.normal;
        const QRect r = ctx.roiRects->value(0);
        ctx.annotations.push_back({ QStringLiteral("平面度 PV %1 mm").arg(fmt4(f.mzPv)),
                                    QPoint(r.center().x(), r.center().y()), false });
        // 剖面：供「截面轮廓」页显示。
        const MeasureTools::SectionProfile sec = MeasureTools::sectionProfile(pts, 64);
        if (sec.valid) {
            ctx.section = sec.points;
            ctx.sectionStep = sec.stepMm;
            ctx.hasSection = true;
        }
        ctx.confidenceNote = QStringLiteral("PV = 最大−最小；MZ ≤ LSQ PV");
    }
};

// ── 2. 高度段差（面到面高度，中位数）──────────────────────────────────
class StepHeightPage : public MeasurePage {
public:
    explicit StepHeightPage(QWidget* parent)
        : MeasurePage(MeasureTools::Method::StepHeight, parent) {}

protected:
    void compute(MeasureContext& ctx) override
    {
        if (ctx.roi[0].size() < 3 || ctx.roi[1].size() < 3) {
            ctx.refusal = QStringLiteral("需要两个测量区域：ROI A（基准面）%1 点、"
                                         "ROI B（被测面）%2 点；每块至少要 3 个点。")
                              .arg(static_cast<qulonglong>(ctx.roi[0].size()))
                              .arg(static_cast<qulonglong>(ctx.roi[1].size()));
            return;
        }
        const MeasureTools::Height h =
            MeasureTools::heightBetween(ctx.roi[0], ctx.roi[1], 3.0);
        if (!h.valid) {
            ctx.refusal = fromStd(h.message);
            return;
        }
        const int used = static_cast<int>(h.usedTarget);
        row(ctx, QStringLiteral("面到面高度(中位数)"), fmt4(h.value), QStringLiteral("mm"),
            used, confidenceFor(used, h.rms));
        row(ctx, QStringLiteral("面到面高度 RMS"), fmt4(h.rms), QStringLiteral("mm"),
            used, confidenceFor(used, h.rms));
        ctx.primaryKey = QStringLiteral("面到面高度(中位数)");
        ctx.primaryValue = h.value;
        ctx.hasPrimary = true;

        std::vector<Vec3> pts;
        std::vector<std::size_t> cells;
        bothRois(ctx, pts, cells);
        ctx.hasDeviation = true;
        ctx.devValues = MeasureTools::deviations(pts, h.ref);
        ctx.devCells = cells;
        ctx.devCoolWarm = true;
        ctx.plane = h.ref;
        ctx.hasPlane = true;
        ctx.planePoint = centroidOf(ctx.roi[0]);
        ctx.planeNormal = h.ref.normal;

        const QRect ra = ctx.roiRects->value(0), rb = ctx.roiRects->value(1);
        ctx.annotations.push_back({ QStringLiteral("基准 A"),
                                    QPoint(ra.center().x(), ra.center().y()), false });
        ctx.annotations.push_back({ QStringLiteral("B 相对 A %1 mm").arg(fmt4(h.value)),
                                    QPoint(rb.center().x(), rb.center().y()), false });
        const MeasureTools::SectionProfile sec = MeasureTools::sectionProfile(pts, 96);
        if (sec.valid) {
            ctx.section = sec.points;
            ctx.sectionStep = sec.stepMm;
            ctx.hasSection = true;
        }
        ctx.confidenceNote = QStringLiteral("高度为正 = ROI B 朝向相机凸起");
    }

private:
    static void bothRois(MeasureContext& ctx, std::vector<Vec3>& pts,
                         std::vector<std::size_t>& cells)
    {
        pts = ctx.roi[0];
        cells = ctx.roiCells[0];
        pts.insert(pts.end(), ctx.roi[1].begin(), ctx.roi[1].end());
        cells.insert(cells.end(), ctx.roiCells[1].begin(), ctx.roiCells[1].end());
    }
};

// ── 3. 面面距离 / 夹角 ─────────────────────────────────────────────────
class PlanePairPage : public MeasurePage {
public:
    explicit PlanePairPage(QWidget* parent)
        : MeasurePage(MeasureTools::Method::PlanePair, parent) {}

protected:
    void compute(MeasureContext& ctx) override
    {
        if (ctx.roi[0].size() < 3 || ctx.roi[1].size() < 3) {
            ctx.refusal = QStringLiteral("需要两个测量区域（ROI A / ROI B），"
                                         "当前 %1 / %2 点，每块至少 3 个点。")
                              .arg(static_cast<qulonglong>(ctx.roi[0].size()))
                              .arg(static_cast<qulonglong>(ctx.roi[1].size()));
            return;
        }
        // 3° 是面向用户的平行判据（Python 工具给的是 5°）。
        const MeasureTools::PlanePair pp =
            MeasureTools::planePair(ctx.roi[0], ctx.roi[1], 3.0, 3.0);
        if (!pp.valid) {
            ctx.refusal = fromStd(pp.message);
            return;
        }
        const int pts = static_cast<int>(pp.usedA + pp.usedB);
        row(ctx, QStringLiteral("面面夹角"), fmt4(pp.angleDeg), QStringLiteral("°"), pts,
            confidenceFor(pts, -1.0));
        if (pp.parallel) {
            row(ctx, QStringLiteral("平行面间距"), fmt4(pp.distanceMm), QStringLiteral("mm"),
                pts, confidenceFor(pts, -1.0));
            ctx.primaryKey = QStringLiteral("平行面间距");
            ctx.primaryValue = pp.distanceMm;
        } else {
            row(ctx, QStringLiteral("夹角 ≥ 3°：不给出间距"), QStringLiteral("—"),
                QStringLiteral("mm"), pts, QStringLiteral("—"));
            ctx.primaryKey = QStringLiteral("面面夹角");
            ctx.primaryValue = pp.angleDeg;
        }
        ctx.hasPrimary = true;

        std::vector<Vec3> p2;
        std::vector<std::size_t> c2;
        p2 = ctx.roi[0];
        c2 = ctx.roiCells[0];
        p2.insert(p2.end(), ctx.roi[1].begin(), ctx.roi[1].end());
        c2.insert(c2.end(), ctx.roiCells[1].begin(), ctx.roiCells[1].end());
        ctx.hasDeviation = true;
        ctx.devValues = MeasureTools::deviations(p2, pp.planeA);
        ctx.devCells = c2;
        ctx.devCoolWarm = true;
        ctx.plane = pp.planeA;
        ctx.hasPlane = true;
        ctx.planePoint = centroidOf(ctx.roi[0]);
        ctx.planeNormal = pp.planeA.normal;

        const QRect ra = ctx.roiRects->value(0), rb = ctx.roiRects->value(1);
        ctx.annotations.push_back({ QStringLiteral("A"),
                                    QPoint(ra.center().x(), ra.center().y()), false });
        ctx.annotations.push_back(
            { QStringLiteral("B：夹角 %1°").arg(fmt4(pp.angleDeg)),
              QPoint(rb.center().x(), rb.center().y()), false });
        ctx.confidenceNote = pp.parallel
            ? QStringLiteral("夹角 < 3°，按平行面给出间距")
            : QStringLiteral("夹角 ≥ 3°，不给出间距（不平行平面的「距离」没有意义）");
    }
};

// ── 4. 圆环拟合（只对环形 ROI 有意义）─────────────────────────────────
class RingCirclePage : public MeasurePage {
public:
    explicit RingCirclePage(QWidget* parent)
        : MeasurePage(MeasureTools::Method::RingCircle, parent) {}

protected:
    void compute(MeasureContext& ctx) override
    {
        const std::vector<Vec3>& pts = ctx.roi[0];
        if (pts.size() < 12) {
            ctx.refusal = QStringLiteral("圆环拟合需要在 ROI A（环形材料）内至少 12 个点，"
                                         "当前 %1 个。")
                              .arg(static_cast<qulonglong>(pts.size()));
            return;
        }
        // T-012：量的是"材料→背景"的外缘（实心外圆、台阶外缘），从 ROI 内的材料
        // 连通区往外长，再在图像上把这条边抠到亚像素；不再是全体点的统计半径。
        const std::vector<double> noGrid;
        const std::vector<double>& gridRef = ctx.grid ? *ctx.grid : noGrid;
        const MeasureTools::BoundaryCircle bc = MeasureTools::measureBoundaryCircle(
            pts, ctx.roiCells[0], ctx.gridW, ctx.gridH, gridRef,
            ctx.image ? ctx.image->width : 0, ctx.image ? ctx.image->height : 0,
            ctx.image ? *ctx.image : MeasureTools::GrayImage{}, true);
        if (!bc.valid) {
            ctx.refusal = fromStd(bc.message);
            return;
        }
        const int used = bc.used > 0 ? bc.used : bc.sectors;
        const QString conf = bc.reliable ? confidenceFor(used, bc.rms)
                                         : QStringLiteral("参考");
        row(ctx, QStringLiteral("圆环直径"), fmt4(bc.diameter), QStringLiteral("mm"), used, conf);
        row(ctx, QStringLiteral("圆环半径"), fmt4(bc.radius), QStringLiteral("mm"), used, conf);
        row(ctx, QStringLiteral("圆环圆度(半径极差)"), fmt4(bc.roundness), QStringLiteral("mm"),
            used, conf);
        row(ctx, QStringLiteral("圆环圆心"),
            QStringLiteral("(%1, %2, %3)")
                .arg(fmt4(bc.center[0])).arg(fmt4(bc.center[1])).arg(fmt4(bc.center[2])),
            QStringLiteral("mm"), used, conf);
        ctx.primaryKey = QStringLiteral("圆环直径");
        ctx.primaryValue = bc.diameter;
        ctx.hasPrimary = true;

        // 偏差图显示"到拟合圆的半径残差"：同一个符号距离思路，只是基准换成圆。
        std::vector<double> radial(pts.size());
        for (std::size_t k = 0; k < pts.size(); ++k) {
            const double dx = pts[k][0] - bc.center[0];
            const double dy = pts[k][1] - bc.center[1];
            const double dz = pts[k][2] - bc.center[2];
            radial[k] = std::sqrt(dx * dx + dy * dy + dz * dz) - bc.radius;
        }
        ctx.hasDeviation = true;
        ctx.devValues = radial;
        ctx.devCells = ctx.roiCells[0];
        ctx.devCoolWarm = false;

        const QRect r = ctx.roiRects->value(0);
        ctx.annotations.push_back({ QStringLiteral("⌀%1 mm").arg(fmt4(bc.diameter)),
                                    QPoint(r.center().x(), r.center().y()), false });
        ctx.hasPlane = true;
        ctx.planePoint = bc.center;
        ctx.planeNormal = bc.normal;
        // T-012：本工具现在量的是最外侧的材料边界（实心外圆 / 台阶外缘）。
        ctx.footer = bc.subpixel
            ? QStringLiteral("图像亚像素外缘 %1 条，局部尺度 %2 mm/px")
                  .arg(bc.used).arg(fmt4(bc.mmPerPx))
            : QStringLiteral("图像不可用，本结果为 3D 外缘边界（粗）");
        ctx.confidenceNote = bc.subpixel
            ? QStringLiteral("材料外缘（从外往内）：亚像素边缘 %1/360 条（覆盖 %2%%），"
                             "圆度 %3 mm，尺度 %4 mm/px")
                  .arg(used).arg(fmt4(100.0 * bc.coverage))
                  .arg(fmt4(bc.roundness)).arg(fmt4(bc.mmPerPx))
            : QStringLiteral("退回 3D 外缘边界：%1").arg(fromStd(bc.message));
        if (!bc.reliable)
            ctx.confidenceNote += QStringLiteral("；覆盖或圆度不达标，已标「参考」");
        ctx.confidenceNote += QStringLiteral("；") + QString::fromStdString(bc.debug);
    }
};

// ── 5. 孔径（孔洞边界法）──────────────────────────────────────────────
class HoleDiameterPage : public MeasurePage {
public:
    explicit HoleDiameterPage(QWidget* parent)
        : MeasurePage(MeasureTools::Method::HoleDiameter, parent) {}

protected:
    void compute(MeasureContext& ctx) override
    {
        const std::vector<Vec3>& pts = ctx.roi[0];
        if (pts.size() < 8) {
            ctx.refusal = QStringLiteral("孔径(孔洞边界法)需要在 ROI A 内至少 8 个点"
                                         "（孔 + 孔外约 2 个点距的材料），当前 %1 个。")
                              .arg(static_cast<qulonglong>(pts.size()));
            return;
        }
        const std::vector<double> noGrid;
        const std::vector<double>& gridRef = ctx.grid ? *ctx.grid : noGrid;
        const MeasureTools::BoundaryCircle bc = MeasureTools::measureBoundaryCircle(
            pts, ctx.roiCells[0], ctx.gridW, ctx.gridH, gridRef,
            ctx.image ? ctx.image->width : 0, ctx.image ? ctx.image->height : 0,
            ctx.image ? *ctx.image : MeasureTools::GrayImage{}, false);
        if (!bc.valid) {
            ctx.refusal = fromStd(bc.message);
            return;
        }
        const int used = bc.used > 0 ? bc.used : bc.sectors;
        // 可信度列：边缘样本不足时直接标"参考"——这是 P2 对用户承诺的降级口径。
        const QString conf = bc.reliable ? confidenceFor(used, bc.rms)
                                         : QStringLiteral("参考");
        row(ctx, QStringLiteral("孔直径"), fmt4(bc.diameter), QStringLiteral("mm"), used, conf);
        row(ctx, QStringLiteral("孔半径"), fmt4(bc.radius), QStringLiteral("mm"), used, conf);
        row(ctx, QStringLiteral("孔圆心"),
            QStringLiteral("(%1, %2, %3)")
                .arg(fmt4(bc.center[0])).arg(fmt4(bc.center[1])).arg(fmt4(bc.center[2])),
            QStringLiteral("mm"), used, conf);
        row(ctx, QStringLiteral("孔圆度(半径极差)"), fmt4(bc.roundness), QStringLiteral("mm"),
            used, conf);
        row(ctx, QStringLiteral("扇区覆盖"),
            QStringLiteral("%1/%2").arg(used).arg(bc.sectors),
            QString(), used, conf);
        row(ctx, QStringLiteral("圆拟合直径(未修正)"), fmt4(bc.diameter),
            QStringLiteral("mm"), used, conf);
        ctx.primaryKey = QStringLiteral("孔直径");
        ctx.primaryValue = bc.diameter;
        ctx.hasPrimary = true;

        // 偏差图 = 到孔壁圆的半径残差（turbo，与旧圆拟合同一套视觉）。
        std::vector<double> radial(pts.size());
        for (std::size_t k = 0; k < pts.size(); ++k) {
            const double dx = pts[k][0] - bc.center[0];
            const double dy = pts[k][1] - bc.center[1];
            const double dz = pts[k][2] - bc.center[2];
            radial[k] = std::sqrt(dx * dx + dy * dy + dz * dz) - bc.radius;
        }
        ctx.hasDeviation = true;
        ctx.devValues = radial;
        ctx.devCells = ctx.roiCells[0];
        ctx.devCoolWarm = false;

        const QRect r = ctx.roiRects->value(0);
        ctx.annotations.push_back({ QStringLiteral("⌀%1 mm").arg(fmt4(bc.diameter)),
                                    QPoint(r.center().x(), r.center().y()), false });
        ctx.hasPlane = true;
        ctx.planePoint = bc.center;
        ctx.planeNormal = bc.normal;

        ctx.footer = bc.subpixel
            ? QStringLiteral("图像亚像素边缘 %1 条，局部尺度 %2 mm/px")
                  .arg(bc.used).arg(fmt4(bc.mmPerPx))
            : QStringLiteral("图像不可用，本结果为 3D 边界（粗）");
        ctx.confidenceNote = bc.subpixel
            ? QStringLiteral("亚像素边缘 %1/360 条（覆盖 %2%%），圆度 %3 mm，尺度 %4 mm/px")
                  .arg(used).arg(fmt4(100.0 * bc.coverage))
                  .arg(fmt4(bc.roundness)).arg(fmt4(bc.mmPerPx))
            : QStringLiteral("退回 3D 边界：%1").arg(fromStd(bc.message));
        if (!bc.reliable)
            ctx.confidenceNote += QStringLiteral("；覆盖或圆度不达标，已标「参考」");
        ctx.confidenceNote += QStringLiteral("；") + QString::fromStdString(bc.debug);
        if (ctx.roiRects && !ctx.roiRects->isEmpty()) {
            const QRect rr = ctx.roiRects->value(0);
            ctx.confidenceNote += QStringLiteral(" roiImg=(%1,%2)-(%3,%4)")
                .arg(rr.left()).arg(rr.top()).arg(rr.right()).arg(rr.bottom());
        }
    }
};

// ── 6. 包围盒 ──────────────────────────────────────────────────────────
class BoundingBoxPage : public MeasurePage {
public:
    explicit BoundingBoxPage(QWidget* parent)
        : MeasurePage(MeasureTools::Method::BoundingBox, parent) {}

protected:
    void compute(MeasureContext& ctx) override
    {
        const std::vector<Vec3>& pts = ctx.roi[0];
        if (pts.size() < 4) {
            ctx.refusal = QStringLiteral("包围盒需要在 ROI A（整个物体）内至少 4 个点，"
                                         "当前 %1 个。")
                              .arg(static_cast<qulonglong>(pts.size()));
            return;
        }
        const MeasureTools::BoundingBox b = MeasureTools::pcaBoundingBox(pts);
        if (!b.valid) {
            ctx.refusal = fromStd(b.message);
            return;
        }
        const int used = static_cast<int>(b.used);
        row(ctx, QStringLiteral("长"), fmt4(b.length), QStringLiteral("mm"), used,
            confidenceFor(used, -1.0));
        row(ctx, QStringLiteral("宽"), fmt4(b.width), QStringLiteral("mm"), used,
            confidenceFor(used, -1.0));
        row(ctx, QStringLiteral("高"), fmt4(b.height), QStringLiteral("mm"), used,
            confidenceFor(used, -1.0));
        row(ctx, QStringLiteral("中心"),
            QStringLiteral("(%1, %2, %3)")
                .arg(fmt4(b.center[0])).arg(fmt4(b.center[1])).arg(fmt4(b.center[2])),
            QStringLiteral("mm"), used, confidenceFor(used, -1.0));
        ctx.primaryKey = QStringLiteral("长");
        ctx.primaryValue = b.length;
        ctx.hasPrimary = true;

        // ROI 的轴对齐范围，用于在 3D 视窗放盒子标记。
        ctx.hasBox = true;
        ctx.boxMin = { std::numeric_limits<double>::max(), std::numeric_limits<double>::max(),
                       std::numeric_limits<double>::max() };
        ctx.boxMax = { std::numeric_limits<double>::lowest(),
                       std::numeric_limits<double>::lowest(),
                       std::numeric_limits<double>::lowest() };
        for (const Vec3& v : pts) {
            for (int k = 0; k < 3; ++k) {
                ctx.boxMin[k] = std::min(ctx.boxMin[k], v[k]);
                ctx.boxMax[k] = std::max(ctx.boxMax[k], v[k]);
            }
        }
        const QRect r = ctx.roiRects->value(0);
        ctx.annotations.push_back(
            { QStringLiteral("%1 × %2 × %3 mm").arg(fmt4(b.length), fmt4(b.width),
                                                     fmt4(b.height)),
              QPoint(r.center().x(), r.center().y()), false });
        ctx.confidenceNote = QStringLiteral("PCA 主轴对齐；长 ≥ 宽 ≥ 高");
    }
};

// ── 7. 截面轮廓 ────────────────────────────────────────────────────────
class SectionPage : public MeasurePage {
public:
    explicit SectionPage(QWidget* parent)
        : MeasurePage(MeasureTools::Method::Section, parent) {}

protected:
    void compute(MeasureContext& ctx) override
    {
        const std::vector<Vec3>& pts = ctx.roi[0];
        if (pts.size() < 8) {
            ctx.refusal = QStringLiteral("截面轮廓需要在 ROI A 内至少 8 个点，当前 %1 个。")
                              .arg(static_cast<qulonglong>(pts.size()));
            return;
        }
        const MeasureTools::SectionProfile sec = MeasureTools::sectionProfile(pts, 64);
        if (!sec.valid) {
            ctx.refusal = fromStd(sec.message);
            return;
        }
        const double length = sec.tMax - sec.tMin;
        row(ctx, QStringLiteral("剖面长度"), fmt4(length), QStringLiteral("mm"),
            static_cast<int>(sec.points.size()), confidenceFor(static_cast<int>(pts.size()), -1.0));
        row(ctx, QStringLiteral("采样步长"), fmt4(sec.stepMm), QStringLiteral("mm"),
            static_cast<int>(sec.points.size()), confidenceFor(static_cast<int>(pts.size()), -1.0));
        row(ctx, QStringLiteral("轮廓点数"), QString::number(sec.points.size()), QString(),
            static_cast<int>(sec.points.size()), confidenceFor(static_cast<int>(pts.size()), -1.0));
        ctx.primaryKey = QStringLiteral("剖面长度");
        ctx.primaryValue = length;
        ctx.hasPrimary = true;

        ctx.hasSection = true;
        ctx.section = sec.points;
        ctx.sectionStep = sec.stepMm;

        // 顺带给出被测面的平面标记与偏差图：截面页仍要能在 3D 里定位。
        const MeasureTools::Plane p = MeasureTools::fitPlane(pts);
        if (p.valid) {
            ctx.hasDeviation = true;
            ctx.devValues = MeasureTools::deviations(pts, p);
            ctx.devCells = ctx.roiCells[0];
            ctx.devCoolWarm = true;
            ctx.plane = p;
            ctx.hasPlane = true;
            ctx.planePoint = { p.normal[0] * -p.d, p.normal[1] * -p.d, p.normal[2] * -p.d };
            ctx.planeNormal = p.normal;
        }
        ctx.confidenceNote = QStringLiteral("轮廓 = 每个距离分箱内点高度的中位数");
    }
};

// ── 8. 重复性 ──────────────────────────────────────────────────────────
class RepeatabilityPage : public MeasurePage {
public:
    explicit RepeatabilityPage(QWidget* parent)
        : MeasurePage(MeasureTools::Method::Repeatability, parent) {}

protected:
    void compute(MeasureContext& ctx) override
    {
        const QString name = currentSeriesName();
        const QVector<double>* vals = currentSeries();
        if (name.isEmpty() || !vals || vals->isEmpty()) {
            ctx.refusal = QStringLiteral(
                "当前没有重复性数据：先用别的方法测一个尺寸并点「加入重复性」，"
                "重新拍照、重新框选后再测一次（可反复采样）。");
            return;
        }
        const MeasureTools::Repeatability rep =
            MeasureTools::repeatability(std::vector<double>(vals->begin(), vals->end()));
        if (!rep.valid) {
            ctx.refusal = QStringLiteral("序列「%1」的有效样本不足。").arg(name);
            return;
        }
        const int n = static_cast<int>(rep.n);
        // 重复性的可信度就是样本数：n<5 时 σ 本身不可信，门槛写在说明里。
        const QString conf = n >= 30 ? QStringLiteral("高")
                                     : (n >= 5 ? QStringLiteral("中") : QStringLiteral("低"));
        row(ctx, QStringLiteral("采样数 n"), QString::number(n), QString(), n, conf);
        row(ctx, QStringLiteral("均值"), fmt4(rep.mean), QStringLiteral("mm"), n, conf);
        row(ctx, QStringLiteral("标准差 σ"), fmt4(rep.stdDev), QStringLiteral("mm"), n, conf);
        row(ctx, QStringLiteral("极差"), fmt4(rep.range), QStringLiteral("mm"), n, conf);
        row(ctx, QStringLiteral("±3σ"), QStringLiteral("±%1").arg(fmt4(rep.sixSigma / 2.0)),
            QStringLiteral("mm"), n, conf);
        row(ctx, QStringLiteral("最小 / 最大"),
            QStringLiteral("%1 / %2").arg(fmt4(rep.min), fmt4(rep.max)),
            QStringLiteral("mm"), n, conf);
        row(ctx, QStringLiteral("最大偏差"), fmt4(rep.maxDev), QStringLiteral("mm"), n, conf);
        ctx.primaryKey = QStringLiteral("均值");
        ctx.primaryValue = rep.mean;
        ctx.hasPrimary = true;
        ctx.footer = QStringLiteral("序列「%1」：n=%2，均值 %3，σ %4（仅本次运行，未写入磁盘）")
                         .arg(name).arg(rep.n).arg(fmt4(rep.mean)).arg(fmt4(rep.stdDev));
        ctx.confidenceNote = n >= 5
            ? QStringLiteral("n ≥ 5，σ 反映重复测同一处的波动")
            : QStringLiteral("n < 5：σ 本身不可信，只作参考");
    }
};

} // namespace

namespace MeasurePages {

MeasurePage* create(MeasureTools::Method method, QWidget* parent)
{
    switch (method) {
    case MeasureTools::Method::Flatness:      return new FlatnessPage(parent);
    case MeasureTools::Method::StepHeight:    return new StepHeightPage(parent);
    case MeasureTools::Method::PlanePair:     return new PlanePairPage(parent);
    case MeasureTools::Method::RingCircle:    return new RingCirclePage(parent);
    case MeasureTools::Method::HoleDiameter:  return new HoleDiameterPage(parent);
    case MeasureTools::Method::BoundingBox:   return new BoundingBoxPage(parent);
    case MeasureTools::Method::Section:       return new SectionPage(parent);
    case MeasureTools::Method::Repeatability: return new RepeatabilityPage(parent);
    case MeasureTools::Method::Count:         break;
    }
    return nullptr;
}

std::vector<MeasurePage*> createAll(QWidget* parent)
{
    std::vector<MeasurePage*> pages;
    int n = 0;
    const MeasureTools::MethodSpec* specs = MeasureTools::methodSpecs(n);
    for (int i = 0; i < n; ++i)
        pages.push_back(create(specs[i].method, parent));
    return pages;
}

} // namespace MeasurePages
