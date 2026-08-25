#pragma once

#include <vector>
#include <array>
#include <cstdint>

// Pure point-cloud helpers (no Qt, no SDK) so they can be unit-tested.
namespace PointCloudUtils {

// RVC raw point data is in meters; the application works in millimeters.
inline constexpr float METERS_TO_MM = 1000.0f;

// Filters invalid points from raw RVC structured point data and extracts colors.
//
// pointData  : raw RVC point buffer, total*3 doubles, meters, may contain NaN/zero
// total      : number of points (row-major grid)
// imageData  : optional BGR8/RGB8 (3ch) or Mono8 (1ch) image aligned with the grid;
//              pass nullptr to skip color extraction (points default to white)
// imageCh    : 1 or 3; ignored when imageData is nullptr
// pointsOut  : filled with N*3 floats in mm (NaN/zero filtered)
// colorsOut  : filled with N*3 floats in [0,1] RGB
void filterValidPoints(const double* pointData, int total,
                       const uint8_t* imageData, int imageCh,
                       std::vector<float>& pointsOut,
                       std::vector<float>& colorsOut);

// Project a 3D scene point onto the screen for a look-at camera
// (eye / look-at-center / up-vector, viewport in px, vertical fov in deg).
// Pure math (no Qt, no Vis/OSG) so it can be unit-tested.  Returns false when
// the point is behind the camera or the inputs are degenerate.
bool projectLookAtToScreen(const std::array<float, 3>& eye,
                           const std::array<float, 3>& center,
                           const std::array<float, 3>& up,
                           int viewW, int viewH, float fovDeg,
                           const std::array<float, 3>& pt,
                           float& screenX, float& screenY);

} // namespace PointCloudUtils
