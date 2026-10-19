#include "test_robot_data_formats.h"

#include "logic/RobotDataFormats.h"
#include "logic/TransformTools.h"

#include <QtTest>

#include <QSet>
#include <QStringList>
#include <array>
#include <cmath>
#include <stdexcept>
#include <vector>

namespace {

using RobotDataFormats::Axis;
using RobotDataFormats::Id;
using RobotDataFormats::Kind;
using RobotDataFormats::Tier;
using TransformTools::AngleUnit;
using TransformTools::Rot3;

constexpr double kPi = 3.14159265358979323846;

bool rotNear(const Rot3& a, const Rot3& b, double eps = 1e-8)
{
    for (std::size_t i = 0; i < a.size(); ++i)
        if (std::abs(a[i] - b[i]) > eps)
            return false;
    return true;
}

std::vector<Id> eulerIds()
{
    std::vector<Id> out;
    for (const auto& e : RobotDataFormats::entries())
        if (e.kind == Kind::Euler)
            out.push_back(e.id);
    return out;
}

std::vector<Id> allIds()
{
    std::vector<Id> out;
    for (const auto& e : RobotDataFormats::entries())
        out.push_back(e.id);
    return out;
}

RobotDataFormats::Axis axisFor(char axis)
{
    switch (axis) {
    case 'X': return RobotDataFormats::Axis::X;
    case 'Y': return RobotDataFormats::Axis::Y;
    default:  return RobotDataFormats::Axis::Z;
    }
}

Rot3 axisRot(char axis, double degrees)
{
    const double t = degrees * kPi / 180.0;
    const double c = std::cos(t), s = std::sin(t);
    switch (axis) {
    case 'X':
        return Rot3{ 1, 0, 0, 0, c, -s, 0, s, c };
    case 'Y':
        return Rot3{ c, 0, s, 0, 1, 0, -s, 0, c };
    default:
        return Rot3{ c, -s, 0, s, c, 0, 0, 0, 1 };
    }
}

Rot3 mul3(const Rot3& a, const Rot3& b)
{
    Rot3 r{};
    for (int row = 0; row < 3; ++row)
        for (int col = 0; col < 3; ++col) {
            double sum = 0.0;
            for (int k = 0; k < 3; ++k)
                sum += a[static_cast<std::size_t>(row * 3 + k)]
                     * b[static_cast<std::size_t>(k * 3 + col)];
            r[static_cast<std::size_t>(row * 3 + col)] = sum;
        }
    return r;
}

Rot3 rotationOf(Id id, const std::array<double, 3>& angles)
{
    return RobotDataFormats::buildRotation(
        id, AngleUnit::Degree, { angles[0], angles[1], angles[2] });
}

// 用真约定把“转完之后的矩阵”写回示教器会显示的那 3 个数。
bool anglesOf(Id id, const Rot3& rot, std::array<double, 3>& out)
{
    double v[3] = { 0.0, 0.0, 0.0 };
    if (!RobotDataFormats::eulerAngles(id, AngleUnit::Degree, rot, v))
        return false;
    out = { v[0], v[1], v[2] };
    return true;
}

// 合成一组“绕基坐标轴点动”：R2 = R_axis(θ)·R1。
bool makeBasePair(Id id, const std::array<double, 3>& start,
                  char axis, double degrees,
                  RobotDataFormats::PosePair& pair)
{
    const Rot3 r1 = rotationOf(id, start);
    const Rot3 r2 = mul3(axisRot(axis, degrees), r1);
    std::array<double, 3> after{};
    if (!anglesOf(id, r2, after))
        return false;
    pair.before = start;
    pair.after = after;
    pair.jogAxis = axisFor(axis);
    return true;
}

// 合成一组“绕工具坐标轴点动”：R2 = R1·R_axis(θ)。
bool makeToolPair(Id id, const std::array<double, 3>& start,
                  char axis, double degrees,
                  RobotDataFormats::PosePair& pair)
{
    const Rot3 r1 = rotationOf(id, start);
    const Rot3 r2 = mul3(r1, axisRot(axis, degrees));
    std::array<double, 3> after{};
    if (!anglesOf(id, r2, after))
        return false;
    pair.before = start;
    pair.after = after;
    pair.jogAxis = axisFor(axis);
    return true;
}

std::vector<RobotDataFormats::Candidate> matchedOnly(
    const std::vector<RobotDataFormats::Candidate>& ranked)
{
    std::vector<RobotDataFormats::Candidate> out;
    for (const auto& c : ranked)
        if (c.axisAligned)
            out.push_back(c);
    return out;
}

QString describeMatches(const std::vector<RobotDataFormats::Candidate>& matched)
{
    QStringList names;
    for (const auto& c : matched)
        names << RobotDataFormats::displayName(c.id);
    return names.join(QStringLiteral(" / "));
}

} // namespace

// ── 目录 ─────────────────────────────────────────────────────────────

void TestRobotDataFormats::idIntegersKeepThePersistedLegacyValues()
{
    // AppConfig 的 calib_pose_format 存的是这些整数。老用户升级后 0..6
    // 必须还是原来那个意思，否则“重启后又变了”。
    QCOMPARE(static_cast<int>(Id::EulerSxyz), 0);       // 旧 EulerRpy
    QCOMPARE(static_cast<int>(Id::EulerRzyx), 1);       // 旧 EulerWpr
    QCOMPARE(static_cast<int>(Id::EulerRxyz), 2);       // 旧 EulerZyxIntrinsic
    QCOMPARE(static_cast<int>(Id::QuatWxyz), 3);
    QCOMPARE(static_cast<int>(Id::QuatXyzw), 4);
    QCOMPARE(static_cast<int>(Id::Matrix3x3Row), 5);     // 旧 RotationMatrix9
    QCOMPARE(static_cast<int>(Id::RotationVector), 6);
}

void TestRobotDataFormats::catalogHasAll24EulerConventions()
{
    QCOMPARE(RobotDataFormats::entries().size(), static_cast<std::size_t>(29));
    QCOMPARE(eulerIds().size(), static_cast<std::size_t>(24));

    // 12 种三轴互异 + 12 种首尾同轴。
    int distinct = 0, proper = 0;
    for (const Id id : eulerIds()) {
        const auto& e = RobotDataFormats::entry(id);
        if (e.first == e.third)
            ++proper;
        else
            ++distinct;
    }
    QCOMPARE(distinct, 12);
    QCOMPARE(proper, 12);

    // 常用档 18 项、高级档 11 项，合起来刚好是全目录（没有漏项/重项）。
    QCOMPARE(RobotDataFormats::ids(Tier::Common).size(), static_cast<std::size_t>(18));
    QCOMPARE(RobotDataFormats::ids(Tier::Advanced).size(), static_cast<std::size_t>(11));
    QCOMPARE(allIds().size(), static_cast<std::size_t>(29));
}

void TestRobotDataFormats::displayNamesAreUniqueAndNonEmpty()
{
    QSet<QString> seen;
    for (const Id id : allIds()) {
        const QString name = RobotDataFormats::displayName(id);
        QVERIFY2(!name.isEmpty(), "格式名不能为空");
        QVERIFY2(!seen.contains(name),
                 qPrintable(QStringLiteral("格式名重复：") + name));
        seen.insert(name);
    }
    QCOMPARE(seen.size(), 29);
}

void TestRobotDataFormats::hintsCarryBrandsPrincipleAndReading()
{
    for (const Id id : allIds()) {
        const QString hint = RobotDataFormats::hint(id);
        const QString name = RobotDataFormats::displayName(id);
        QVERIFY2(hint.contains(QStringLiteral("常见机器人：")),
                 qPrintable(name + QStringLiteral("：缺品牌行")));
        QVERIFY2(hint.contains(QStringLiteral("原理：")),
                 qPrintable(name + QStringLiteral("：缺原理行")));
        QVERIFY2(hint.contains(QStringLiteral("读法：")),
                 qPrintable(name + QStringLiteral("：缺读法行")));
        // 品牌只出现在提示里，不出现在下拉框文字里。
        QVERIFY2(!name.contains(QStringLiteral("FANUC"))
                     && !name.contains(QStringLiteral("KUKA"))
                     && !name.contains(QStringLiteral("UR ")),
                 qPrintable(QStringLiteral("下拉项里混进了品牌：") + name));
    }
}

void TestRobotDataFormats::advancedTierIsTheRemainingProperEulerSet()
{
    // 用户勾“高级”才看到的 11 项，全部是首尾同轴；常用档里只留 rZYZ
    // 这一种（Kawasaki / Doosan / Comau 在用的常见约定）。
    for (const Id id : RobotDataFormats::ids(Tier::Advanced)) {
        const auto& e = RobotDataFormats::entry(id);
        QVERIFY2(e.kind == Kind::Euler,
                 qPrintable(RobotDataFormats::displayName(id)));
        QVERIFY2(e.first == e.third,
                 qPrintable(RobotDataFormats::displayName(id)));
    }
    QVERIFY(RobotDataFormats::tier(Id::EulerRzyz) == Tier::Common);

    int properInCommon = 0;
    for (const Id id : RobotDataFormats::ids(Tier::Common)) {
        const auto& e = RobotDataFormats::entry(id);
        if (e.kind == Kind::Euler && e.first == e.third)
            ++properInCommon;
    }
    QCOMPARE(properInCommon, 1);
}

void TestRobotDataFormats::cardUsableOnlyForThreeValueFormats()
{
    for (const Id id : allIds()) {
        const auto& e = RobotDataFormats::entry(id);
        // 标定卡片固定 6 个数（x y z + 3 个旋转数）—— 只有 3 值格式能写进去。
        QVERIFY2(RobotDataFormats::cardUsable(id) == (e.valueCount == 3),
                 qPrintable(RobotDataFormats::displayName(id)));
    }
    QVERIFY(RobotDataFormats::cardUsable(Id::EulerSxyz));
    QVERIFY(!RobotDataFormats::cardUsable(Id::QuatWxyz));
    QVERIFY(!RobotDataFormats::cardUsable(Id::Matrix3x3Row));
}

// ── 旋转数学 ─────────────────────────────────────────────────────────

void TestRobotDataFormats::knownConventionsProduceKnownRotations()
{
    // sXYZ：R = Rz(c)·Ry(b)·Rx(a)。第 1 个数绕 X。
    QVERIFY(rotNear(rotationOf(Id::EulerSxyz, { 90, 0, 0 }),
                    Rot3{ 1, 0, 0, 0, 0, -1, 0, 1, 0 }));
    // rZYX：R = Rz(a)·Ry(b)·Rx(c)。第 3 个数绕 X。
    QVERIFY(rotNear(rotationOf(Id::EulerRzyx, { 0, 0, 90 }),
                    Rot3{ 1, 0, 0, 0, 0, -1, 0, 1, 0 }));
    // rZYX 的第 1 个数绕 Z（KUKA ABC 的 A）。
    QVERIFY(rotNear(rotationOf(Id::EulerRzyx, { 90, 0, 0 }),
                    Rot3{ 0, -1, 0, 1, 0, 0, 0, 0, 1 }));
    // rXYZ：R = Rx(a)·Ry(b)·Rz(c)。第 1 个数绕 X。
    QVERIFY(rotNear(rotationOf(Id::EulerRxyz, { 90, 0, 0 }),
                    Rot3{ 1, 0, 0, 0, 0, -1, 0, 1, 0 }));
    // rZYZ（Kawasaki OAT）：a = 0, b = 0 时只剩 Rz(c)。
    QVERIFY(rotNear(rotationOf(Id::EulerRzyz, { 0, 0, 90 }),
                    Rot3{ 0, -1, 0, 1, 0, 0, 0, 0, 1 }));
}

void TestRobotDataFormats::extrinsicEqualsReversedIntrinsic()
{
    // extrinsic(i,j,k)(a,b,c) == intrinsic(k,j,i)(c,b,a)。这条恒等式是
    // 24 种约定之间互相转换的基础，也说明外旋与内旋不能靠“名字像”来判断。
    int found = 0;
    for (const Id id : eulerIds()) {
        const auto& e = RobotDataFormats::entry(id);
        Id reversed = Id::EulerSxyz;
        bool haveReversed = false;
        for (const Id other : eulerIds()) {
            const auto& o = RobotDataFormats::entry(other);
            if (o.first == e.third && o.second == e.second
                    && o.third == e.first && o.intrinsic != e.intrinsic) {
                reversed = other;
                haveReversed = true;
                break;
            }
        }
        QVERIFY2(haveReversed, qPrintable(QStringLiteral("缺少倒序约定：")
                                              + RobotDataFormats::displayName(id)));

        const std::array<double, 3> abc { 23.0, -41.0, 67.0 };
        const Rot3 direct = rotationOf(id, abc);
        const Rot3 mirrored = rotationOf(reversed, { abc[2], abc[1], abc[0] });
        QVERIFY2(rotNear(direct, mirrored, 1e-8),
                 qPrintable(RobotDataFormats::displayName(id) + QStringLiteral(" vs ")
                            + RobotDataFormats::displayName(reversed)));
        ++found;
    }
    QCOMPARE(found, 24);
}

void TestRobotDataFormats::everyEulerConventionRoundTrips()
{
    const std::array<std::array<double, 3>, 4> samples {{
        {{ 20.0, -35.0, 50.0 }},
        {{ -15.0, 40.0, -70.0 }},
        {{ 120.0, 25.0, -10.0 }},
        {{ 0.0, 0.0, 0.0 }},
    }};

    for (const Id id : eulerIds()) {
        for (const auto& abc : samples) {
            const Rot3 r = rotationOf(id, abc);
            double out[3] = { 0.0, 0.0, 0.0 };
            const bool ok = RobotDataFormats::eulerAngles(
                id, AngleUnit::Degree, r, out);
            QVERIFY2(ok, qPrintable(RobotDataFormats::displayName(id)
                                    + QStringLiteral("：逆解失败")));
            const Rot3 back = RobotDataFormats::buildRotation(
                id, AngleUnit::Degree, { out[0], out[1], out[2] });
            QVERIFY2(rotNear(r, back, 1e-7),
                     qPrintable(QStringLiteral("%1：[%2 %3 %4] -> [%5 %6 %7]")
                                    .arg(RobotDataFormats::displayName(id))
                                    .arg(abc[0]).arg(abc[1]).arg(abc[2])
                                    .arg(out[0], 0, 'f', 6)
                                    .arg(out[1], 0, 'f', 6)
                                    .arg(out[2], 0, 'f', 6)));
        }
    }
}

void TestRobotDataFormats::quaternionOrdersAndMatrixOrders()
{
    // wxyz 与 xyzw 读同一组分量只是顺序不同；列主序矩阵是行主序的转置。
    const Rot3 wxyz = RobotDataFormats::buildRotation(
        Id::QuatWxyz, AngleUnit::Radian, { 0.5, 0.5, 0.5, 0.5 });
    const Rot3 xyzw = RobotDataFormats::buildRotation(
        Id::QuatXyzw, AngleUnit::Radian, { 0.5, 0.5, 0.5, 0.5 });
    QVERIFY(rotNear(wxyz, xyzw));
    QVERIFY(rotNear(wxyz, TransformTools::quatToRot(0.5, 0.5, 0.5, 0.5)));

    const std::vector<double> m { 0, 0, 1,
                                  0, 1, 0,
                                 -1, 0, 0 };
    const Rot3 row = RobotDataFormats::buildRotation(
        Id::Matrix3x3Row, AngleUnit::Radian, m);
    const Rot3 col = RobotDataFormats::buildRotation(
        Id::Matrix3x3Col, AngleUnit::Radian, m);
    QVERIFY(rotNear(row, Rot3{ 0, 0, 1, 0, 1, 0, -1, 0, 0 }));
    QVERIFY(rotNear(col, Rot3{ 0, 0, -1, 0, 1, 0, 1, 0, 0 }));
    QVERIFY(rotNear(mul3(row, col), Rot3{ 1, 0, 0, 0, 1, 0, 0, 0, 1 }));

    // 轴角按单位制换算：90° == π/2 rad。
    const Rot3 vecDeg = RobotDataFormats::buildRotation(
        Id::RotationVector, AngleUnit::Degree, { 0, 0, 90 });
    const Rot3 vecRad = RobotDataFormats::buildRotation(
        Id::RotationVector, AngleUnit::Radian, { 0, 0, kPi / 2.0 });
    QVERIFY(rotNear(vecDeg, vecRad));
}

void TestRobotDataFormats::buildRotationRejectsWrongCount()
{
    QVERIFY_EXCEPTION_THROWN(
        RobotDataFormats::buildRotation(Id::EulerSxyz, AngleUnit::Degree, { 1, 2 }),
        std::invalid_argument);
    QVERIFY_EXCEPTION_THROWN(
        RobotDataFormats::buildRotation(Id::QuatWxyz, AngleUnit::Degree, { 1, 2, 3 }),
        std::invalid_argument);
    QVERIFY_EXCEPTION_THROWN(
        RobotDataFormats::buildRotation(Id::Matrix3x3Row, AngleUnit::Degree,
                                        { 1, 2, 3, 4, 5, 6, 7, 8 }),
        std::invalid_argument);
}

void TestRobotDataFormats::poseToMat4KeepsTranslation()
{
    const TransformTools::Mat4 m = RobotDataFormats::poseToMat4(
        1, 2, 3, Id::EulerSxyz, AngleUnit::Degree, { 90, 0, 0 });
    double x = 0, y = 0, z = 0;
    TransformTools::transformPoint(m, 0, 1, 0, x, y, z);
    QVERIFY(std::abs(x - 1.0) < 1e-12);
    QVERIFY(std::abs(y - 2.0) < 1e-12);
    QVERIFY(std::abs(z - 4.0) < 1e-12);
}

// ── 点动实验推算 ─────────────────────────────────────────────────────

void TestRobotDataFormats::inferenceIdentifiesEveryConventionBaseJog()
{
    // 对每一种约定合成一个“真机器人”：起始姿态三轴都不为 0，先绕基轴 X
    // 转 25°，再绕基轴 Z 转 40°。两组实验合起来必须只剩唯一候选。
    for (const Id id : eulerIds()) {
        const std::array<double, 3> start { 20.0, -35.0, 50.0 };
        RobotDataFormats::PosePair pairX, pairZ;
        const QString name = RobotDataFormats::displayName(id);
        QVERIFY2(makeBasePair(id, start, 'X', 25.0, pairX),
                 qPrintable(name + QStringLiteral("：合成 X 点动失败")));
        QVERIFY2(makeBasePair(id, start, 'Z', 40.0, pairZ),
                 qPrintable(name + QStringLiteral("：合成 Z 点动失败")));

        const auto ranked = RobotDataFormats::inferEulerConventions(
            { pairX, pairZ }, AngleUnit::Degree, RobotDataFormats::JogFrame::Base);
        const auto matched = matchedOnly(ranked);
        QVERIFY2(matched.size() == 1,
                 qPrintable(QStringLiteral("%1：匹配到 %2 种（%3）")
                                .arg(name)
                                .arg(matched.size())
                                .arg(describeMatches(matched))));
        QVERIFY2(matched.front().id == id,
                 qPrintable(QStringLiteral("%1 被判成了 %2")
                                .arg(name, RobotDataFormats::displayName(
                                               matched.front().id))));
    }
}

void TestRobotDataFormats::inferenceIdentifiesEveryConventionToolJog()
{
    // 绕工具坐标点动：R2 = R1·R_axis(θ)，判据换成 D = R1ᵀ·R2。
    for (const Id id : eulerIds()) {
        const std::array<double, 3> start { -25.0, 30.0, -55.0 };
        RobotDataFormats::PosePair pairY, pairZ;
        const QString name = RobotDataFormats::displayName(id);
        QVERIFY2(makeToolPair(id, start, 'Y', 30.0, pairY),
                 qPrintable(name + QStringLiteral("：合成 Y 点动失败")));
        QVERIFY2(makeToolPair(id, start, 'Z', 35.0, pairZ),
                 qPrintable(name + QStringLiteral("：合成 Z 点动失败")));

        const auto ranked = RobotDataFormats::inferEulerConventions(
            { pairY, pairZ }, AngleUnit::Degree, RobotDataFormats::JogFrame::Tool);
        const auto matched = matchedOnly(ranked);
        QVERIFY2(matched.size() == 1,
                 qPrintable(QStringLiteral("%1：匹配到 %2 种（%3）")
                                .arg(name)
                                .arg(matched.size())
                                .arg(describeMatches(matched))));
        QVERIFY2(matched.front().id == id,
                 qPrintable(QStringLiteral("%1 被判成了 %2")
                                .arg(name, RobotDataFormats::displayName(
                                               matched.front().id))));
    }
}

void TestRobotDataFormats::inferenceKeepsTheSwapAmbiguityForASingleJog()
{
    // 只绕 Z 点动时，sXYZ 与 sYXZ 的“第三个值”都绕 Z：
    //   sXYZ: R = Rz(c)·Ry(b)·Rx(a)
    //   sYXZ: R = Rz(c)·Rx(b)·Ry(a)
    // 前两个值不变、第三个值加同一个角，相对旋转都是 Rz(θ)。
    // 这不是判据写错了，是数据本身分不开 —— 界面必须据此提示再做一组不同轴。
    RobotDataFormats::PosePair pair;
    QVERIFY(makeBasePair(Id::EulerSxyz, { 15.0, -25.0, 35.0 }, 'Z', 45.0, pair));
    const auto matched = matchedOnly(RobotDataFormats::inferEulerConventions(
        { pair }, AngleUnit::Degree, RobotDataFormats::JogFrame::Base));

    bool hasSxyz = false, hasSyxz = false;
    for (const auto& c : matched) {
        hasSxyz = hasSxyz || c.id == Id::EulerSxyz;
        hasSyxz = hasSyxz || c.id == Id::EulerSyxz;
    }
    QVERIFY2(hasSxyz, qPrintable(describeMatches(matched)));
    QVERIFY2(hasSyxz, qPrintable(describeMatches(matched)));
    QVERIFY2(matched.size() >= 2, qPrintable(describeMatches(matched)));
}

void TestRobotDataFormats::inferenceRejectsWrongAngleUnit()
{
    // 数字是“度”，却按弧度读 —— 必须一种都判不出来，而不是硬塞一个答案。
    RobotDataFormats::PosePair pairX, pairZ;
    QVERIFY(makeBasePair(Id::EulerSxyz, { 20.0, -35.0, 50.0 }, 'X', 25.0, pairX));
    QVERIFY(makeBasePair(Id::EulerSxyz, { 20.0, -35.0, 50.0 }, 'Z', 40.0, pairZ));

    const auto matched = matchedOnly(RobotDataFormats::inferEulerConventions(
        { pairX, pairZ }, AngleUnit::Radian, RobotDataFormats::JogFrame::Base));
    bool hasSxyz = false;
    for (const auto& c : matched)
        hasSxyz = hasSxyz || c.id == Id::EulerSxyz;
    QVERIFY2(!hasSxyz,
             qPrintable(QStringLiteral("错单位却判出了 sXYZ：") + describeMatches(matched)));
}

void TestRobotDataFormats::inferenceRejectsJogOutsideTheValidRange()
{
    const std::array<double, 3> start { 20.0, -35.0, 50.0 };

    // 只转了 1°：噪声就能让轴偏差看起来“对齐”，判据必须直接拒绝。
    RobotDataFormats::PosePair tiny;
    QVERIFY(makeBasePair(Id::EulerSxyz, start, 'X', 1.0, tiny));
    auto matched = matchedOnly(RobotDataFormats::inferEulerConventions(
        { tiny }, AngleUnit::Degree, RobotDataFormats::JogFrame::Base));
    QVERIFY2(matched.empty(),
             qPrintable(QStringLiteral("1° 点动却匹配到：") + describeMatches(matched)));

    // 179°：接近半圈时转轴病态，真约定必须被拒绝。
    // （别的约定碰巧算出别的角度时可能通过 —— 所以只断言“真约定不在里面”。）
    RobotDataFormats::PosePair huge;
    QVERIFY(makeBasePair(Id::EulerSxyz, start, 'X', 179.0, huge));
    matched = matchedOnly(RobotDataFormats::inferEulerConventions(
        { huge }, AngleUnit::Degree, RobotDataFormats::JogFrame::Base));
    bool hasSxyz = false;
    for (const auto& c : matched)
        hasSxyz = hasSxyz || c.id == Id::EulerSxyz;
    QVERIFY2(!hasSxyz,
             qPrintable(QStringLiteral("179° 点动却判出了 sXYZ：") + describeMatches(matched)));

    // 转动前后一模一样：轴不可辨。
    RobotDataFormats::PosePair same;
    same.before = start;
    same.after = start;
    matched = matchedOnly(RobotDataFormats::inferEulerConventions(
        { same }, AngleUnit::Degree, RobotDataFormats::JogFrame::Base));
    QVERIFY(matched.empty());
}

void TestRobotDataFormats::inferenceRejectsUnrelatedPoses()
{
    // 两组姿态之间不是“绕一根轴点动”的关系：不允许随便挑一个最像的。
    RobotDataFormats::PosePair a, b;
    a.before = { 10.0, 20.0, 30.0 };
    a.after = { -70.0, 5.0, 160.0 };
    b.before = { -40.0, 80.0, -15.0 };
    b.after = { 95.0, -60.0, 10.0 };

    const auto matched = matchedOnly(RobotDataFormats::inferEulerConventions(
        { a, b }, AngleUnit::Degree, RobotDataFormats::JogFrame::Base));
    QVERIFY2(matched.empty(),
             qPrintable(QStringLiteral("无关数据却匹配到：") + describeMatches(matched)));
}

void TestRobotDataFormats::inferenceRejectsEmptyInput()
{
    QVERIFY(RobotDataFormats::inferEulerConventions(
                {}, AngleUnit::Degree, RobotDataFormats::JogFrame::Base).empty());
    QVERIFY(RobotDataFormats::inferEulerConventions(
                {}, AngleUnit::Degree, RobotDataFormats::JogFrame::Tool).empty());
}

void TestRobotDataFormats::inferenceSortsAlignedCandidatesFirst()
{
    RobotDataFormats::PosePair pairX, pairZ;
    QVERIFY(makeBasePair(Id::EulerSxyz, { 20.0, -35.0, 50.0 }, 'X', 25.0, pairX));
    QVERIFY(makeBasePair(Id::EulerSxyz, { 20.0, -35.0, 50.0 }, 'Z', 40.0, pairZ));

    const auto ranked = RobotDataFormats::inferEulerConventions(
        { pairX, pairZ }, AngleUnit::Degree, RobotDataFormats::JogFrame::Base);
    QCOMPARE(ranked.size(), static_cast<std::size_t>(24));
    QVERIFY(ranked.front().axisAligned);
    QVERIFY(!ranked.front().detail.isEmpty());
    QVERIFY2(ranked.front().maxAxisErrorDeg <= RobotDataFormats::kAxisToleranceDeg,
             qPrintable(ranked.front().detail));

    // 排好序之后不允许再出现“未对齐的排在已对齐的前面”。
    bool seenMiss = false;
    double lastErr = -1.0;
    bool lastAligned = true;
    for (const auto& c : ranked) {
        if (!c.axisAligned)
            seenMiss = true;
        else
            QVERIFY2(!seenMiss, "已对齐的候选被排到了未对齐的后面");
        if (c.axisAligned == lastAligned)
            QVERIFY(c.maxAxisErrorDeg + 1e-12 >= lastErr);
        lastAligned = c.axisAligned;
        lastErr = c.maxAxisErrorDeg;
        QVERIFY(!c.detail.isEmpty());
    }
}
