#pragma once

// ── 机器人控制台页面（第 17 阶段 P1）──────────────────────────────────
//
// 这是 ToolsPanel 里的独立一项，不塞进「机器人通信」页：
//   左：程序节点列表 + 增删/更新/运行；
//   右：连接状态、使能、停止、笛卡尔/关节点动。
//
// 页面只负责显示和收集输入，所有状态都在 RobotProgramController 里；
// 控制端通过 setController() 晚绑定（ToolsPanel 构造时还没有主窗口控制器）。
#include <QVector>
#include <QWidget>

#include "logic/ProgramRunner.h"
#include "logic/RobotMotionBackend.h"
#include "logic/RobotProgram.h"

class QAbstractButton;
class QButtonGroup;
class QDoubleSpinBox;
class QLabel;
class QLineEdit;
class QListWidget;
class QPushButton;
class QSlider;
class QSpinBox;
class QStackedWidget;
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
    void buildUi();
    void bindController();
    void refreshNodes();
    void refreshActions();
    void refreshSelection();
    void updatePose(const RobotMotion::State& state);
    void setConnected(bool connected);
    void setEnabled(bool enabled);
    void onRunnerState(ProgramRunner::State state);
    void setStatus(const QString& text, bool error);
    void log(const QString& text, bool error = false);

    void onConnectClicked();
    void onEnableToggled(bool on);
    void onStopClicked();
    void onAddMove();
    void onAddPhoto();
    void onAddWait();
    void onDeleteNode();
    void onUpdateTarget();
    void onRunSelected();
    void onRunAll();
    void onJog(int axis, int direction);
    void onJointSliderReleased(int axis, int value);
    void onModeChanged(int id);

    RobotProgramController* m_controller = nullptr;
    RobotMotion::State m_state;
    bool m_jointMode = false;
    bool m_connected = false;
    bool m_enabled = false;
    bool m_running = false;

    QLabel* m_statusDot = nullptr;
    QLabel* m_statusLabel = nullptr;
    QLabel* m_backendLabel = nullptr;
    QLabel* m_hintLabel = nullptr;
    QLabel* m_countLabel = nullptr;
    QLineEdit* m_hostEdit = nullptr;
    QSpinBox* m_portSpin = nullptr;
    QPushButton* m_connectButton = nullptr;
    QPushButton* m_enableButton = nullptr;
    QPushButton* m_stopButton = nullptr;

    QListWidget* m_nodeList = nullptr;
    QPushButton* m_addMoveButton = nullptr;
    QPushButton* m_addPhotoButton = nullptr;
    QPushButton* m_addWaitButton = nullptr;
    QPushButton* m_deleteButton = nullptr;
    QPushButton* m_updateTargetButton = nullptr;
    QDoubleSpinBox* m_waitSeconds = nullptr;
    QPushButton* m_runSelectedButton = nullptr;
    QPushButton* m_runAllButton = nullptr;

    QButtonGroup* m_modeGroup = nullptr;
    QSlider* m_speedSlider = nullptr;
    QLabel* m_speedLabel = nullptr;
    QDoubleSpinBox* m_stepSpin = nullptr;
    QStackedWidget* m_jogStack = nullptr;
    QLabel* m_poseValueLabels[6]{};
    QVector<QLabel*> m_jointValueLabels;
    QVector<QAbstractButton*> m_jogButtons;
    QVector<QSlider*> m_jointSliders;
};
