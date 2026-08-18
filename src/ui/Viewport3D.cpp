#include "Viewport3D.h"

#include <QHBoxLayout>
#include <QLabel>
#include <QSpinBox>
#include <QToolButton>
#include <QVBoxLayout>

#include <QVTKOpenGLNativeWidget.h>
#include <pcl/common/common.h>
#include <vtkActor.h>
#include <vtkBoxRepresentation.h>
#include <vtkBoxWidget2.h>
#include <vtkCommand.h>
#include <vtkGenericOpenGLRenderWindow.h>
#include <vtkInteractorStyleTrackballCamera.h>
#include <vtkNew.h>
#include <vtkPolyDataMapper.h>
#include <vtkProperty.h>
#include <vtkRenderWindowInteractor.h>
#include <vtkRenderer.h>
#include <vtkTransform.h>

namespace rvc {
namespace {

// 由法线构造一对正交基（用于平面/圆的绘制）
void orthonormalBasis(const Eigen::Vector3f& n, Eigen::Vector3f& u, Eigen::Vector3f& v)
{
    const Eigen::Vector3f ref = std::fabs(n.z()) < 0.9f ? Eigen::Vector3f(0, 0, 1)
                                                        : Eigen::Vector3f(1, 0, 0);
    u = n.cross(ref).normalized();
    v = n.cross(u).normalized();
}

} // namespace

Viewport3D::Viewport3D(QWidget* parent) : QWidget(parent)
{
    // 顶部工具条：重置视角 / 编辑ROI / 点大小
    auto* resetBtn = new QToolButton(this);
    resetBtn->setText(QStringLiteral("重置视角"));
    editRoiButton_ = new QToolButton(this);
    editRoiButton_->setText(QStringLiteral("编辑ROI"));
    editRoiButton_->setCheckable(true);
    auto* sizeLabel = new QLabel(QStringLiteral("点大小"), this);
    pointSizeSpin_ = new QSpinBox(this);
    pointSizeSpin_->setRange(1, 10);
    pointSizeSpin_->setValue(1);

    auto* toolbar = new QHBoxLayout;
    toolbar->setContentsMargins(4, 2, 4, 2);
    toolbar->addWidget(resetBtn);
    toolbar->addWidget(editRoiButton_);
    toolbar->addStretch();
    toolbar->addWidget(sizeLabel);
    toolbar->addWidget(pointSizeSpin_);

    qvtkWidget_ = new QVTKOpenGLNativeWidget(this);

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->addLayout(toolbar);
    layout->addWidget(qvtkWidget_, 1);

    // PCLVisualizer 复用 widget 的 renderWindow（PCL 官方 Qt 教程写法）
    renderWindow_ = vtkSmartPointer<vtkGenericOpenGLRenderWindow>::New();
    vtkNew<vtkRenderer> renderer;
    viewer_ = pcl::visualization::PCLVisualizer::Ptr(
        new pcl::visualization::PCLVisualizer(renderer, renderWindow_, "viewport3d", false));
    viewer_->setBackgroundColor(0.059, 0.059, 0.075);  // 与主题 surface-0 (#0F0F13) 一致
    viewer_->addCoordinateSystem(0.1);  // 点云单位米
    viewer_->initCameraParameters();
    qvtkWidget_->setRenderWindow(renderWindow_);

    // 相机交互样式（轨迹球）
    vtkNew<vtkInteractorStyleTrackballCamera> trackball;
    qvtkWidget_->interactor()->SetInteractorStyle(trackball);

    // ROI box widget（默认隐藏，编辑模式时开启）
    boxRep_ = vtkSmartPointer<vtkBoxRepresentation>::New();
    boxRep_->SetPlaceFactor(1.0);
    boxRep_->GetOutlineProperty()->SetColor(0.1, 1.0, 0.3);
    boxRep_->GetOutlineProperty()->SetLineWidth(2.0);
    boxRep_->GetHandleProperty()->SetColor(0.1, 1.0, 0.3);
    boxRep_->GetSelectedHandleProperty()->SetColor(1.0, 0.85, 0.1);
    boxRep_->GetFaceProperty()->SetOpacity(0.15);
    boxRep_->GetFaceProperty()->SetColor(0.1, 1.0, 0.3);

    boxWidget_ = vtkSmartPointer<vtkBoxWidget2>::New();
    boxWidget_->SetRepresentation(boxRep_);
    boxWidget_->SetInteractor(qvtkWidget_->interactor());
    boxWidget_->RotationEnabledOff();   // 保持轴对齐
    boxWidget_->TranslationEnabledOn();
    boxWidget_->ScalingEnabledOn();
    boxWidget_->MoveFacesEnabledOn();
    boxWidget_->AddObserver(vtkCommand::InteractionEvent, this,
                            &Viewport3D::onBoxWidgetInteraction);

    connect(resetBtn, &QToolButton::clicked, this, [this] { resetCamera(); });
    connect(pointSizeSpin_, QOverload<int>::of(&QSpinBox::valueChanged), this, [this](int v) {
        viewer_->setPointCloudRenderingProperties(
            pcl::visualization::PCL_VISUALIZER_POINT_SIZE, v, "cloud");
        renderWindow_->Render();
    });
    connect(editRoiButton_, &QToolButton::toggled, this, &Viewport3D::setRoiEditing);
}

Viewport3D::~Viewport3D() = default;

void Viewport3D::resetCamera()
{
    viewer_->resetCamera();
    renderWindow_->Render();
}

void Viewport3D::setPointCloud(PointCloud cloud, DisplayOverlays overlays)
{
    if (!cloud || cloud->empty())
        return;

    cloud_ = std::move(cloud);
    overlays_ = std::move(overlays);

    if (!viewer_->updatePointCloud<pcl::PointXYZ>(cloud_, "cloud"))
        viewer_->addPointCloud<pcl::PointXYZ>(cloud_, "cloud");

    clearOverlays();
    drawOverlays(overlays_);

    viewer_->resetCamera();
    renderWindow_->Render();

    // 若正在编辑 ROI 且尚未初始化 box，则以点云包围盒初始化
    if (roiEditing_ && !currentRoi_.valid) {
        pcl::PointXYZ minPt, maxPt;
        pcl::getMinMax3D(*cloud_, minPt, maxPt);
        currentRoi_ = RoiBox::fromMinMax({minPt.x, minPt.y, minPt.z},
                                         {maxPt.x, maxPt.y, maxPt.z});
        updateBoxWidgetFromRoi();
    }
}

void Viewport3D::clearOverlays()
{
    for (const auto& id : overlayShapeIds_)
        viewer_->removeShape(id);
    overlayShapeIds_.clear();
}

void Viewport3D::drawOverlays(const DisplayOverlays& overlays)
{
    if (!overlays.plane && !overlays.line && !overlays.circle)
        return;

    // 以点云包围盒对角线为几何图形的绘制尺度
    pcl::PointXYZ minPt, maxPt;
    pcl::getMinMax3D(*cloud_, minPt, maxPt);
    const float diag = (Eigen::Vector3f(maxPt.x, maxPt.y, maxPt.z) -
                        Eigen::Vector3f(minPt.x, minPt.y, minPt.z))
                           .norm();
    const float extent = std::max(diag, 0.01f);

    // 平面：按点云尺度画网格线（黄色），示意平面位置与朝向
    if (overlays.plane) {
        const Plane3D& pl = *overlays.plane;
        const Eigen::Vector3f n(pl.a, pl.b, pl.c);
        const Eigen::Vector3f origin = -pl.d * n;  // 平面上距原点最近的点
        Eigen::Vector3f u, v;
        orthonormalBasis(n, u, v);

        const int grid = 2;  // 每侧 2 格
        for (int i = -grid; i <= grid; ++i) {
            const float t = extent / 2.0f * i / grid;
            const Eigen::Vector3f c1 = origin + u * t;
            const Eigen::Vector3f c2 = origin + v * t;
            pcl::PointXYZ a1(c1.x() - v.x() * extent / 2, c1.y() - v.y() * extent / 2,
                             c1.z() - v.z() * extent / 2);
            pcl::PointXYZ b1(c1.x() + v.x() * extent / 2, c1.y() + v.y() * extent / 2,
                             c1.z() + v.z() * extent / 2);
            pcl::PointXYZ a2(c2.x() - u.x() * extent / 2, c2.y() - u.y() * extent / 2,
                             c2.z() - u.z() * extent / 2);
            pcl::PointXYZ b2(c2.x() + u.x() * extent / 2, c2.y() + u.y() * extent / 2,
                             c2.z() + u.z() * extent / 2);
            std::string id1 = "plane_u_" + std::to_string(i + grid);
            std::string id2 = "plane_v_" + std::to_string(i + grid);
            viewer_->addLine(a1, b1, 1.0, 0.85, 0.1, id1);
            viewer_->addLine(a2, b2, 1.0, 0.85, 0.1, id2);
            overlayShapeIds_.push_back(id1);
            overlayShapeIds_.push_back(id2);
        }
    }

    // 直线：沿方向延长画线（青色）
    if (overlays.line) {
        const Line3D& ln = *overlays.line;
        const Eigen::Vector3f p1 = ln.point - ln.direction * extent;
        const Eigen::Vector3f p2 = ln.point + ln.direction * extent;
        viewer_->addLine(pcl::PointXYZ(p1.x(), p1.y(), p1.z()),
                         pcl::PointXYZ(p2.x(), p2.y(), p2.z()), 0.1, 0.9, 0.9, "overlay_line");
        overlayShapeIds_.push_back("overlay_line");
    }

    // 圆：64 段折线圆环（品红）+ 圆心小球
    if (overlays.circle) {
        const Circle3D& ci = *overlays.circle;
        Eigen::Vector3f u, v;
        orthonormalBasis(ci.normal, u, v);
        constexpr int kSeg = 64;
        constexpr float kTwoPi = 6.28318530718f;
        for (int i = 0; i < kSeg; ++i) {
            const float a1 = kTwoPi * i / kSeg;
            const float a2 = kTwoPi * (i + 1) / kSeg;
            const Eigen::Vector3f p1 = ci.center + ci.radius * (u * std::cos(a1) + v * std::sin(a1));
            const Eigen::Vector3f p2 = ci.center + ci.radius * (u * std::cos(a2) + v * std::sin(a2));
            std::string id = "circle_seg_" + std::to_string(i);
            viewer_->addLine(pcl::PointXYZ(p1.x(), p1.y(), p1.z()),
                             pcl::PointXYZ(p2.x(), p2.y(), p2.z()), 1.0, 0.2, 0.8, id);
            overlayShapeIds_.push_back(id);
        }
        viewer_->addSphere(pcl::PointXYZ(ci.center.x(), ci.center.y(), ci.center.z()),
                           ci.radius * 0.02, 1.0, 0.2, 0.8, "circle_center");
        overlayShapeIds_.push_back("circle_center");
    }
}

void Viewport3D::setRoi(const RoiBox& roi)
{
    if (updatingBoxWidget_)
        return;
    currentRoi_ = roi;
    updateBoxWidgetFromRoi();
}

void Viewport3D::setRoiEditing(bool on)
{
    roiEditing_ = on;
    editRoiButton_->setChecked(on);

    if (on) {
        if (!currentRoi_.valid && cloud_ && !cloud_->empty()) {
            pcl::PointXYZ minPt, maxPt;
            pcl::getMinMax3D(*cloud_, minPt, maxPt);
            currentRoi_ = RoiBox::fromMinMax({minPt.x, minPt.y, minPt.z},
                                             {maxPt.x, maxPt.y, maxPt.z});
        }
        updateBoxWidgetFromRoi();
        boxWidget_->On();
    } else {
        boxWidget_->Off();
    }
    renderWindow_->Render();
}

void Viewport3D::updateBoxWidgetFromRoi()
{
    if (!currentRoi_.valid || !boxRep_)
        return;

    updatingBoxWidget_ = true;

    if (!hasInitialBounds_) {
        initialBounds_[0] = currentRoi_.min.x();
        initialBounds_[1] = currentRoi_.max.x();
        initialBounds_[2] = currentRoi_.min.y();
        initialBounds_[3] = currentRoi_.max.y();
        initialBounds_[4] = currentRoi_.min.z();
        initialBounds_[5] = currentRoi_.max.z();
        boxRep_->PlaceWidget(initialBounds_);
        hasInitialBounds_ = true;
    } else {
        // 用 transform 把初始 bounds 映射到当前 ROI
        const double sx = (initialBounds_[1] - initialBounds_[0]) > 1e-12
                              ? (currentRoi_.max.x() - currentRoi_.min.x()) /
                                    (initialBounds_[1] - initialBounds_[0])
                              : 1.0;
        const double sy = (initialBounds_[3] - initialBounds_[2]) > 1e-12
                              ? (currentRoi_.max.y() - currentRoi_.min.y()) /
                                    (initialBounds_[3] - initialBounds_[2])
                              : 1.0;
        const double sz = (initialBounds_[5] - initialBounds_[4]) > 1e-12
                              ? (currentRoi_.max.z() - currentRoi_.min.z()) /
                                    (initialBounds_[5] - initialBounds_[4])
                              : 1.0;
        const double tx = currentRoi_.min.x() - initialBounds_[0] * sx;
        const double ty = currentRoi_.min.y() - initialBounds_[2] * sy;
        const double tz = currentRoi_.min.z() - initialBounds_[4] * sz;

        vtkNew<vtkTransform> t;
        t->PostMultiply();
        t->Identity();
        t->Translate(tx, ty, tz);
        t->Scale(sx, sy, sz);
        boxRep_->SetTransform(t);
    }

    updatingBoxWidget_ = false;
    renderWindow_->Render();
}

void Viewport3D::onBoxWidgetInteraction()
{
    if (updatingBoxWidget_ || !boxRep_ || !hasInitialBounds_)
        return;

    vtkNew<vtkTransform> t;
    boxRep_->GetTransform(t);

    const double* scale = t->GetScale();
    const double* pos = t->GetPosition();

    RoiBox roi;
    roi.min = Eigen::Vector3f(
        static_cast<float>(initialBounds_[0] * scale[0] + pos[0]),
        static_cast<float>(initialBounds_[2] * scale[1] + pos[1]),
        static_cast<float>(initialBounds_[4] * scale[2] + pos[2]));
    roi.max = Eigen::Vector3f(
        static_cast<float>(initialBounds_[1] * scale[0] + pos[0]),
        static_cast<float>(initialBounds_[3] * scale[1] + pos[1]),
        static_cast<float>(initialBounds_[5] * scale[2] + pos[2]));
    roi.valid = true;
    roi.is2D = false;

    currentRoi_ = roi;
    if (roiPickedCallback)
        roiPickedCallback(roi);
}

} // namespace rvc
