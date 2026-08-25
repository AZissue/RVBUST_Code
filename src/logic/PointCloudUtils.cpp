#include "logic/PointCloudUtils.h"

#include <cmath>

namespace PointCloudUtils {

void filterValidPoints(const double* pointData, int total,
                       const uint8_t* imageData, int imageCh,
                       std::vector<float>& pointsOut,
                       std::vector<float>& colorsOut)
{
    pointsOut.clear();
    colorsOut.clear();

    if (!pointData || total <= 0)
        return;

    const int imgCh = imageData ? imageCh : 0;

    pointsOut.reserve(static_cast<size_t>(total) * 3);
    colorsOut.reserve(static_cast<size_t>(total) * 3);

    for (int i = 0; i < total; ++i) {
        const double x = pointData[i * 3 + 0] * METERS_TO_MM;
        const double y = pointData[i * 3 + 1] * METERS_TO_MM;
        const double z = pointData[i * 3 + 2] * METERS_TO_MM;

        if (std::isnan(x) || std::isnan(y) || std::isnan(z))
            continue;
        if (x == 0.0f && y == 0.0f && z == 0.0f)
            continue;

        pointsOut.push_back(x);
        pointsOut.push_back(y);
        pointsOut.push_back(z);

        if (imgCh >= 3) {
            // BGR8/RGB8 -> RGB, normalized to [0,1]
            colorsOut.push_back(imageData[i * 3 + 2] / 255.0f);
            colorsOut.push_back(imageData[i * 3 + 1] / 255.0f);
            colorsOut.push_back(imageData[i * 3 + 0] / 255.0f);
        } else if (imgCh == 1) {
            const float v = imageData[i] / 255.0f;
            colorsOut.push_back(v);
            colorsOut.push_back(v);
            colorsOut.push_back(v);
        } else {
            colorsOut.push_back(1.0f);
            colorsOut.push_back(1.0f);
            colorsOut.push_back(1.0f);
        }
    }
}

bool projectLookAtToScreen(const std::array<float, 3>& eye,
                           const std::array<float, 3>& center,
                           const std::array<float, 3>& up,
                           int viewW, int viewH, float fovDeg,
                           const std::array<float, 3>& pt,
                           float& screenX, float& screenY)
{
    if (viewW <= 0 || viewH <= 0 || fovDeg <= 1.0f || fovDeg >= 179.0f)
        return false;

    // Forward = normalize(center - eye)
    float fx = center[0] - eye[0];
    float fy = center[1] - eye[1];
    float fz = center[2] - eye[2];
    const float fl = std::sqrt(fx * fx + fy * fy + fz * fz);
    if (fl < 1e-9f)
        return false;
    fx /= fl; fy /= fl; fz /= fl;

    // Right = normalize(cross(forward, up))
    float rx = fy * up[2] - fz * up[1];
    float ry = fz * up[0] - fx * up[2];
    float rz = fx * up[1] - fy * up[0];
    const float rl = std::sqrt(rx * rx + ry * ry + rz * rz);
    if (rl < 1e-9f)
        return false;
    rx /= rl; ry /= rl; rz /= rl;

    // Up' = cross(right, forward)
    const float ux = ry * fz - rz * fy;
    const float uy = rz * fx - rx * fz;
    const float uz = rx * fy - ry * fx;

    const float focal = (viewH * 0.5f)
        / std::tan(fovDeg * 3.14159265358979323846f / 360.0f);

    const float dx = pt[0] - eye[0];
    const float dy = pt[1] - eye[1];
    const float dz = pt[2] - eye[2];
    const float z = dx * fx + dy * fy + dz * fz;   // depth along view axis
    if (z < 0.001f)
        return false;                              // behind the camera

    const float x = dx * rx + dy * ry + dz * rz;   // right
    const float y = dx * ux + dy * uy + dz * uz;   // up

    screenX = viewW * 0.5f + x * focal / z;
    screenY = viewH * 0.5f - y * focal / z;        // screen y grows downward
    return true;
}

} // namespace PointCloudUtils
