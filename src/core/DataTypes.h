#pragma once

// 核心数据类型定义：模块端口上传输的类型化数据。
// core 层不依赖 QWidget，可无头运行。
// 单位约定：长度一律为米（RVC 惯例），角度为度。

#include <memory>
#include <string>
#include <variant>

#include <Eigen/Dense>
#include <pcl/point_cloud.h>
#include <pcl/point_types.h>

namespace rvc {

// 点云：PCL XYZ 点云智能指针
using PointCloud = pcl::PointCloud<pcl::PointXYZ>::Ptr;

// 图像占位类型（M0 不引入 OpenCV，UI 层图像统一用 QImage）
struct Image {
    int width = 0;
    int height = 0;
};

// 平面：ax + by + cz + d = 0，(a,b,c) 为单位法线
struct Plane3D {
    float a = 0.0f, b = 0.0f, c = 1.0f, d = 0.0f;

    // 点（带符号）到平面距离（法线已单位化）
    float signedDistance(float x, float y, float z) const { return a * x + b * y + c * z + d; }

    // 使法线朝向与参考方向一致（保证同一平面的表示唯一）
    void alignWith(const Eigen::Vector3f& ref)
    {
        if (a * ref.x() + b * ref.y() + c * ref.z() < 0.0f) {
            a = -a;
            b = -b;
            c = -c;
            d = -d;
        }
    }
};

// 直线：过点 point，单位方向 direction
struct Line3D {
    Eigen::Vector3f point{0, 0, 0};
    Eigen::Vector3f direction{1, 0, 0};
};

// 空间圆：圆心 center、所在平面单位法线 normal、半径 radius（米）
struct Circle3D {
    Eigen::Vector3f center{0, 0, 0};
    Eigen::Vector3f normal{0, 0, 1};
    float radius = 0.0f;
};

// 盒式 ROI：轴对齐包围盒（米）。valid=false 表示未设置（不裁剪）。
// is2D=true 时仅约束 x/y（平面矩形），z 方向视为无限；此时 z 范围参数仍保存为 ±1e9。
struct RoiBox {
    Eigen::Vector3f min{-1e9f, -1e9f, -1e9f};
    Eigen::Vector3f max{1e9f, 1e9f, 1e9f};
    bool valid = false;
    bool is2D = false;

    static RoiBox fromMinMax(const Eigen::Vector3f& lo, const Eigen::Vector3f& hi,
                             bool is2D = false)
    {
        RoiBox r;
        r.min = lo;
        r.max = hi;
        r.valid = true;
        r.is2D = is2D;
        return r;
    }

    bool contains2D(float x, float y) const
    {
        return x >= min.x() && x <= max.x() && y >= min.y() && y <= max.y();
    }

    bool contains(float x, float y, float z) const
    {
        if (is2D)
            return contains2D(x, y);
        return contains2D(x, y) && z >= min.z() && z <= max.z();
    }
};

// 端口数据类型标签
enum class DataType {
    PointCloud,
    Image,
    Pose,    // Eigen::Matrix4d 刚体变换
    Scalar,  // double
    String,
    Plane,   // Plane3D
    Line,    // Line3D
    Circle,  // Circle3D
    Roi      // RoiBox
};

// 端口值：类型标签 + 变体数据
using DataVariant = std::variant<std::monostate, PointCloud, Image, Eigen::Matrix4d, double,
                                 std::string, Plane3D, Line3D, Circle3D, RoiBox>;

struct PortValue {
    DataType type = DataType::String;
    DataVariant data;

    bool isValid() const { return !std::holds_alternative<std::monostate>(data); }

    template <typename T>
    const T* get() const { return std::get_if<T>(&data); }
};

inline const char* dataTypeName(DataType t)
{
    switch (t) {
    case DataType::PointCloud: return "PointCloud";
    case DataType::Image:      return "Image";
    case DataType::Pose:       return "Pose";
    case DataType::Scalar:     return "Scalar";
    case DataType::String:     return "String";
    case DataType::Plane:      return "Plane";
    case DataType::Line:       return "Line";
    case DataType::Circle:     return "Circle";
    case DataType::Roi:        return "Roi";
    }
    return "Unknown";
}

// 便捷构造：带类型的端口值
template <typename T>
PortValue makePortValue(DataType t, T v)
{
    PortValue pv;
    pv.type = t;
    pv.data = std::move(v);
    return pv;
}

} // namespace rvc
