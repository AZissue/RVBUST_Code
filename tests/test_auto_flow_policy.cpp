#include "test_auto_flow_policy.h"

#include <QtTest>

#include "logic/AutoFlowPolicy.h"
#include "logic/CaptureFlow.h"

using AutoFlowPolicy::SaveDecision;
using AutoFlowPolicy::decideAutoSave;
using AutoFlowPolicy::shouldAutoDetect;

void TestAutoFlowPolicy::switchOffNeverTriggers()
{
    // Even with a perfect detection and complete cards: the switch is the
    // operator's, and "off" has to be indistinguishable from the old build.
    const SaveDecision d = decideAutoSave(/*autoSaveOn=*/false, true, true, QString());
    QVERIFY(!d.trigger);
    QVERIFY(d.reason.isEmpty());   // nothing worth a log line
}

void TestAutoFlowPolicy::successfulDetectWithValidCardsTriggers()
{
    const SaveDecision d = decideAutoSave(true, /*detectOk=*/true, /*inputsOk=*/true, QString());
    QVERIFY(d.trigger);
    QVERIFY(d.reason.isEmpty());
}

void TestAutoFlowPolicy::failedDetectSkipsWithReason()
{
    // Detection failed → the cards were not auto-filled, so saving would write
    // the previous frame's values.  Never do that; say why instead.
    const SaveDecision d = decideAutoSave(true, /*detectOk=*/false, /*inputsOk=*/true, QString());
    QVERIFY(!d.trigger);
    QVERIFY(d.reason.contains(QStringLiteral("自动保存跳过")));
    QVERIFY(d.reason.contains(QStringLiteral("识别未成功")));
}

void TestAutoFlowPolicy::invalidCardsSkipWithTheValidatorMessage()
{
    // Real validator, real cards.  TCP-touch mode with the robot target point
    // still empty — the case the operator hits when the robot pose read did not
    // happen (the "机器人目标点为空" example).
    CalibrationMode mode;
    mode.calibType = CalibType::TcpTouch;
    mode.eyeHand = EyeHandMode::EyeInHand;
    const CaptureFlow::SaveIssue issue = CaptureFlow::validateSaveInputs(
        QStringLiteral("1 2 3"), QStringLiteral("1 2 3 4 5 6"), QString(), mode);
    QVERIFY(!issue.ok);     // the validator itself is covered by its own test
    QCOMPARE(issue.field, QStringLiteral("robot_target_xyz"));
    QVERIFY(!issue.message.isEmpty());

    const SaveDecision d = decideAutoSave(true, /*detectOk=*/true,
                                          /*inputsOk=*/issue.ok, issue.message);
    QVERIFY(!d.trigger);
    // The operator sees exactly the field problem the manual save would show —
    // automation must not invent its own (weaker) rule.
    QVERIFY(d.reason.contains(issue.message));
    QVERIFY(d.reason.startsWith(QStringLiteral("自动保存跳过：")));

    // And the happy path through the same real validator: same mode, all three
    // cards filled as a successful detect + pose read would leave them.
    const CaptureFlow::SaveIssue ok = CaptureFlow::validateSaveInputs(
        QStringLiteral("1 2 3"), QStringLiteral("1 2 3 4 5 6"),
        QStringLiteral("7 8 9"), mode);
    QVERIFY(ok.ok);
    QVERIFY(decideAutoSave(true, true, ok.ok, ok.message).trigger);
}

void TestAutoFlowPolicy::missingValidatorMessageFallsBack()
{
    const SaveDecision d = decideAutoSave(true, true, /*inputsOk=*/false, QString());
    QVERIFY(!d.trigger);
    QVERIFY(d.reason.contains(QStringLiteral("必填项校验未通过")));
}

void TestAutoFlowPolicy::autoDetectNeedsAFrame()
{
    QVERIFY(shouldAutoDetect(true, true));
    // A failed capture leaves nothing to detect on.
    QVERIFY(!shouldAutoDetect(true, false));
    QVERIFY(!shouldAutoDetect(false, true));
    QVERIFY(!shouldAutoDetect(false, false));
}
