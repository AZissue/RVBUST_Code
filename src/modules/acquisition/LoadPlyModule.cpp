#include "LoadPlyModule.h"

#include <cstring>

#include <pcl/PCLPointField.h>
#include <pcl/PCLPointCloud2.h>
#include <pcl/io/ply_io.h>

namespace rvc {
namespace {

// 将 PLY 加载为 PointXYZ。
// 不用 pcl::io::loadPLYFile<PointXYZ>：它对二进制 double 型 x/y/z 字段不做类型
// 转换（报 "Failed to find match for field" 并输出全零点）。先读入
// PCLPointCloud2 保留原始字段类型，再按字段原生类型（float/double）手动转换。
bool loadPlyAsPointXYZ(const std::string& path, pcl::PointCloud<pcl::PointXYZ>& cloud,
                       std::string* err)
{
    pcl::PCLPointCloud2 blob;
    pcl::PLYReader reader;
    if (reader.read(path, blob) < 0) {
        if (err) *err = "failed to load PLY file: " + path;
        return false;
    }

    // 定位 x/y/z 字段
    const pcl::PCLPointField* fields[3] = {nullptr, nullptr, nullptr};
    const char* names[3] = {"x", "y", "z"};
    for (int a = 0; a < 3; ++a) {
        for (const auto& f : blob.fields) {
            if (f.name == names[a]) {
                fields[a] = &f;
                break;
            }
        }
        if (!fields[a]) {
            if (err) *err = std::string("PLY file has no '") + names[a] + "' field: " + path;
            return false;
        }
        if (fields[a]->datatype != pcl::PCLPointField::FLOAT32 &&
            fields[a]->datatype != pcl::PCLPointField::FLOAT64) {
            if (err) *err = "unsupported PLY field datatype (only float/double): " + path;
            return false;
        }
    }

    cloud.width = blob.width;
    cloud.height = blob.height;
    cloud.is_dense = blob.is_dense;
    cloud.points.resize(static_cast<size_t>(blob.width) * blob.height);

    for (size_t i = 0; i < cloud.points.size(); ++i) {
        const std::uint8_t* base = blob.data.data() + i * blob.point_step;
        auto& pt = cloud.points[i];
        float* out[3] = {&pt.x, &pt.y, &pt.z};
        for (int a = 0; a < 3; ++a) {
            const std::uint8_t* src = base + fields[a]->offset;
            if (fields[a]->datatype == pcl::PCLPointField::FLOAT32) {
                float v;
                std::memcpy(&v, src, sizeof(v));
                *out[a] = v;
            } else {
                double v;
                std::memcpy(&v, src, sizeof(v));
                *out[a] = static_cast<float>(v);
            }
        }
    }
    return true;
}

} // namespace

bool LoadPlyModule::execute(ModuleContext& ctx)
{
    const std::string filePath = getString("filePath");
    if (filePath.empty()) {
        ctx.log("PLY file path is empty");
        return false;
    }

    auto cloud = std::make_shared<pcl::PointCloud<pcl::PointXYZ>>();
    std::string err;
    if (!loadPlyAsPointXYZ(filePath, *cloud, &err)) {
        ctx.log(err);
        return false;
    }
    if (cloud->empty()) {
        ctx.log("PLY file contains no points: " + filePath);
        return false;
    }

    ctx.log("loaded " + std::to_string(cloud->size()) + " points from " + filePath);

    // 输出非零点数量，便于快速发现字段未匹配（全零）等加载异常
    size_t nonZero = 0;
    for (const auto& p : cloud->points) {
        if (p.x != 0.0f || p.y != 0.0f || p.z != 0.0f)
            ++nonZero;
    }
    ctx.log("non-zero points: " + std::to_string(nonZero));
    if (nonZero == 0) {
        ctx.log("all points are zero, PLY field matching likely failed");
        return false;
    }

    ctx.setOutput("cloud", makePortValue(DataType::PointCloud, PointCloud(cloud)));
    return true;
}

} // namespace rvc
