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
    // 后端种类 = 合并后的「机器人控制」支持的品牌。UR/法奥有运动；其余
    // 三个只读位姿（supportsMotion()==false，控制台隐藏运动区）。
    enum class BackendKind { Simulated, Ur, Fairino, Modbus, NrcJson, Efort };

    // kind 必须与 backend 的类型一致：三个后端都能"连接"，不能靠
    // isSimulated() 反推（那是两后端时代的写法）。
    RobotProgramController(RobotMotionBackend* backend, BackendKind kind,
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
    // 用一份完整程序替换当前流程（导入文件用）。运行中拒绝：执行器的下标
    // 指向旧表，换掉会执行到别的节点。成功时发 programChanged，界面自己刷新。
    bool setProgram(const RobotProgram::Program& program, QString* error = nullptr);
    void addNode(const RobotProgram::NodePayload& payload);
    bool removeNode(int index);
    // 把选中移动节点的目标改成当前位姿（space 沿用节点自己的）。
    bool updateMoveTarget(int index, const RobotMotion::Pose& target);
    // 把选中移动节点的速度改掉。
    bool updateMoveSpeed(int index, double speedPct);
    // 把选中等待节点的秒数改掉（0..3600）。
    bool updateWaitSeconds(int index, double seconds);

    // ── 运行 ──
    // repeats>1：有界循环（1..999），一轮成功后自动从头再来，失败/停止即终止。
    void runAll(int repeats = 1);
    void runOne(int index);
    // 停止：程序运行中 → 结束列表；只是点动/空转 → 停下运动。
    void stop();

    // ── 连接 / 使能 / 点动 ──
    void connectDevice(const QString& host, quint16 port);
    // 合并后的统一连接入口：Modbus 的寄存器参数也从这里下去。
    void connectDevice(const RobotMotion::ConnectOptions& options);
    bool supportsMotion() const
    {
        return m_backend && m_backend->supportsMotion();
    }
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
    // 运行前准备也由主窗口注入：流程节点恒按标记物标定采集，主窗口在这里
    // 把采集模式/会话切成标记物（必要时先问用户）。返回 false 拒绝本次运行。
    // 参数 willWriteRecord 见 ProgramActions::prepareRun()。
    using RunPreparation = std::function<bool(bool willWriteRecord, QString* error)>;
    void setRunPreparation(RunPreparation prepare);
    // 采集链路结束后调用（ok=false 时 error 进日志/提示）。
    void notifyPhotoFinished(bool ok, const QString& error = QString());

    // ── ProgramActions ──
    bool prepareRun(bool willWriteRecord, QString* error) override;
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
    // 一轮跑完、开始下一轮（done/total）。
    void loopAdvanced(int done, int total);
    // 拍照节点真正开始采集（界面据此显示进度）。
    void photoStarted();

private:
    void onMotionFinished(bool ok, const QString& error);
    void attachBackend(RobotMotionBackend* backend, BackendKind kind);
    void detachBackend();

    RobotMotionBackend* m_backend = nullptr;
    BackendKind m_backendKind = BackendKind::Simulated;
    ProgramRunner* m_runner = nullptr;
    QTimer* m_waitTimer = nullptr;
    double m_jogSpeedPct = 30.0;

    PhotoHandler m_photoStart;
    PhotoAbort m_photoAbort;
    bool m_photoPending = false;
    RunPreparation m_prepareRun;
};
