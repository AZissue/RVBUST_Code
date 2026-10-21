#include "logic/ProgramRunner.h"

ProgramRunner::ProgramRunner(QObject* parent) : QObject(parent) {}

void ProgramRunner::setActions(ProgramActions* actions)
{
    m_actions = actions;
}

void ProgramRunner::setProgram(const RobotProgram::Program& program)
{
    // 运行中不允许换表：执行器的 index 指向旧表，换掉会执行到别的节点。
    // 界面在运行时也会禁用编辑，这里再兜一层。
    if (isRunning())
        return;
    m_program = program;
    emit programChanged();
}

bool ProgramRunner::runAll()
{
    if (isRunning())
        return false;
    if (m_program.nodes.empty()) {
        emit finished(false, QStringLiteral("程序为空，请先添加节点"));
        return false;
    }
    m_runAll = true;
    m_index = 0;
    m_waiting = false;
    m_state = State::Running;
    emit stateChanged(m_state);
    startNodeAt(m_index);
    return true;
}

bool ProgramRunner::runOne(int index)
{
    if (isRunning())
        return false;
    if (index < 0 || index >= static_cast<int>(m_program.nodes.size())) {
        emit finished(false, QStringLiteral("没有选中要运行的节点"));
        return false;
    }
    m_runAll = false;
    m_index = index;
    m_waiting = false;
    m_state = State::Running;
    emit stateChanged(m_state);
    startNodeAt(m_index);
    return true;
}

void ProgramRunner::startNodeAt(int index)
{
    m_index = index;
    m_waiting = true;
    emit nodeStarted(index);

    if (!m_actions) {
        notifyNodeFinished(false, QStringLiteral("未配置执行端"));
        return;
    }
    m_actions->startNode(m_program.nodes[static_cast<std::size_t>(index)].payload);
}

void ProgramRunner::notifyNodeFinished(bool ok, const QString& error)
{
    if (!m_waiting || m_state == State::Idle)
        return;
    m_waiting = false;

    const int index = m_index;
    emit nodeFinished(index, ok, error);

    if (m_state == State::Stopping) {
        finish(false, QStringLiteral("已停止"));
        return;
    }
    if (!ok) {
        finish(false, error.isEmpty() ? QStringLiteral("节点执行失败") : error);
        return;
    }
    if (!m_runAll) {
        finish(true, QString());
        return;
    }

    ++m_index;
    if (m_index >= static_cast<int>(m_program.nodes.size())) {
        finish(true, QString());
        return;
    }
    startNodeAt(m_index);
}

void ProgramRunner::stop()
{
    if (m_state == State::Idle)
        return;

    const int stoppedIndex = m_index;
    const bool wasWaiting = m_waiting;

    // 先切断"等待结果"的路径，再通知执行端取消：取消过程里同步发回来的
    // 完成信号会被 notifyNodeFinished 忽略，不会重复推进或重复发 finished。
    m_waiting = false;
    m_state = State::Idle;
    if (m_actions)
        m_actions->stopProgram();

    if (wasWaiting && stoppedIndex >= 0)
        emit nodeFinished(stoppedIndex, false, QStringLiteral("已停止"));
    emit stateChanged(State::Idle);
    emit finished(false, QStringLiteral("已停止"));
}

void ProgramRunner::finish(bool ok, const QString& error)
{
    m_waiting = false;
    m_state = State::Idle;
    m_index = -1;
    emit stateChanged(State::Idle);
    emit finished(ok, error);
}
