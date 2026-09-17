#pragma once

// Data contract between the tools panel (which computes) and the 2D/3D views
// (which draw).  Everything here is plain QtCore/QtGui so the views stay
// passive: they receive a snapshot and paint it, they never reach back into the
// measurement code or into CameraManager.
#include <QImage>
#include <QRect>
#include <QString>
#include <QStringList>
#include <QVector>

#include <array>
#include <cmath>
#include <cstddef>
#include <memory>
#include <vector>

namespace Measurement {

// NOTE: the deviation colormap itself lives in logic/MeasureTools.h
// (MeasureTools::colormap) so that the 2D page, the 3D colouring and the unit
// tests all use one implementation — this header stays a plain data contract
// with no algorithm in it.

// One row of the result table (方法 / 数值 / 单位 / 点数 / 可信度).
struct ResultRow {
    QString method;
    QString value;
    QString unit;
    int points = 0;
    QString confidence;
};

// A dimension call-out for the 尺寸总图 page: the text is placed next to
// `anchor` (image pixels) and joined to it with a leader line.
struct Annotation {
    QString text;
    QPoint anchor;
    bool highlight = false;   // draw in the warning colour (out of tolerance)
};

// One coloured deviation sample: the value and the organized-grid cell it came
// from.  Grid cells are used rather than image pixels because the 3D point map
// and the 2D image do not have to share a resolution — the view scales.
struct DevSample {
    double value = 0.0;
    int gx = 0;
    int gy = 0;
};

// Everything the display pages need.  Built once per measurement on the panel
// side; the views only read it.
struct Snapshot {
    bool valid = false;
    QString title;        // e.g. "平面度"
    QString footer;       // colour-scale explanation, point count, ...

    // ── 偏差图 ──
    QVector<DevSample> devSamples;
    int gridW = 0;
    int gridH = 0;
    double limitLo = 0.0;
    double limitHi = 0.0;
    bool robustLimits = false;   // ±3σ_MAD band (false = percentile fallback)
    int clipped = 0;             // samples pinned to an end colour
    QString unit;
    bool coolWarm = true;        // flatness/deviation uses coolwarm, line turbo

    // ── 尺寸总图 ──
    QVector<Annotation> annotations;

    // ── 截面轮廓 ──
    std::vector<std::array<double, 2>> section;   // (distance along, height)
    double sectionStep = 0.0;
    int sectionPoints = 0;

    // ── 重复性趋势 ──
    QString seriesName;
    QVector<double> series;
    bool hasTolerance = false;
    double tolLo = 0.0;
    double tolHi = 0.0;
    double seriesMean = 0.0;
    double seriesSigma = 0.0;
    double seriesRange = 0.0;
    int seriesN = 0;

    // ── 3D (P4) ──
    // Per-point colour for the *captured flat cloud*: one RGB triple in [0,1]
    // per point of the uploaded cloud, or null when no deviation colouring is
    // active.  Built by the panel from the same grid scan the cloud used, so
    // the two stay index-aligned.
    //
    // Shared, like the capture buffers themselves: this array is ~8 MB at
    // 682k points and the snapshot is copied by every view that receives it
    // (and rebuilt on every tolerance edit), so a deep copy per hand-off would
    // be pure waste.  Handing it over is a refcount bump.
    std::shared_ptr<const std::vector<std::array<float, 3>>> cloudColors;
    bool hasCloudColors = false;

    // 3D annotations: a fitted-plane marker and a bounding box for the ROI.
    bool hasPlane = false;
    std::array<double, 3> planePoint{};    // a point on the fitted plane
    std::array<double, 3> planeNormal{};
    bool hasRoiBox = false;
    std::array<double, 3> boxMin{};
    std::array<double, 3> boxMax{};
    QString label;                         // text shown next to the 3D marker
};

} // namespace Measurement
