#include "logic/FairinoMotionBackend.h"

#include "logic/FairinoCommand.h"
#include "logic/FairinoMath.h"
#include "logic/JogPolicy.h"

#include <QNetworkProxy>
#include <QTcpSocket>
#include <QTimer>

#include <algorithm>
#include <cmath>

namespace {

constexpr quint16 kRealtimePort = 20004;
constexpr int kRpcTimeoutMs = 1800;
constexpr int kStreamConnectMs = 2500;
constexpr int kFirstFrameMs = 1800;
constexpr int kStreamStaleMs = 1500;
constexpr int kPoseFreshMs = 500;
constexpr int kPublishIntervalMs = 50;
constexpr int kSettleMs = 400;

FairinoMath::Pose6 toMathPose(const RobotMotion::Pose& pose)
{
    return FairinoMath::Pose6{ pose[0], pose[1], pose[2],
                               pose[3], pose[4], pose[5] };
}

RobotMotion::Pose toMotionPose(const FairinoMath::Pose6& pose)
{
    return RobotMotion::Pose{ pose[0], pose[1], pose[2],
                              pose[3], pose[4], pose[5] };
}

bool sixNumbers(const QList<FairinoXmlRpc::Value>& values, int first,
                RobotMotion::Pose* out)
{
    if (!out || values.size() < first + 6)
        return false;
    for (int i = 0; i < 6; ++i) {
        double v = 0.0;
        if (!values.at(first + i).asDouble(&v) || !std::isfinite(v))
            return false;
        (*out)[static_cast<std::size_t>(i)] = v;
    }
    return true;
}

QString jointSpaceHint()
{
    return QStringLiteral("请确认控制器处于自动模式、已上使能、无故障码，"
                          "且目标在工作空间内");
}

} // namespace

// ── Worker ────────────────────────────────────────────────────────────

FairinoMotionWorker::FairinoMotionWorker(QObject* parent) : QObject(parent) {}

FairinoMotionWorker::~FairinoMotionWorker() = default;

void FairinoMotionWorker::start(const QString& host, quint16 rpcPort)
{
    if (m_connected || m_stream)
        teardown(true);

    m_host = host.trimmed();
    m_rpcPort = rpcPort == 0 ? 20003 : rpcPort;
    m_rpc.setEndpoint(m_host, m_rpcPort);
    m_rpc.setTimeoutMs(kRpcTimeoutMs);

    m_parser.clear();
    m_raw = FairinoRealtime::State{};
    m_state = RobotMotion::State{};
    m_haveState = false;
    m_connected = false;
    m_armed = false;
    m_hwEnabled = false;
    m_enabledReported = false;
    m_motionInFlight = false;
    m_streamWarned = false;
    m_withinTolerance = false;
    m_pending = PendingMove{};
    m_queuedActive = false;
    m_queued = PendingMove{};
    m_lastMainCode = 0;
    m_lastSubCode = 0;
    m_lastPublishAt.invalidate();

    emit statusMessage(
        QStringLiteral("正在连接法奥 %1（XML-RPC %2 / 实时 %3）…")
            .arg(m_host).arg(m_rpcPort).arg(kRealtimePort),
        false);

    // 1) 命令口 20003：用 GetControllerIP 做一次真实的请求/应答，而不是只看
    //    TCP 能不能连上。连不上就不进入"已连接"状态，避免"界面已连接但点不动"。
    QList<FairinoXmlRpc::Value> values;
    QString error;
    if (!m_rpc.callOk(QStringLiteral("GetControllerIP"),
                      QList<FairinoXmlRpc::Value>(), values, &error)) {
        emit statusMessage(QStringLiteral("连接法奥失败：%1").arg(error), true);
        emit connectedChanged(false);
        return;
    }

    // 2) 实时口 20004：没有它就没有位姿、使能和到位判据，因此是连接的前提。
    m_stream = new QTcpSocket(this);
    m_stream->setProxy(QNetworkProxy::NoProxy);
    QObject::connect(m_stream, &QTcpSocket::readyRead, this,
                     &FairinoMotionWorker::onStreamReady);
    QObject::connect(m_stream, &QTcpSocket::disconnected, this,
                     &FairinoMotionWorker::onStreamDisconnected);
    m_stream->connectToHost(m_host, kRealtimePort);
    if (!m_stream->waitForConnected(kStreamConnectMs)) {
        const QString text =
            QStringLiteral("连接法奥实时口 %1:%2 失败：%3")
                .arg(m_host).arg(kRealtimePort).arg(m_stream->errorString());
        emit statusMessage(text, true);
        teardown(false);
        emit connectedChanged(false);
        return;
    }

    QElapsedTimer timer;
    timer.start();
    while (!m_haveState && timer.elapsed() < kFirstFrameMs) {
        const int remaining = kFirstFrameMs - static_cast<int>(timer.elapsed());
        if (remaining <= 0)
            break;
        if (m_stream->bytesAvailable() <= 0)
            m_stream->waitForReadyRead(remaining);
        onStreamReady();
    }
    if (!m_haveState) {
        emit statusMessage(
            QStringLiteral("法奥实时口 20004 已连接，但 %1 ms 内没有有效状态包"
                           "（校验失败 %2 帧、丢弃 %3 字节）；无法判断位姿/到位，"
                           "已断开。请确认控制器固件与 20004 包格式一致。")
                .arg(kFirstFrameMs)
                .arg(m_parser.rejectedChecksums())
                .arg(m_parser.skippedBytes()),
            true);
        teardown(false);
        emit connectedChanged(false);
        return;
    }

    m_connected = true;
    m_armed = false;
    m_hwEnabled = m_raw.enabled != 0;
    m_enabledReported = false;
    publishEnabled();

    if (!m_watchdog) {
        m_watchdog = new QTimer(this);
        m_watchdog->setInterval(500);
        QObject::connect(m_watchdog, &QTimer::timeout, this,
                         &FairinoMotionWorker::checkStream);
    }
    m_watchdog->start();

    emit connectedChanged(true);

    const QString mode = m_raw.robotMode == 0
        ? QStringLiteral("自动模式")
        : QStringLiteral("手动模式（%1）")
              .arg(static_cast<int>(m_raw.robotMode));
    const QString enable = m_hwEnabled ? QStringLiteral("已上使能")
                                       : QStringLiteral("未上使能");
    emit statusMessage(
        QStringLiteral("法奥已连接（%1）：%2，%3。点击「开启使能」后才会下发"
                       "运动指令。")
            .arg(m_host, mode, enable),
        false);
    if (m_raw.robotMode != 0) {
        emit statusMessage(
            QStringLiteral("法奥当前不是自动模式（robot_mode=%1）；若运动指令"
                           "被拒绝，请先在示教器切换到自动模式。")
                .arg(static_cast<int>(m_raw.robotMode)),
            true);
    }
    reportFaults(m_raw);
}

void FairinoMotionWorker::shutdown()
{
    teardown(true);
    if (m_watchdog)
        m_watchdog->stop();
}

void FairinoMotionWorker::teardown(bool notify)
{
    if (m_watchdog)
        m_watchdog->stop();

    // 断开/关闭时不要留下我们下发的运动。只在"确实有运动在飞"时发
    // StopMotion，避免停掉示教器上别人正在跑的程序。等不到应答也要继续
    // 关连接（本函数不能无限等）。
    if (m_connected && m_motionInFlight) {
        QList<FairinoXmlRpc::Value> values;
        QString ignored;
        m_rpc.callOk(QStringLiteral("StopMotion"),
                     QList<FairinoXmlRpc::Value>(), values, &ignored);
    }

    const bool wasConnected = m_connected;
    const bool wasEnabled = m_enabledReported;
    if (m_pending.active) {
        m_pending.active = false;
        emit motionFinished(false, QStringLiteral("连接已断开"));
    }

    m_connected = false;
    m_armed = false;
    m_hwEnabled = false;
    m_enabledReported = false;
    m_motionInFlight = false;
    m_haveState = false;
    m_streamWarned = false;
    m_withinTolerance = false;
    m_pending = PendingMove{};
    m_queuedActive = false;
    m_queued = PendingMove{};
    m_state = RobotMotion::State{};
    m_raw = FairinoRealtime::State{};
    m_parser.clear();
    m_lastPublishAt.invalidate();
    m_lastMainCode = 0;
    m_lastSubCode = 0;

    if (m_stream) {
        QObject::disconnect(m_stream, nullptr, this, nullptr);
        if (m_stream->state() != QAbstractSocket::UnconnectedState)
            m_stream->disconnectFromHost();
        m_stream->deleteLater();
        m_stream = nullptr;
    }

    if (notify && wasConnected)
        emit connectedChanged(false);
    if (notify && wasEnabled)
        emit enabledChanged(false);
}

void FairinoMotionWorker::publishEnabled()
{
    const bool reported = m_armed && m_hwEnabled;
    if (reported == m_enabledReported)
        return;
    m_enabledReported = reported;
    emit enabledChanged(reported);
}

void FairinoMotionWorker::setEnabled(bool enabled)
{
    if (enabled) {
        if (!m_connected) {
            emit statusMessage(QStringLiteral("请先连接法奥"), true);
            if (m_enabledReported) {
                m_armed = false;
                publishEnabled();
            }
            return;
        }
        QList<FairinoXmlRpc::Value> values;
        QString error;
        if (!m_rpc.callOk(QStringLiteral("RobotEnable"),
                          FairinoCommand::enableParams(true), values, &error)) {
            emit statusMessage(QStringLiteral("上使能失败：%1").arg(error), true);
            m_armed = false;
            publishEnabled();
            return;
        }
        m_armed = true;
        // 指令已接受；先乐观地把界面切到"已使能"，下一帧 rbtEnableState 会
        // 把它纠正成控制器的真实状态（避免按钮闪回未选中的假象）。
        m_hwEnabled = true;
        publishEnabled();
        emit statusMessage(
            QStringLiteral("已发送上使能；若被拒绝，请先清除控制器故障码"
                           "（部分固件要求先在示教器手动模式上使能）"),
            false);
        if (m_raw.mainCode != 0 || m_raw.subCode != 0) {
            emit statusMessage(
                QStringLiteral("控制器仍有故障码 main=%1 sub=%2，运动指令会被拒绝")
                    .arg(m_raw.mainCode).arg(m_raw.subCode),
                true);
        }
        return;
    }

    if (m_pending.active || m_motionInFlight)
        stopMotion();
    m_armed = false;
    m_hwEnabled = false;
    publishEnabled();
    if (!m_connected)
        return;

    QList<FairinoXmlRpc::Value> values;
    QString error;
    if (!m_rpc.callOk(QStringLiteral("RobotEnable"),
                      FairinoCommand::enableParams(false), values, &error)) {
        emit statusMessage(QStringLiteral("下使能失败：%1").arg(error), true);
        return;
    }
    emit statusMessage(QStringLiteral("已下使能，运动指令将被拒绝"), false);
}

bool FairinoMotionWorker::ensureReady(const QString& action)
{
    if (!m_connected) {
        emit statusMessage(QStringLiteral("%1失败：未连接法奥").arg(action), true);
        emit motionFinished(false, QStringLiteral("未连接法奥"));
        return false;
    }
    if (!m_enabledReported) {
        emit statusMessage(QStringLiteral("%1失败：未使能").arg(action), true);
        emit motionFinished(false, QStringLiteral("未使能"));
        return false;
    }
    if (!m_haveState || !m_lastFrameAt.isValid()
        || m_lastFrameAt.elapsed() > kPoseFreshMs) {
        emit statusMessage(
            QStringLiteral("%1失败：%2 ms 内没有新的实时位姿（20004）")
                .arg(action).arg(kPoseFreshMs), true);
        emit motionFinished(false, QStringLiteral("实时位姿不新鲜"));
        return false;
    }
    if (m_raw.mainCode != 0 || m_raw.subCode != 0) {
        const QString text =
            QStringLiteral("%1失败：控制器故障码 main=%2 sub=%3，请先在示教器复位")
                .arg(action).arg(m_raw.mainCode).arg(m_raw.subCode);
        emit statusMessage(text, true);
        emit motionFinished(false, text);
        return false;
    }
    if (!m_stream
        || m_stream->state() != QAbstractSocket::ConnectedState) {
        emit statusMessage(
            QStringLiteral("%1失败：实时口 20004 未连接").arg(action), true);
        emit motionFinished(false, QStringLiteral("实时口 20004 未连接"));
        return false;
    }
    return true;
}

bool FairinoMotionWorker::targetFrameIds(int* tool, int* user)
{
    // 用控制器当前的工具/工件号，和读到的 TCP 位姿保持同一坐标系。
    const int t = m_raw.toolId;
    const int u = m_raw.userId;
    if (tool)
        *tool = (t >= 0 && t <= 14) ? t : 0;
    if (user)
        *user = (u >= 0 && u <= 14) ? u : 0;
    return t >= 0 && t <= 14 && u >= 0 && u <= 14;
}

bool FairinoMotionWorker::callOk(const QString& method,
                                 const QList<FairinoXmlRpc::Value>& params,
                                 QList<FairinoXmlRpc::Value>& values,
                                 const QString& action)
{
    QString error;
    if (!m_rpc.callOk(method, params, values, &error)) {
        emit statusMessage(QStringLiteral("%1失败：%2").arg(action, error), true);
        return false;
    }
    return true;
}

bool FairinoMotionWorker::solveInverseKin(const RobotMotion::Pose& cart,
                                          RobotMotion::Pose* joint,
                                          QString* error)
{
    QList<FairinoXmlRpc::Value> values;
    if (!callOk(QStringLiteral("GetInverseKin"),
                FairinoCommand::inverseKinParams(toMathPose(cart)), values,
                QStringLiteral("逆解"))) {
        if (error)
            *error = m_rpc.lastError();
        return false;
    }
    if (!sixNumbers(values, 1, joint)) {
        if (error)
            *error = QStringLiteral("逆解应答缺少 6 个有效关节值");
        return false;
    }
    return true;
}

bool FairinoMotionWorker::solveForwardKin(const RobotMotion::Pose& joint,
                                          RobotMotion::Pose* cart,
                                          QString* error)
{
    QList<FairinoXmlRpc::Value> values;
    if (!callOk(QStringLiteral("GetForwardKin"),
                FairinoCommand::forwardKinParams(toMathPose(joint)), values,
                QStringLiteral("正解"))) {
        if (error)
            *error = m_rpc.lastError();
        return false;
    }
    if (!sixNumbers(values, 1, cart)) {
        if (error)
            *error = QStringLiteral("正解应答缺少 6 个有效位姿值");
        return false;
    }
    return true;
}

void FairinoMotionWorker::moveCartesian(const RobotMotion::Pose& target,
                                        double speedPct, double toleranceMm,
                                        double toleranceDeg, int timeoutMs)
{
    if (!ensureReady(QStringLiteral("笛卡尔移动")))
        return;
    if (!FairinoMath::poseFinite(toMathPose(target))) {
        emit motionFinished(false, QStringLiteral("目标位姿含 NaN/Inf"));
        return;
    }
    beginMove(target, speedPct, toleranceMm, toleranceDeg, timeoutMs, false,
              false);
}

void FairinoMotionWorker::moveJoint(const RobotMotion::Pose& target,
                                    double speedPct, double toleranceDeg,
                                    int timeoutMs)
{
    if (!ensureReady(QStringLiteral("关节移动")))
        return;
    RobotMotion::Pose clamped = target;
    for (double& v : clamped)
        v = JogPolicy::clampJoint(v);
    if (!FairinoMath::poseFinite(toMathPose(clamped))) {
        emit motionFinished(false, QStringLiteral("目标关节含 NaN/Inf"));
        return;
    }
    beginMove(clamped, speedPct, 2.0, toleranceDeg, timeoutMs, true, false);
}

void FairinoMotionWorker::jogCartesian(int axis, double delta,
                                       double speedPct)
{
    if (!ensureReady(QStringLiteral("点动")))
        return;
    if (!JogPolicy::validAxis(axis)) {
        emit motionFinished(false, QStringLiteral("点动轴无效"));
        return;
    }

    const RobotMotion::Pose base = latestJogBase(false);
    RobotMotion::Pose target = base;
    if (axis < 3) {
        target[static_cast<std::size_t>(axis)] += delta;
    } else {
        const FairinoMath::Vec3 rotated =
            FairinoMath::rotateEulerAboutBaseAxisDeg(
                FairinoMath::Vec3{ base[3], base[4], base[5] }, axis - 3,
                delta);
        target[3] = rotated[0];
        target[4] = rotated[1];
        target[5] = rotated[2];
    }
    beginMove(target, speedPct, 0.2, 0.2, 10000, false, true);
}

void FairinoMotionWorker::jogJoint(int axis, double delta, double speedPct)
{
    if (!ensureReady(QStringLiteral("关节点动")))
        return;
    if (!JogPolicy::validAxis(axis)) {
        emit motionFinished(false, QStringLiteral("点动轴无效"));
        return;
    }
    const RobotMotion::Pose base = latestJogBase(true);
    const RobotMotion::Pose target =
        JogPolicy::clampJoints(JogPolicy::jog(base, axis, delta));
    beginMove(target, speedPct, 2.0, 0.2, 10000, true, true);
}

void FairinoMotionWorker::moveJointAxisTo(int axis, double degrees,
                                          double speedPct)
{
    if (!ensureReady(QStringLiteral("关节滑杆")))
        return;
    if (!JogPolicy::validAxis(axis) || !std::isfinite(degrees)) {
        emit motionFinished(false, QStringLiteral("关节轴或角度无效"));
        return;
    }
    RobotMotion::Pose target = latestJogBase(true);
    target[static_cast<std::size_t>(axis)] = JogPolicy::clampJoint(degrees);
    beginMove(JogPolicy::clampJoints(target), speedPct, 2.0, 0.2, 10000,
              true, true);
}

RobotMotion::Pose FairinoMotionWorker::latestJogBase(bool joint) const
{
    if (m_queuedActive && m_queued.joint == joint)
        return m_queued.target;
    if (m_pending.active && m_pending.joint == joint)
        return m_pending.target;
    return joint ? m_state.joint : m_state.cart;
}

void FairinoMotionWorker::beginMove(const RobotMotion::Pose& target,
                                    double speedPct, double toleranceMm,
                                    double toleranceDeg, int timeoutMs,
                                    bool joint, bool jog)
{
    // 长按点动：上一条还在飞就只记住最新目标，等它到位再发。法奥控制器
    // 自己也会排队，但把几十条 1 mm 的 MoveL 全塞进去，松手后还会多走。
    if (jog && m_pending.active && m_pending.jog
        && m_pending.joint == joint) {
        m_queued = PendingMove{};
        m_queued.active = true;
        m_queued.joint = joint;
        m_queued.jog = true;
        m_queued.target = target;
        m_queued.speedPct = JogPolicy::clampSpeed(speedPct);
        m_queued.toleranceMm = toleranceMm;
        m_queued.toleranceDeg = toleranceDeg;
        m_queued.timeoutMs = timeoutMs;
        m_queuedActive = true;
        return;
    }
    if (!jog) {
        m_queuedActive = false;
        m_queued = PendingMove{};
    }

    m_pending = PendingMove{};
    m_pending.active = true;
    m_pending.joint = joint;
    m_pending.jog = jog;
    m_pending.target = target;
    m_pending.speedPct = JogPolicy::clampSpeed(speedPct);
    m_pending.toleranceMm = toleranceMm;
    m_pending.toleranceDeg = toleranceDeg;
    m_pending.timeoutMs = timeoutMs;
    m_pending.elapsed.start();
    m_motionInFlight = true;
    m_withinTolerance = false;

    int tool = 0;
    int user = 0;
    if (!targetFrameIds(&tool, &user)) {
        emit statusMessage(
            QStringLiteral("控制器工具号/工件号超出 0~14（tool=%1, user=%2），"
                           "本次按 0/0 下发；请检查示教器坐标系设置")
                .arg(m_raw.toolId).arg(m_raw.userId),
            true);
    }

    QList<FairinoXmlRpc::Value> values;
    QString error;
    const auto dispatch = [&](const QString& method,
                              const QList<FairinoXmlRpc::Value>& params) {
        if (m_rpc.callOk(method, params, values, &error))
            return true;
        // 官方协议：MoveL/MoveJ 返回错误码即"已接收"，不代表到位；正常
        // 应立刻返回。若应答在 1.8 s 内没回来，先别判失败：有些固件会
        // 等运动结束才回包。此时以 20004 的 robot_state/motion_done 为准
        // 继续等待到位；真的没动，15 s 的 pending 超时会如实报出来。
        if (error.contains(QStringLiteral("超时"))
            && m_haveState
            && (m_raw.robotState == 2 || m_raw.motionDone == 0)) {
            emit statusMessage(
                QStringLiteral("%1 应答超时，但控制器状态显示运动已开始；"
                               "继续按 20004 等待到位。请现场确认机器人是否"
                               "真的在动。")
                    .arg(method),
                true);
            return true;
        }
        return false;
    };

    if (!joint) {
        RobotMotion::Pose solved{};
        if (!solveInverseKin(target, &solved, &error)) {
            m_motionInFlight = false;
            finishPending(false, error, false, false);
            return;
        }
        if (!dispatch(QStringLiteral("MoveL"),
                      FairinoCommand::moveLParams(toMathPose(solved),
                                                  toMathPose(target), tool,
                                                  user, m_pending.speedPct))) {
            m_motionInFlight = false;
            finishPending(false, error, false, false);
            return;
        }
    } else {
        RobotMotion::Pose desc{};
        if (!solveForwardKin(target, &desc, &error)) {
            m_motionInFlight = false;
            finishPending(false, error, false, false);
            return;
        }
        if (!dispatch(QStringLiteral("MoveJ"),
                      FairinoCommand::moveJParams(toMathPose(target),
                                                  toMathPose(desc), tool, user,
                                                  m_pending.speedPct))) {
            m_motionInFlight = false;
            finishPending(false, error, false, false);
            return;
        }
    }

    if (jog)
        emit statusMessage(QStringLiteral("点动中…"), false);
}

void FairinoMotionWorker::finishPending(bool ok, const QString& error,
                                        bool motionMayContinue,
                                        bool announceArrival)
{
    const bool wasJog = m_pending.jog;
    m_pending.active = false;
    m_withinTolerance = false;
    if (!motionMayContinue)
        m_motionInFlight = false;
    if (!ok) {
        m_queuedActive = false;
        m_queued = PendingMove{};
    }
    const bool chain = ok && m_queuedActive && m_enabledReported;
    PendingMove next;
    if (chain) {
        next = m_queued;
        m_queuedActive = false;
        m_queued = PendingMove{};
    }
    emit motionFinished(ok, error);
    if (ok && announceArrival && !wasJog)
        emit statusMessage(QStringLiteral("已到达目标位姿"), false);
    if (chain) {
        beginMove(next.target, next.speedPct, next.toleranceMm,
                  next.toleranceDeg, next.timeoutMs, next.joint, next.jog);
    }
}

void FairinoMotionWorker::stopMotion()
{
    const bool inFlight =
        m_pending.active || m_queuedActive || m_motionInFlight;
    m_withinTolerance = false;
    m_queuedActive = false;
    m_queued = PendingMove{};
    if (m_pending.active) {
        m_pending.active = false;
        emit motionFinished(false, QStringLiteral("已停止"));
    }
    if (!inFlight) {
        emit statusMessage(QStringLiteral("当前没有运动"), false);
        return;
    }
    m_motionInFlight = false;

    QList<FairinoXmlRpc::Value> values;
    QString error;
    if (m_rpc.callOk(QStringLiteral("StopMotion"),
                     QList<FairinoXmlRpc::Value>(), values, &error)) {
        emit statusMessage(QStringLiteral("已发送停止（StopMotion）"), false);
    } else {
        emit statusMessage(
            QStringLiteral("本地已停止等待，但 StopMotion 失败：%1；"
                           "如仍在运动请用示教器停止")
                .arg(error),
            true);
    }
}

void FairinoMotionWorker::onStreamReady()
{
    if (!m_stream)
        return;
    FairinoRealtime::State state;
    const int accepted = m_parser.feed(m_stream->readAll(), &state);
    if (accepted > 0) {
        m_haveState = true;
        m_lastFrameAt.start();
        if (m_streamWarned) {
            m_streamWarned = false;
            emit statusMessage(QStringLiteral("法奥实时数据流已恢复"), false);
        }
        onStreamState(state);
    }
}

void FairinoMotionWorker::onStreamState(const FairinoRealtime::State& state)
{
    m_raw = state;
    for (std::size_t i = 0; i < 6; ++i) {
        m_state.cart[i] = state.tcp[i];
        m_state.joint[i] = state.joint[i];
    }
    m_state.hasJoint = true;

    if (!m_lastPublishAt.isValid()
        || m_lastPublishAt.elapsed() >= kPublishIntervalMs) {
        m_lastPublishAt.restart();
        emit poseUpdated(m_state);
    }

    const bool hwEnabled = state.enabled != 0;
    if (hwEnabled != m_hwEnabled) {
        m_hwEnabled = hwEnabled;
        publishEnabled();
        if (!hwEnabled) {
            emit statusMessage(
                QStringLiteral("控制器下使能或急停（rbtEnableState=0）"), true);
        }
    }

    reportFaults(state);

    if (m_motionInFlight && m_pending.active && !hwEnabled) {
        finishPending(false,
                      QStringLiteral("控制器已下使能/急停，运动被中断"), false,
                      false);
    } else if (m_motionInFlight && !m_pending.active
               && state.motionDone == 1 && state.queueLength == 0) {
        // 超时/停止后机器人自己走完：只清"可能还在动"，不再发 motionFinished。
        m_motionInFlight = false;
    }

    checkReached();
}

void FairinoMotionWorker::reportFaults(const FairinoRealtime::State& state)
{
    if (state.mainCode == m_lastMainCode && state.subCode == m_lastSubCode)
        return;
    const bool hadFault = m_lastMainCode != 0 || m_lastSubCode != 0;
    m_lastMainCode = state.mainCode;
    m_lastSubCode = state.subCode;
    if (m_lastMainCode != 0 || m_lastSubCode != 0) {
        emit statusMessage(
            QStringLiteral("法奥控制器故障码 main=%1 sub=%2；请先在示教器"
                           "查看/复位，运动指令会被拒绝")
                .arg(m_lastMainCode).arg(m_lastSubCode),
            true);
    } else if (hadFault) {
        emit statusMessage(QStringLiteral("法奥控制器故障码已清除"), false);
    }
}

void FairinoMotionWorker::checkReached()
{
    if (!m_pending.active)
        return;

    const bool reached = m_pending.joint
        ? FairinoMath::reachedJoint(toMathPose(m_state.joint),
                                    toMathPose(m_pending.target),
                                    m_pending.toleranceDeg)
        : FairinoMath::reachedCartesian(toMathPose(m_state.cart),
                                        toMathPose(m_pending.target),
                                        m_pending.toleranceMm,
                                        m_pending.toleranceDeg);

    if (reached) {
        if (m_raw.motionDone == 1 && m_raw.queueLength == 0) {
            finishPending(true, QString(), false, true);
            return;
        }
        // 有些固件在短距离运动时 motion_done 不一定置位；位置/姿态连续
        // 400 ms 在容差内且队列为空，同样可以判定到位（并写日志）。
        if (!m_withinTolerance) {
            m_withinTolerance = true;
            m_withinToleranceAt.start();
        } else if (m_withinToleranceAt.elapsed() >= kSettleMs
                   && m_raw.queueLength == 0) {
            emit statusMessage(
                QStringLiteral("motion_done 未置位，按位置稳定 %1 ms 判定到位")
                    .arg(kSettleMs),
                false);
            finishPending(true, QString(), false, true);
            return;
        }
    } else {
        m_withinTolerance = false;
    }

    if (m_pending.elapsed.elapsed() > m_pending.timeoutMs) {
        finishPending(
            false,
            QStringLiteral("超时未到位（%1 ms）。%2（robot_mode=%3, "
                           "enabled=%4, motion_done=%5, queue=%6）")
                .arg(m_pending.timeoutMs)
                .arg(jointSpaceHint())
                .arg(static_cast<int>(m_raw.robotMode))
                .arg(m_raw.enabled)
                .arg(m_raw.motionDone)
                .arg(m_raw.queueLength),
            true, false);
    }
}

void FairinoMotionWorker::checkStream()
{
    if (!m_connected)
        return;
    if (!m_lastFrameAt.isValid() || m_lastFrameAt.elapsed() > kStreamStaleMs) {
        if (!m_streamWarned) {
            m_streamWarned = true;
            emit statusMessage(
                QStringLiteral("法奥实时口 20004 已 %1 ms 没有数据")
                    .arg(m_lastFrameAt.isValid() ? m_lastFrameAt.elapsed()
                                                 : kStreamStaleMs),
                true);
        }
    }
    if (m_motionInFlight && !m_pending.active && m_raw.motionDone == 1
        && m_raw.queueLength == 0) {
        m_motionInFlight = false;
    }
}

void FairinoMotionWorker::onStreamDisconnected()
{
    if (!m_connected)
        return;
    emit statusMessage(QStringLiteral("法奥实时口连接已断开"), true);
    teardown(true);
}

// ── 后端门面（UI 线程）────────────────────────────────────────────────

FairinoMotionBackend::FairinoMotionBackend(QObject* parent)
    : RobotMotionBackend(parent)
{
    m_thread = new QThread(this);
    m_worker = new FairinoMotionWorker;
    m_worker->moveToThread(m_thread);

    connect(m_worker, &FairinoMotionWorker::connectedChanged, this,
            [this](bool connected) {
                m_connected = connected;
                if (!connected)
                    m_enabled = false;
                emit connectedChanged(connected);
            });
    connect(m_worker, &FairinoMotionWorker::enabledChanged, this,
            [this](bool enabled) {
                m_enabled = enabled;
                emit enabledChanged(enabled);
            });
    connect(m_worker, &FairinoMotionWorker::poseUpdated, this,
            [this](const RobotMotion::State& state) {
                m_state = state;
                emit poseUpdated(state);
            });
    connect(m_worker, &FairinoMotionWorker::motionFinished, this,
            &FairinoMotionBackend::motionFinished);
    connect(m_worker, &FairinoMotionWorker::statusMessage, this,
            &FairinoMotionBackend::statusMessage);

    connect(m_thread, &QThread::finished, m_worker, &QObject::deleteLater);
    m_thread->start();
}

FairinoMotionBackend::~FairinoMotionBackend()
{
    if (m_thread && m_thread->isRunning()) {
        QMetaObject::invokeMethod(
            m_worker, [worker = m_worker]() { worker->shutdown(); },
            Qt::BlockingQueuedConnection);
        m_thread->quit();
        m_thread->wait();
    }
}

void FairinoMotionBackend::connectDevice(const QString& host, quint16 port)
{
    QMetaObject::invokeMethod(
        m_worker,
        [worker = m_worker, host, port]() { worker->start(host, port); },
        Qt::QueuedConnection);
}

void FairinoMotionBackend::disconnectDevice()
{
    QMetaObject::invokeMethod(
        m_worker, [worker = m_worker]() { worker->shutdown(); },
        Qt::QueuedConnection);
}

void FairinoMotionBackend::setEnabled(bool enabled)
{
    QMetaObject::invokeMethod(
        m_worker, [worker = m_worker, enabled]() { worker->setEnabled(enabled); },
        Qt::QueuedConnection);
}

void FairinoMotionBackend::moveCartesian(const RobotMotion::Pose& target,
                                         double speedPct, double toleranceMm,
                                         double toleranceDeg, int timeoutMs)
{
    QMetaObject::invokeMethod(
        m_worker,
        [worker = m_worker, target, speedPct, toleranceMm, toleranceDeg,
         timeoutMs]() {
            worker->moveCartesian(target, speedPct, toleranceMm, toleranceDeg,
                                  timeoutMs);
        },
        Qt::QueuedConnection);
}

void FairinoMotionBackend::moveJoint(const RobotMotion::Pose& target,
                                     double speedPct, double toleranceDeg,
                                     int timeoutMs)
{
    QMetaObject::invokeMethod(
        m_worker,
        [worker = m_worker, target, speedPct, toleranceDeg, timeoutMs]() {
            worker->moveJoint(target, speedPct, toleranceDeg, timeoutMs);
        },
        Qt::QueuedConnection);
}

void FairinoMotionBackend::jogCartesian(int axis, double delta,
                                        double speedPct)
{
    QMetaObject::invokeMethod(
        m_worker, [worker = m_worker, axis, delta, speedPct]() {
            worker->jogCartesian(axis, delta, speedPct);
        },
        Qt::QueuedConnection);
}

void FairinoMotionBackend::jogJoint(int axis, double delta, double speedPct)
{
    QMetaObject::invokeMethod(
        m_worker, [worker = m_worker, axis, delta, speedPct]() {
            worker->jogJoint(axis, delta, speedPct);
        },
        Qt::QueuedConnection);
}

void FairinoMotionBackend::moveJointAxisTo(int axis, double degrees,
                                           double speedPct)
{
    QMetaObject::invokeMethod(
        m_worker, [worker = m_worker, axis, degrees, speedPct]() {
            worker->moveJointAxisTo(axis, degrees, speedPct);
        },
        Qt::QueuedConnection);
}

void FairinoMotionBackend::stopMotion()
{
    QMetaObject::invokeMethod(
        m_worker, [worker = m_worker]() { worker->stopMotion(); },
        Qt::QueuedConnection);
}
