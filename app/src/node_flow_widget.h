#pragma once

#include "pcsearch/pipeline/graph.h"

#include <QGraphicsView>

#include <map>
#include <vector>

class QGraphicsScene;
class QGraphicsPathItem;
class QPixmap;

namespace app {

class NodeItem;

class NodeFlowWidget : public QGraphicsView {
    Q_OBJECT
public:
    enum class CanvasStyle { Grid, Dots, Solid, Image };

    explicit NodeFlowWidget(QWidget* parent = nullptr);

    void setGraph(pcsearch::pipeline::Graph* graph) { graph_ = graph; }
    void addNode(pcsearch::pipeline::Node* node, const QPointF& scene_pos);
    void addEdge(const QString& from_id, int from_port, const QString& to_id, int to_port);
    void removeEdge(const QString& from_id, int from_port, const QString& to_id,
                    int to_port);
    void clearScene();
    void rebuildEdges();
    // Remove a node item and every edge touching it (graph is updated by the
    // caller). Also cancels any in-flight port drag on this node.
    void removeNode(const std::string& id);
    // Scene position of a node item (for solution persistence).
    QPointF nodePosition(const std::string& id) const;
    // Port centers in scene coordinates (used by tests and future UX).
    QPointF inputPortPos(const std::string& id, int port) const;
    QPointF outputPortPos(const std::string& id, int port) const;
    void selectNode(const std::string& id);
    int nodeCount() const { return static_cast<int>(node_items_.size()); }

    QString canvasStyleName() const;
    void setCanvasStyle(const QString& style, const QString& imagePath = {});
    void loadBackgroundImage(const QString& path);
    void setChinese(bool zh) {
        chinese_ = zh;
        viewport()->update();
    }
    bool chinese() const { return chinese_; }
    QString displayTitle(pcsearch::pipeline::Node* node) const;

    // Called by NodeItem (port/node interaction).
    void onPortClicked(NodeItem* item, bool input, int index);
    void onPortPressed(NodeItem* item, bool input, int index, const QPointF& scene_pos);
    void onNodeContextMenu(NodeItem* item, const QPoint& screen_pos);
    void onEdgeContextMenu(const QString& from_id, int from_port, const QString& to_id,
                           int to_port, const QPoint& screen_pos);
    void onNodeClicked(NodeItem* item);
    void onNodeDoubleClicked(NodeItem* item);
    bool portDragActive() const { return port_drag_active_; }
    void updatePortDrag(const QPointF& scene_pos);
    void finishPortDrag(const QPointF& scene_pos);
    int edgeCount() const { return static_cast<int>(edges_.size()); }
    QPointF edgeEndPoint(int index) const;
    int rebuildCount() const { return rebuild_count_; }

signals:
    void nodeAddRequested(const QString& type, const QPointF& scene_pos);
    void connectionRequested(const QString& from_id, int from_port, const QString& to_id,
                             int to_port);
    void nodeSelected(const QString& id);
    void nodeDoubleClicked(const QString& id);
    void nodeDeleteRequested(const QString& id);
    void edgeDisconnectRequested(const QString& from_id, int from_port,
                                 const QString& to_id, int to_port);
    void statusMessage(const QString& message);
    void zoomScaleChanged(double scale);

protected:
    void drawBackground(QPainter* painter, const QRectF& rect) override;
    void wheelEvent(QWheelEvent* event) override;
    void keyPressEvent(QKeyEvent* event) override;
    void dragEnterEvent(QDragEnterEvent* event) override;
    void dragMoveEvent(QDragMoveEvent* event) override;
    void dropEvent(QDropEvent* event) override;

private:
    struct EdgeRecord {
        QGraphicsPathItem* item = nullptr;
        std::string from_id;
        int from_port = 0;
        std::string to_id;
        int to_port = 0;
    };

    QGraphicsScene* scene_ = nullptr;
    pcsearch::pipeline::Graph* graph_ = nullptr;
    std::map<std::string, NodeItem*> node_items_;
    std::vector<EdgeRecord> edges_;
    std::string pending_from_;
    int pending_from_port_ = -1;
    bool port_drag_active_ = false;
    NodeItem* drag_source_ = nullptr;
    int drag_source_port_ = -1;
    QGraphicsPathItem* drag_line_ = nullptr;
    CanvasStyle canvas_style_ = CanvasStyle::Grid;
    QPixmap* bg_image_ = nullptr;
    bool chinese_ = true;
    int rebuild_count_ = 0;
};

}  // namespace app
