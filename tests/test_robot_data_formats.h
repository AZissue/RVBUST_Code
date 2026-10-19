#pragma once

#include <QObject>

// 机器人数据格式目录（src/logic/RobotDataFormats.{h,cpp}）。
//
// 这里钉住三件事：
//   1. 目录本身 —— 29 项、24 种欧拉约定、常用/高级两档、Id 的持久化整数；
//   2. 数学 —— 每种约定的正解 / 逆解都可往返，外旋与倒序内旋等价；
//   3. 推算 —— 用“绕基轴 / 工具轴点动”的数据能判出唯一一种约定，坏数据不能瞎判。
class TestRobotDataFormats : public QObject {
    Q_OBJECT
private slots:
    // ── 目录 ──
    void idIntegersKeepThePersistedLegacyValues();
    void catalogHasAll24EulerConventions();
    void displayNamesAreUniqueAndNonEmpty();
    void hintsCarryBrandsPrincipleAndReading();
    void advancedTierIsTheRemainingProperEulerSet();
    void cardUsableOnlyForThreeValueFormats();

    // ── 旋转数学 ──
    void knownConventionsProduceKnownRotations();
    void extrinsicEqualsReversedIntrinsic();
    void everyEulerConventionRoundTrips();
    void quaternionOrdersAndMatrixOrders();
    void buildRotationRejectsWrongCount();
    void poseToMat4KeepsTranslation();

    // ── 点动实验推算 ──
    void inferenceIdentifiesEveryConventionBaseJog();
    void inferenceIdentifiesEveryConventionToolJog();
    // 只绕同一根轴点动时，前两根轴互换的约定会同时通过 —— 这是数据本身的
    // 局限，工具必须据此提示“再做一组绕另一根轴”，而不是假装能唯一判定。
    void inferenceKeepsTheSwapAmbiguityForASingleJog();
    void inferenceRejectsWrongAngleUnit();
    void inferenceRejectsJogOutsideTheValidRange();
    void inferenceRejectsUnrelatedPoses();
    void inferenceRejectsEmptyInput();
    void inferenceSortsAlignedCandidatesFirst();
};
