#pragma once
#include <QString>

struct CaptureRecord {
    int     index = 0;              // 1-based
    QString pngPath;                // absolute path to PNG
    QString plyPath;                // absolute path to PLY
    QString cameraTargetXyz;        // "x y z"
    QString robotCapturePose;       // "x y z rx ry rz"
    QString robotTargetXyz;         // "x y z" (TCP touch only)
    float   cameraErrorPct = -1.0f; // detection accuracy for the board, -1 = N/A
    int     markerCount = 0;        // detected markers/circles in this frame

    bool isValid() const { return index > 0 && !pngPath.isEmpty() && !plyPath.isEmpty(); }
};
