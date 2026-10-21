#include "logic/SimulatedMotionBackend.h"

#include "logic/JogPolicy.h"

#include <algorithm>
#include <cmath>

namespace {

double lerp(double a, double b, double t)
{
    return a + (b - a) * t;
}

double lerpAngle(double a, double b, double t)
{
    return a + JogPolicy::angleDiff(b, a) * t;
}

} // namespace

SimulatedMotionBackend::SimulatedMotionBackend(QObject* parent)
    : RobotMotionBackend(parent)
{
    // 一个接近 UR 默认安装姿态的初始位姿，让界面一打开就有东西可看。
    m_state.cart = { 400.0, 0.0, 300.0, 180.0, 0.0, 0.0 };
    m_state.joint = { 0.0, -90.0, 0.0, -90.0, 0.0, 0.0 };
    m_state.hasJoint = true;

    m_timer.setInterval(20);
    connect(&m_timer, &QTimer::timeout, this, &SimulatedMotionBackend::onTick);
}

void SimulatedMotionBackend::connectDevice(const QString& host, quint16 port)
{
    if (m_connected) {
        emit statusMessage(QStringLiteral("仿真后端已连接"), false);
        return;
    }
    // 用递增的代数作废旧的回调：快速点两次连接/断开时，早先的 250 ms
    // 回调不能把已经取消的连接又"连上"。
    ++m_connectGeneration;
    const int generation = m_connectGeneration;
    emit statusMessage(QStringLiteral("仿真后端连接中…"), false);
    QTimer::singleShot(250, this, [this, generation, host, port]() {
        if (generation != m_connectGeneration || m_connected)
            return;
        m_connected = true;
        emit connectedChanged(true);
        emit statusMessage(
            QStringLiteral("仿真后端已连接（%1:%2，不控制真机）")
                .arg(host).arg(port), false);
        publishPose();
    });
}

void SimulatedMotionBackend::disconnectDevice()
{
    ++m_connectGeneration;   // 取消尚未落地的连接回调
    m_timer.stop();
    m_moving = false;
    const bool wasConnected = m_connected;
    const bool wasEnabled = m_enabled;
    m_connected = false;
    m_enabled = false;
    if (wasConnected)
        emit connectedChanged(false);
    if (wasEnabled)
        emit enabledChanged(false);
    emit statusMessage(QStringLiteral("仿真后端已断开"), false);
}

void SimulatedMotionBackend::setEnabled(bool enabled)
{
    if (enabled && !m_connected) {
        emit statusMessage(QStringLiteral("请先连接仿真后端"), true);
        if (m_enabled) {
            m_enabled = false;
            emit enabledChanged(false);
        }
        return;
    }
    if (m_enabled == enabled)
        return;
    m_enabled = enabled;
    emit enabledChanged(enabled);
    emit statusMessage(enabled ? QStringLiteral("已使能（仿真）")
                               : QStringLiteral("已去使能（仿真）"), false);
}

void SimulatedMotionBackend::moveCartesian(const RobotMotion::Pose& target,
                                           double speedPct, double toleranceMm,
                                           double toleranceDeg, int timeoutMs)
{
    Q_UNUSED(toleranceMm);
    Q_UNUSED(toleranceDeg);
    Q_UNUSED(timeoutMs);
    if (!m_connected) {
        emit motionFinished(false, QStringLiteral("未连接机器人（仿真后端）"));
        return;
    }
    if (!m_enabled) {
        emit motionFinished(false, QStringLiteral("未使能，请先点「使能」"));
        return;
    }

    // 关节目标只是给界面看的近似联动（不是运动学正/逆解）。
    RobotMotion::Pose jointTarget = m_state.joint;
    const double dj[6] = {
        (target[0] - m_state.cart[0]) * 0.05,
        (target[1] - m_state.cart[1]) * 0.05,
        (target[2] - m_state.cart[2]) * 0.05,
        JogPolicy::angleDiff(target[3], m_state.cart[3]) * 0.10,
        JogPolicy::angleDiff(target[4], m_state.cart[4]) * 0.10,
        JogPolicy::angleDiff(target[5], m_state.cart[5]) * 0.10,
    };
    for (int i = 0; i < 6; ++i)
        jointTarget[static_cast<std::size_t>(i)] += dj[i];
    jointTarget = JogPolicy::clampJoints(jointTarget);

    startMove(target, jointTarget, speedPct, false);
}

void SimulatedMotionBackend::moveJoint(const RobotMotion::Pose& target,
                                       double speedPct, double toleranceDeg,
                                       int timeoutMs)
{
    Q_UNUSED(toleranceDeg);
    Q_UNUSED(timeoutMs);
    if (!m_connected) {
        emit motionFinished(false, QStringLiteral("未连接机器人（仿真后端）"));
        return;
    }
    if (!m_enabled) {
        emit motionFinished(false, QStringLiteral("未使能，请先点「使能」"));
        return;
    }

    RobotMotion::Pose jointTarget = JogPolicy::clampJoints(target);
    // 同上：笛卡尔显示值做一份近似联动。
    RobotMotion::Pose cartTarget = m_state.cart;
    for (int i = 0; i < 3; ++i)
        cartTarget[static_cast<std::size_t>(i)] +=
            (jointTarget[static_cast<std::size_t>(i)]
             - m_state.joint[static_cast<std::size_t>(i)]) * 20.0;
    for (int i = 3; i < 6; ++i)
        cartTarget[static_cast<std::size_t>(i)] +=
            JogPolicy::angleDiff(jointTarget[static_cast<std::size_t>(i)],
                                 m_state.joint[static_cast<std::size_t>(i)])
            * 10.0;

    startMove(cartTarget, jointTarget, speedPct, true);
}

void SimulatedMotionBackend::jogCartesian(int axis, double delta,
                                          double speedPct)
{
    // 连点时以上一条目标为基准；用插值中的当前位置会把上一拍吃掉。
    const RobotMotion::Pose base = m_moving ? m_targetCart : m_state.cart;
    moveCartesian(JogPolicy::jog(base, axis, delta), speedPct);
}

void SimulatedMotionBackend::jogJoint(int axis, double delta, double speedPct)
{
    const RobotMotion::Pose base = m_moving ? m_targetJoint : m_state.joint;
    moveJoint(JogPolicy::clampJoints(JogPolicy::jog(base, axis, delta)),
              speedPct);
}

void SimulatedMotionBackend::moveJointAxisTo(int axis, double degrees,
                                             double speedPct)
{
    if (!JogPolicy::validAxis(axis))
        return;
    RobotMotion::Pose target = m_moving ? m_targetJoint : m_state.joint;
    target[static_cast<std::size_t>(axis)] = JogPolicy::clampJoint(degrees);
    moveJoint(target, speedPct);
}

void SimulatedMotionBackend::startMove(const RobotMotion::Pose& cartTarget,
                                       const RobotMotion::Pose& jointTarget,
                                       double speedPct, bool angular)
{
    // 后一条点动指令直接接管当前位置，不排队：连续点 ± 时手感才跟手。
    // 这里不发 motionFinished(false)，否则正在等待节点的执行器会被误判为失败；
    // 程序运行时点动是禁用的，两者不会同时发生。
    m_timer.stop();
    m_startCart = m_state.cart;
    m_startJoint = m_state.joint;
    m_targetCart = cartTarget;
    m_targetJoint = jointTarget;
    m_durationMs = JogPolicy::simulatedDurationMs(
        angular ? m_state.joint : m_state.cart,
        angular ? jointTarget : cartTarget,
        speedPct, angular);
    m_elapsed.restart();
    m_moving = true;
    m_timer.start();
}

void SimulatedMotionBackend::onTick()
{
    if (!m_moving) {
        m_timer.stop();
        return;
    }
    const double t = m_durationMs <= 0
        ? 1.0
        : std::clamp(static_cast<double>(m_elapsed.elapsed()) / m_durationMs,
                     0.0, 1.0);

    for (int i = 0; i < 6; ++i) {
        const auto idx = static_cast<std::size_t>(i);
        if (i < 3) {
            m_state.cart[idx] = lerp(m_startCart[idx], m_targetCart[idx], t);
            m_state.joint[idx] = lerp(m_startJoint[idx], m_targetJoint[idx], t);
        } else {
            m_state.cart[idx] = lerpAngle(m_startCart[idx], m_targetCart[idx], t);
            m_state.joint[idx] = lerpAngle(m_startJoint[idx], m_targetJoint[idx], t);
        }
    }
    m_state.hasJoint = true;
    publishPose();

    if (t >= 1.0) {
        m_state.cart = m_targetCart;
        m_state.joint = m_targetJoint;
        m_timer.stop();
        m_moving = false;
        publishPose();
        emit motionFinished(true, QString());
    }
}

void SimulatedMotionBackend::stopMotion()
{
    if (!m_moving)
        return;
    m_timer.stop();
    m_moving = false;
    emit statusMessage(QStringLiteral("运动已停止（仿真）"), false);
    emit motionFinished(false, QStringLiteral("已停止"));
}

void SimulatedMotionBackend::publishPose()
{
    emit poseUpdated(m_state);
}
