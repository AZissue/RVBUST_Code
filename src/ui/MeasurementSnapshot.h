#pragma once

// Data contract between the tools panel (which computes) and the 3D view
// (which draws).  Everything here is plain QtCore/QtGui so the view stays
// passive: it receives a snapshot and paints it, it never reaches back into the
// measurement code or into CameraManager.
#include <QString>

#include <array>

namespace Measurement {

// One row of the result table (方法 / 数值 / 单位 / 点数 / 可信度).
struct ResultRow {
    QString method;
    QString value;
    QString unit;
    int points = 0;
    QString confidence;
};

// Everything the 3D viewport needs: a fitted-plane marker and a bounding box
// for the measured region.  Built once per measurement on the panel side; the
// view only reads it.
struct Snapshot {
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
