#include "logic/PixelTo3DService.h"

#include <cstdio>
#include <string>

// Shared "pixel -> 3D point" service used by both the offline tool page
// (src/ui/ToolsPanel.cpp) and the online click-to-pick path.  It owns the one
// and only dispatch over the supported point-cloud layouts; callers just fill
// in a Source and render the returned Query.
namespace PixelTo3DService {

namespace {

bool inImage(int px, int py, int w, int h)
{
    return px >= 0 && py >= 0 && px < w && py < h;
}

Query okQuery(const std::array<double, 3>& pt)
{
    Query q;
    q.status = Status::Ok;
    q.pointMm = pt;
    return q;
}

Query failQuery(Status status)
{
    Query q;
    q.status = status;
    return q;
}

// Shared tail of the index-based paths: a stored index plus an in-range pixel
// is "Ok" unless the point itself is missing or invalid.
Query fromIndex(const std::vector<int>& index, int w, int h,
                const std::vector<double>& xyz, int px, int py)
{
    std::array<double, 3> pt{};
    if (PixelTo3DTools::queryIndex(index, w, h, px, py, xyz, pt))
        return okQuery(pt);
    return failQuery(inImage(px, py, w, h) ? Status::NoPointAtPixel
                                           : Status::OutOfRange);
}

} // namespace

bool hasData(const Source& src)
{
    if (src.xyzMm == nullptr || src.xyzMm->empty())
        return false;
    return src.imageWidth > 0 && src.imageHeight > 0;
}

Query query(const Source& src, int pixelX, int pixelY)
{
    if (!hasData(src))
        return failQuery(Status::NoData);

    const std::vector<double>& xyz = *src.xyzMm;
    const int w = src.imageWidth;
    const int h = src.imageHeight;

    // (2) RVC correspond map: 3D point index -> pixel.
    if (src.correspondMap != nullptr) {
        std::vector<int> index;
        PixelTo3DTools::buildCorrespondIndex(*src.correspondMap, w, h, index);
        return fromIndex(index, w, h, xyz, pixelX, pixelY);
    }

    // (3) Aligned point cloud (one point per pixel): direct index lookup.
    if (xyz.size() == static_cast<std::size_t>(w) * static_cast<std::size_t>(h) * 3) {
        std::size_t idx = 0;
        if (!PixelTo3DTools::alignedIndex(pixelX, pixelY, w, h, idx))
            return failQuery(Status::OutOfRange);
        std::array<double, 3> pt{};
        if (PixelTo3DTools::pointAt(xyz, idx, pt))
            return okQuery(pt);
        return failQuery(Status::NoPointAtPixel);
    }

    // (4) Non-aligned cloud: project every point through the camera model.
    if (!src.hasIntrinsics)
        return failQuery(Status::MissingIntrinsics);
    if (src.intrinsics.fx <= 0.0 || src.intrinsics.fy <= 0.0)
        return failQuery(Status::InvalidIntrinsics);

    std::vector<int> index;
    PixelTo3DTools::buildProjectedIndex(
        xyz, src.extrinsics16, src.intrinsics, w, h, index);
    return fromIndex(index, w, h, xyz, pixelX, pixelY);
}

std::string statusText(Status status)
{
    switch (status) {
    case Status::Ok:
        return "找到 3D 点";
    case Status::NoData:
        return "点云为空或图像尺寸非法";
    case Status::MissingIntrinsics:
        return "点云与图像尺寸不一致，需要相机内参";
    case Status::InvalidIntrinsics:
        return "内参无效（fx/fy 必须大于 0）";
    case Status::OutOfRange:
        return "像素坐标超出图像范围";
    case Status::NoPointAtPixel:
        return "该像素无有效 3D 点（背景或无效深度）";
    }
    return "未知状态";
}

std::string formatPoint(const std::array<double, 3>& pointMm)
{
    char buf[128];
    std::snprintf(buf, sizeof(buf), "%.3f, %.3f, %.3f",
                  pointMm[0], pointMm[1], pointMm[2]);
    return std::string(buf);
}

} // namespace PixelTo3DService
