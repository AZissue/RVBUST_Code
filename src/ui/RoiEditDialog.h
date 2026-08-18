#pragma once

// ROI 设置弹窗：支持 2D 矩形（XY 投影拖拽）/ 3D 盒体（3D 视窗框选）两种模式。
// 从属性面板「设置 ROI…」打开，确定后把 ROI 写回模块参数组。

#include <QDialog>

#include "core/DataTypes.h"

class QComboBox;
class QDoubleSpinBox;
class QStackedWidget;
class QDialogButtonBox;

namespace rvc {

class ModuleBase;
class Roi2DView;
class Viewport3D;

class RoiEditDialog : public QDialog {
    Q_OBJECT
public:
    RoiEditDialog(ModuleBase* module, PointCloud cloud, QWidget* parent = nullptr);

    // 当前编辑的 ROI（含 2D/3D 标志）
    RoiBox roi() const;

private Q_SLOTS:
    void onModeChanged(int index);
    void onRoi2DChanged(const RoiBox& roi);
    void onRoi3DPicked(const RoiBox& roi);
    void onSpinEdited();
    void accept() override;

private:
    void syncFromModule();
    void syncToViews();
    void updateSpinVisibility();

    ModuleBase* module_ = nullptr;
    PointCloud cloud_;
    RoiBox currentRoi_;

    QComboBox* modeCombo_ = nullptr;
    QStackedWidget* stack_ = nullptr;
    Roi2DView* view2d_ = nullptr;
    Viewport3D* view3d_ = nullptr;
    QDialogButtonBox* buttons_ = nullptr;

    QDoubleSpinBox* spinXmin_ = nullptr;
    QDoubleSpinBox* spinXmax_ = nullptr;
    QDoubleSpinBox* spinYmin_ = nullptr;
    QDoubleSpinBox* spinYmax_ = nullptr;
    QDoubleSpinBox* spinZmin_ = nullptr;
    QDoubleSpinBox* spinZmax_ = nullptr;
};

} // namespace rvc
