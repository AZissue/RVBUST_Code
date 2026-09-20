#pragma once
#include <array>
#include <string>
#include <vector>
#include "logic/PixelTo3DTools.h"   // 复用其中的 Intrinsics（fx/fy/cx/cy）

namespace PixelTo3DService {

// 一帧数据 + 像素↔点云的对应关系。所有指针只在调用期间有效，不接管所有权。
struct Source {
    const std::vector<double>* xyzMm = nullptr;  // n*3，毫米；必须非空
    int imageWidth = 0;                          // 2D 图像宽（像素）
    int imageHeight = 0;                         // 2D 图像高（像素）
    PixelTo3DTools::Intrinsics intrinsics{};     // 非对齐点云需要
    bool hasIntrinsics = false;                  // 调用方是否提供了内参
    const double* extrinsics16 = nullptr;        // 4×4 行主序，可为 null（点云已在相机系）
    const std::vector<double>* correspondMap = nullptr;  // n*2（3D 点索引 → 像素），可为 null
};

enum class Status {
    Ok,                 // 找到 3D 点
    NoData,             // 点云为空 / 图像尺寸非法
    MissingIntrinsics,  // 点云与图像不对齐，但没给内参
    InvalidIntrinsics,  // 给了内参但 fx/fy <= 0
    OutOfRange,         // 像素坐标不在图像范围内
    NoPointAtPixel      // 该像素没有有效点（背景 / 无效深度）
};

struct Query {
    Status status = Status::NoData;
    std::array<double, 3> pointMm{};   // 仅 status == Ok 时有效
};

bool hasData(const Source& src);
Query query(const Source& src, int pixelX, int pixelY);
std::string statusText(Status status);
std::string formatPoint(const std::array<double, 3>& pointMm);
}
