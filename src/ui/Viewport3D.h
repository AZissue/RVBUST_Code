#pragma once

// 3D 视口（交互式）：QVTKOpenGLNativeWidget + vtkGenericOpenGLRenderWindow +
// pcl::visualization::PCLVisualizer（PCL 官方 Qt 教程写法）。
// 渲染用自编译的 VTK 9.2.2（带 GUISupportQt），与 PCL 预编译 DLL 同名 ABI 兼容。
//
// 功能：点云 + 几何叠加（平面网格/直线/圆）、鼠标旋转/缩放/平移、
// 重置视角、点大小、ROI 编辑（vtkBoxWidget2：拖动 box 位置、拖 handle 调整大小）。

#include <functional>

#include <QWidget>

#include <pcl/visualization/pcl_visualizer.h>
#include <vtkSmartPointer.h>

#include "core/DataTypes.h"
#include "modules/display/Display3DModule.h"

class QVTKOpenGLNativeWidget;
class QToolButton;
class QSpinBox;
class vtkGenericOpenGLRenderWindow;
class vtkBoxWidget2;
class vtkBoxRepresentation;

namespace rvc {

class Viewport3D : public QWidget {
    Q_OBJECT
public:
    explicit Viewport3D(QWidget* parent = nullptr);
    ~Viewport3D() override;

    // 刷新显示的点云与几何叠加（GUI 线程调用）
    void setPointCloud(PointCloud cloud, DisplayOverlays overlays = {});

    // 当前显示的点云（供 ROI 编辑弹窗预览）
    PointCloud cloud() const { return cloud_; }

    // ROI 编辑完成回调（MainWindow / RoiEditDialog 注入；GUI 线程触发）
    std::function<void(RoiBox)> roiPickedCallback;

    // 外部设置 ROI（RoiEditDialog spin box 编辑时同步到 3D box widget）
    void setRoi(const RoiBox& roi);
    // 进入/退出 ROI 编辑模式
    void setRoiEditing(bool on);
    bool roiEditing() const { return roiEditing_; }

private:
    void clearOverlays();
    void drawOverlays(const DisplayOverlays& overlays);
    void resetCamera();
    void updateBoxWidgetFromRoi();
    void onBoxWidgetInteraction();

    QVTKOpenGLNativeWidget* qvtkWidget_;
    QToolButton* editRoiButton_;
    QSpinBox* pointSizeSpin_;
    pcl::visualization::PCLVisualizer::Ptr viewer_;
    vtkSmartPointer<vtkGenericOpenGLRenderWindow> renderWindow_;
    vtkSmartPointer<vtkBoxWidget2> boxWidget_;
    vtkSmartPointer<vtkBoxRepresentation> boxRep_;

    PointCloud cloud_;
    DisplayOverlays overlays_;
    std::vector<std::string> overlayShapeIds_;  // 本次叠加的形状 id（供下次清除）

    RoiBox currentRoi_;
    bool roiEditing_ = false;
    bool updatingBoxWidget_ = false;  // 防止 setRoi → box widget → callback 循环

    // box widget 初始 bounds（PlaceWidget 的参考系，用于 transform 换算）
    double initialBounds_[6] = {0, 1, 0, 1, 0, 1};
    bool hasInitialBounds_ = false;
};

} // namespace rvc
