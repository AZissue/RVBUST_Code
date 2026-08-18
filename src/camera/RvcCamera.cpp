#include "RvcCamera.h"

#include <atomic>
#include <mutex>
#include <set>

namespace rvc {
namespace {

// SystemInit/SystemShutdown 引用计数（陷阱无关，SDK 要求进程级配对调用）
std::atomic<int> g_systemRefCount{0};

// 已打开相机 SN 登记表（陷阱 2：SDK 不阻止同一相机多次 Open，应用层按 SN 查重）
std::mutex g_snMutex;
std::set<std::string> g_snRegistry;

} // namespace

RvcSystemGuard::RvcSystemGuard()
{
    if (g_systemRefCount.fetch_add(1) == 0)
        valid_ = RVC::SystemInit();
    else
        valid_ = true;
}

RvcSystemGuard::~RvcSystemGuard()
{
    if (g_systemRefCount.fetch_sub(1) == 1)
        RVC::SystemShutdown();
}

RvcCamera::~RvcCamera()
{
    close();
}

std::vector<RvcDeviceSummary> RvcCamera::listDevices()
{
    std::vector<RvcDeviceSummary> out;

    // 先探测数量，再取完整列表
    size_t actual = 0;
    if (RVC::SystemListDevices(nullptr, 0, &actual, RVC::SystemListDeviceType::All) < 0 || actual == 0)
        return out;

    std::vector<RVC::Device> devices(actual);
    if (RVC::SystemListDevices(devices.data(), devices.size(), &actual,
                               RVC::SystemListDeviceType::All) < 0)
        return out;

    for (size_t i = 0; i < actual; ++i) {
        RVC::DeviceInfo info{};
        if (devices[i].GetDeviceInfo(&info)) {
            RvcDeviceSummary s;
            s.name = info.name;
            s.sn = info.sn;
            s.port = info.port;
            s.firmware = info.firmware_version;
            out.push_back(std::move(s));
        }
    }
    // Device 数组由 SDK 管理生命周期，无需逐个 Destroy
    return out;
}

bool RvcCamera::isSnInUse(const std::string& sn)
{
    std::lock_guard<std::mutex> lock(g_snMutex);
    return g_snRegistry.count(sn) > 0;
}

bool RvcCamera::openBySn(const std::string& sn)
{
    // 陷阱 2：应用层按 SN 查重
    {
        std::lock_guard<std::mutex> lock(g_snMutex);
        if (g_snRegistry.count(sn) > 0)
            return false;
    }

    // M0 不连接真机：M1 在此实现 X1::Create + Open，成功后登记 SN。
    // if (x1_.Open()) { ... g_snRegistry.insert(sn); opened_ = true; }
    (void)sn;
    return false;
}

void RvcCamera::close()
{
    if (opened_) {
        x1_.Close();
        std::lock_guard<std::mutex> lock(g_snMutex);
        g_snRegistry.erase(sn_);
        opened_ = false;
        sn_.clear();
    }
}

pcl::PointCloud<pcl::PointXYZ>::Ptr RvcCamera::pointMapToPointCloud(const RVC::PointMap& pm)
{
    auto cloud = std::make_shared<pcl::PointCloud<pcl::PointXYZ>>();
    if (!pm.IsValid())
        return cloud;

    const RVC::Size size = pm.GetSize();
    const double* data = pm.GetPointDataConstPtr();
    if (!data || size.cols <= 0 || size.rows <= 0)
        return cloud;

    // 保留 W×H 组织结构；内存数据单位米，行主序 x,y,z 连续（陷阱 3）
    cloud->width = static_cast<std::uint32_t>(size.cols);
    cloud->height = static_cast<std::uint32_t>(size.rows);
    cloud->is_dense = false;
    cloud->points.resize(static_cast<size_t>(size.cols) * static_cast<size_t>(size.rows));

    for (int r = 0; r < size.rows; ++r) {
        for (int c = 0; c < size.cols; ++c) {
            const double* p = data + 3 * (static_cast<size_t>(r) * size.cols + c);
            auto& pt = cloud->points[static_cast<size_t>(r) * size.cols + c];
            pt.x = static_cast<float>(p[0]);
            pt.y = static_cast<float>(p[1]);
            pt.z = static_cast<float>(p[2]);
        }
    }
    return cloud;
}

} // namespace rvc
