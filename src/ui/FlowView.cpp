#include "FlowView.h"

#include <QDragEnterEvent>
#include <QDropEvent>
#include <QMimeData>

#include <QtNodes/Definitions>

#include "FlowModel.h"
#include "Toolbox.h"

namespace rvc {

FlowView::FlowView(FlowModel& model, QtNodes::BasicGraphicsScene* scene, QWidget* parent)
    : QtNodes::GraphicsView(scene, parent), model_(model)
{
    setAcceptDrops(true);
}

void FlowView::dragEnterEvent(QDragEnterEvent* event)
{
    if (event->mimeData()->hasFormat(QLatin1String(kModuleMimeType))) {
        event->acceptProposedAction();
        return;
    }
    QtNodes::GraphicsView::dragEnterEvent(event);
}

void FlowView::dragMoveEvent(QDragMoveEvent* event)
{
    if (event->mimeData()->hasFormat(QLatin1String(kModuleMimeType))) {
        event->acceptProposedAction();
        return;
    }
    QtNodes::GraphicsView::dragMoveEvent(event);
}

void FlowView::dropEvent(QDropEvent* event)
{
    if (!event->mimeData()->hasFormat(QLatin1String(kModuleMimeType))) {
        QtNodes::GraphicsView::dropEvent(event);
        return;
    }

    // 在落点实例化模块（画布加节点 → Process 加模块）
    const QString typeId = QString::fromUtf8(event->mimeData()->data(QLatin1String(kModuleMimeType)));
    const QtNodes::NodeId nodeId = model_.addNode(typeId);
    if (nodeId != QtNodes::InvalidNodeId) {
        const QPointF scenePos = mapToScene(event->position().toPoint());
        model_.setNodeData(nodeId, QtNodes::NodeRole::Position, scenePos);
        event->acceptProposedAction();
    }
}

} // namespace rvc
