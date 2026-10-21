#pragma once

// ── 程序执行器（纯状态机，不碰网络/界面）───────────────────────────────
//
// ProgramRunner 只负责"第几个节点、成功还是失败、下一步是谁"。它把节点的
// 执行语义交给 ProgramActions（真实实现是 RobotProgramController，单测里是
// 一个立即完成的假实现），因此：
//   * 顺序、单步、失败即停、停止这些规则可以完全离线测；
//   * 以后换后端（仿真 / UR）不需要改执行器。
//
// 一次只执行一个节点：startNode() 之后必须恰好调用一次 notifyNodeFinished()。
// 执行器对重复/迟到的通知是幂等的（忽略），停止后到达的结果也不会再推进列表。
#include <QObject>
#include <QString>

#include "logic/RobotProgram.h"

class ProgramActions {
public:
    virtual ~ProgramActions() = default;
    // 开始执行一个节点。实现方完成后调用 ProgramRunner::notifyNodeFinished。
    virtual void startNode(const RobotProgram::NodePayload& payload) = 0;
    // 取消正在等待的动作（运动停止 / 计时器取消 / 拍照序列中止）。
    // 不要在这里反过来调用 runner->stop()，那是递归。
    virtual void stopProgram() = 0;
};

class ProgramRunner : public QObject {
    Q_OBJECT
public:
    enum class State { Idle, Running, Stopping };

    explicit ProgramRunner(QObject* parent = nullptr);

    void setActions(ProgramActions* actions);
    ProgramActions* actions() const { return m_actions; }

    void setProgram(const RobotProgram::Program& program);
    const RobotProgram::Program& program() const { return m_program; }

    State state() const { return m_state; }
    bool isRunning() const { return m_state != State::Idle; }
    int currentIndex() const { return m_index; }

    // 从第一个节点开始；空程序或正在运行时返回 false 并给出信号。
    bool runAll();
    // 只跑一个节点（从选中项开始，不继续后面的）。
    bool runOne(int index);
    // 停止：立刻结束本次运行，等待中的结果会被忽略。
    void stop();

    // ProgramActions 在节点完成时调用。ok=false 时 error 会随 nodeFinished
    // 一起上报；运行中任一节点失败 → 整个列表停下（不执行后面的节点）。
    void notifyNodeFinished(bool ok, const QString& error = QString());

signals:
    void stateChanged(ProgramRunner::State state);
    void programChanged();
    void nodeStarted(int index);
    void nodeFinished(int index, bool ok, const QString& error);
    // 本次运行结束。ok=false 时 error 说明原因（节点失败 / 已停止 / 空程序）。
    void finished(bool ok, const QString& error);

private:
    void startNodeAt(int index);
    void finish(bool ok, const QString& error);

    ProgramActions* m_actions = nullptr;
    RobotProgram::Program m_program;
    State m_state = State::Idle;
    int m_index = -1;
    bool m_runAll = false;
    bool m_waiting = false;
};
