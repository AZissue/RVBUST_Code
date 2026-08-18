#include "StatisticalDenoiseModule.h"

#include <pcl/filters/statistical_outlier_removal.h>

#include "modules/CloudUtils.h"

namespace rvc {

bool StatisticalDenoiseModule::execute(ModuleContext& ctx)
{
    const PointCloud* cloudIn = ctx.input("cloud").get<PointCloud>();
    if (!cloudIn || !*cloudIn || (*cloudIn)->empty()) {
        ctx.log("no point cloud on input port 'cloud'");
        return false;
    }

    const int meanK = getInt("meanK");
    const double stddevMul = getDouble("stddevMul");

    pcl::StatisticalOutlierRemoval<pcl::PointXYZ> sor;
    sor.setInputCloud(removeNaNIfNeeded(*cloudIn));
    sor.setMeanK(meanK);
    sor.setStddevMulThresh(stddevMul);
    auto out = std::make_shared<pcl::PointCloud<pcl::PointXYZ>>();
    sor.filter(*out);

    ctx.log("denoised " + std::to_string((*cloudIn)->size()) + " -> " +
            std::to_string(out->size()) + " points (meanK " + std::to_string(meanK) +
            ", stddevMul " + std::to_string(stddevMul) + ")");
    if (out->empty()) {
        ctx.log("denoise result is empty");
        return false;
    }

    ctx.setOutput("cloud", makePortValue(DataType::PointCloud, PointCloud(out)));
    return true;
}

} // namespace rvc
