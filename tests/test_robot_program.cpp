#include "test_robot_program.h"

#include <QtTest>
#include <QElapsedTimer>
#include <QJsonArray>
#include <QJsonDocument>
#include <QSignalSpy>
#include <QTemporaryDir>

#include <limits>

#ifdef _WIN32
#  ifndef NOMINMAX
#    define NOMINMAX   // 否则 windows.h 的 min/max 宏会打坏 std::max
#  endif
#  include <winsock2.h>
// winsock2.h 的老式 near/far 宏会把下面的局部变量名改没。
#  undef near
#  undef far
#endif

#include "logic/JogPolicy.h"
#include "logic/ProgramRunner.h"
#include "logic/RobotProgram.h"
#include "logic/SimulatedMotionBackend.h"
#include "logic/UrMotionBackend.h"
#include "logic/UrMotionMath.h"

using namespace RobotProgram;

namespace {

class FakeActions : public ProgramActions {
public:
    explicit FakeActions(ProgramRunner* runner) : m_runner(runner) {}

    void startNode(const NodePayload& payload) override
    {
        order.push_back(kindOf(payload));
        if (autoComplete)
            m_runner->notifyNodeFinished(completeOk,
                                         completeOk ? QString()
                                                    : QStringLiteral("boom"));
    }
    void stopProgram() override { ++stopCalls; }

    ProgramRunner* m_runner = nullptr;
    bool autoComplete = true;
    bool completeOk = true;
    int stopCalls = 0;
    std::vector<NodeKind> order;
};

} // namespace

void TestRobotProgram::jsonRoundTrip()
{
    Program program;
    program.name = QStringLiteral("标定扫描");
    program.nodes.push_back(makeMove({ 400.0, 0.0, 300.0, 180.0, 0.0, 0.0 },
                                     MoveNode::Space::Cartesian, 25.0));
    program.nodes.push_back(makePhoto(true));
    program.nodes.push_back(makeWait(1.5));
    program.nodes.push_back(makeMove({ 0.0, -90.0, 0.0, -90.0, 0.0, 0.0 },
                                     MoveNode::Space::Joint, 40.0));

    const QJsonObject json = toJson(program);
    const ParseResult parsed = fromJson(json);
    QVERIFY2(parsed.ok, qPrintable(parsed.error));
    QCOMPARE(parsed.program.name, program.name);
    QCOMPARE(parsed.program.nodes.size(), program.nodes.size());

    const auto* m0 = std::get_if<MoveNode>(&parsed.program.nodes[0].payload);
    QVERIFY(m0);
    QCOMPARE(m0->space, MoveNode::Space::Cartesian);
    QCOMPARE(m0->target[0], 400.0);
    QCOMPARE(m0->speedPct, 25.0);

    const auto* p1 = std::get_if<PhotoNode>(&parsed.program.nodes[1].payload);
    QVERIFY(p1);
    QCOMPARE(p1->autoSave, true);

    const auto* w2 = std::get_if<WaitNode>(&parsed.program.nodes[2].payload);
    QVERIFY(w2);
    QCOMPARE(w2->seconds, 1.5);

    const auto* m3 = std::get_if<MoveNode>(&parsed.program.nodes[3].payload);
    QVERIFY(m3);
    QCOMPARE(m3->space, MoveNode::Space::Joint);
    QCOMPARE(m3->target[1], -90.0);
    QCOMPARE(m3->speedPct, 40.0);

    // id 必须原样保留，否则选中项/将来撤销会在重新载入后指错节点。
    QCOMPARE(parsed.program.nodes[0].id, program.nodes[0].id);
}

void TestRobotProgram::jsonRejectsUnknownType()
{
    QJsonObject root;
    root.insert(QStringLiteral("version"), kProgramJsonVersion);
    QJsonArray nodes;
    QJsonObject node;
    node.insert(QStringLiteral("type"), QStringLiteral("teleport"));
    nodes.append(node);
    root.insert(QStringLiteral("nodes"), nodes);

    const ParseResult parsed = fromJson(root);
    QVERIFY(!parsed.ok);
    QVERIFY(parsed.error.contains(QStringLiteral("teleport")));
}

void TestRobotProgram::jsonRejectsBadPose()
{
    QJsonObject root;
    root.insert(QStringLiteral("version"), kProgramJsonVersion);
    QJsonArray nodes;
    QJsonObject node;
    node.insert(QStringLiteral("type"), QStringLiteral("move"));
    node.insert(QStringLiteral("space"), QStringLiteral("cartesian"));
    node.insert(QStringLiteral("target"),
                QJsonArray{ 1.0, 2.0, 3.0 });   // only three values
    nodes.append(node);
    root.insert(QStringLiteral("nodes"), nodes);

    const ParseResult parsed = fromJson(root);
    QVERIFY(!parsed.ok);
    QVERIFY(parsed.error.contains(QStringLiteral("6")));
}

void TestRobotProgram::invalidNumbersAreClamped()
{
    MoveNode move;
    move.speedPct = 900.0;
    move.toleranceMm = 0.0;
    move.toleranceDeg = -5.0;
    move.settleTimeoutMs = 900000;
    move.target[0] = std::numeric_limits<double>::quiet_NaN();
    const MoveNode clamped = clampMove(move);
    QCOMPARE(clamped.speedPct, 100.0);
    QCOMPARE(clamped.toleranceMm, 0.1);
    QCOMPARE(clamped.toleranceDeg, 0.1);
    QCOMPARE(clamped.settleTimeoutMs, 120000);
    QCOMPARE(clamped.target[0], 0.0);

    const Node wait = makeWait(-3.0);
    QCOMPARE(std::get<WaitNode>(wait.payload).seconds, 0.0);
}

void TestRobotProgram::displayTextIsReadable()
{
    const Node cart = makeMove({ 400.0, -10.5, 300.0, 180.0, 0.0, 0.0 },
                               MoveNode::Space::Cartesian);
    QVERIFY(displayTitle(cart.payload).contains(QStringLiteral("笛卡尔")));
    QVERIFY(displayDetail(cart.payload).contains(QStringLiteral("X 400.0")));

    const Node joint = makeMove({ 1, 2, 3, 4, 5, 6 },
                                 MoveNode::Space::Joint);
    QVERIFY(displayDetail(joint.payload).contains(QStringLiteral("J1 1.0")));

    QCOMPARE(kindOf(joint.payload), NodeKind::Move);
    QCOMPARE(kindOf(makePhoto().payload), NodeKind::Photo);
    QCOMPARE(kindOf(makeWait(2).payload), NodeKind::Wait);
    QCOMPARE(kindTag(NodeKind::Photo), QStringLiteral("PHOTO"));
}

void TestRobotProgram::programSavesAndLoadsFile()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString path = dir.path() + QStringLiteral("/program.json");

    Program program;
    program.name = QStringLiteral("现场程序");
    program.nodes.push_back(makeWait(0.5));
    QString error;
    QVERIFY2(saveToFile(program, path, &error), qPrintable(error));

    const ParseResult loaded = loadFromFile(path);
    QVERIFY2(loaded.ok, qPrintable(loaded.error));
    QCOMPARE(loaded.program.name, program.name);
    QCOMPARE(loaded.program.nodes.size(), std::size_t(1));

    QVERIFY(!loadFromFile(dir.path() + QStringLiteral("/missing.json")).ok);
}

void TestRobotProgram::jogPolicyClampsAndWraps()
{
    QCOMPARE(JogPolicy::clampStep(-1.0), JogPolicy::MIN_STEP);
    QCOMPARE(JogPolicy::clampStep(1e9), JogPolicy::MAX_STEP);
    QCOMPARE(JogPolicy::clampSpeed(0.0), JogPolicy::MIN_SPEED);
    QCOMPARE(JogPolicy::clampSpeed(500.0), JogPolicy::MAX_SPEED);

    // 179° 与 -179° 的最短差是 2°（走 180° 附近过去），不是 358°。
    QCOMPARE(JogPolicy::angleDiff(179.0, -179.0), -2.0);
    QCOMPARE(JogPolicy::angleDiff(-179.0, 179.0), 2.0);
    QCOMPARE(JogPolicy::angleDiff(10.0, 10.0), 0.0);

    const JogPolicy::Pose base{ 1, 2, 3, 4, 5, 6 };
    const auto moved = JogPolicy::jog(base, 2, 5.0);
    QCOMPARE(moved[2], 8.0);
    QCOMPARE(moved[0], 1.0);
    // 越界轴不动。
    QCOMPARE(JogPolicy::jog(base, 99, 5.0), base);
}

void TestRobotProgram::jogPolicyReachesTolerance()
{
    const JogPolicy::Pose target{ 100, 200, 300, 180, 0, 90 };
    const JogPolicy::Pose near{ 101, 200, 300, 179.5, 0, 89.4 };
    QVERIFY(JogPolicy::reachedCartesian(near, target, 2.0, 1.0));
    QVERIFY(!JogPolicy::reachedCartesian(near, target, 2.0, 0.4));

    JogPolicy::Pose far = target;
    far[0] += 5.0;
    QVERIFY(!JogPolicy::reachedCartesian(far, target, 2.0, 1.0));

    QVERIFY(JogPolicy::reachedJoint(
        JogPolicy::Pose{ 0, -90, 0, -90, 0, 0 },
        JogPolicy::Pose{ 0, -90, 0, -90, 0, 0.4 }, 1.0));
}

void TestRobotProgram::urMathConvertsFeedbackUnits()
{
    // 30003 给的是米 + 弧度旋转向量；界面统一 mm + 度。
    const double raw[6] = { 0.4, -0.2, 0.3, 0.5 * UrMotionMath::kPi,
                            0.0, 0.25 * UrMotionMath::kPi };
    const UrMotionMath::Pose6 state = UrMotionMath::feedbackToState(raw);
    QVERIFY(std::abs(state[0] - 400.0) < 1e-9);
    QVERIFY(std::abs(state[1] + 200.0) < 1e-9);
    QVERIFY(std::abs(state[2] - 300.0) < 1e-9);
    QVERIFY(std::abs(state[3] - 90.0) < 1e-9);
    QVERIFY(std::abs(state[4]) < 1e-9);
    QVERIFY(std::abs(state[5] - 45.0) < 1e-9);
}

void TestRobotProgram::urMathNormalizesScriptRotation()
{
    const UrMotionMath::Pose6 script = UrMotionMath::stateToScriptPose(
        { 400.0, 0.0, 300.0, 180.0, 0.0, 0.0 });
    QVERIFY(std::abs(script[0] - 0.4) < 1e-12);
    QVERIFY(std::abs(script[1]) < 1e-12);
    QVERIFY(std::abs(script[2] - 0.3) < 1e-12);
    QVERIFY(std::abs(script[3] - UrMotionMath::kPi) < 1e-9);

    // 270° 等价于 -90°：URScript 只接受范数 ≤ π 的旋转向量。
    const UrMotionMath::Pose6 wrapped = UrMotionMath::stateToScriptPose(
        { 0, 0, 0, 0, 0, 270.0 });
    QVERIFY(std::abs(wrapped[5] + UrMotionMath::kPi / 2.0) < 1e-9);
    // 400° 等价于 40°。
    const UrMotionMath::Pose6 wrapped2 = UrMotionMath::stateToScriptPose(
        { 0, 0, 0, 0, 0, 400.0 });
    QVERIFY(std::abs(wrapped2[5] - 40.0 * UrMotionMath::kDegToRad) < 1e-9);

    // 未超过 π 的旋转原样保留。
    const UrMotionMath::Pose6 passthrough = UrMotionMath::stateToScriptPose(
        { 0, 0, 0, 90.0, 0, 0 });
    QVERIFY(std::abs(passthrough[3] - 90.0 * UrMotionMath::kDegToRad) < 1e-12);
}

void TestRobotProgram::urMathRotatesAboutBaseAxis()
{
    using namespace UrMotionMath;
    const Vec3 zero{ 0.0, 0.0, 0.0 };
    const Vec3 rz = rotateVectorAboutBaseAxisDeg(zero, 2, 90.0);
    QVERIFY(std::abs(rz[2] - 90.0) < 1e-9);

    // 绕基座 X 再转 90°：R = Rx(90)·Rz(90)，不是把欧拉角分量相加。
    const Vec3 composed = rotateVectorAboutBaseAxisDeg(rz, 0, 90.0);
    const Mat3 expected = multiply(
        rotvecToMatrix({ 90.0 * kDegToRad, 0.0, 0.0 }),
        rotvecToMatrix({ 0.0, 0.0, 90.0 * kDegToRad }));
    const Mat3 actual = rotvecToMatrix(
        { composed[0] * kDegToRad, composed[1] * kDegToRad,
          composed[2] * kDegToRad });
    for (int i = 0; i < 9; ++i)
        QVERIFY(std::abs(actual[static_cast<std::size_t>(i)]
                         - expected[static_cast<std::size_t>(i)]) < 1e-9);

    // 反向点动应回到原点姿态。
    const Vec3 back = rotateVectorAboutBaseAxisDeg(composed, 0, -90.0);
    QVERIFY(rotationDistanceDeg(back, rz) < 1e-6);
}

void TestRobotProgram::urMathRotationTolerance()
{
    using namespace UrMotionMath;
    // 179° 与 -179° 只差 2°，不是 358°。
    QVERIFY(std::abs(rotationDistanceDeg({ 0, 0, 179 }, { 0, 0, -179 }) - 2.0)
            < 1e-6);

    const Pose6 actual{ 100.0, 200.0, 300.0, 0.0, 0.0, 179.0 };
    const Pose6 target{ 101.0, 200.0, 300.0, 0.0, 0.0, -179.0 };
    QVERIFY(reachedCartesian(actual, target, 2.0, 2.5));
    QVERIFY(!reachedCartesian(actual, target, 2.0, 1.5));
    QVERIFY(!reachedCartesian(actual, target, 0.5, 2.5));
}

void TestRobotProgram::urBackendLiveMovesIfRequested()
{
    // 硬件在环冒烟测试：ctest 默认不跑（没有 HE_UR_HOST）。它验证的是
    // 本工具自己的那条链路——工作线程、30003 解析、30001 movel、到位判据
    // ——而不是 UR 的数学库。
    //   HE_UR_HOST=192.168.0.38 build/src/Release/unit_tests.exe \
    //       robot_program urBackendLiveMovesIfRequested -o out.txt,txt
    const QString host = qEnvironmentVariable("HE_UR_HOST").trimmed();
    if (host.isEmpty())
        QSKIP("set HE_UR_HOST to run the live UR smoke test");

    // 同进程里前面的 socket 测试会自己 WSAStartup/WSACleanup；跑到这里时
    // Winsock 可能已经不再可用（QTcpSocket 立刻 Unknown error）。真机冒烟
    // 测试自己把 Winsock 拉起来，和产品进程的行为保持一致。
#ifdef _WIN32
    WSADATA wsa{};
    const bool wsaOk = WSAStartup(MAKEWORD(2, 2), &wsa) == 0;
    QVERIFY2(wsaOk, "WSAStartup failed");
    struct WsaGuard {
        ~WsaGuard() { WSACleanup(); }
    } wsaGuard;
#endif

    UrMotionBackend backend;
    QSignalSpy finished(&backend, &RobotMotionBackend::motionFinished);
    QStringList messages;
    connect(&backend, &RobotMotionBackend::statusMessage, this,
            [&messages](const QString& text, bool error) {
                messages << (error ? QStringLiteral("ERR ") : QString())
                                + text;
            });

    backend.connectDevice(host, 30003);
    QElapsedTimer connectTimer;
    connectTimer.start();
    while (!backend.isConnected() && connectTimer.elapsed() < 8000)
        QTest::qWait(50);
    QVERIFY2(backend.isConnected(),
             qPrintable(messages.join(QStringLiteral(" | "))));
    backend.setEnabled(true);
    QTRY_VERIFY_WITH_TIMEOUT(backend.isEnabled(), 3000);
    QTRY_VERIFY_WITH_TIMEOUT(backend.state().hasJoint, 3000);

    const RobotMotion::Pose start = backend.state().cart;
    QVERIFY(std::abs(start[0]) + std::abs(start[1]) + std::abs(start[2]) > 1.0);
    RobotMotion::Pose target = start;
    target[2] += 5.0;

    finished.clear();
    backend.moveCartesian(target, 20.0, 2.0, 1.0, 10000);
    QTRY_VERIFY_WITH_TIMEOUT(finished.count() > 0, 15000);
    QCOMPARE(finished.last().at(0).toBool(), true);
    QVERIFY2(std::abs(backend.state().cart[2] - target[2]) < 2.5,
             qPrintable(QStringLiteral("z=%1 target=%2")
                            .arg(backend.state().cart[2]).arg(target[2])));

    // 停止路径：发一条慢速长距离运动，中途 stop。Dashboard stop 会停掉
    // 正在执行的 URScript；之后必须还能继续接受新指令，否则"停止"就等于
    // 把控制台锁死。
    finished.clear();
    RobotMotion::Pose longTarget = backend.state().cart;
    longTarget[2] += 100.0;
    backend.moveCartesian(longTarget, 5.0, 2.0, 1.0, 15000);
    QTest::qWait(400);
    backend.stopMotion();
    QTRY_VERIFY_WITH_TIMEOUT(finished.count() > 0, 5000);
    QCOMPARE(finished.last().at(0).toBool(), false);

    const RobotMotion::Pose resumeBase = backend.state().cart;
    RobotMotion::Pose resumeTarget = resumeBase;
    resumeTarget[2] += 5.0;
    finished.clear();
    backend.moveCartesian(resumeTarget, 20.0, 2.0, 1.0, 10000);
    QTRY_VERIFY_WITH_TIMEOUT(finished.count() > 0, 15000);
    QCOMPARE(finished.last().at(0).toBool(), true);

    // 回到起点，别把 VM 留在移动后的位置。
    finished.clear();
    backend.moveCartesian(start, 20.0, 2.0, 1.0, 10000);
    QTRY_VERIFY_WITH_TIMEOUT(finished.count() > 0, 15000);
    QCOMPARE(finished.last().at(0).toBool(), true);

    backend.setEnabled(false);
    backend.disconnectDevice();
    QTRY_VERIFY_WITH_TIMEOUT(!backend.isConnected(), 5000);
}

void TestRobotProgram::runnerRunsAllInOrder()
{
    ProgramRunner runner;
    FakeActions actions(&runner);
    runner.setActions(&actions);

    Program program;
    program.nodes.push_back(makeMove({}, MoveNode::Space::Cartesian));
    program.nodes.push_back(makePhoto());
    program.nodes.push_back(makeWait(1));
    runner.setProgram(program);

    QSignalSpy started(&runner, &ProgramRunner::nodeStarted);
    QSignalSpy finished(&runner, &ProgramRunner::finished);
    QVERIFY(runner.runAll());
    QCOMPARE(started.count(), 3);
    QCOMPARE(int(actions.order.size()), 3);
    QCOMPARE(actions.order[0], NodeKind::Move);
    QCOMPARE(actions.order[1], NodeKind::Photo);
    QCOMPARE(actions.order[2], NodeKind::Wait);
    QCOMPARE(finished.count(), 1);
    QCOMPARE(finished.last().at(0).toBool(), true);
    QCOMPARE(runner.state(), ProgramRunner::State::Idle);
}

void TestRobotProgram::runnerStopsOnFailure()
{
    ProgramRunner runner;
    FakeActions actions(&runner);
    actions.completeOk = false;
    runner.setActions(&actions);

    Program program;
    program.nodes.push_back(makeWait(1));
    program.nodes.push_back(makeWait(1));
    runner.setProgram(program);

    QSignalSpy finished(&runner, &ProgramRunner::finished);
    QVERIFY(runner.runAll());
    // 第一个节点失败后，第二个不能被执行。
    QCOMPARE(int(actions.order.size()), 1);
    QCOMPARE(finished.count(), 1);
    QCOMPARE(finished.last().at(0).toBool(), false);
    QCOMPARE(finished.last().at(1).toString(), QStringLiteral("boom"));
}

void TestRobotProgram::runnerRunOneAndStop()
{
    ProgramRunner runner;
    FakeActions actions(&runner);
    actions.autoComplete = false;
    runner.setActions(&actions);

    Program program;
    program.nodes.push_back(makeWait(5));
    program.nodes.push_back(makeWait(5));
    runner.setProgram(program);

    QSignalSpy finished(&runner, &ProgramRunner::finished);
    QVERIFY(runner.runOne(1));
    QCOMPARE(int(actions.order.size()), 1);
    QVERIFY(runner.isRunning());

    runner.stop();
    QCOMPARE(actions.stopCalls, 1);
    QCOMPARE(finished.count(), 1);
    QCOMPARE(finished.last().at(0).toBool(), false);
    QCOMPARE(finished.last().at(1).toString(), QStringLiteral("已停止"));

    // 停止后迟到的完成信号不能再推进列表 / 重复发 finished。
    runner.notifyNodeFinished(true);
    QCOMPARE(finished.count(), 1);
    QVERIFY(!runner.isRunning());
}

void TestRobotProgram::runnerRejectsEmptyProgram()
{
    ProgramRunner runner;
    FakeActions actions(&runner);
    runner.setActions(&actions);

    QSignalSpy finished(&runner, &ProgramRunner::finished);
    QVERIFY(!runner.runAll());
    QCOMPARE(finished.count(), 1);
    QCOMPARE(finished.last().at(0).toBool(), false);
    QVERIFY(finished.last().at(1).toString().contains(QStringLiteral("空")));
}

void TestRobotProgram::simulatedBackendMovesOnlyWhenEnabled()
{
    SimulatedMotionBackend backend;
    QSignalSpy finished(&backend, &RobotMotionBackend::motionFinished);
    QSignalSpy connected(&backend, &RobotMotionBackend::connectedChanged);

    RobotMotion::Pose target = backend.state().cart;
    target[0] += 10.0;
    backend.moveCartesian(target, 30.0);
    QCOMPARE(finished.count(), 1);
    QCOMPARE(finished.last().at(0).toBool(), false);

    backend.connectDevice(QStringLiteral("127.0.0.1"), 30001);
    QTRY_VERIFY_WITH_TIMEOUT(backend.isConnected(), 2000);
    QCOMPARE(connected.count(), 1);

    backend.setEnabled(true);
    QVERIFY(backend.isEnabled());

    // 未使能的情况：先断开再直接发移动。
    backend.setEnabled(false);
    backend.moveCartesian(target, 30.0);
    QCOMPARE(finished.last().at(0).toBool(), false);
}

void TestRobotProgram::simulatedBackendCompletesMove()
{
    SimulatedMotionBackend backend;
    backend.connectDevice(QStringLiteral("127.0.0.1"), 30001);
    QTRY_VERIFY_WITH_TIMEOUT(backend.isConnected(), 2000);
    backend.setEnabled(true);

    QSignalSpy finished(&backend, &RobotMotionBackend::motionFinished);
    RobotMotion::Pose target = backend.state().cart;
    target[0] += 10.0;
    backend.moveCartesian(target, 100.0);

    QTRY_VERIFY_WITH_TIMEOUT(finished.count() > 0, 5000);
    QCOMPARE(finished.last().at(0).toBool(), true);
    QVERIFY(std::abs(backend.state().cart[0] - target[0]) < 1e-6);
}
