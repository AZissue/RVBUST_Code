#pragma once

#include <QObject>

// 第 5 回合 任务 2: the post-detection auto-save decision and the auto-detect
// precondition.  Default off must mean "identical to the manual workflow".
class TestAutoFlowPolicy : public QObject {
    Q_OBJECT
private slots:
    // A disabled switch is silent — no trigger and nothing to log.
    void switchOffNeverTriggers();
    void successfulDetectWithValidCardsTriggers();
    void failedDetectSkipsWithReason();
    // The auto path runs the *same* validator as the manual save button; this
    // feeds a real validateSaveInputs() result through the decision.
    void invalidCardsSkipWithTheValidatorMessage();
    // A validator that reports a problem without a message must still produce a
    // line the operator can act on.
    void missingValidatorMessageFallsBack();
    void autoDetectNeedsAFrame();
};
