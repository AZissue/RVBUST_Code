#pragma once

// RVC SDK 封装（M0 骨架）。
// M0 不连接真机，本模块保证编译链接通过并提供 M1 采集节点的接口地基。
//
// RVC SDK 已知陷阱（来自现场经验，务必遵守）：
//  1. 修改 CaptureOptions 前必须先 Load（X1::LoadCaptureOptions），否则设置不生效；
//  2. SDK 不阻止同一台相机被多次 Open —— 应用层必须按 SN 查重（本类 openBySn 已预留查重）；
//  3. PointMap 内存数据单位是米（double，行主序 x,y,z 连续），Save 存盘时才选米/毫米；
//  4. SaveImage / PointMap::Save 不支持中文路径（写文件前需检查路径或改用 ASCII 临时文件）。

#include <string>
#include <vector>

#include <pcl/point_cloud.h>
#include <pcl/point_types.h>

#include <RVC/RVC.h>

namespace rvc {

// 设备摘要信息（供 UI 设备列表展示）
struct RvcDeviceSummary {
    std::string name;
    std::string sn;
    std::string port;      // USB / GIGE
    std::string firmware;
};

// SystemInit / SystemShutdown 的 RAII 守卫（进程内引用计数）。
// 任何使用 RVC SDK 的对象（采集模块、设备枚举）都应先持有一个 RvcSystemGuard。
class RvcSystemGuard {
public:
    RvcSystemGuard();
    ~RvcSystemGuard();

    RvcSystemGuard(const RvcSystemGuard&) = delete;
    RvcSystemGuard& operator=(const RvcSystemGuard&) = delete;

    bool isValid() const { return valid_; }

private:
    bool valid_ = false;
};

// RVC 相机封装骨架。M0 仅实现枚举与转换；Open/Capture 在 M1 接入。
class RvcCamera {
public:
    RvcCamera() = default;
    ~RvcCamera();

    RvcCamera(const RvcCamera&) = delete;
    RvcCamera& operator=(const RvcCamera&) = delete;

    // 枚举在线设备（SystemListDevices），需要调用方持有 RvcSystemGuard
    static std::vector<RvcDeviceSummary> listDevices();

    // 当前已按 SN 打开的相机列表（应用层查重，陷阱 2 的兜底）
    static bool isSnInUse(const std::string& sn);

    // 按 SN 打开相机（M1 实现；重复 SN 直接失败）
    bool openBySn(const std::string& sn);
    void close();
    bool isOpen() const { return opened_; }
    const std::string& sn() const { return sn_; }

    // 点云转换：PointMap（W×H 组织结构，行主序 double x,y,z，单位米）
    // → pcl::PointCloud<PointXYZ>，保留 height/width 组织结构，is_dense = false
    // （PointMap 中无效点坐标为 0 或 NaN，由下游滤波处理）
    static pcl::PointCloud<pcl::PointXYZ>::Ptr pointMapToPointCloud(const RVC::PointMap& pm);

private:
    RVC::X1 x1_;
    bool opened_ = false;
    std::string sn_;
};

} // namespace rvc
