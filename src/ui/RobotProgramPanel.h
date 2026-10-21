#pragma once

// ── 机器人控制台页面（第 17 阶段 P1）──────────────────────────────────
//
// 视觉与交互按 MyUIdesign/1.html 重做：
//   顶部：连接状态、运行速度、使能、停止（软件停止，不是安全级急停）；
//   左卡：流程节点列表（标签/详情/选中/执行中）+ 添加/删除；
//   右卡：可折叠的通信配置、笛卡尔/关节控制盘、节点编辑、运行按钮。
//
// 页面只负责显示和收集输入，所有状态都在 RobotProgramController 里；
// 控制端通过 setController() 晚绑定（ToolsPanel 构造时还没有主窗口控制器）。
//
// 选中节点 = 进入编辑模式（与 1.html 一致）：右侧显示该节点的目标值，
// ± 只改草稿，不动机器人；点「保存当前节点修改」才写回执行器。未选中时
// ± 才是真机点动。
#include <QString>
#include <QVector>
#include <QWidget>

#include "logic/ProgramRunner.h"
#include "logic/RobotMotionBackend.h"
#include "logic/RobotProgram.h"

class QButtonGroup;
class QComboBox;
class QDoubleSpinBox;
class QFrame;
class QLabel;
class QLineEdit;
class QPushButton;
class QScrollArea;
class QSlider;
class QSpinBox;
class QStackedWidget;
class QTimer;
class QToolButton;
class QVBoxLayout;
class RobotProgramController;

class RobotProgramPanel : public QWidget {
    Q_OBJECT
public:
    explicit RobotProgramPanel(QWidget* parent = nullptr);

    void setController(RobotProgramController* controller);
    RobotProgramController* controller() const { return m_controller; }

signals:
    // 控制台的状态/节点消息 → 主窗口操作日志（由 ToolsPanel 转发）。
    void logMessage(const QString& line);

private:
    // ── 布局 ──
    void buildUi();
    QWidget* buildTopBar();
    QWidget* buildLeftCard();
    QWidget* buildRightCard();
    QWidget* buildCommSection();
    QWidget* buildCartPad();
    QWidget* buildJointPad();
    QWidget* buildWaitPad();
    QWidget* buildPhotoPad();
    QWidget* buildStepSetting();

    // ── 控制器绑定与状态刷新 ──
    void bindController();
    void refreshNodes();
    void refreshRowStyles();
    void refreshActions();
    void refreshPadValues();
    void updatePose(const RobotMotion::State& state);
    void setConnected(bool connected);
    void setEnabled(bool enabled);
    void onRunnerState(ProgramRunner::State state);
    void showToast(const QString& text, bool error = false);
    void log(const QString& text, bool error = false);
    void syncAddressFields();

    // ── 节点选择 / 编辑 ──
    bool isEditing() const;
    RobotProgram::NodeKind selectedKind() const;
    void selectNode(int index);
    void clearSelection();
    void applyEditMode();
    void setDraftDirty(bool dirty);
    void commitDraftCart(int axis);
    void commitDraftJoint(int axis);
    void onCapturePose();
    void onSaveNode();
    void onCancelEdit();

    // ── 动作 ──
    void onBackendKindChanged(int index);
    void onConnectClicked();
    void onEnableToggled(bool on);
    void onStopClicked();
    void onAddMove();
    void onAddPhoto();
    void onAddWait();
    void onDeleteNode();
    void onRunSelected();
    void onRunAll();
    void onCartStep(int axis, int direction);
    void onJointStep(int axis, int direction);
    void onJointSliderMoved(int axis, int value);
    void onJointSliderReleased(int axis, int value);
    void onModeChanged(int id);
    void onWaitDraftChanged(double seconds);

    RobotProgramController* m_controller = nullptr;
    RobotMotion::State m_state;
    bool m_jointMode = false;
    bool m_connected = false;
    bool m_enabled = false;
    bool m_running = false;

    // 选中节点（=编辑模式）与执行中节点。
    int m_selectedIndex = -1;
    QString m_selectedId;
    int m_runningIndex = -1;
    bool m_editDirty = false;

    // 编辑草稿：移动节点用 pose + space，等待节点用 seconds。
    RobotProgram::MoveNode::Space m_draftSpace =
        RobotProgram::MoveNode::Space::Cartesian;
    RobotMotion::Pose m_draftPose{};
    double m_draftSeconds = 1.0;

    // ── 顶部状态栏 ──
    QLabel* m_statusDot = nullptr;
    QLabel* m_connLabel = nullptr;
    QSlider* m_speedSlider = nullptr;
    QLabel* m_speedLabel = nullptr;
    QPushButton* m_enableButton = nullptr;
    QPushButton* m_stopButton = nullptr;

    // ── 左卡 ──
    QLabel* m_countLabel = nullptr;
    QScrollArea* m_listScroll = nullptr;
    QWidget* m_listContainer = nullptr;
    QVBoxLayout* m_listLayout = nullptr;
    QVector<QWidget*> m_nodeRows;
    QPushButton* m_addMoveButton = nullptr;
    QPushButton* m_addPhotoButton = nullptr;
    QPushButton* m_addWaitButton = nullptr;
    QPushButton* m_deleteButton = nullptr;

    // ── 右卡：通信配置 ──
    QWidget* m_commSection = nullptr;
    QToolButton* m_commHeader = nullptr;
    QWidget* m_commBody = nullptr;
    QComboBox* m_backendCombo = nullptr;
    QLineEdit* m_hostEdit = nullptr;
    QSpinBox* m_portSpin = nullptr;
    QPushButton* m_connectButton = nullptr;

    // ── 右卡：编辑条 / 模式切换 ──
    QFrame* m_editBanner = nullptr;
    QLabel* m_editBannerText = nullptr;
    QPushButton* m_captureButton = nullptr;
    QPushButton* m_cancelEditButton = nullptr;
    QWidget* m_modeSwitcher = nullptr;
    QButtonGroup* m_modeGroup = nullptr;
    QPushButton* m_cartTab = nullptr;
    QPushButton* m_jointTab = nullptr;

    // ── 右卡：控制盘 ──
    QStackedWidget* m_pad = nullptr;
    QWidget* m_cartPad = nullptr;
    QWidget* m_jointPad = nullptr;
    QWidget* m_waitPad = nullptr;
    QWidget* m_photoPad = nullptr;
    QLineEdit* m_cartEdits[6]{};
    QPushButton* m_cartMinus[6]{};
    QPushButton* m_cartPlus[6]{};
    QLineEdit* m_jointEdits[6]{};
    QPushButton* m_jointMinus[6]{};
    QPushButton* m_jointPlus[6]{};
    QSlider* m_jointSliders[6]{};
    QDoubleSpinBox* m_editWaitSpin = nullptr;
    QDoubleSpinBox* m_stepSpin = nullptr;

    // ── 右卡：底部 ──
    QPushButton* m_saveButton = nullptr;
    QPushButton* m_runSelectedButton = nullptr;
    QPushButton* m_runAllButton = nullptr;

    // 顶部悬浮提示（对应 1.html 的 toast）。
    QLabel* m_toast = nullptr;
    QTimer* m_toastTimer = nullptr;
};
