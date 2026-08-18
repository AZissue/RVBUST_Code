#include "Roi2DView.h"

#include <QMouseEvent>
#include <QPainter>
#include <QPen>
#include <QWheelEvent>

#include <algorithm>

namespace rvc {

namespace {
constexpr float kHandleTolerance = 6.0f; // 边缘/角命中容差（像素）
}

Roi2DView::Roi2DView(QWidget* parent) : QWidget(parent)
{
    setMinimumSize(320, 240);
    setAutoFillBackground(true);
    setMouseTracking(true); // 悬停时更新光标
    QPalette pal = palette();
    pal.setColor(QPalette::Window, QColor(15, 15, 19)); // surface-0
    setPalette(pal);
}

void Roi2DView::setPointCloud(PointCloud cloud)
{
    cloud_ = std::move(cloud);
    updateTransform();
    update();
}

void Roi2DView::setRoi(const RoiBox& roi)
{
    roi_ = roi;
    hasRoi_ = roi.valid;
    update();
}

RoiBox Roi2DView::roi() const
{
    return roi_;
}

void Roi2DView::resizeEvent(QResizeEvent* event)
{
    QWidget::resizeEvent(event);
    updateTransform();
}

void Roi2DView::updateTransform()
{
    if (!cloud_ || cloud_->empty()) {
        scale_ = 1.0f;
        offsetX_ = width() * 0.5f;
        offsetY_ = height() * 0.5f;
        return;
    }

    float minX = 1e30f, maxX = -1e30f, minY = 1e30f, maxY = -1e30f;
    for (const auto& p : cloud_->points) {
        minX = std::min(minX, p.x);
        maxX = std::max(maxX, p.x);
        minY = std::min(minY, p.y);
        maxY = std::max(maxY, p.y);
    }

    const float rangeX = std::max(maxX - minX, 1e-6f);
    const float rangeY = std::max(maxY - minY, 1e-6f);
    const float margin = 20.0f;
    const float w = std::max(width() - 2 * margin, 1.0f);
    const float h = std::max(height() - 2 * margin, 1.0f);

    scale_ = std::min(w / rangeX, h / rangeY);
    offsetX_ = margin + (w - rangeX * scale_) * 0.5f - minX * scale_;
    // Y 翻转：world Y 越大，screen Y 越小（屏幕上方）
    offsetY_ = margin + (h - rangeY * scale_) * 0.5f + maxY * scale_;
}

QPointF Roi2DView::worldToScreen(float x, float y) const
{
    return QPointF(x * scale_ + offsetX_, -y * scale_ + offsetY_);
}

QPointF Roi2DView::screenToWorld(const QPointF& p) const
{
    return QPointF((p.x() - offsetX_) / scale_, -(p.y() - offsetY_) / scale_);
}

Roi2DView::DragMode Roi2DView::hitTest(const QPointF& screenPos) const
{
    if (!hasRoi_)
        return DragMode::Draw;

    const QPointF p1 = worldToScreen(roi_.min.x(), roi_.min.y());
    const QPointF p2 = worldToScreen(roi_.max.x(), roi_.max.y());
    const QRectF rect(p1, p2);
    const QRectF r = rect.normalized();

    const qreal x = screenPos.x();
    const qreal y = screenPos.y();

    const bool nearLeft = std::abs(x - r.left()) <= kHandleTolerance;
    const bool nearRight = std::abs(x - r.right()) <= kHandleTolerance;
    const bool nearTop = std::abs(y - r.top()) <= kHandleTolerance;
    const bool nearBottom = std::abs(y - r.bottom()) <= kHandleTolerance;
    const bool insideX = x >= r.left() && x <= r.right();
    const bool insideY = y >= r.top() && y <= r.bottom();

    // 角优先
    if (nearLeft && nearTop)
        return DragMode::ResizeTopLeft;
    if (nearRight && nearTop)
        return DragMode::ResizeTopRight;
    if (nearLeft && nearBottom)
        return DragMode::ResizeBottomLeft;
    if (nearRight && nearBottom)
        return DragMode::ResizeBottomRight;

    // 边
    if (nearLeft && insideY)
        return DragMode::ResizeLeft;
    if (nearRight && insideY)
        return DragMode::ResizeRight;
    if (nearTop && insideX)
        return DragMode::ResizeTop;
    if (nearBottom && insideX)
        return DragMode::ResizeBottom;

    // 内部
    if (insideX && insideY)
        return DragMode::Move;

    return DragMode::Draw;
}

void Roi2DView::updateCursor(DragMode mode)
{
    switch (mode) {
    case DragMode::Move:
        setCursor(Qt::SizeAllCursor);
        break;
    case DragMode::ResizeLeft:
    case DragMode::ResizeRight:
        setCursor(Qt::SizeHorCursor);
        break;
    case DragMode::ResizeTop:
    case DragMode::ResizeBottom:
        setCursor(Qt::SizeVerCursor);
        break;
    case DragMode::ResizeTopLeft:
    case DragMode::ResizeBottomRight:
        setCursor(Qt::SizeFDiagCursor);
        break;
    case DragMode::ResizeTopRight:
    case DragMode::ResizeBottomLeft:
        setCursor(Qt::SizeBDiagCursor);
        break;
    default:
        setCursor(Qt::CrossCursor);
        break;
    }
}

void Roi2DView::paintEvent(QPaintEvent* event)
{
    Q_UNUSED(event)
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing, false);

    // 背景
    painter.fillRect(rect(), QColor(15, 15, 19));

    if (!cloud_ || cloud_->empty()) {
        painter.setPen(QColor(139, 141, 152));
        painter.drawText(rect(), Qt::AlignCenter, QStringLiteral("无点云数据"));
        return;
    }

    // 点云投影（限制绘制点数以保持流畅）
    painter.setPen(QPen(QColor(120, 125, 140), 1));
    const size_t step = std::max<size_t>(cloud_->size() / 50000, 1);
    for (size_t i = 0; i < cloud_->size(); i += step) {
        const auto& p = cloud_->points[i];
        const QPointF sp = worldToScreen(p.x, p.y);
        painter.drawPoint(sp);
    }

    // ROI 矩形
    if (hasRoi_) {
        const QPointF p1 = worldToScreen(roi_.min.x(), roi_.min.y());
        const QPointF p2 = worldToScreen(roi_.max.x(), roi_.max.y());
        const QRectF rect(p1, p2);
        const QRectF r = rect.normalized();

        painter.setPen(QPen(QColor(46, 204, 113), 2)); // success green
        painter.setBrush(QColor(46, 204, 113, 30));
        painter.drawRect(r);

        // 拖拽中显示半透明填充
        if (dragMode_ != DragMode::None) {
            painter.setBrush(QColor(46, 204, 113, 60));
            painter.drawRect(r);
        }

        // 绘制 8 个 handle（边缘中点 + 角）
        painter.setBrush(QColor(46, 204, 113));
        const qreal hs = 3.0; // handle 半径
        const qreal cx = r.center().x();
        const qreal cy = r.center().y();
        const QPointF handles[8] = {
            {r.left(), cy}, {r.right(), cy}, {cx, r.top()}, {cx, r.bottom()},
            {r.left(), r.top()}, {r.right(), r.top()}, {r.left(), r.bottom()}, {r.right(), r.bottom()}
        };
        for (const auto& h : handles)
            painter.drawEllipse(h, hs, hs);
    }
}

void Roi2DView::mousePressEvent(QMouseEvent* event)
{
    if (event->button() == Qt::RightButton) {
        panning_ = true;
        panStartScreen_ = event->position();
        panStartOffsetX_ = offsetX_;
        panStartOffsetY_ = offsetY_;
        setCursor(Qt::ClosedHandCursor);
        return;
    }

    if (event->button() != Qt::LeftButton)
        return;

    dragMode_ = hitTest(event->position());
    dragStartWorld_ = screenToWorld(event->position());
    dragStartRoi_ = roi_;

    if (dragMode_ == DragMode::Draw) {
        roi_.min = Eigen::Vector3f(static_cast<float>(dragStartWorld_.x()),
                                   static_cast<float>(dragStartWorld_.y()), -1e9f);
        roi_.max = roi_.min;
        roi_.valid = true;
        roi_.is2D = true;
        hasRoi_ = true;
    }
    update();
}

void Roi2DView::mouseMoveEvent(QMouseEvent* event)
{
    if (panning_) {
        const QPointF delta = event->position() - panStartScreen_;
        offsetX_ = panStartOffsetX_ + delta.x();
        offsetY_ = panStartOffsetY_ + delta.y();
        update();
        return;
    }

    if (dragMode_ == DragMode::None) {
        updateCursor(hitTest(event->position()));
        return;
    }

    const QPointF curWorld = screenToWorld(event->position());
    const float x = static_cast<float>(curWorld.x());
    const float y = static_cast<float>(curWorld.y());

    switch (dragMode_) {
    case DragMode::Draw:
        roi_.min = Eigen::Vector3f(
            std::min(static_cast<float>(dragStartWorld_.x()), x),
            std::min(static_cast<float>(dragStartWorld_.y()), y), -1e9f);
        roi_.max = Eigen::Vector3f(
            std::max(static_cast<float>(dragStartWorld_.x()), x),
            std::max(static_cast<float>(dragStartWorld_.y()), y), 1e9f);
        break;
    case DragMode::Move: {
        const float dx = x - static_cast<float>(dragStartWorld_.x());
        const float dy = y - static_cast<float>(dragStartWorld_.y());
        roi_.min.x() = dragStartRoi_.min.x() + dx;
        roi_.max.x() = dragStartRoi_.max.x() + dx;
        roi_.min.y() = dragStartRoi_.min.y() + dy;
        roi_.max.y() = dragStartRoi_.max.y() + dy;
        break;
    }
    case DragMode::ResizeLeft:
        roi_.min.x() = std::min(x, roi_.max.x());
        break;
    case DragMode::ResizeRight:
        roi_.max.x() = std::max(x, roi_.min.x());
        break;
    case DragMode::ResizeTop:
        roi_.max.y() = std::max(y, roi_.min.y());
        break;
    case DragMode::ResizeBottom:
        roi_.min.y() = std::min(y, roi_.max.y());
        break;
    case DragMode::ResizeTopLeft:
        roi_.min.x() = std::min(x, roi_.max.x());
        roi_.max.y() = std::max(y, roi_.min.y());
        break;
    case DragMode::ResizeTopRight:
        roi_.max.x() = std::max(x, roi_.min.x());
        roi_.max.y() = std::max(y, roi_.min.y());
        break;
    case DragMode::ResizeBottomLeft:
        roi_.min.x() = std::min(x, roi_.max.x());
        roi_.min.y() = std::min(y, roi_.max.y());
        break;
    case DragMode::ResizeBottomRight:
        roi_.max.x() = std::max(x, roi_.min.x());
        roi_.min.y() = std::min(y, roi_.max.y());
        break;
    default:
        break;
    }

    clampRoi();
    update();
}

void Roi2DView::mouseReleaseEvent(QMouseEvent* event)
{
    if (event->button() == Qt::RightButton) {
        panning_ = false;
        updateCursor(hitTest(event->position()));
        return;
    }

    if (event->button() != Qt::LeftButton || dragMode_ == DragMode::None)
        return;

    dragMode_ = DragMode::None;
    clampRoi();
    update();
    updateCursor(hitTest(event->position()));
    emitRoiChanged();
}

void Roi2DView::wheelEvent(QWheelEvent* event)
{
    if (!cloud_ || cloud_->empty())
        return;

    const float factor = event->angleDelta().y() > 0 ? 1.1f : 1.0f / 1.1f;
    const QPointF mouseWorld = screenToWorld(event->position());

    scale_ *= factor;
    // 以鼠标为中心缩放：调整 offset 使鼠标下的 world 点保持不动
    offsetX_ = static_cast<float>(event->position().x()) - static_cast<float>(mouseWorld.x()) * scale_;
    offsetY_ = static_cast<float>(event->position().y()) + static_cast<float>(mouseWorld.y()) * scale_;

    update();
    event->accept();
}

void Roi2DView::clampRoi()
{
    if (!cloud_ || cloud_->empty())
        return;

    float minX = 1e30f, maxX = -1e30f, minY = 1e30f, maxY = -1e30f;
    for (const auto& p : cloud_->points) {
        minX = std::min(minX, p.x);
        maxX = std::max(maxX, p.x);
        minY = std::min(minY, p.y);
        maxY = std::max(maxY, p.y);
    }

    roi_.min.x() = std::clamp(roi_.min.x(), minX, maxX);
    roi_.max.x() = std::clamp(roi_.max.x(), minX, maxX);
    roi_.min.y() = std::clamp(roi_.min.y(), minY, maxY);
    roi_.max.y() = std::clamp(roi_.max.y(), minY, maxY);
}

void Roi2DView::emitRoiChanged()
{
    Q_EMIT roiChanged(roi_);
}

} // namespace rvc
