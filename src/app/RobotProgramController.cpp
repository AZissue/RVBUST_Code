#include "app/RobotProgramController.h"

#include "logic/JogPolicy.h"

#include <algorithm>

RobotProgramController::RobotProgramController(RobotMotionBackend* backend,
                                               QObject* parent)
    : QObject(parent), m_backend(backend)
{
    if (m_backend && !m_backend->parent())
        m_backend->setParent(this);

    m_runner = new ProgramRunner(this);
    m_runner->setActions(this);

    m_waitTimer = new QTimer(this);
    m_waitTimer->setSingleShot(true);
    connect(m_waitTimer, &QTimer::timeout, this, [this]() {
        m_runner->notifyNodeFinished(true);
    });

    if (m_backend) {
        connect(m_backend, &RobotMotionBackend::connectedChanged,
                this, &RobotProgramController::connectedChanged);
        connect(m_backend, &RobotMotionBackend::enabledChanged,
                this, &RobotProgramController::enabledChanged);
        connect(m_backend, &RobotMotionBackend::poseUpdated,
                this, &RobotProgramController::poseUpdated);
        connect(m_backend, &RobotMotionBackend::statusMessage,
                this, &RobotProgramController::statusMessage);
        connect(m_backend, &RobotMotionBackend::motionFinished,
                this, &RobotProgramController::onMotionFinished);
    }

    connect(m_runner, &ProgramRunner::programChanged,
            this, &RobotProgramController::programChanged);
    connect(m_runner, &ProgramRunner::stateChanged,
            this, &RobotProgramController::runnerStateChanged);
    connect(m_runner, &ProgramRunner::nodeStarted,
            this, &RobotProgramController::nodeStarted);
    connect(m_runner, &ProgramRunner::nodeFinished,
            this, &RobotProgramController::nodeFinished);
    connect(m_runner, &ProgramRunner::finished,
            this, &RobotProgramController::runFinished);
}

RobotProgramController::~RobotProgramController() = default;

void RobotProgramController::addNode(const RobotProgram::NodePayload& payload)
{
    if (m_runner->isRunning()) {
        emit statusMessage(QStringLiteral("运行中不能修改程序"), true);
        return;
    }
    RobotProgram::Program program = m_runner->program();
    RobotProgram::Node node;
    if (const auto* move = std::get_if<RobotProgram::MoveNode>(&payload)) {
        node = RobotProgram::makeMove(move->target, move->space, move->speedPct);
    } else if (const auto* photo = std::get_if<RobotProgram::PhotoNode>(&payload)) {
        node = RobotProgram::makePhoto(photo->autoSave);
    } else {
        node = RobotProgram::makeWait(std::get<RobotProgram::WaitNode>(payload).seconds);
    }
    program.nodes.push_back(node);
    m_runner->setProgram(program);
}

bool RobotProgramController::removeNode(int index)
{
    if (m_runner->isRunning())
        return false;
    RobotProgram::Program program = m_runner->program();
    if (index < 0 || index >= static_cast<int>(program.nodes.size()))
        return false;
    program.nodes.erase(program.nodes.begin() + index);
    m_runner->setProgram(program);
    return true;
}

bool RobotProgramController::updateMoveTarget(int index,
                                              const RobotMotion::Pose& target)
{
    if (m_runner->isRunning())
        return false;
    RobotProgram::Program program = m_runner->program();
    if (index < 0 || index >= static_cast<int>(program.nodes.size()))
        return false;
    auto* move = std::get_if<RobotProgram::MoveNode>(
        &program.nodes[static_cast<std::size_t>(index)].payload);
    if (!move)
        return false;
    move->target = target;
    *move = RobotProgram::clampMove(*move);
    m_runner->setProgram(program);
    return true;
}

bool RobotProgramController::updateMoveSpeed(int index, double speedPct)
{
    if (m_runner->isRunning())
        return false;
    RobotProgram::Program program = m_runner->program();
    if (index < 0 || index >= static_cast<int>(program.nodes.size()))
        return false;
    auto* move = std::get_if<RobotProgram::MoveNode>(
        &program.nodes[static_cast<std::size_t>(index)].payload);
    if (!move)
        return false;
    move->speedPct = JogPolicy::clampSpeed(speedPct);
    m_runner->setProgram(program);
    return true;
}

void RobotProgramController::runAll()
{
    m_runner->runAll();
}

void RobotProgramController::runOne(int index)
{
    m_runner->runOne(index);
}

void RobotProgramController::stop()
{
    if (m_runner->isRunning()) {
        m_runner->stop();
        return;
    }
    if (m_backend)
        m_backend->stopMotion();
}

void RobotProgramController::connectDevice(const QString& host, quint16 port)
{
    if (m_backend)
        m_backend->connectDevice(host, port);
}

void RobotProgramController::disconnectDevice()
{
    if (m_runner->isRunning())
        m_runner->stop();
    if (m_backend)
        m_backend->disconnectDevice();
}

void RobotProgramController::setEnabled(bool enabled)
{
    if (m_backend)
        m_backend->setEnabled(enabled);
}

void RobotProgramController::setJogSpeed(double speedPct)
{
    m_jogSpeedPct = JogPolicy::clampSpeed(speedPct);
}

void RobotProgramController::jog(int axis, double delta, bool jointMode)
{
    if (!m_backend)
        return;
    if (m_runner->isRunning()) {
        emit statusMessage(QStringLiteral("程序运行中不能点动"), true);
        return;
    }
    const RobotMotion::State st = m_backend->state();
    if (jointMode) {
        RobotMotion::Pose target =
            JogPolicy::jog(st.joint, axis, delta);
        m_backend->moveJoint(JogPolicy::clampJoints(target), m_jogSpeedPct);
    } else {
        RobotMotion::Pose target = JogPolicy::jog(st.cart, axis, delta);
        m_backend->moveCartesian(target, m_jogSpeedPct);
    }
}

void RobotProgramController::moveJointAxisTo(int axis, double degrees)
{
    if (!m_backend || !JogPolicy::validAxis(axis))
        return;
    if (m_runner->isRunning()) {
        emit statusMessage(QStringLiteral("程序运行中不能点动"), true);
        return;
    }
    RobotMotion::Pose target = m_backend->state().joint;
    target[static_cast<std::size_t>(axis)] = JogPolicy::clampJoint(degrees);
    m_backend->moveJoint(target, m_jogSpeedPct);
}

void RobotProgramController::setPhotoHandler(PhotoHandler start, PhotoAbort abort)
{
    m_photoStart = std::move(start);
    m_photoAbort = std::move(abort);
}

void RobotProgramController::notifyPhotoFinished(bool ok, const QString& error)
{
    if (!m_photoPending)
        return;
    m_photoPending = false;
    m_runner->notifyNodeFinished(ok, error);
}

void RobotProgramController::startNode(const RobotProgram::NodePayload& payload)
{
    m_waitTimer->stop();

    if (const auto* move = std::get_if<RobotProgram::MoveNode>(&payload)) {
        if (!m_backend) {
            m_runner->notifyNodeFinished(false, QStringLiteral("未配置运动后端"));
            return;
        }
        const double speed = JogPolicy::clampSpeed(move->speedPct);
        emit statusMessage(
            QStringLiteral("移动至 %1（%2%）")
                .arg(RobotProgram::displayDetail(payload))
                .arg(speed, 0, 'f', 0), false);
        if (move->space == RobotProgram::MoveNode::Space::Joint)
            m_backend->moveJoint(JogPolicy::clampJoints(move->target), speed);
        else
            m_backend->moveCartesian(move->target, speed);
        return;
    }

    if (const auto* wait = std::get_if<RobotProgram::WaitNode>(&payload)) {
        emit statusMessage(QStringLiteral("等待 %1 s")
                               .arg(wait->seconds, 0, 'f', 1), false);
        m_waitTimer->start(static_cast<int>(wait->seconds * 1000.0));
        return;
    }

    // 拍照节点：读位姿 → 拍照 → 识别 → 保存由主窗口的采集链路完成。
    if (!m_photoStart) {
        m_runner->notifyNodeFinished(
            false, QStringLiteral("拍照节点未接入采集链路（请先连接相机）"));
        return;
    }
    QString error;
    if (!m_photoStart(&error)) {
        m_runner->notifyNodeFinished(
            false, error.isEmpty() ? QStringLiteral("无法开始拍照节点") : error);
        return;
    }
    m_photoPending = true;
    emit photoStarted();
}

void RobotProgramController::stopProgram()
{
    m_waitTimer->stop();
    m_photoPending = false;
    if (m_photoAbort)
        m_photoAbort();
    if (m_backend)
        m_backend->stopMotion();
}

void RobotProgramController::onMotionFinished(bool ok, const QString& error)
{
    // 只有执行器正在等这个结果时才会推进；点动/停止后的迟到结果会被忽略。
    m_runner->notifyNodeFinished(ok, error);
}
