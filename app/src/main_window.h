#pragma once

#include "pcsearch/pipeline/graph.h"

#include <QMainWindow>

class QComboBox;
class QHBoxLayout;
class QPlainTextEdit;
class QTreeWidget;
class QMenu;
class QStackedWidget;
class QPushButton;
class QThread;
class QTimer;

class QAction;

namespace app {

class GraphRunner;
class NodeFlowWidget;
class ParamsPanel;
class PointCloudView;
class ToolboxWidget;
class ViewportManager;

class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    explicit MainWindow(QWidget* parent = nullptr);
    ~MainWindow() override;

    void log(const QString& message);

protected:
    void changeEvent(QEvent* event) override;

public slots:
    // `to_selected` runs the pipeline only up to the selected node (dirty
    // nodes re-run, upstream of the last change is skipped).
    void runGraph(bool to_selected = false);
    void setLanguageChinese(bool chinese);

private slots:
    void doAddNode(const QString& type, const QPointF& scene_pos);
    void doConnect(const QString& from_id, int from_port, const QString& to_id, int to_port);
    void doSelectNode(const QString& id);
    void doDeleteNode(const QString& id);
    void doDisconnect(const QString& from_id, int from_port, const QString& to_id,
                      int to_port);
    void doParamChanged(const QString& node_id, const QString& name,
                        pcsearch::pipeline::ParamValue value);
    void onParamsAction(const QString& node_id, const QString& action);
    void openCloud();
    void saveSolution();
    void openSolution();
    void onRoiToggle(bool on);
    void onRoiEdited(double cx, double cy, double cz, double hx, double hy, double hz,
                     double rx, double ry, double rz);
    void onRoiEditFinished();
    void setThemeDark(bool);
    void showAbout();

public:
    // Build the demo pipeline used by --demo (load -> clean -> voxel -> ROI).
    bool loadDemo(const QString& plyPath);

signals:
    void runRequested(bool to_selected, const QString& stop_node);

private:
    void buildUi();
    void retranslateUi();
    void setEditingEnabled(bool enabled);
    // Put the currently selected Box ROI node's box into the interactive
    // vtkBoxWidget2 editor (auto-entered when the node is selected).
    void enterRoiEdit();
    void refreshResults();
    // Rebuild the cloud-properties tree for the selected node: its inputs
    // (from upstream edges, grouped by port) and outputs (grouped by port),
    // one row per object/frame. Falls back to all node outputs when nothing
    // is selected. Rows are multi-selectable and drive the 3D view.
    void refreshPropsTree();
    // Collect the selected rows and push them to the 3D viewport: output
    // selections win, otherwise input selections; empty selection clears the
    // view. Also refreshes the ROI baseline (selected input frames).
    void applyPropsSelection();
    // Object indices of the selected input rows on input port `port`
    // (only cloud-carrying objects), used as the Box ROI baseline.
    std::vector<std::int64_t> selectedInputIndices(int port) const;
    // Select / deselect every object row of the properties tree. Selecting
    // picks the input group by default (falling back to outputs for source
    // nodes like load_cloud, which have no inputs).
    void selectAllProps(bool select, bool sync_filter = true);
    // Write the selected input frames into the selected Box ROI node's
    // frame_filter param (empty selection / select-all -> all frames).
    void syncBoxRoiFilter();
    void refreshOutputCombo();
    void showSelectedOutput();
    // Node-specific action buttons shown on the 3D viewport toolbar (e.g.
    // Box ROI -> reset bounds). Rebuilt whenever the selected node changes.
    void updateNodeActionButtons();
    void rebuildPalette();
    void refreshCanvasTree();
    void routeDisplayNodes();
    // Coalesced mid-stream display refresh: reads the runner's latest block
    // snapshot and updates display3d layers (latest-wins, §8.7).
    void refreshDisplayLayers();
    void updateRoiBoxPreview();
    bool nodeInputBounds(const std::string& id, double bounds[6],
                         std::int64_t* valid_points = nullptr) const;
    void onRunFinished(bool ok, const QString& error);

    pcsearch::pipeline::Graph graph_;

    ToolboxWidget* toolbox_ = nullptr;
    NodeFlowWidget* flow_ = nullptr;
    ParamsPanel* params_panel_ = nullptr;
    PointCloudView* cloud_view_ = nullptr;
    QComboBox* output_combo_ = nullptr;
    QPushButton* run_button_ = nullptr;
    QPushButton* run_to_button_ = nullptr;
    QPushButton* roi_button_ = nullptr;
    QHBoxLayout* node_action_bar_ = nullptr;
    QAction* run_action_ = nullptr;
    QStackedWidget* canvas_stack_ = nullptr;
    QTreeWidget* canvas_tree_ = nullptr;
    QTreeWidget* results_tree_ = nullptr;
    QPlainTextEdit* log_view_ = nullptr;
    QMenu* file_menu_ = nullptr;
    QMenu* view_menu_ = nullptr;
    QMenu* help_menu_ = nullptr;
    class SimpleTranslator* translator_ = nullptr;
    ViewportManager* viewports_ = nullptr;

    bool running_ = false;
    std::string selected_node_id_;
    GraphRunner* runner_ = nullptr;
    QThread* runner_thread_ = nullptr;
    QTimer* display_timer_ = nullptr;
    // False while refreshPropsTree() applies its default selection, so the
    // Box ROI frame filter is not reset just by selecting a node.
    bool props_sync_filter_ = true;
    // display3d node id -> viewport name it was last routed to (for stale
    // layer cleanup when a node moves to another viewport or is deleted).
    std::map<std::string, std::string> display_routes_;
};

}  // namespace app
