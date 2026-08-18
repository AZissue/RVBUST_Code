#pragma once

// 2D ROI 编辑视图：点云 XY 投影散点 + 可交互矩形框。
// 交互：空白处拖新矩形 / 矩形内拖动 / 拖边缘或角调整大小；滚轮缩放、右键平移视图。

#include <QWidget>

#include "core/DataTypes.h"

namespace rvc {

class Roi2DView : public QWidget {
    Q_OBJECT
public:
    explicit Roi2DView(QWidget* parent = nullptr);

    // 设置点云数据（仅取 x/y 投影）
    void setPointCloud(PointCloud cloud);
    // 设置/获取当前 ROI（仅使用 min/max 的 x/y）
    void setRoi(const RoiBox& roi);
    RoiBox roi() const;

Q_SIGNALS:
    void roiChanged(const RoiBox& roi);

protected:
    void paintEvent(QPaintEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void wheelEvent(QWheelEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;

private:
    enum class DragMode { None, Draw, Move, ResizeLeft, ResizeRight, ResizeTop, ResizeBottom,
                          ResizeTopLeft, ResizeTopRight, ResizeBottomLeft, ResizeBottomRight };

    void updateTransform();      // 根据点云包围盒与控件尺寸更新映射
    QPointF worldToScreen(float x, float y) const;
    QPointF screenToWorld(const QPointF& p) const;
    DragMode hitTest(const QPointF& screenPos) const;
    void clampRoi();
    void updateCursor(DragMode mode);
    void emitRoiChanged();

    PointCloud cloud_;
    RoiBox roi_;
    bool hasRoi_ = false;

    // 坐标变换（Y 轴翻转：屏幕上方 = 较大的 world Y）
    float scale_ = 1.0f;
    float offsetX_ = 0.0f;
    float offsetY_ = 0.0f;

    // 视图导航
    bool panning_ = false;
    QPointF panStartScreen_;
    float panStartOffsetX_ = 0.0f;
    float panStartOffsetY_ = 0.0f;

    // ROI 拖拽
    DragMode dragMode_ = DragMode::None;
    QPointF dragStartWorld_;
    RoiBox dragStartRoi_;
};

} // namespace rvc
