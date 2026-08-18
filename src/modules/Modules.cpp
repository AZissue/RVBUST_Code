#include "Modules.h"

#include "acquisition/LoadPlyModule.h"
#include "display/Display3DModule.h"
#include "fit/FitCircleModule.h"
#include "fit/FitLineModule.h"
#include "fit/FitPlaneModule.h"
#include "io/SavePlyModule.h"
#include "measure/BoundingBoxMeasureModule.h"
#include "measure/CircleMeasureModule.h"
#include "measure/PlaneToPlaneModule.h"
#include "measure/PointToPlaneDistanceModule.h"
#include "preprocess/BoxRoiModule.h"
#include "preprocess/StatisticalDenoiseModule.h"
#include "preprocess/VoxelDownsampleModule.h"
#include "core/ModuleRegistry.h"

namespace rvc {

void registerBuiltinModules()
{
    static bool done = false;
    if (done)
        return;
    done = true;

    auto& reg = ModuleRegistry::instance();
    // 采集
    reg.reg<LoadPlyModule>(LoadPlyModule::kTypeId, "采集", "加载PLY点云");
    // 预处理
    reg.reg<BoxRoiModule>(BoxRoiModule::kTypeId, "预处理", "ROI裁剪");
    reg.reg<VoxelDownsampleModule>(VoxelDownsampleModule::kTypeId, "预处理", "体素降采样");
    reg.reg<StatisticalDenoiseModule>(StatisticalDenoiseModule::kTypeId, "预处理", "统计去噪");
    // 拟合
    reg.reg<FitPlaneModule>(FitPlaneModule::kTypeId, "拟合", "平面拟合");
    reg.reg<FitLineModule>(FitLineModule::kTypeId, "拟合", "直线拟合");
    reg.reg<FitCircleModule>(FitCircleModule::kTypeId, "拟合", "圆拟合");
    // 测量
    reg.reg<PointToPlaneDistanceModule>(PointToPlaneDistanceModule::kTypeId, "测量", "点面距离");
    reg.reg<PlaneToPlaneModule>(PlaneToPlaneModule::kTypeId, "测量", "面面夹角/间距");
    reg.reg<BoundingBoxMeasureModule>(BoundingBoxMeasureModule::kTypeId, "测量", "包围盒尺寸");
    reg.reg<CircleMeasureModule>(CircleMeasureModule::kTypeId, "测量", "圆直径");
    // 显示
    reg.reg<Display3DModule>(Display3DModule::kTypeId, "显示", "3D显示");
    // IO
    reg.reg<SavePlyModule>(SavePlyModule::kTypeId, "IO", "保存PLY点云");
}

} // namespace rvc
