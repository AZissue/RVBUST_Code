#include "app/RobotProgramController.h"

#include "logic/FairinoMotionBackend.h"
#include "logic/JogPolicy.h"
#include "logic/PoseOnlyMotionBackend.h"
#include "logic/SimulatedMotionBackend.h"
#include "logic/UrMotionBackend.h"

#include <algorithm>

RobotProgramController::RobotProgramController(RobotMotionBackend* backend,
                                               BackendKind kind,
                                               QObject* parent)
    : QObject(parent)
{
    m_runner = new ProgramRunner(this);
    m_runner->setActions(this);

    m_waitTimer = new QTimer(this);
    m_waitTimer->setSingleShot(true);
    connect(m_waitTimer, &QTimer::timeout, this, [this]() {
        m_runner->notifyNodeFinished(true);
    });

    attachBackend(backend, kind);

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
    connect(m_runner, &ProgramRunner::loopAdvanced,
            this, &RobotProgramController::loopAdvanced);
}

RobotProgramController::~RobotProgramController() = default;

void RobotProgramController::attachBackend(RobotMotionBackend* backend,
                                           BackendKind kind)
{
    m_backend = backend;
    m_backendKind = kind;
    if (!backend)
        return;
    if (!backend->parent())
        backend->setParent(this);

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

void RobotProgramController::detachBackend()
{
    if (!m_backend)
        return;
    m_backend->disconnect(this);
    // 只销毁自己接管的后端；外部已指定 parent 的对象留给它的所有者。
    if (m_backend->parent() == this)
        m_backend->deleteLater();
    m_backend = nullptr;
}

void RobotProgramController::setBackendKind(BackendKind kind)
{
    if (m_backend && m_backendKind == kind)
        return;

    if (m_runner->isRunning())
        m_runner->stop();
    m_waitTimer->stop();
    m_photoPending = false;

    if (m_backend) {
        m_backend->disconnectDevice();
        detachBackend();
    }

    RobotMotionBackend* next = nullptr;
    switch (kind) {
    case BackendKind::Ur:
        next = new UrMotionBackend(this);
        break;
    case BackendKind::Fairino:
        next = new FairinoMotionBackend(this);
        break;
    case BackendKind::Modbus:
        next = new PoseOnlyMotionBackend(PoseOnlyMotionBackend::Kind::Modbus, this);
        break;
    case BackendKind::NrcJson:
        next = new PoseOnlyMotionBackend(PoseOnlyMotionBackend::Kind::NrcJson, this);
        break;
    case BackendKind::Efort:
        next = new PoseOnlyMotionBackend(PoseOnlyMotionBackend::Kind::Efort, this);
        break;
    case BackendKind::Simulated:
        next = new SimulatedMotionBackend(this);
        break;
    }
    attachBackend(next, kind);
    emit backendChanged();
}

QString RobotProgramController::defaultHost(BackendKind kind)
{
    // 法奥控制器的出厂/常见网段是 192.168.58.2（SDK 示例同此）；UR 沿用现场
    // 一直用的 192.168.0.38。Modbus/博纳斯沿用通信页此前的默认 192.168.0.1；
    // 埃夫特同样填 IP（端口由 SDK 固定）。仿真不访问网络。
    switch (kind) {
    case BackendKind::Fairino:
        return QStringLiteral("192.168.58.2");
    case BackendKind::Modbus:
    case BackendKind::NrcJson:
    case BackendKind::Efort:
        return QStringLiteral("192.168.0.1");
    default:
        return QStringLiteral("192.168.0.38");
    }
}

quint16 RobotProgramController::defaultPort(BackendKind kind)
{
    // 法奥控制台连的是 20003 命令口（20004 实时口由后端固定使用）；
    // UR 是 30003 实时反馈；Modbus 502；博纳斯 6001；埃夫特不用端口
    // （SDK 固定 8100），给一个不会误导的 0。
    switch (kind) {
    case BackendKind::Ur:      return 30003;
    case BackendKind::Fairino: return 20003;
    case BackendKind::Modbus:  return 502;
    case BackendKind::NrcJson: return 6001;
    case BackendKind::Efort:   return 0;
    case BackendKind::Simulated: break;
    }
    return 30003;
}

bool RobotProgramController::setProgram(const RobotProgram::Program& program,
                                        QString* error)
{
    if (m_runner->isRunning()) {
        if (error)
            *error = QStringLiteral("机器人程序正在运行，请先停止后再导入。");
        return false;
    }
    m_runner->setProgram(program);   // emits programChanged
    return true;
}

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

bool RobotProgramController::updateWaitSeconds(int index, double seconds)
{
    if (m_runner->isRunning())
        return false;
    RobotProgram::Program program = m_runner->program();
    if (index < 0 || index >= static_cast<int>(program.nodes.size()))
        return false;
    auto* wait = std::get_if<RobotProgram::WaitNode>(
        &program.nodes[static_cast<std::size_t>(index)].payload);
    if (!wait)
        return false;
    wait->seconds = std::clamp(seconds, 0.0, 3600.0);
    m_runner->setProgram(program);
    return true;
}

void RobotProgramController::runAll(int repeats)
{
    m_runner->runAll(repeats);
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

void RobotProgramController::connectDevice(
    const RobotMotion::ConnectOptions& options)
{
    if (m_backend)
        m_backend->connectDevice(options);
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
    // 点动与程序执行共用这一档速度（见 startNode）。
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
    if (jointMode) {
        // 基准由后端用最新反馈算：界面缓存有 50 ms 节流，连续点按时会
        // 从同一个旧值出发，机器人少走一步（看起来像"乱走/不跟手"）。
        m_backend->jogJoint(axis, delta, m_jogSpeedPct);
    } else {
        // 姿态增量由后端按自己的约定合成（UR 是旋转向量，不是欧拉角）。
        m_backend->jogCartesian(axis, delta, m_jogSpeedPct);
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
    m_backend->moveJointAxisTo(axis, degrees, m_jogSpeedPct);
}

void RobotProgramController::setPhotoHandler(PhotoHandler start, PhotoAbort abort)
{
    m_photoStart = std::move(start);
    m_photoAbort = std::move(abort);
}

void RobotProgramController::setRunPreparation(RunPreparation prepare)
{
    m_prepareRun = std::move(prepare);
}

bool RobotProgramController::prepareRun(bool willWriteRecord, QString* error)
{
    // 没注入准备逻辑（单测/无主窗口）时保持"直接跑"。
    if (!m_prepareRun)
        return true;
    return m_prepareRun(willWriteRecord, error);
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
        // 顶部「运行速度」是全局速度：点动与列表执行都用它。节点里存的
        // speedPct 只是创建时的快照（当前界面没有逐节点调速入口），不能再
        // 覆盖用户刚拖动的滑杆——否则滑杆在运行列表时看起来"没用"。
        const double speed = JogPolicy::clampSpeed(m_jogSpeedPct);
        emit statusMessage(
            QStringLiteral("移动至 %1（%2%）")
                .arg(RobotProgram::displayDetail(payload))
                .arg(speed, 0, 'f', 0), false);
        if (move->space == RobotProgram::MoveNode::Space::Joint)
            m_backend->moveJoint(JogPolicy::clampJoints(move->target), speed,
                                 move->toleranceDeg, move->settleTimeoutMs);
        else
            m_backend->moveCartesian(move->target, speed, move->toleranceMm,
                                     move->toleranceDeg, move->settleTimeoutMs);
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
