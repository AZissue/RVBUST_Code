#include "point_cloud_view.h"

#include "roi_selector.h"

#include <QLabel>
#include <QVBoxLayout>

#ifdef PCSEARCH_HAS_VTK
#include <vtkActor.h>
#include <vtkAxesActor.h>
#include <vtkCamera.h>
#include <vtkCellArray.h>
#include <vtkCubeSource.h>
#include <vtkDataSetMapper.h>
#include <vtkInteractorStyleTrackballCamera.h>
#include <vtkNew.h>
#include <vtkPoints.h>
#include <vtkPointData.h>
#include <vtkPolyData.h>
#include <vtkPolyDataMapper.h>
#include <vtkProperty.h>
#include <vtkRenderWindow.h>
#include <vtkRenderWindowInteractor.h>
#include <vtkRenderer.h>
#include <vtkTransform.h>
#include <vtkTransformPolyDataFilter.h>
#include <vtkUnsignedCharArray.h>
#include <QVTKOpenGLNativeWidget.h>
#endif

#include <algorithm>
#include <cmath>

namespace app {

PointCloudView::PointCloudView(QWidget* parent) : QWidget(parent) {
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
#ifdef PCSEARCH_HAS_VTK
    vtk_widget_ = new QVTKOpenGLNativeWidget(this);
    layout->addWidget(vtk_widget_);
    renderer_ = vtkRenderer::New();
    renderer_->SetBackground(0.16, 0.16, 0.18);
    vtk_widget_->renderWindow()->AddRenderer(renderer_);
    vtkNew<vtkInteractorStyleTrackballCamera> style;
    vtk_widget_->renderWindow()->GetInteractor()->SetInteractorStyle(style);
    roi_selector_ = new RoiSelector(this);
    roi_selector_->attach(vtk_widget_->renderWindow()->GetInteractor());
    connect(roi_selector_, &RoiSelector::roiChanged, this,
            &PointCloudView::roiEdited);
    connect(roi_selector_, &RoiSelector::roiEditFinished, this,
            &PointCloudView::roiEditFinished);
#else
    placeholder_ = new QLabel(tr("3D View (VTK not built yet)"), this);
    placeholder_->setAlignment(Qt::AlignCenter);
    layout->addWidget(placeholder_);
#endif
}

void PointCloudView::clearView() {
#ifdef PCSEARCH_HAS_VTK
    enableRoiEdit(false);
    hideRoiBox();
    clearCloudActors();
    vtk_widget_->renderWindow()->Render();
#endif
}

void PointCloudView::enableRoiEdit(bool on, const double bounds[6]) {
    if (!on || !bounds) {
        enableRoiEditObb(on, nullptr, nullptr, nullptr);
        return;
    }
    const double center[3] = {0.5 * (bounds[0] + bounds[1]),
                              0.5 * (bounds[2] + bounds[3]),
                              0.5 * (bounds[4] + bounds[5])};
    const double half[3] = {0.5 * (bounds[1] - bounds[0]),
                            0.5 * (bounds[3] - bounds[2]),
                            0.5 * (bounds[5] - bounds[4])};
    const double rot[3] = {0.0, 0.0, 0.0};
    enableRoiEditObb(on, center, half, rot);
}

void PointCloudView::enableRoiEditObb(bool on, const double center[3],
                                      const double half[3],
                                      const double rot_deg[3]) {
#ifdef PCSEARCH_HAS_VTK
    if (!roi_selector_) return;
    roi_editing_ = on;
    if (on) {
        // The vtkBoxWidget2 renders its own box (outline + handles + translucent
        // faces) once enabled. The static preview actor would otherwise leave a
        // second, overlapping box in the scene while the user drags, so hide it
        // on entry and let the interaction box be the only visible box.
        hideRoiBox();
        if (center && half && rot_deg) {
            roi_selector_->setBoxObb(center[0], center[1], center[2], half[0], half[1],
                                     half[2], rot_deg[0], rot_deg[1], rot_deg[2]);
        }
    }
    roi_selector_->setEnabled(on);
    vtk_widget_->renderWindow()->Render();
#else
    (void)on;
    (void)center;
    (void)half;
    (void)rot_deg;
#endif
}

void PointCloudView::showRoiBox(double xmin, double ymin, double zmin, double xmax,
                                double ymax, double zmax) {
    const double center[3] = {0.5 * (xmin + xmax), 0.5 * (ymin + ymax),
                              0.5 * (zmin + zmax)};
    const double half[3] = {0.5 * (xmax - xmin), 0.5 * (ymax - ymin),
                            0.5 * (zmax - zmin)};
    const double rot[3] = {0.0, 0.0, 0.0};
    showRoiBoxObb(center, half, rot);
}

void PointCloudView::showRoiBoxObb(const double center[3], const double half[3],
                                   const double rot_deg[3]) {
#ifdef PCSEARCH_HAS_VTK
    if (!renderer_) return;
    // While interactive ROI editing is active the vtkBoxWidget2 is the only box
    // shown; never draw the static wireframe preview on top of it.
    if (roi_editing_) return;
    hideRoiBox();
    vtkNew<vtkCubeSource> cube;
    cube->SetCenter(0.0, 0.0, 0.0);
    cube->SetXLength(std::max(0.002, 2.0 * half[0]));
    cube->SetYLength(std::max(0.002, 2.0 * half[1]));
    cube->SetZLength(std::max(0.002, 2.0 * half[2]));

    vtkNew<vtkTransform> transform;
    transform->PreMultiply();
    transform->Translate(center[0], center[1], center[2]);
    transform->RotateZ(rot_deg[2]);
    transform->RotateY(rot_deg[1]);
    transform->RotateX(rot_deg[0]);
    vtkNew<vtkTransformPolyDataFilter> tf;
    tf->SetTransform(transform);
    tf->SetInputConnection(cube->GetOutputPort());

    vtkNew<vtkPolyDataMapper> mapper;
    mapper->SetInputConnection(tf->GetOutputPort());
    roi_box_actor_ = vtkActor::New();
    roi_box_actor_->SetMapper(mapper);
    roi_box_actor_->GetProperty()->SetColor(0.16, 0.84, 0.35);
    roi_box_actor_->GetProperty()->SetRepresentationToWireframe();
    roi_box_actor_->GetProperty()->SetLineWidth(2.0);
    renderer_->AddActor(roi_box_actor_);
    vtk_widget_->renderWindow()->Render();
#else
    (void)center;
    (void)half;
    (void)rot_deg;
#endif
}

void PointCloudView::hideRoiBox() {
#ifdef PCSEARCH_HAS_VTK
    if (roi_box_actor_) {
        renderer_->RemoveActor(roi_box_actor_);
        roi_box_actor_->Delete();
        roi_box_actor_ = nullptr;
        vtk_widget_->renderWindow()->Render();
    }
#endif
}

void PointCloudView::frameScene() {
#ifdef PCSEARCH_HAS_VTK
    if (!renderer_) return;
    renderer_->ResetCamera();
    vtk_widget_->renderWindow()->Render();
#endif
}

void PointCloudView::showObjectList(const pcsearch::core::ObjectList* list) {
#ifdef PCSEARCH_HAS_VTK
    if (!list) {
        clearView();
        return;
    }
    // Remove only the cloud actors we own so the interactive ROI widget (and
    // its pickers) stay alive; RemoveAllViewProps would strip the widget's
    // representation actors and break box dragging/scaling/rotation.
    clearCloudActors();

    bool any = false;
    std::int64_t total_points = 0;
    std::int64_t shown_points = 0;
    try {
        for (const auto& obj : list->objects) {
            const auto& cloud = *obj->cloud;
            const std::int64_t n = cloud.size();
            if (n <= 0) continue;
            total_points += n;

            // Display decimation: huge clouds (RVC 5MP / stitched 10M+) must
            // not be uploaded to the GPU in full on integrated graphics or
            // over remote desktop - building double-precision VTK arrays on
            // the UI thread then rendering freezes the app and can crash the
            // GL driver. Uniform stride keeps the outline while capping GPU
            // work. The pipeline data is never modified, only the view.
            const std::int64_t stride = displayStride(n);
            const std::int64_t count = displayCount(n);
            shown_points += count;

            vtkNew<vtkPoints> points;
            points->SetDataTypeToFloat();
            points->SetNumberOfPoints(count);
            vtkNew<vtkCellArray> verts;
            verts->AllocateEstimate(count, 1);
            verts->InsertNextCell(count);
            std::int64_t out = 0;
            for (std::int64_t i = 0; i < n; i += stride, ++out) {
                points->SetPoint(static_cast<vtkIdType>(out), cloud.points(i, 0),
                                 cloud.points(i, 1), cloud.points(i, 2));
                verts->InsertCellPoint(static_cast<vtkIdType>(out));
            }

            vtkNew<vtkPolyData> poly;
            poly->SetPoints(points);
            poly->SetVerts(verts);

            if (cloud.hasColors()) {
                vtkNew<vtkUnsignedCharArray> colors;
                colors->SetNumberOfComponents(3);
                colors->SetName("RGB");
                colors->SetNumberOfTuples(count);
                out = 0;
                for (std::int64_t i = 0; i < n; i += stride, ++out) {
                    unsigned char rgb[3] = {
                        static_cast<unsigned char>(cloud.colors(i, 0) * 255.0 + 0.5),
                        static_cast<unsigned char>(cloud.colors(i, 1) * 255.0 + 0.5),
                        static_cast<unsigned char>(cloud.colors(i, 2) * 255.0 + 0.5)};
                    colors->SetTypedTuple(static_cast<vtkIdType>(out), rgb);
                }
                poly->GetPointData()->SetScalars(colors);
            }

            vtkNew<vtkPolyDataMapper> mapper;
            mapper->SetInputData(poly);
            vtkNew<vtkActor> actor;
            actor->SetMapper(mapper);
            if (!cloud.hasColors()) {
                actor->GetProperty()->SetColor(obj->display_color.x(),
                                               obj->display_color.y(),
                                               obj->display_color.z());
            }
            renderer_->AddActor(actor);
            cloud_actors_.push_back(actor);
            any = true;
        }
        if (any) {
            renderer_->ResetCamera();
            renderer_->GetActiveCamera()->SetClippingRange(0.1, 1e7);
        }
        vtk_widget_->renderWindow()->Render();
        if (shown_points < total_points) {
            emit displayInfo(tr("Display decimated: showing %1 of %2 points")
                                 .arg(shown_points)
                                 .arg(total_points));
        }
    } catch (const std::exception& e) {
        emit displayInfo(QString::fromUtf8(e.what()));
    } catch (...) {
        emit displayInfo(tr("Display failed (unknown error)"));
    }
#else
    (void)list;
#endif
}

void PointCloudView::clearCloudActors() {
#ifdef PCSEARCH_HAS_VTK
    if (!renderer_) return;
    for (vtkProp* actor : cloud_actors_) {
        // The renderer's prop collection holds the last reference (actors were
        // created with vtkNew), so removal unregisters and deletes them.
        renderer_->RemoveViewProp(actor);
    }
    cloud_actors_.clear();
#endif
}

}  // namespace app
