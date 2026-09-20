#pragma once

// ── Optional flow automation (第 5 回合 任务 2) ──
//
// Three independent switches let an operator skip the manual steps they do not
// need: 拍照→自动识别, 识别→自动保存, 拍照时自动读机器人位姿.  All three default
// off, so the behaviour of an untouched installation is unchanged.
//
// The decisions are pure functions: the caller owns the cards / the detection
// state, this file owns the rule.  In particular the auto-save path runs the
// *same* validateSaveInputs() as the manual button — automation must never
// bypass a required-field check (PROJECT.md: 质量告警不拦截，必填项校验拦截).

#include <QString>

namespace AutoFlowPolicy {

// Post-detection auto-save decision.
struct SaveDecision {
    bool trigger = false;
    QString reason;   // filled when !trigger and the switch is on; logged verbatim
};

// autoSaveOn    : AppConfig "auto_save_after_detect"
// detectOk      : the detection that just finished succeeded
// inputsOk      : CaptureFlow::validateSaveInputs(...).ok on the current cards
// validationMsg : that validator's message (empty when inputsOk)
inline SaveDecision decideAutoSave(bool autoSaveOn, bool detectOk,
                                   bool inputsOk, const QString& validationMsg)
{
    if (!autoSaveOn)
        return { false, QString() };   // feature off — nothing worth logging
    if (!detectOk)
        return { false, QStringLiteral("自动保存跳过：本次识别未成功") };
    if (!inputsOk) {
        return { false, QStringLiteral("自动保存跳过：%1")
                            .arg(validationMsg.isEmpty()
                                     ? QStringLiteral("必填项校验未通过")
                                     : validationMsg) };
    }
    return { true, QString() };
}

// Auto-detect needs a frame to work on.  A failed capture never reaches the
// detection stage, and this keeps that explicit instead of relying on
// CaptureFlow::detect()'s own "未采集数据" guard.
inline bool shouldAutoDetect(bool autoDetectOn, bool hasCapturedFrame)
{
    return autoDetectOn && hasCapturedFrame;
}

} // namespace AutoFlowPolicy
