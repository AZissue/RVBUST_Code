#include "logic/UrMotionBackend.h"

#include "logic/JogPolicy.h"

#include <QDataStream>
#include <QNetworkProxy>
#include <QTcpSocket>
#include <QTimer>

#include <algorithm>
#include <cmath>
#include <utility>

namespace {

// UR 侧端口。30003 由调用方给出（实时反馈）；脚本与 Dashboard 是固定的。
constexpr quint16 kScriptPort = 30001;
constexpr quint16 kDashboardPort = 29999;

// 30003 包体布局（偏移相对 4 字节长度前缀之后的 body），与
// logic/URRealtimeReader.cpp 中的实测常量一致：
//   body 248 = q_actual     (6 × double, 弧度)
//   body 440 = actual_TCP_pose (6 × double, 米 + 旋转向量弧度)
constexpr int kJointOffset = 8 + 48 * 5;   // 248
constexpr int kPoseOffset = 8 + 48 * 9;    // 440
constexpr int kFieldBytes = 48;
constexpr int kHeaderBytes = 4;
constexpr quint32 kMaxPacket = 8192;
constexpr int kMaxBuffered = 1 << 20;

quint32 beU32(const char* p)
{
    return (quint32(static_cast<quint8>(p[0])) << 24)
         | (quint32(static_cast<quint8>(p[1])) << 16)
         | (quint32(static_cast<quint8>(p[2])) << 8)
         |  quint32(static_cast<quint8>(p[3]));
}

QString num(double v)
{
    // URScript 的浮点字面量；避免 -0.000000 这种无意义写法。
    if (std::abs(v) < 1e-12)
        v = 0.0;
    return QString::number(v, 'f', 6);
}

bool readDoubles(const QByteArray& packet, int bodyOffset, double out[6])
{
    if (packet.size() < kHeaderBytes + bodyOffset + kFieldBytes)
        return false;
    QDataStream ds(packet);
    ds.setByteOrder(QDataStream::BigEndian);
    ds.skipRawData(kHeaderBytes + bodyOffset);
    for (int i = 0; i < 6; ++i) {
        ds >> out[i];
        if (!std::isfinite(out[i]))
            return false;
    }
    return true;
}

} // namespace

// ── Worker ────────────────────────────────────────────────────────────

UrMotionWorker::UrMotionWorker(QObject* parent) : QObject(parent) {}

UrMotionWorker::~UrMotionWorker()
{
    // 正常情况下 shutdown() 已经跑过；析构时 socket 由父子关系回收。
    if (m_feedback)
        QObject::disconnect(m_feedback, nullptr, this, nullptr);
    if (m_script)
        QObject::disconnect(m_script, nullptr, this, nullptr);
    if (m_dashboard)
        QObject::disconnect(m_dashboard, nullptr, this, nullptr);
}

void UrMotionWorker::start(const QString& host, quint16 feedbackPort)
{
    if (m_connected)
        teardown(true);
    else if (m_feedback || m_script || m_dashboard)
        teardown(false);

    emit statusMessage(
        QStringLiteral("正在连接 UR %1（反馈 %2 / 脚本 %3 / 控制 %4）…")
            .arg(host).arg(feedbackPort).arg(kScriptPort).arg(kDashboardPort),
        false);

    auto makeSocket = [](QTcpSocket*& socket, QObject* owner) {
        socket = new QTcpSocket(owner);
        // VM 上常被系统代理干扰：原始 TCP 端口必须直连。
        socket->setProxy(QNetworkProxy::NoProxy);
    };

    // 1) 实时反馈。没有它就没有位姿、也没法判断到位，因此是连接的前提。
    makeSocket(m_feedback, this);
    QObject::connect(m_feedback, &QTcpSocket::readyRead, this,
                     &UrMotionWorker::onFeedbackReady);
    QObject::connect(m_feedback, &QTcpSocket::disconnected, this,
                     &UrMotionWorker::onDisconnected);
    m_feedback->connectToHost(host, feedbackPort);
    if (!m_feedback->waitForConnected(3000)) {
        const QString error =
            QStringLiteral("连接 UR 实时端口 %1:%2 失败：%3（state=%4, err=%5）")
                .arg(host).arg(feedbackPort).arg(m_feedback->errorString())
                .arg(static_cast<int>(m_feedback->state()))
                .arg(static_cast<int>(m_feedback->error()));
        emit statusMessage(error, true);
        teardown(false);
        emit connectedChanged(false);
        return;
    }

    // 2) 脚本端口：移动指令的通道。连不上就明确失败，避免"界面已连接但
    //    点不动"的假连接。30001 同时以 ~10 Hz 回推状态包；必须持续排空，
    //    否则接收缓冲满了以后控制器会认为客户端卡死。这里不解析它的内容
    //    （实时位姿只信 30003），只把数据读掉。
    makeSocket(m_script, this);
    QObject::connect(m_script, &QTcpSocket::disconnected, this,
                     &UrMotionWorker::onDisconnected);
    QObject::connect(m_script, &QTcpSocket::readyRead, this, [this]() {
        if (m_script)
            m_script->readAll();
    });
    m_script->connectToHost(host, kScriptPort);
    if (!m_script->waitForConnected(2000)) {
        const QString error =
            QStringLiteral("连接 UR 脚本端口 %1:%2 失败（可能已被其他客户端占用）：%3")
                .arg(host).arg(kScriptPort).arg(m_script->errorString());
        emit statusMessage(error, true);
        teardown(false);
        emit connectedChanged(false);
        return;
    }

    // 3) Dashboard：停止指令。连不上仍可运动，但停止只能去示教器，
    //    所以明确告诉操作员，而不是悄悄降级。
    makeSocket(m_dashboard, this);
    QObject::connect(m_dashboard, &QTcpSocket::readyRead, this,
                     &UrMotionWorker::onDashboardReady);
    m_dashboard->connectToHost(host, kDashboardPort);
    const bool dashboardOk = m_dashboard->waitForConnected(1500);
    if (!dashboardOk) {
        emit statusMessage(
            QStringLiteral("Dashboard 端口 %1 未连上：停止按钮将无法下发，"
                           "请用示教器停止")
                .arg(kDashboardPort), true);
    }

    m_feedbackBuf.clear();
    m_dashboardBuf.clear();
    m_streamWarned = false;
    m_lastPacketAt.start();
    m_lastPublishAt.invalidate();
    // 新连接不继承上一次的位姿：第一次反馈到达前，任何基于位姿的点动都
    // 必须被拒绝，而不是把全零状态当成"机器人在原点"。
    m_state = RobotMotion::State{};
    m_havePose = false;
    m_pending = PendingMove{};
    m_motionInFlight = false;
    m_connected = true;
    m_enabled = false;

    // 让操作员看到控制器当前模式；非 RUNNING / MANUAL / 保护性停止时
    // movel 不会执行（UR 会静默丢弃或直接触发保护性停止），所以连接后
    // 主动查询并把这些状态告诉操作员。
    sendDashboard(QStringLiteral("robotmode"));
    sendDashboard(QStringLiteral("safetymode"));
    sendDashboard(QStringLiteral("get operational mode"));

    if (!m_watchdog) {
        m_watchdog = new QTimer(this);
        m_watchdog->setInterval(500);
        QObject::connect(m_watchdog, &QTimer::timeout, this,
                         &UrMotionWorker::checkStream);
    }
    m_watchdog->start();

    emit connectedChanged(true);
    emit statusMessage(dashboardOk
                           ? QStringLiteral("UR 已连接（%1）").arg(host)
                           : QStringLiteral("UR 已连接（%1），但 Dashboard 不可用")
                                 .arg(host),
                       !dashboardOk);
}

void UrMotionWorker::shutdown()
{
    teardown(true);
    if (m_watchdog)
        m_watchdog->stop();
}

void UrMotionWorker::teardown(bool notify)
{
    if (m_watchdog)
        m_watchdog->stop();

    const bool wasConnected = m_connected;
    const bool wasEnabled = m_enabled;
    m_connected = false;
    m_enabled = false;
    m_motionInFlight = false;
    m_streamWarned = false;
    m_havePose = false;
    m_state = RobotMotion::State{};

    if (m_pending.active) {
        m_pending.active = false;
        emit motionFinished(false, QStringLiteral("连接已断开"));
    }
    m_pending = PendingMove{};
    m_queuedActive = false;
    m_queued = PendingMove{};

    auto drop = [](QTcpSocket*& socket) {
        if (!socket)
            return;
        socket->disconnect();   // 断开它作为发送者的所有连接
        if (socket->state() != QAbstractSocket::UnconnectedState)
            socket->disconnectFromHost();
        socket->deleteLater();
        socket = nullptr;
    };
    drop(m_feedback);
    drop(m_script);
    drop(m_dashboard);
    m_feedbackBuf.clear();
    m_dashboardBuf.clear();
    m_lastPublishAt.invalidate();

    if (notify && wasConnected)
        emit connectedChanged(false);
    if (notify && wasEnabled)
        emit enabledChanged(false);
}

void UrMotionWorker::setEnabled(bool enabled)
{
    if (enabled && !m_connected) {
        emit statusMessage(QStringLiteral("请先连接 UR"), true);
        if (m_enabled) {
            m_enabled = false;
            emit enabledChanged(false);
        }
        return;
    }
    if (m_enabled == enabled)
        return;
    m_enabled = enabled;
    if (!enabled && (m_pending.active || m_motionInFlight))
        stopMotion();   // 去使能必须立刻停下正在进行的运动
    emit enabledChanged(enabled);
    emit statusMessage(
        enabled ? QStringLiteral("已使能（软件许可）；请确认示教器模式为 RUNNING")
                : QStringLiteral("已去使能，运动指令将被拒绝"),
        false);
}

bool UrMotionWorker::ensureReady(const QString& action)
{
    if (!m_connected) {
        emit statusMessage(QStringLiteral("%1失败：未连接 UR").arg(action), true);
        emit motionFinished(false, QStringLiteral("未连接 UR"));
        return false;
    }
    if (!m_enabled) {
        emit statusMessage(QStringLiteral("%1失败：未使能").arg(action), true);
        emit motionFinished(false, QStringLiteral("未使能"));
        return false;
    }
    if (!m_script || m_script->state() != QAbstractSocket::ConnectedState) {
        emit statusMessage(
            QStringLiteral("%1失败：脚本端口 30001 未连接").arg(action), true);
        emit motionFinished(false, QStringLiteral("脚本端口 30001 未连接"));
        return false;
    }
    return true;
}

void UrMotionWorker::moveCartesian(const RobotMotion::Pose& target,
                                   double speedPct, double toleranceMm,
                                   double toleranceDeg, int timeoutMs)
{
    if (!ensureReady(QStringLiteral("笛卡尔移动")))
        return;
    beginMove(target, speedPct, toleranceMm, toleranceDeg, timeoutMs,
              false, false);
}

void UrMotionWorker::moveJoint(const RobotMotion::Pose& target, double speedPct,
                               double toleranceDeg, int timeoutMs)
{
    if (!ensureReady(QStringLiteral("关节移动")))
        return;
    RobotMotion::Pose clamped = target;
    for (double& v : clamped)
        v = JogPolicy::clampJoint(v);
    beginMove(clamped, speedPct, 2.0, toleranceDeg, timeoutMs, true, false);
}

void UrMotionWorker::jogCartesian(int axis, double delta, double speedPct)
{
    if (!ensureReady(QStringLiteral("点动")))
        return;
    if (!JogPolicy::validAxis(axis)) {
        emit motionFinished(false, QStringLiteral("点动轴无效"));
        return;
    }
    // 没有实时位姿就无从计算"在当前位姿上加一步"。30003 断流超过 0.5 s
    // 时同样拒绝：拿旧位姿累加会让目标与真机越来越远。
    if (!m_havePose || !m_lastPacketAt.isValid()
        || m_lastPacketAt.elapsed() > 500) {
        emit statusMessage(
            QStringLiteral("点动已拒绝：尚未收到有效的实时位姿（30003）"), true);
        return;
    }

    // 连续点击时以上一条指令（含排队中的那一步）的目标为基准，否则每次都用
    // 反馈位置会把前一次增量"吃掉"（反馈还没到，目标就已经被后一次覆盖）。
    const RobotMotion::Pose base = latestJogBase(false);
    RobotMotion::Pose target = base;
    if (axis < 3) {
        target[static_cast<std::size_t>(axis)] += delta;
    } else {
        const UrMotionMath::Vec3 rotated =
            UrMotionMath::rotateVectorAboutBaseAxisDeg(
                UrMotionMath::Vec3{ base[3], base[4], base[5] },
                axis - 3, delta);
        target[3] = rotated[0];
        target[4] = rotated[1];
        target[5] = rotated[2];
    }
    beginMove(target, speedPct, 0.2, 0.2, 10000, false, true);
}

void UrMotionWorker::jogJoint(int axis, double delta, double speedPct)
{
    if (!ensureReady(QStringLiteral("关节点动")))
        return;
    if (!JogPolicy::validAxis(axis)) {
        emit motionFinished(false, QStringLiteral("点动轴无效"));
        return;
    }
    if (!m_havePose || !m_lastPacketAt.isValid()
        || m_lastPacketAt.elapsed() > 500) {
        emit statusMessage(
            QStringLiteral("关节点动已拒绝：尚未收到有效的实时位姿（30003）"),
            true);
        return;
    }

    // 与笛卡尔点动一样：连续点击时以上一条指令的目标为基准，避免界面
    // 缓存（50 ms 节流）把上一拍的增量吃掉。
    const RobotMotion::Pose base = latestJogBase(true);
    const RobotMotion::Pose target =
        JogPolicy::clampJoints(JogPolicy::jog(base, axis, delta));
    beginMove(target, speedPct, 2.0, 0.2, 10000, true, true);
}

void UrMotionWorker::moveJointAxisTo(int axis, double degrees,
                                     double speedPct)
{
    if (!ensureReady(QStringLiteral("关节滑杆")))
        return;
    if (!JogPolicy::validAxis(axis) || !std::isfinite(degrees)) {
        emit motionFinished(false, QStringLiteral("关节轴或角度无效"));
        return;
    }
    if (!m_havePose || !m_lastPacketAt.isValid()
        || m_lastPacketAt.elapsed() > 500) {
        emit statusMessage(
            QStringLiteral("关节移动已拒绝：尚未收到有效的实时位姿（30003）"),
            true);
        return;
    }

    RobotMotion::Pose target = latestJogBase(true);
    target[static_cast<std::size_t>(axis)] = JogPolicy::clampJoint(degrees);
    beginMove(JogPolicy::clampJoints(target), speedPct, 2.0, 0.2, 10000,
              true, true);
}

RobotMotion::Pose UrMotionWorker::latestJogBase(bool joint) const
{
    // 排队中的那一步更新，长按累加必须从它出发，否则会丢掉中间的一步。
    if (m_queuedActive && m_queued.joint == joint)
        return m_queued.target;
    if (m_pending.active && m_pending.joint == joint)
        return m_pending.target;
    return joint ? m_state.joint : m_state.cart;
}

void UrMotionWorker::beginMove(const RobotMotion::Pose& target,
                               double speedPct, double toleranceMm,
                               double toleranceDeg, int timeoutMs, bool joint,
                               bool jog)
{
    // 长按点动：上一条还在飞就只更新排队目标，等它到位再发。否则每按一次
    // 都往 30001 写一条 movel，慢速时会积压，松手后机器人还会多走几步。
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

    const UrMotionMath::ScriptSpeeds speeds =
        UrMotionMath::scriptSpeedsFor(speedPct, joint);
    QString statement;
    if (joint) {
        statement = QStringLiteral("movej([%1,%2,%3,%4,%5,%6], a=%7, v=%8)\n")
                        .arg(num(target[0] * UrMotionMath::kDegToRad),
                             num(target[1] * UrMotionMath::kDegToRad),
                             num(target[2] * UrMotionMath::kDegToRad),
                             num(target[3] * UrMotionMath::kDegToRad),
                             num(target[4] * UrMotionMath::kDegToRad),
                             num(target[5] * UrMotionMath::kDegToRad),
                             num(speeds.a), num(speeds.v));
    } else {
        const UrMotionMath::Pose6 script =
            UrMotionMath::stateToScriptPose(target);
        statement =
            QStringLiteral("movel(p[%1,%2,%3,%4,%5,%6], a=%7, v=%8)\n")
                .arg(num(script[0]), num(script[1]), num(script[2]),
                     num(script[3]), num(script[4]), num(script[5]),
                     num(speeds.a), num(speeds.v));
    }

    // 新指令直接接管：程序运行中点动是禁用的，点动与程序节点不会互相
    // 取代；这里不发失败信号，避免正在等待的执行器被误判为节点失败。
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

    if (!sendScript(statement)) {
        finishPending(false, QStringLiteral("脚本发送失败"));
        return;
    }
    if (jog)
        emit statusMessage(QStringLiteral("点动中…"), false);
}

void UrMotionWorker::finishPending(bool ok, const QString& error)
{
    m_pending.active = false;
    m_motionInFlight = false;
    if (!ok) {
        // 失败/超时/停止：排队中的那一步也不再执行。
        m_queuedActive = false;
        m_queued = PendingMove{};
    }
    const bool chain = ok && m_queuedActive && m_enabled;
    PendingMove next;
    if (chain) {
        next = m_queued;
        m_queuedActive = false;
        m_queued = PendingMove{};
    }
    emit motionFinished(ok, error);
    if (chain) {
        beginMove(next.target, next.speedPct, next.toleranceMm,
                  next.toleranceDeg, next.timeoutMs, next.joint, next.jog);
    }
}

bool UrMotionWorker::sendScript(const QString& statement)
{
    if (!m_script)
        return false;
    if (m_script->state() != QAbstractSocket::ConnectedState)
        return false;
    const QByteArray bytes = statement.toUtf8();
    if (m_script->write(bytes) != bytes.size())
        return false;
    m_script->flush();
    return true;
}

void UrMotionWorker::sendDashboard(const QString& command)
{
    if (!m_dashboard || m_dashboard->state() != QAbstractSocket::ConnectedState)
        return;
    m_dashboard->write((command + QLatin1Char('\n')).toUtf8());
    m_dashboard->flush();
}

void UrMotionWorker::stopMotion()
{
    const bool inFlight = m_pending.active || m_motionInFlight;
    m_motionInFlight = false;
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
    // Dashboard 的 stop 只停"正在运行的程序"。没有运动在飞时绝不发送，
    // 否则可能把示教器上别人正在跑的程序停掉。
    if (m_dashboard && m_dashboard->state() == QAbstractSocket::ConnectedState) {
        sendDashboard(QStringLiteral("stop"));
        emit statusMessage(QStringLiteral("已发送停止（Dashboard stop）"), false);
    } else {
        emit statusMessage(
            QStringLiteral("已停止本地等待；Dashboard 不可用，"
                           "如仍在运动请用示教器停止"), true);
    }
}

void UrMotionWorker::onFeedbackReady()
{
    if (!m_feedback)
        return;
    m_feedbackBuf.append(m_feedback->readAll());

    int scan = 0;
    while (m_feedbackBuf.size() - scan >= kHeaderBytes) {
        const quint32 msgLen = beU32(m_feedbackBuf.constData() + scan);
        if (msgLen < kHeaderBytes || msgLen > kMaxPacket) {
            ++scan;   // 流失去对齐：逐字节找下一个长度头
            continue;
        }
        const int total = static_cast<int>(msgLen);
        if (m_feedbackBuf.size() - scan < total)
            break;
        const QByteArray packet = m_feedbackBuf.mid(scan, total);
        double tcp[6];
        double joints[6];
        if (readDoubles(packet, kPoseOffset, tcp)
            && readDoubles(packet, kJointOffset, joints)) {
            RobotMotion::State state;
            const UrMotionMath::Pose6 cart = UrMotionMath::feedbackToState(tcp);
            for (int i = 0; i < 6; ++i) {
                state.cart[static_cast<std::size_t>(i)] = cart[i];
                state.joint[static_cast<std::size_t>(i)] =
                    joints[i] * UrMotionMath::kRadToDeg;
            }
            state.hasJoint = true;
            onStatePacket(state);
        }
        scan += total;
    }
    if (scan > 0)
        m_feedbackBuf.remove(0, scan);
    if (m_feedbackBuf.size() > kMaxBuffered)
        m_feedbackBuf.clear();   // 只可能在失步时发生
}

void UrMotionWorker::onStatePacket(const RobotMotion::State& state)
{
    m_state = state;
    m_havePose = true;
    m_lastPacketAt.start();
    if (m_streamWarned) {
        m_streamWarned = false;
        emit statusMessage(QStringLiteral("UR 数据流已恢复"), false);
    }

    // 125 Hz 的包没必要每个都刷界面。
    if (!m_lastPublishAt.isValid() || m_lastPublishAt.elapsed() >= 50) {
        m_lastPublishAt.restart();
        emit poseUpdated(m_state);
    }

    checkReached();
}

void UrMotionWorker::checkReached()
{
    if (!m_pending.active)
        return;

    const bool reached = m_pending.joint
        ? JogPolicy::reachedJoint(m_state.joint, m_pending.target,
                                  m_pending.toleranceDeg)
        : UrMotionMath::reachedCartesian(
              m_state.cart, m_pending.target,
              m_pending.toleranceMm, m_pending.toleranceDeg);

    if (reached) {
        const bool wasJog = m_pending.jog;
        finishPending(true, QString());
        if (!wasJog)
            emit statusMessage(QStringLiteral("已到达目标位姿"), false);
        return;
    }

    if (m_pending.elapsed.elapsed() > m_pending.timeoutMs) {
        finishPending(
            false,
            QStringLiteral("超时未到位（%1 ms）；请检查示教器程序状态")
                .arg(m_pending.timeoutMs));
        // 超时最常见的两个原因：安全停止 / MANUAL 模式。把控制器状态
        // 查回来，操作员就不用猜为什么"发了指令但不动"。
        sendDashboard(QStringLiteral("safetymode"));
        sendDashboard(QStringLiteral("get operational mode"));
    }
}

void UrMotionWorker::checkStream()
{
    if (!m_connected)
        return;
    if (m_lastPacketAt.isValid() && m_lastPacketAt.elapsed() > 1500
        && !m_streamWarned) {
        m_streamWarned = true;
        emit statusMessage(
            QStringLiteral("实时端口 30003 已 %1 ms 没有数据")
                .arg(m_lastPacketAt.elapsed()), true);
    }
}

void UrMotionWorker::onDashboardReady()
{
    if (!m_dashboard)
        return;
    m_dashboardBuf.append(m_dashboard->readAll());
    int newline = -1;
    while ((newline = m_dashboardBuf.indexOf('\n')) >= 0) {
        const QString line =
            QString::fromUtf8(m_dashboardBuf.left(newline)).trimmed();
        m_dashboardBuf.remove(0, newline + 1);
        if (line.startsWith(QStringLiteral("Robotmode"), Qt::CaseInsensitive)) {
            const bool running = line.contains(QStringLiteral("RUNNING"));
            emit statusMessage(
                running ? QStringLiteral("UR 控制器模式：RUNNING")
                        : QStringLiteral("UR 控制器模式：%1（movel 不会执行）")
                              .arg(line.section(QLatin1Char(':'), 1).trimmed()),
                !running);
        } else if (line.startsWith(QStringLiteral("Safetymode"),
                                   Qt::CaseInsensitive)) {
            const QString mode =
                line.section(QLatin1Char(':'), 1).trimmed();
            const bool normal =
                mode.compare(QStringLiteral("NORMAL"), Qt::CaseInsensitive) == 0;
            emit statusMessage(
                normal ? QStringLiteral("UR 安全状态：NORMAL")
                       : QStringLiteral("UR 安全状态：%1（请先在示教器复位，"
                                        "否则运动指令会被拒绝）").arg(mode),
                !normal);
        } else if (line.compare(QStringLiteral("MANUAL"),
                                Qt::CaseInsensitive) == 0) {
            // CB3/e-Series：MANUAL 操作模式下外部脚本不会驱动真机。
            emit statusMessage(
                QStringLiteral("UR 操作模式：MANUAL（外部运动指令会被忽略；"
                               "请在示教器切换到自动/远程模式）"),
                true);
        } else if (line.compare(QStringLiteral("AUTOMATIC"),
                                Qt::CaseInsensitive) == 0) {
            emit statusMessage(QStringLiteral("UR 操作模式：AUTOMATIC"), false);
        }
    }
}

void UrMotionWorker::onDisconnected()
{
    if (!m_connected)
        return;
    emit statusMessage(QStringLiteral("UR 连接已断开"), true);
    teardown(true);
}

// ── 后端门面（UI 线程）────────────────────────────────────────────────

UrMotionBackend::UrMotionBackend(QObject* parent)
    : RobotMotionBackend(parent)
{
    m_thread = new QThread(this);
    m_worker = new UrMotionWorker;
    m_worker->moveToThread(m_thread);

    connect(m_worker, &UrMotionWorker::connectedChanged, this,
            [this](bool connected) {
                m_connected = connected;
                if (!connected)
                    m_enabled = false;
                emit connectedChanged(connected);
            });
    connect(m_worker, &UrMotionWorker::enabledChanged, this,
            [this](bool enabled) {
                m_enabled = enabled;
                emit enabledChanged(enabled);
            });
    connect(m_worker, &UrMotionWorker::poseUpdated, this,
            [this](const RobotMotion::State& state) {
                m_state = state;
                emit poseUpdated(state);
            });
    connect(m_worker, &UrMotionWorker::motionFinished, this,
            &UrMotionBackend::motionFinished);
    connect(m_worker, &UrMotionWorker::statusMessage, this,
            &UrMotionBackend::statusMessage);

    connect(m_thread, &QThread::finished, m_worker, &QObject::deleteLater);
    m_thread->start();
}

UrMotionBackend::~UrMotionBackend()
{
    if (m_thread && m_thread->isRunning()) {
        QMetaObject::invokeMethod(
            m_worker, [worker = m_worker]() { worker->shutdown(); },
            Qt::BlockingQueuedConnection);
        m_thread->quit();
        m_thread->wait();
    }
}

void UrMotionBackend::connectDevice(const QString& host, quint16 port)
{
    QMetaObject::invokeMethod(
        m_worker, [worker = m_worker, host, port]() { worker->start(host, port); },
        Qt::QueuedConnection);
}

void UrMotionBackend::disconnectDevice()
{
    QMetaObject::invokeMethod(
        m_worker, [worker = m_worker]() { worker->shutdown(); },
        Qt::QueuedConnection);
}

void UrMotionBackend::setEnabled(bool enabled)
{
    QMetaObject::invokeMethod(
        m_worker, [worker = m_worker, enabled]() { worker->setEnabled(enabled); },
        Qt::QueuedConnection);
}

void UrMotionBackend::moveCartesian(const RobotMotion::Pose& target,
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

void UrMotionBackend::moveJoint(const RobotMotion::Pose& target, double speedPct,
                                double toleranceDeg, int timeoutMs)
{
    QMetaObject::invokeMethod(
        m_worker,
        [worker = m_worker, target, speedPct, toleranceDeg, timeoutMs]() {
            worker->moveJoint(target, speedPct, toleranceDeg, timeoutMs);
        },
        Qt::QueuedConnection);
}

void UrMotionBackend::jogCartesian(int axis, double delta, double speedPct)
{
    QMetaObject::invokeMethod(
        m_worker,
        [worker = m_worker, axis, delta, speedPct]() {
            worker->jogCartesian(axis, delta, speedPct);
        },
        Qt::QueuedConnection);
}

void UrMotionBackend::jogJoint(int axis, double delta, double speedPct)
{
    QMetaObject::invokeMethod(
        m_worker,
        [worker = m_worker, axis, delta, speedPct]() {
            worker->jogJoint(axis, delta, speedPct);
        },
        Qt::QueuedConnection);
}

void UrMotionBackend::moveJointAxisTo(int axis, double degrees,
                                      double speedPct)
{
    QMetaObject::invokeMethod(
        m_worker,
        [worker = m_worker, axis, degrees, speedPct]() {
            worker->moveJointAxisTo(axis, degrees, speedPct);
        },
        Qt::QueuedConnection);
}

void UrMotionBackend::stopMotion()
{
    QMetaObject::invokeMethod(
        m_worker, [worker = m_worker]() { worker->stopMotion(); },
        Qt::QueuedConnection);
}
