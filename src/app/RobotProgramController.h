#pragma once

// ── 机器人控制台的粘合层 ────────────────────────────────────────────────
//
// 把三块互相独立的东西接起来：
//   * ProgramRunner（纯状态机：第几个节点、失败即停）；
//   * RobotMotionBackend（仿真 / 将来的 UR 真机运动通道）；
//   * 主窗口的采集链路（拍照节点要读位姿、拍照、识别、保存）。
//
// 界面（RobotProgramPanel）只跟本类说话，不直接碰后端或执行器。拍照节点的
// 采集流程用回调注入，主窗口不把相机/标定细节泄漏到本类：
//   setPhotoHandler(启动一次一条龙采集，返回 false + error 表示没法开始)
//   notifyPhotoFinished(采集链路完成后回报结果)
#include <QObject>
#include <QString>
#include <QTimer>

#include <functional>

#include "logic/ProgramRunner.h"
#include "logic/RobotMotionBackend.h"
#include "logic/RobotProgram.h"

class RobotProgramController : public QObject, public ProgramActions {
    Q_OBJECT
public:
    // 运动后端种类。目前只有仿真和 UR；其他品牌按 RobotMotionBackend
    // 接口新增一个枚举值 + 一个工厂分支即可，界面/执行器不用动。
    enum class BackendKind { Simulated, Ur };

    explicit RobotProgramController(RobotMotionBackend* backend,
                                    QObject* parent = nullptr);
    ~RobotProgramController() override;

    RobotMotionBackend* backend() const { return m_backend; }
    BackendKind backendKind() const { return m_backendKind; }
    // 切换后端：会先停止正在运行的程序并断开旧后端。外部传入的后端由本类
    // 接管所有权（与构造函数一致）。
    void setBackendKind(BackendKind kind);
    static QString defaultHost(BackendKind kind);
    static quint16 defaultPort(BackendKind kind);
    ProgramRunner* runner() const { return m_runner; }

    const RobotProgram::Program& program() const { return m_runner->program(); }
    bool isRunning() const { return m_runner->isRunning(); }
    int currentIndex() const { return m_runner->currentIndex(); }

    // ── 程序编辑（运行时拒绝，界面也会禁用）──
    void addNode(const RobotProgram::NodePayload& payload);
    bool removeNode(int index);
    // 把选中移动节点的目标改成当前位姿（space 沿用节点自己的）。
    bool updateMoveTarget(int index, const RobotMotion::Pose& target);
    // 把选中移动节点的速度改掉。
    bool updateMoveSpeed(int index, double speedPct);
    // 把选中等待节点的秒数改掉（0..3600）。
    bool updateWaitSeconds(int index, double seconds);

    // ── 运行 ──
    void runAll();
    void runOne(int index);
    // 停止：程序运行中 → 结束列表；只是点动/空转 → 停下运动。
    void stop();

    // ── 连接 / 使能 / 点动 ──
    void connectDevice(const QString& host, quint16 port);
    void disconnectDevice();
    void setEnabled(bool enabled);
    void setJogSpeed(double speedPct);
    double jogSpeed() const { return m_jogSpeedPct; }
    // jointMode=false：轴 0..2 = X/Y/Z (mm)，3..5 = RX/RY/RZ (度)；
    // jointMode=true ：轴 0..5 = J1..J6 (度)。
    void jog(int axis, double delta, bool jointMode);
    // 关节滑杆：直接移动到某个绝对关节角。
    void moveJointAxisTo(int axis, double degrees);

    // 拍照节点的一条龙采集由主窗口注入。
    using PhotoHandler = std::function<bool(QString* error)>;
    using PhotoAbort = std::function<void()>;
    void setPhotoHandler(PhotoHandler start, PhotoAbort abort = {});
    // 采集链路结束后调用（ok=false 时 error 进日志/提示）。
    void notifyPhotoFinished(bool ok, const QString& error = QString());

    // ── ProgramActions ──
    void startNode(const RobotProgram::NodePayload& payload) override;
    void stopProgram() override;

signals:
    // 后端被替换（仿真 ⇄ UR）。界面据此重绑状态，不能沿用旧后端的连接状态。
    void backendChanged();
    void connectedChanged(bool connected);
    void enabledChanged(bool enabled);
    void poseUpdated(const RobotMotion::State& state);
    void statusMessage(const QString& text, bool error);
    void programChanged();
    void runnerStateChanged(ProgramRunner::State state);
    void nodeStarted(int index);
    void nodeFinished(int index, bool ok, const QString& error);
    void runFinished(bool ok, const QString& error);
    // 拍照节点真正开始采集（界面据此显示进度）。
    void photoStarted();

private:
    void onMotionFinished(bool ok, const QString& error);
    void attachBackend(RobotMotionBackend* backend);
    void detachBackend();

    RobotMotionBackend* m_backend = nullptr;
    BackendKind m_backendKind = BackendKind::Simulated;
    ProgramRunner* m_runner = nullptr;
    QTimer* m_waitTimer = nullptr;
    double m_jogSpeedPct = 30.0;

    PhotoHandler m_photoStart;
    PhotoAbort m_photoAbort;
    bool m_photoPending = false;
};
