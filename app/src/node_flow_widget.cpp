#include "node_flow_widget.h"

#include "node_titles.h"

#include <QDragEnterEvent>
#include <QDragMoveEvent>
#include <QDropEvent>
#include <QGraphicsSceneContextMenuEvent>
#include <QGraphicsSceneMouseEvent>
#include <QGraphicsPathItem>
#include <QGraphicsScene>
#include <QKeyEvent>
#include <QMenu>
#include <QMimeData>
#include <QMouseEvent>
#include <QPainter>
#include <QPainterPath>
#include <QPainterPathStroker>
#include <QPalette>
#include <QPixmap>
#include <QWheelEvent>

#include <algorithm>
#include <cmath>

namespace app {

namespace {

constexpr qreal kNodeWidth = 170.0;
constexpr qreal kNodeHeight = 56.0;
constexpr qreal kPortRadius = 6.0;
constexpr qreal kHitMargin = 4.0;

QColor kindColor(const std::string& kind) {
    if (kind == "cloud") return QColor(37, 99, 235);
    if (kind == "region") return QColor(22, 163, 74);
    if (kind == "any" || kind.empty()) return QColor(148, 163, 184);
    return QColor(234, 88, 12);
}

}  // namespace

class EdgeItem : public QGraphicsPathItem {
public:
    using QGraphicsPathItem::QGraphicsPathItem;

    // Wider hit shape so the line is easy to right-click: the visual line is
    // only 2px, so the hit corridor is 20px (10px each side).
    QPainterPath shape() const override {
        QPainterPathStroker stroker;
        stroker.setWidth(20.0);
        return stroker.createStroke(path());
    }

protected:
    void contextMenuEvent(QGraphicsSceneContextMenuEvent* event) override {
        if (widget_) {
            widget_->onEdgeContextMenu(
                QString::fromStdString(from_id_), from_port_,
                QString::fromStdString(to_id_), to_port_, event->screenPos());
        }
        event->accept();
    }

public:
    NodeFlowWidget* widget_ = nullptr;
    std::string from_id_;
    int from_port_ = 0;
    std::string to_id_;
    int to_port_ = 0;
};

class NodeItem : public QGraphicsItem {
public:
    NodeItem(pcsearch::pipeline::Node* node, NodeFlowWidget* widget)
        : node_(node), widget_(widget) {
        setFlag(ItemIsMovable);
        setFlag(ItemIsSelectable);
        // Without this flag, Qt never delivers ItemPositionHasChanged to
        // itemChange(), so connected edges would not follow node drags.
        setFlag(ItemSendsGeometryChanges);
        QString tip = QString::fromStdString(node_->title());
        for (std::size_t i = 0; i < node_->inputCount(); ++i) {
            const std::string kind = node_->inputKind(i);
            tip += QString("\nIn %1: %2")
                       .arg(i)
                       .arg(QString::fromStdString(kind.empty() ? "any" : kind));
        }
        for (std::size_t i = 0; i < node_->outputCount(); ++i) {
            const std::string kind = node_->outputKind(i);
            tip += QString("\nOut %1: %2")
                       .arg(i)
                       .arg(QString::fromStdString(kind.empty() ? "any" : kind));
        }
        setToolTip(tip);
    }

    QRectF boundingRect() const override {
        // Inflate the hit box so port centers (which sit on the node edges)
        // are reliably clickable; the visible body stays inside the margin.
        return QRectF(-kHitMargin, -kHitMargin, kNodeWidth + 2 * kHitMargin,
                      kNodeHeight + 2 * kHitMargin);
    }

    QRectF bodyRect() const {
        return QRectF(kHitMargin, kHitMargin, kNodeWidth, kNodeHeight);
    }

    void paint(QPainter* painter, const QStyleOptionGraphicsItem*, QWidget*) override {
        const QRectF body = bodyRect();
        const bool selected = isSelected();
        painter->setBrush(selected ? QColor(37, 99, 235) : QColor(248, 250, 255));
        painter->setPen(QPen(selected ? QColor(29, 78, 216) : QColor(191, 214, 255), 1.5));
        painter->drawRoundedRect(body, 6, 6);
        painter->setPen(selected ? Qt::white : QColor(30, 41, 59));
        painter->drawText(body.adjusted(2, 0, -2, 0), Qt::AlignCenter,
                          widget_->displayTitle(node_));
        const int in_count = static_cast<int>(node_->inputCount());
        const int out_count = static_cast<int>(node_->outputCount());
        for (int i = 0; i < in_count; ++i) {
            const QColor color = kindColor(node_->inputKind(static_cast<std::size_t>(i)));
            painter->setBrush(color);
            painter->setPen(QPen(color.darker(130), 1.2));
            painter->drawEllipse(portRect(true, i, in_count));
        }
        for (int i = 0; i < out_count; ++i) {
            const QColor color = kindColor(node_->outputKind(static_cast<std::size_t>(i)));
            painter->setBrush(color);
            painter->setPen(QPen(color.darker(130), 1.2));
            painter->drawEllipse(portRect(false, i, out_count));
        }
    }

    pcsearch::pipeline::Node* node() const { return node_; }

    QPointF portScenePos(bool input, int index) const {
        const int count =
            static_cast<int>(input ? node_->inputCount() : node_->outputCount());
        return mapToScene(portRect(input, index, count).center());
    }

protected:
    void mousePressEvent(QGraphicsSceneMouseEvent* event) override {
        const QPointF p = event->pos();
        const int in_count = static_cast<int>(node_->inputCount());
        const int out_count = static_cast<int>(node_->outputCount());
        for (int i = 0; i < in_count; ++i) {
            if (portRect(true, i, in_count).contains(p)) {
                widget_->onPortClicked(this, true, i);
                return;
            }
        }
        for (int i = 0; i < out_count; ++i) {
            if (portRect(false, i, out_count).contains(p)) {
                widget_->onPortPressed(this, false, i, event->scenePos());
                event->accept();
                return;
            }
        }
        QGraphicsItem::mousePressEvent(event);
        widget_->onNodeClicked(this);
    }

    void mouseMoveEvent(QGraphicsSceneMouseEvent* event) override {
        if (widget_->portDragActive()) {
            widget_->updatePortDrag(event->scenePos());
            event->accept();
            return;
        }
        QGraphicsItem::mouseMoveEvent(event);
    }

    void mouseReleaseEvent(QGraphicsSceneMouseEvent* event) override {
        if (widget_->portDragActive()) {
            widget_->finishPortDrag(event->scenePos());
            event->accept();
            return;
        }
        QGraphicsItem::mouseReleaseEvent(event);
    }

    void mouseDoubleClickEvent(QGraphicsSceneMouseEvent* event) override {
        widget_->onNodeDoubleClicked(this);
        QGraphicsItem::mouseDoubleClickEvent(event);
    }

    void contextMenuEvent(QGraphicsSceneContextMenuEvent* event) override {
        widget_->onNodeContextMenu(this, event->screenPos());
        event->accept();
    }

    QVariant itemChange(GraphicsItemChange change, const QVariant& value) override {
        if (change == ItemPositionHasChanged) {
            widget_->rebuildEdges();
        }
        return QGraphicsItem::itemChange(change, value);
    }

private:
    QRectF portRect(bool input, int index, int count) const {
        const qreal y = kHitMargin + (index + 0.5) * (kNodeHeight / count);
        const qreal x = kHitMargin + (input ? 0.0 : kNodeWidth);
        return QRectF(x - kPortRadius, y - kPortRadius, 2 * kPortRadius, 2 * kPortRadius);
    }

    pcsearch::pipeline::Node* node_;
    NodeFlowWidget* widget_;
};

NodeFlowWidget::NodeFlowWidget(QWidget* parent) : QGraphicsView(parent) {
    scene_ = new QGraphicsScene(this);
    scene_->setSceneRect(-2000, -2000, 4000, 4000);
    setScene(scene_);
    setAcceptDrops(true);
    viewport()->setAcceptDrops(true);
    setDragMode(QGraphicsView::RubberBandDrag);
    setRenderHint(QPainter::Antialiasing);
    // Full-viewport updates eliminate ghosting artifacts while dragging nodes
    // (edge curves are re-computed on every position change).
    setViewportUpdateMode(QGraphicsView::FullViewportUpdate);
    setFocusPolicy(Qt::StrongFocus);
    setMinimumSize(480, 320);
}

void NodeFlowWidget::addNode(pcsearch::pipeline::Node* node, const QPointF& scene_pos) {
    auto* item = new NodeItem(node, this);
    scene_->addItem(item);
    if (!scene_pos.isNull()) {
        item->setPos(scene_pos -
                     QPointF(kNodeWidth / 2 + kHitMargin,
                             kNodeHeight / 2 + kHitMargin));
    }
    node_items_[node->id()] = item;
}

QPointF NodeFlowWidget::nodePosition(const std::string& id) const {
    const auto it = node_items_.find(id);
    return it == node_items_.end() ? QPointF() : it->second->pos();
}

QPointF NodeFlowWidget::inputPortPos(const std::string& id, int port) const {
    const auto it = node_items_.find(id);
    return it == node_items_.end() ? QPointF()
                                   : it->second->portScenePos(true, port);
}

QPointF NodeFlowWidget::outputPortPos(const std::string& id, int port) const {
    const auto it = node_items_.find(id);
    return it == node_items_.end() ? QPointF()
                                   : it->second->portScenePos(false, port);
}

void NodeFlowWidget::selectNode(const std::string& id) {
    const auto it = node_items_.find(id);
    if (it == node_items_.end()) return;
    scene_->clearSelection();
    it->second->setSelected(true);
    emit nodeSelected(QString::fromStdString(id));
}

void NodeFlowWidget::removeNode(const std::string& id) {
    if (pending_from_ == id) {
        pending_from_.clear();
        pending_from_port_ = -1;
    }
    if (drag_source_ && drag_source_->node()->id() == id) {
        port_drag_active_ = false;
        if (drag_line_) {
            scene_->removeItem(drag_line_);
            delete drag_line_;
            drag_line_ = nullptr;
        }
        drag_source_ = nullptr;
        drag_source_port_ = -1;
    }
    const auto it = node_items_.find(id);
    if (it == node_items_.end()) return;
    scene_->removeItem(it->second);
    delete it->second;
    node_items_.erase(it);

    for (auto eit = edges_.begin(); eit != edges_.end();) {
        if (eit->from_id == id || eit->to_id == id) {
            scene_->removeItem(eit->item);
            delete eit->item;
            eit = edges_.erase(eit);
        } else {
            ++eit;
        }
    }
}

void NodeFlowWidget::onPortClicked(NodeItem* item, bool input, int index) {
    if (input) {
        if (pending_from_.empty()) {
            emit statusMessage(tr("Click an output port first"));
            return;
        }
        emit connectionRequested(QString::fromStdString(pending_from_), pending_from_port_,
                                 QString::fromStdString(item->node()->id()), index);
        pending_from_.clear();
        pending_from_port_ = -1;
    } else {
        pending_from_ = item->node()->id();
        pending_from_port_ = index;
        emit statusMessage(tr("Click an input port to connect"));
    }
}

void NodeFlowWidget::onPortPressed(NodeItem* item, bool input, int index,
                                   const QPointF& scene_pos) {
    if (input) {
        onPortClicked(item, true, index);
        return;
    }
    pending_from_ = item->node()->id();
    pending_from_port_ = index;
    drag_source_ = item;
    drag_source_port_ = index;
    port_drag_active_ = true;
    if (!drag_line_) {
        drag_line_ = scene_->addPath(QPainterPath());
    }
    drag_line_->setPen(QPen(QColor(37, 99, 235, 170), 2, Qt::DashLine));
    updatePortDrag(scene_pos);
    emit statusMessage(tr("Release over an input port to connect"));
}

void NodeFlowWidget::updatePortDrag(const QPointF& scene_pos) {
    if (!port_drag_active_ || !drag_source_ || !drag_line_) return;
    QPainterPath path(drag_source_->portScenePos(false, drag_source_port_));
    path.lineTo(scene_pos);
    drag_line_->setPath(path);
}

void NodeFlowWidget::finishPortDrag(const QPointF& scene_pos) {
    if (!port_drag_active_) return;
    port_drag_active_ = false;
    if (drag_line_) {
        scene_->removeItem(drag_line_);
        delete drag_line_;
        drag_line_ = nullptr;
    }
    NodeItem* source = drag_source_;
    const int source_port = drag_source_port_;
    drag_source_ = nullptr;
    drag_source_port_ = -1;
    if (!source) return;

    // Snap by port distance instead of scene hit-testing so releases on port
    // edges (which may fall just outside an item's shape) still connect.
    const qreal kPortSnap = kPortRadius + 8.0;
    for (const auto& [nid, target] : node_items_) {
        if (target == source) continue;
        for (int i = 0; i < static_cast<int>(target->node()->inputCount()); ++i) {
            if ((target->portScenePos(true, i) - scene_pos).manhattanLength() <=
                kPortSnap) {
                emit connectionRequested(QString::fromStdString(source->node()->id()),
                                         source_port,
                                         QString::fromStdString(target->node()->id()), i);
                pending_from_.clear();
                pending_from_port_ = -1;
                return;
            }
        }
    }
    // Released on empty space: keep pending_from_ so click-click still works.
}

void NodeFlowWidget::onNodeContextMenu(NodeItem* item, const QPoint& screen_pos) {
    emit nodeSelected(QString::fromStdString(item->node()->id()));
    QMenu menu;
    QAction* del = menu.addAction(tr("Delete Node"));
    if (menu.exec(screen_pos) == del) {
        emit nodeDeleteRequested(QString::fromStdString(item->node()->id()));
    }
}

void NodeFlowWidget::onNodeClicked(NodeItem* item) {
    emit nodeSelected(QString::fromStdString(item->node()->id()));
}

void NodeFlowWidget::onNodeDoubleClicked(NodeItem* item) {
    emit nodeDoubleClicked(QString::fromStdString(item->node()->id()));
}

void NodeFlowWidget::addEdge(const QString& from_id, int from_port, const QString& to_id,
                             int to_port) {
    EdgeRecord rec;
    rec.from_id = from_id.toStdString();
    rec.from_port = from_port;
    rec.to_id = to_id.toStdString();
    rec.to_port = to_port;
    auto* edge = new EdgeItem();
    edge->widget_ = this;
    edge->from_id_ = from_id.toStdString();
    edge->from_port_ = from_port;
    edge->to_id_ = to_id.toStdString();
    edge->to_port_ = to_port;
    scene_->addItem(edge);
    rec.item = edge;
    edges_.push_back(rec);
    rebuildEdges();
}

void NodeFlowWidget::removeEdge(const QString& from_id, int from_port,
                                const QString& to_id, int to_port) {
    for (auto it = edges_.begin(); it != edges_.end(); ++it) {
        if (it->from_id == from_id.toStdString() &&
            it->from_port == from_port && it->to_id == to_id.toStdString() &&
            it->to_port == to_port) {
            scene_->removeItem(it->item);
            delete it->item;
            edges_.erase(it);
            return;
        }
    }
}

void NodeFlowWidget::onEdgeContextMenu(const QString& from_id, int from_port,
                                       const QString& to_id, int to_port,
                                       const QPoint& screen_pos) {
    QMenu menu;
    QAction* disconnect = menu.addAction(tr("Disconnect"));
    if (menu.exec(screen_pos) == disconnect) {
        emit edgeDisconnectRequested(from_id, from_port, to_id, to_port);
    }
}

QPointF NodeFlowWidget::edgeEndPoint(int index) const {
    if (index < 0 || index >= static_cast<int>(edges_.size())) return {};
    return edges_[static_cast<std::size_t>(index)].item->path().pointAtPercent(1.0);
}

void NodeFlowWidget::rebuildEdges() {
    ++rebuild_count_;
    for (auto& e : edges_) {
        const auto fit = node_items_.find(e.from_id);
        const auto tit = node_items_.find(e.to_id);
        if (fit == node_items_.end() || tit == node_items_.end()) continue;
        const QPointF a = fit->second->portScenePos(false, e.from_port);
        const QPointF b = tit->second->portScenePos(true, e.to_port);
        QPainterPath path(a);
        const qreal dx = std::max<qreal>(40.0, std::abs(b.x() - a.x()) * 0.5);
        path.cubicTo(a + QPointF(dx, 0), b - QPointF(dx, 0), b);
        e.item->setPath(path);
        e.item->setPen(QPen(QColor(37, 99, 235, 190), 2));
    }
}

void NodeFlowWidget::clearScene() {
    scene_->clear();
    node_items_.clear();
    edges_.clear();
}

QString NodeFlowWidget::canvasStyleName() const {
    switch (canvas_style_) {
        case CanvasStyle::Grid: return QStringLiteral("grid");
        case CanvasStyle::Dots: return QStringLiteral("dots");
        case CanvasStyle::Solid: return QStringLiteral("solid");
        case CanvasStyle::Image: return QStringLiteral("image");
    }
    return QStringLiteral("grid");
}

void NodeFlowWidget::setCanvasStyle(const QString& style, const QString& imagePath) {
    if (style == QStringLiteral("dots")) {
        canvas_style_ = CanvasStyle::Dots;
    } else if (style == QStringLiteral("solid")) {
        canvas_style_ = CanvasStyle::Solid;
    } else if (style == QStringLiteral("image")) {
        if (!imagePath.isEmpty()) {
            loadBackgroundImage(imagePath);
            return;
        }
        canvas_style_ = CanvasStyle::Image;
    } else {
        canvas_style_ = CanvasStyle::Grid;
    }
    viewport()->update();
}

void NodeFlowWidget::loadBackgroundImage(const QString& path) {
    auto* pixmap = new QPixmap(path);
    if (pixmap->isNull()) {
        delete pixmap;
        emit statusMessage(tr("Cannot load canvas background image"));
        return;
    }
    delete bg_image_;
    bg_image_ = pixmap;
    canvas_style_ = CanvasStyle::Image;
    viewport()->update();
}

QString NodeFlowWidget::displayTitle(pcsearch::pipeline::Node* node) const {
    return node ? nodeTitle(node->type(), chinese_)
                : QString::fromStdString(node ? node->type() : std::string{});
}

void NodeFlowWidget::drawBackground(QPainter* painter, const QRectF& rect) {
    const QColor base = palette().color(QPalette::Base);
    painter->fillRect(rect, base);

    if (canvas_style_ == CanvasStyle::Image && bg_image_ && !bg_image_->isNull()) {
        const int w = bg_image_->width();
        const int h = bg_image_->height();
        if (w > 0 && h > 0) {
            for (qreal y = rect.top(); y < rect.bottom(); y += h) {
                for (qreal x = rect.left(); x < rect.right(); x += w) {
                    painter->drawPixmap(QPointF(x, y), *bg_image_);
                }
            }
        }
        return;
    }
    if (canvas_style_ == CanvasStyle::Solid) return;

    const bool dark = base.lightness() < 128;
    const QColor line = dark ? QColor(255, 255, 255, 20) : QColor(37, 99, 235, 26);
    const qreal spacing = 36.0;
    const qreal x0 = std::floor(rect.left() / spacing) * spacing;
    const qreal y0 = std::floor(rect.top() / spacing) * spacing;
    painter->setPen(QPen(line, 1));
    if (canvas_style_ == CanvasStyle::Dots) {
        for (qreal y = y0; y <= rect.bottom(); y += spacing) {
            for (qreal x = x0; x <= rect.right(); x += spacing) {
                painter->drawEllipse(QPointF(x, y), 1.5, 1.5);
            }
        }
    } else {
        for (qreal x = x0; x <= rect.right(); x += spacing) {
            painter->drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()));
        }
        for (qreal y = y0; y <= rect.bottom(); y += spacing) {
            painter->drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y));
        }
    }
}

void NodeFlowWidget::wheelEvent(QWheelEvent* event) {
    if (event->modifiers() & Qt::ControlModifier) {
        const double factor = event->angleDelta().y() > 0 ? 1.15 : 1.0 / 1.15;
        const double current = transform().m11();
        const double next = std::clamp(current * factor, 0.15, 3.0);
        scale(next / current, next / current);
        emit zoomScaleChanged(next);
        event->accept();
        return;
    }
    QGraphicsView::wheelEvent(event);
}

void NodeFlowWidget::keyPressEvent(QKeyEvent* event) {
    if (event->key() == Qt::Key_Delete) {
        const auto selected = scene_->selectedItems();
        for (auto* gi : selected) {
            if (auto* item = dynamic_cast<NodeItem*>(gi)) {
                emit nodeDeleteRequested(QString::fromStdString(item->node()->id()));
            }
        }
        event->accept();
        return;
    }
    QGraphicsView::keyPressEvent(event);
}

void NodeFlowWidget::dragEnterEvent(QDragEnterEvent* event) {
    if (event->mimeData()->hasFormat("application/x-pcsearch-node")) {
        event->acceptProposedAction();
    }
}

void NodeFlowWidget::dragMoveEvent(QDragMoveEvent* event) {
    if (event->mimeData()->hasFormat("application/x-pcsearch-node")) {
        event->acceptProposedAction();
    }
}

void NodeFlowWidget::dropEvent(QDropEvent* event) {
    const QByteArray data = event->mimeData()->data("application/x-pcsearch-node");
    if (data.isEmpty()) return;
    emit nodeAddRequested(QString::fromUtf8(data), mapToScene(event->position().toPoint()));
    event->acceptProposedAction();
}

}  // namespace app
