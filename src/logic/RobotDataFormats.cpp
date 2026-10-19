#include "logic/RobotDataFormats.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace RobotDataFormats {

namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr double kDegPerRad = 180.0 / kPi;

double clampUnit(double v)
{
    return std::max(-1.0, std::min(1.0, v));
}

double radians(double v, TransformTools::AngleUnit unit)
{
    return TransformTools::toRadians(v, unit);
}

double angleOut(double rad, TransformTools::AngleUnit unit)
{
    return unit == TransformTools::AngleUnit::Degree ? rad * kDegPerRad : rad;
}

int axisIndex(Axis a)
{
    switch (a) {
    case Axis::X: return 0;
    case Axis::Y: return 1;
    case Axis::Z: return 2;
    }
    return 0;
}

QString axisLetter(Axis a)
{
    switch (a) {
    case Axis::X: return QStringLiteral("X");
    case Axis::Y: return QStringLiteral("Y");
    case Axis::Z: return QStringLiteral("Z");
    }
    return QStringLiteral("?");
}

using Rot3 = TransformTools::Rot3;

Rot3 identity()
{
    return Rot3{ 1, 0, 0, 0, 1, 0, 0, 0, 1 };
}

Rot3 axisRotation(Axis axis, double angle)
{
    const double c = std::cos(angle), s = std::sin(angle);
    switch (axis) {
    case Axis::X:
        return Rot3{ 1, 0, 0, 0, c, -s, 0, s, c };
    case Axis::Y:
        return Rot3{ c, 0, s, 0, 1, 0, -s, 0, c };
    case Axis::Z:
        return Rot3{ c, -s, 0, s, c, 0, 0, 0, 1 };
    }
    return identity();
}

Rot3 mul3(const Rot3& a, const Rot3& b)
{
    Rot3 r{};
    for (int row = 0; row < 3; ++row) {
        for (int col = 0; col < 3; ++col) {
            double sum = 0.0;
            for (int k = 0; k < 3; ++k)
                sum += a[static_cast<std::size_t>(row * 3 + k)]
                     * b[static_cast<std::size_t>(k * 3 + col)];
            r[static_cast<std::size_t>(row * 3 + col)] = sum;
        }
    }
    return r;
}

Rot3 transpose3(const Rot3& a)
{
    return Rot3{ a[0], a[3], a[6],
                 a[1], a[4], a[7],
                 a[2], a[5], a[8] };
}

bool rotNear(const Rot3& a, const Rot3& b, double eps = 1e-7)
{
    for (std::size_t i = 0; i < a.size(); ++i)
        if (std::abs(a[i] - b[i]) > eps)
            return false;
    return true;
}

// R = Ri(a)·Rj(b)·Rk(c)（内旋）或 Rk(c)·Rj(b)·Ri(a)（外旋）。角度为弧度。
Rot3 eulerRot(Axis i, Axis j, Axis k, bool intrinsic,
              double a, double b, double c)
{
    const Rot3 ri = axisRotation(i, a);
    const Rot3 rj = axisRotation(j, b);
    const Rot3 rk = axisRotation(k, c);
    return intrinsic ? mul3(mul3(ri, rj), rk)
                     : mul3(mul3(rk, rj), ri);
}

// 把 R 按“输出轴 t ← 源轴 src[t]”重排：M[t][u] = R[src[t]][src[u]]。
// 这样任意三轴互异的序列都能复用 rXYZ 的提取公式。
Rot3 gatherSub(const Rot3& r, const int src[3])
{
    Rot3 m{};
    for (int row = 0; row < 3; ++row)
        for (int col = 0; col < 3; ++col)
            m[static_cast<std::size_t>(row * 3 + col)] =
                r[static_cast<std::size_t>(src[row] * 3 + src[col])];
    return m;
}

// 内旋欧拉角逆解。proper = 首尾同轴（i == k）。
bool extractIntrinsic(Axis i, Axis j, Axis k, bool proper,
                      const Rot3& r, double& a, double& b, double& c)
{
    int src[3];
    if (!proper) {
        // 新 X ← i、新 Y ← j、新 Z ← k：M = Rx(a)·Ry(b)·Rz(c)。
        src[0] = axisIndex(i);
        src[1] = axisIndex(j);
        src[2] = axisIndex(k);
    } else {
        // 首尾同轴（i == k）：公式是 Z-Y-Z，所以新 Z ← i（= k）、新 Y ← j、
        // 新 X ← 剩下那根轴。这里 **不能** 直接写 {i, j, k} —— i == k 时
        // 它不是置换，重排出来的 M 根本不是旋转矩阵。
        src[0] = 3 - axisIndex(i) - axisIndex(j);
        src[1] = axisIndex(j);
        src[2] = axisIndex(i);
    }
    const Rot3 m = gatherSub(r, src);

    // 轴重排矩阵 P 是正交的；det(P) = -1 时它是“镜像置换”，
    // 共轭会把旋转角整体取反：P·R(n,θ)·Pᵀ = R(P·n, det(P)·θ)。
    // 所以奇置换下，按 XYZ / ZYZ 公式解出来的角要再取负才是原约定的角。
    int inversions = 0;
    for (int x = 0; x < 3; ++x)
        for (int y = x + 1; y < 3; ++y)
            if (src[x] > src[y])
                ++inversions;
    const double sign = (inversions % 2) ? -1.0 : 1.0;

    double angleA = 0.0, angleB = 0.0, angleC = 0.0;

    if (!proper) {
        // m = Rx(a)·Ry(b)·Rz(c)
        angleB = std::asin(clampUnit(m[2]));
        const double cb = std::cos(angleB);
        if (std::abs(cb) > 1e-8) {
            angleA = std::atan2(-m[5], m[8]);
            angleC = std::atan2(-m[1], m[0]);
        } else {
            // 万向节锁：固定 a = 0，从剩余元素取 c。
            angleA = 0.0;
            angleC = std::atan2(m[3], m[4]);
        }
    } else {
        // m = Rz(a)·Ry(b)·Rz(c)
        angleB = std::acos(clampUnit(m[8]));
        const double sb = std::sin(angleB);
        if (std::abs(sb) > 1e-8) {
            angleA = std::atan2(m[5], m[2]);
            angleC = std::atan2(m[7], -m[6]);
        } else {
            angleA = 0.0;
            angleC = angleB < kPi / 2.0 ? std::atan2(m[3], m[0])
                                        : std::atan2(m[3], -m[0]);
        }
    }

    angleA *= sign;
    angleB *= sign;
    angleC *= sign;

    // 同一旋转还有第二组解；主分支验证不过时换过去（万向节锁附近尤其需要）。
    const std::array<std::array<double, 3>, 2> tries {{
        { angleA, angleB, angleC },
        { angleA + kPi,
          proper ? -angleB : kPi - angleB,
          angleC + kPi },
    }};
    for (const auto& t : tries) {
        if (rotNear(eulerRot(i, j, k, true, t[0], t[1], t[2]), r)) {
            a = t[0];
            b = t[1];
            c = t[2];
            return true;
        }
    }
    return false;
}

Rot3 buildRotationUnchecked(Id id, TransformTools::AngleUnit unit,
                            const std::vector<double>& v)
{
    const Entry& e = entry(id);
    switch (e.kind) {
    case Kind::Euler:
        return eulerRot(e.first, e.second, e.third, e.intrinsic,
                        radians(v[0], unit), radians(v[1], unit),
                        radians(v[2], unit));
    case Kind::RotationVector:
        return TransformTools::rotationVectorToRot(v[0], v[1], v[2], unit);
    case Kind::Quaternion:
        return id == Id::QuatWxyz
                   ? TransformTools::quatToRot(v[1], v[2], v[3], v[0])
                   : TransformTools::quatToRot(v[0], v[1], v[2], v[3]);
    case Kind::Matrix3x3:
        if (id == Id::Matrix3x3Col)
            return Rot3{ v[0], v[3], v[6],
                         v[1], v[4], v[7],
                         v[2], v[5], v[8] };
        return Rot3{ v[0], v[1], v[2],
                     v[3], v[4], v[5],
                     v[6], v[7], v[8] };
    }
    return identity();
}

// ── 目录 ─────────────────────────────────────────────────────────────

Entry makeEuler(Id id, const char* key, Axis first, Axis second, Axis third,
                bool intrinsic, Tier tier, const QString& name,
                const QString& brands)
{
    Entry e;
    e.id = id;
    e.key = QString::fromLatin1(key);
    e.name = name;
    e.brands = brands;
    e.kind = Kind::Euler;
    e.first = first;
    e.second = second;
    e.third = third;
    e.intrinsic = intrinsic;
    e.valueCount = 3;
    e.usesAngleUnit = true;
    e.cardUsable = true;
    e.tier = tier;

    const QString a = axisLetter(first);
    const QString b = axisLetter(second);
    const QString c = axisLetter(third);
    if (intrinsic) {
        e.principle = QStringLiteral(
            "内旋（随动轴）：依次绕 %1 → %2 → %3 转，R = R%1(a)·R%2(b)·R%3(c)")
            .arg(a, b, c);
        e.reading = QStringLiteral(
            "3 个数依次是绕 %1、%2、%3 的转角（单位见「角度单位」）；"
            "每转一次，下一根轴跟着转").arg(a, b, c);
    } else {
        e.principle = QStringLiteral(
            "外旋（固定基轴）：依次绕 %1 → %2 → %3 转，R = R%3(c)·R%2(b)·R%1(a)")
            .arg(a, b, c);
        e.reading = QStringLiteral(
            "3 个数依次是绕 %1、%2、%3 的转角（单位见「角度单位」）；"
            "三根轴都固定在基坐标上").arg(a, b, c);
    }
    return e;
}

Entry makeSimple(Id id, const char* key, Kind kind, int valueCount,
                 bool usesAngleUnit, const QString& name, const QString& brands,
                 const QString& principle, const QString& reading)
{
    Entry e;
    e.id = id;
    e.key = QString::fromLatin1(key);
    e.name = name;
    e.brands = brands;
    e.kind = kind;
    e.valueCount = valueCount;
    e.usesAngleUnit = usesAngleUnit;
    e.cardUsable = valueCount == 3;
    e.tier = Tier::Common;
    e.principle = principle;
    e.reading = reading;
    return e;
}

Entry makeEntry(Id id)
{
    switch (id) {
    case Id::EulerSxyz:
        return makeEuler(id, "sxyz", Axis::X, Axis::Y, Axis::Z, false,
                         Tier::Common, QStringLiteral("欧拉角 sXYZ（静态 XYZ / RPY）"),
                         QStringLiteral(
                             "FANUC 示教器 W/P/R（W 绕 X、P 绕 Y、R 绕 Z）、"
                             "Yaskawa 安川 RX/RY/RZ、Denso、TM、Dobot、AUBO、HANS、"
                             "JAKA、MELFA、ROKAE 珞石、SIASUN 新松、ELITE、STEP、"
                             "HYUNDAI、FLEXIV、DELTA、TOPSTAR、CGXI"));
    case Id::EulerRzyx:
        return makeEuler(id, "rzyx", Axis::Z, Axis::Y, Axis::X, true,
                         Tier::Common, QStringLiteral("欧拉角 rZYX（内旋 ZYX）"),
                         QStringLiteral(
                             "KUKA ABC、ABB EulerZYX / OrientZYX、Epson U/V/W、"
                             "Nachi、Efort 埃夫特、Estun 埃斯顿、Inovance 汇川；"
                             "RVC 官方软件导出的 FANUC 位姿（本项目实测）"));
    case Id::EulerRzyz:
        return makeEuler(id, "rzyz", Axis::Z, Axis::Y, Axis::Z, true,
                         Tier::Common, QStringLiteral("欧拉角 rZYZ（内旋 ZYZ）"),
                         QStringLiteral(
                             "Kawasaki OAT、Doosan A/B/C、Comau、QJAR 钱江"));
    case Id::EulerRxyz:
        return makeEuler(id, "rxyz", Axis::X, Axis::Y, Axis::Z, true,
                         Tier::Common, QStringLiteral("欧拉角 rXYZ（内旋 XYZ）"),
                         QStringLiteral("Stäubli、Turin、ADT"));
    case Id::EulerSzyx:
        return makeEuler(id, "szyx", Axis::Z, Axis::Y, Axis::X, false,
                         Tier::Common, QStringLiteral("欧拉角 sZYX（静态 ZYX）"),
                         QStringLiteral(
                             "无主流品牌默认使用；与 rXYZ 互为倒序写法，"
                             "个别控制器 / 二次开发协议里会出现"));
    case Id::EulerSxzy:
        return makeEuler(id, "sxzy", Axis::X, Axis::Z, Axis::Y, false,
                         Tier::Common, QStringLiteral("欧拉角 sXZY（静态 XZY）"),
                         QStringLiteral("无主流品牌默认使用（少见组合）"));
    case Id::EulerSyxz:
        return makeEuler(id, "syxz", Axis::Y, Axis::X, Axis::Z, false,
                         Tier::Common, QStringLiteral("欧拉角 sYXZ（静态 YXZ）"),
                         QStringLiteral("无主流品牌默认使用（少见组合）"));
    case Id::EulerSyzx:
        return makeEuler(id, "syzx", Axis::Y, Axis::Z, Axis::X, false,
                         Tier::Common, QStringLiteral("欧拉角 sYZX（静态 YZX）"),
                         QStringLiteral("无主流品牌默认使用（少见组合）"));
    case Id::EulerSzxy:
        return makeEuler(id, "szxy", Axis::Z, Axis::X, Axis::Y, false,
                         Tier::Common, QStringLiteral("欧拉角 sZXY（静态 ZXY）"),
                         QStringLiteral("无主流品牌默认使用（少见组合）"));
    case Id::EulerRxzy:
        return makeEuler(id, "rxzy", Axis::X, Axis::Z, Axis::Y, true,
                         Tier::Common, QStringLiteral("欧拉角 rXZY（内旋 XZY）"),
                         QStringLiteral("无主流品牌默认使用（少见组合）"));
    case Id::EulerRyxz:
        return makeEuler(id, "ryxz", Axis::Y, Axis::X, Axis::Z, true,
                         Tier::Common, QStringLiteral("欧拉角 rYXZ（内旋 YXZ）"),
                         QStringLiteral("无主流品牌默认使用（少见组合）"));
    case Id::EulerRyzx:
        return makeEuler(id, "ryzx", Axis::Y, Axis::Z, Axis::X, true,
                         Tier::Common, QStringLiteral("欧拉角 rYZX（内旋 YZX）"),
                         QStringLiteral("无主流品牌默认使用（少见组合）"));
    case Id::EulerRzxy:
        return makeEuler(id, "rzxy", Axis::Z, Axis::X, Axis::Y, true,
                         Tier::Common, QStringLiteral("欧拉角 rZXY（内旋 ZXY）"),
                         QStringLiteral("无主流品牌默认使用（少见组合）"));
    case Id::RotationVector:
        return makeSimple(
            id, "rotvec", Kind::RotationVector, 3, true,
            QStringLiteral("旋转矢量（轴角 / UR）"),
            QStringLiteral("UR 优傲（RX/RY/RZ 为轴角旋转矢量）、部分协作机器人"),
            QStringLiteral(
                "方向 = 转轴，模长 = 转角；先把 3 个数归一化，"
                "再按 R = I + sinθ·[u]× + (1−cosθ)·[u]×² 构造"),
            QStringLiteral(
                "3 个数是 (rx, ry, rz)：模长 = 转角，方向 = 转轴；"
                "角度单位同上方"));
    case Id::QuatWxyz:
        return makeSimple(
            id, "quat_wxyz", Kind::Quaternion, 4, false,
            QStringLiteral("四元数 w x y z"),
            QStringLiteral("ABB RAPID Q1..Q4、RVC HandEyeSDK poseType=1"),
            QStringLiteral("单位四元数 (w, x, y, z)（标量在前），直接构造旋转矩阵"),
            QStringLiteral("4 个数依次是 w, x, y, z；先归一化再使用"));
    case Id::QuatXyzw:
        return makeSimple(
            id, "quat_xyzw", Kind::Quaternion, 4, false,
            QStringLiteral("四元数 x y z w"),
            QStringLiteral("ROS / TF、RVC HandEyeSDK poseType=2"),
            QStringLiteral("单位四元数 (x, y, z, w)（标量在后），直接构造旋转矩阵"),
            QStringLiteral("4 个数依次是 x, y, z, w；先归一化再使用"));
    case Id::Matrix3x3Row:
        return makeSimple(
            id, "matrix_row", Kind::Matrix3x3, 9, false,
            QStringLiteral("旋转矩阵 3×3（行主序）"),
            QStringLiteral("RVC HandEyeSDK 的 16 数矩阵前 3×3、多数 JSON / 视觉接口"),
            QStringLiteral("直接给出 3×3 旋转矩阵 R 的 9 个元素"),
            QStringLiteral("9 个数依次是第 1 行、第 2 行、第 3 行"));
    case Id::Matrix3x3Col:
        return makeSimple(
            id, "matrix_col", Kind::Matrix3x3, 9, false,
            QStringLiteral("旋转矩阵 3×3（列主序）"),
            QStringLiteral("OpenGL / Eigen 列主序、部分视觉库"),
            QStringLiteral("直接给出 3×3 旋转矩阵 R 的 9 个元素，按列优先存放"),
            QStringLiteral("9 个数依次是第 1 列、第 2 列、第 3 列"));
    case Id::EulerRxyx:
        return makeEuler(id, "rxyx", Axis::X, Axis::Y, Axis::X, true,
                         Tier::Advanced, QStringLiteral("欧拉角 rXYX（内旋 XYX）"),
                         QStringLiteral("无主流品牌默认使用（首尾同轴，少见）"));
    case Id::EulerRxzx:
        return makeEuler(id, "rxzx", Axis::X, Axis::Z, Axis::X, true,
                         Tier::Advanced, QStringLiteral("欧拉角 rXZX（内旋 XZX）"),
                         QStringLiteral("无主流品牌默认使用（首尾同轴，少见）"));
    case Id::EulerRyxy:
        return makeEuler(id, "ryxy", Axis::Y, Axis::X, Axis::Y, true,
                         Tier::Advanced, QStringLiteral("欧拉角 rYXY（内旋 YXY）"),
                         QStringLiteral("无主流品牌默认使用（首尾同轴，少见）"));
    case Id::EulerRyzy:
        return makeEuler(id, "ryzy", Axis::Y, Axis::Z, Axis::Y, true,
                         Tier::Advanced, QStringLiteral("欧拉角 rYZY（内旋 YZY）"),
                         QStringLiteral("无主流品牌默认使用（首尾同轴，少见）"));
    case Id::EulerRzxz:
        return makeEuler(id, "rzxz", Axis::Z, Axis::X, Axis::Z, true,
                         Tier::Advanced, QStringLiteral("欧拉角 rZXZ（内旋 ZXZ）"),
                         QStringLiteral("无主流品牌默认使用（首尾同轴，少见）"));
    case Id::EulerSxyx:
        return makeEuler(id, "sxyx", Axis::X, Axis::Y, Axis::X, false,
                         Tier::Advanced, QStringLiteral("欧拉角 sXYX（静态 XYX）"),
                         QStringLiteral("无主流品牌默认使用（首尾同轴，少见）"));
    case Id::EulerSxzx:
        return makeEuler(id, "sxzx", Axis::X, Axis::Z, Axis::X, false,
                         Tier::Advanced, QStringLiteral("欧拉角 sXZX（静态 XZX）"),
                         QStringLiteral("无主流品牌默认使用（首尾同轴，少见）"));
    case Id::EulerSyxy:
        return makeEuler(id, "syxy", Axis::Y, Axis::X, Axis::Y, false,
                         Tier::Advanced, QStringLiteral("欧拉角 sYXY（静态 YXY）"),
                         QStringLiteral("无主流品牌默认使用（首尾同轴，少见）"));
    case Id::EulerSyzy:
        return makeEuler(id, "syzy", Axis::Y, Axis::Z, Axis::Y, false,
                         Tier::Advanced, QStringLiteral("欧拉角 sYZY（静态 YZY）"),
                         QStringLiteral("无主流品牌默认使用（首尾同轴，少见）"));
    case Id::EulerSzxz:
        return makeEuler(id, "szxz", Axis::Z, Axis::X, Axis::Z, false,
                         Tier::Advanced, QStringLiteral("欧拉角 sZXZ（静态 ZXZ）"),
                         QStringLiteral("无主流品牌默认使用（首尾同轴，少见）"));
    case Id::EulerSzyz:
        return makeEuler(id, "szyz", Axis::Z, Axis::Y, Axis::Z, false,
                         Tier::Advanced, QStringLiteral("欧拉角 sZYZ（静态 ZYZ）"),
                         QStringLiteral("无主流品牌默认使用（首尾同轴，少见）"));
    }
    return Entry{};
}

const std::vector<Id>& commonIdsStorage()
{
    // 常用档的显示顺序 = 常见程度：
    //   4 种主流约定 → rZYZ（也常见）→ 其余三轴互异 → 其它表示法。
    static const std::vector<Id> v {
        Id::EulerSxyz,      Id::EulerRzyx,      Id::EulerRzyz,
        Id::EulerRxyz,      Id::EulerSzyx,      Id::EulerSxzy,
        Id::EulerSyxz,      Id::EulerSyzx,      Id::EulerSzxy,
        Id::EulerRxzy,      Id::EulerRyxz,      Id::EulerRyzx,
        Id::EulerRzxy,
        Id::RotationVector, Id::QuatWxyz,       Id::QuatXyzw,
        Id::Matrix3x3Row,   Id::Matrix3x3Col,
    };
    return v;
}

const std::vector<Id>& advancedIdsStorage()
{
    // 首尾同轴的其余 11 种：先把偶见的 ZXZ / ZYZ 外旋排在前面。
    static const std::vector<Id> v {
        Id::EulerRzxz, Id::EulerSzyz, Id::EulerSzxz,
        Id::EulerRxyx, Id::EulerRxzx, Id::EulerRyxy, Id::EulerRyzy,
        Id::EulerSxyx, Id::EulerSxzx, Id::EulerSyxy, Id::EulerSyzy,
    };
    return v;
}

const std::vector<Id>& eulerIdsStorage()
{
    static const std::vector<Id> v = [] {
        std::vector<Id> out;
        for (const Id id : commonIdsStorage())
            if (entry(id).kind == Kind::Euler)
                out.push_back(id);
        for (const Id id : advancedIdsStorage())
            out.push_back(id);
        return out;
    }();
    return v;
}

// 相对旋转矩阵 → (转角, 单位转轴)。转角接近 0 时轴无意义。
bool rotationAxisAngle(const Rot3& d, double& angleRad,
                       std::array<double, 3>& axis)
{
    const double trace = d[0] + d[4] + d[8];
    angleRad = std::acos(clampUnit((trace - 1.0) / 2.0));
    const double s = std::sin(angleRad);

    if (std::abs(s) > 1e-6) {
        axis = { d[7] - d[5], d[2] - d[6], d[3] - d[1] };
    } else if (trace > 0.0) {
        // 近似单位阵：转角 ~ 0，轴不可辨。
        return false;
    } else {
        // 转角 ~ 180°：用 (R + I) 里范数最大的列当轴。
        const std::array<std::array<double, 3>, 3> cols {{
            { d[0] + 1.0, d[3], d[6] },
            { d[1], d[4] + 1.0, d[7] },
            { d[2], d[5], d[8] + 1.0 },
        }};
        int best = 0;
        double bestNorm = -1.0;
        for (int i = 0; i < 3; ++i) {
            const double n = cols[static_cast<std::size_t>(i)][0] * cols[static_cast<std::size_t>(i)][0]
                           + cols[static_cast<std::size_t>(i)][1] * cols[static_cast<std::size_t>(i)][1]
                           + cols[static_cast<std::size_t>(i)][2] * cols[static_cast<std::size_t>(i)][2];
            if (n > bestNorm) {
                bestNorm = n;
                best = i;
            }
        }
        axis = cols[static_cast<std::size_t>(best)];
    }

    const double norm = std::sqrt(axis[0] * axis[0] + axis[1] * axis[1]
                                + axis[2] * axis[2]);
    if (norm < 1e-12)
        return false;
    axis = { axis[0] / norm, axis[1] / norm, axis[2] / norm };
    return true;
}

// 转轴到“用户实际点动的那根轴”（正负都算）的夹角，度。
// 只要求“落在某根基轴上”不够：把轴名循环换一下（sXYZ / sYZX / sZXY）
// 得到的相对旋转同样轴对齐。用户说了点的是 X，就必须是 X。
double axisErrorToDeg(const std::array<double, 3>& axis, Axis target)
{
    const double dot = std::abs(axis[static_cast<std::size_t>(axisIndex(target))]);
    return std::acos(clampUnit(dot)) * kDegPerRad;
}

} // namespace

// ── 目录查询 ─────────────────────────────────────────────────────────

const std::vector<Entry>& entries()
{
    static const std::vector<Entry> all = [] {
        std::vector<Entry> v;
        for (const Id id : commonIdsStorage())
            v.push_back(makeEntry(id));
        for (const Id id : advancedIdsStorage())
            v.push_back(makeEntry(id));
        return v;
    }();
    return all;
}

std::vector<Id> ids(Tier tier)
{
    return tier == Tier::Common ? commonIdsStorage() : advancedIdsStorage();
}

const Entry& entry(Id id)
{
    const int raw = static_cast<int>(id);
    for (const Entry& e : entries())
        if (static_cast<int>(e.id) == raw)
            return e;
    return entries().front();
}

const Entry* findEntry(int raw)
{
    for (const Entry& e : entries())
        if (static_cast<int>(e.id) == raw)
            return &e;
    return nullptr;
}

bool isValidId(int raw)
{
    return findEntry(raw) != nullptr;
}

QString displayName(Id id)
{
    return entry(id).name;
}

QString hint(Id id)
{
    const Entry& e = entry(id);
    return QStringLiteral("常见机器人：%1\n原理：%2\n读法：%3")
        .arg(e.brands, e.principle, e.reading);
}

int valueCount(Id id)
{
    return entry(id).valueCount;
}

bool usesAngleUnit(Id id)
{
    return entry(id).usesAngleUnit;
}

bool cardUsable(Id id)
{
    return entry(id).cardUsable;
}

bool isEuler(Id id)
{
    return entry(id).kind == Kind::Euler;
}

Tier tier(Id id)
{
    return entry(id).tier;
}

// ── 旋转数学 ─────────────────────────────────────────────────────────

TransformTools::Rot3 buildRotation(Id id, TransformTools::AngleUnit unit,
                                   const std::vector<double>& values)
{
    const Entry& e = entry(id);
    if (static_cast<int>(values.size()) != e.valueCount)
        throw std::invalid_argument(
            "RobotDataFormats: rotation value count mismatch");
    return buildRotationUnchecked(id, unit, values);
}

TransformTools::Mat4 poseToMat4(double px, double py, double pz, Id id,
                                TransformTools::AngleUnit unit,
                                const std::vector<double>& rotValues)
{
    return TransformTools::makeMat4(buildRotation(id, unit, rotValues),
                                    px, py, pz);
}

bool eulerAngles(Id id, TransformTools::AngleUnit unit,
                 const TransformTools::Rot3& rot, double out[3])
{
    const Entry& e = entry(id);
    if (e.kind != Kind::Euler)
        return false;

    double a = 0.0, b = 0.0, c = 0.0;
    bool ok = false;
    if (e.intrinsic) {
        ok = extractIntrinsic(e.first, e.second, e.third,
                              e.first == e.third, rot, a, b, c);
    } else {
        // 外旋 (i,j,k) 与内旋 (k,j,i) 同矩阵、角度倒序：
        //   extrinsic(i,j,k)(a,b,c) == intrinsic(k,j,i)(c,b,a)
        double alpha = 0.0, beta = 0.0, gamma = 0.0;
        ok = extractIntrinsic(e.third, e.second, e.first,
                              e.first == e.third, rot, alpha, beta, gamma);
        if (ok) {
            a = gamma;
            b = beta;
            c = alpha;
        }
    }
    if (!ok)
        return false;

    out[0] = angleOut(a, unit);
    out[1] = angleOut(b, unit);
    out[2] = angleOut(c, unit);
    return true;
}

// ── 位姿格式推算 ─────────────────────────────────────────────────────

std::vector<Candidate> inferEulerConventions(const std::vector<PosePair>& pairs,
                                             TransformTools::AngleUnit unit,
                                             JogFrame frame)
{
    std::vector<Candidate> out;
    if (pairs.empty())
        return out;

    for (const Id id : eulerIdsStorage()) {
        Candidate cand;
        cand.id = id;
        cand.axisAligned = true;
        cand.maxAxisErrorDeg = 0.0;
        cand.minRotationDeg = std::numeric_limits<double>::max();
        cand.maxRotationDeg = 0.0;
        double firstAngleDeg = 0.0;
        double firstAxisError = 0.0;
        QString firstAxis;
        bool firstPair = true;

        for (const PosePair& pair : pairs) {
            const Rot3 r1 = buildRotation(id, unit,
                                          { pair.before[0], pair.before[1],
                                            pair.before[2] });
            const Rot3 r2 = buildRotation(id, unit,
                                          { pair.after[0], pair.after[1],
                                            pair.after[2] });
            const Rot3 d = frame == JogFrame::Base
                               ? mul3(r2, transpose3(r1))
                               : mul3(transpose3(r1), r2);

            double angleRad = 0.0;
            std::array<double, 3> axis{};
            const bool axisOk = rotationAxisAngle(d, angleRad, axis);
            const double angleDeg = angleRad * kDegPerRad;
            const double err = axisOk ? axisErrorToDeg(axis, pair.jogAxis) : 180.0;

            cand.minRotationDeg = std::min(cand.minRotationDeg, angleDeg);
            cand.maxRotationDeg = std::max(cand.maxRotationDeg, angleDeg);
            cand.maxAxisErrorDeg = std::max(cand.maxAxisErrorDeg, err);

            if (firstPair) {
                firstPair = false;
                firstAngleDeg = angleDeg;
                firstAxisError = err;
                firstAxis = axisOk
                    ? axisLetter(pair.jogAxis) + QStringLiteral(" 轴")
                    : QString();
            }

            const bool angleInRange = angleDeg >= kMinJogDeg
                                   && angleDeg <= kMaxJogDeg;
            if (!axisOk || !angleInRange || err > kAxisToleranceDeg)
                cand.axisAligned = false;
        }

        if (cand.axisAligned) {
            cand.detail = QStringLiteral("相对旋转 %1°，绕 %2，轴向偏差 %3°")
                .arg(firstAngleDeg, 0, 'f', 2)
                .arg(firstAxis)
                .arg(firstAxisError, 0, 'f', 3);
        } else if (cand.minRotationDeg < kMinJogDeg
                   || cand.maxRotationDeg > kMaxJogDeg) {
            cand.detail = QStringLiteral(
                "相对转角 %1°~%2°，不在 %3°~%4° 的有效范围内")
                .arg(cand.minRotationDeg, 0, 'f', 1)
                .arg(cand.maxRotationDeg, 0, 'f', 1)
                .arg(kMinJogDeg, 0, 'f', 0)
                .arg(kMaxJogDeg, 0, 'f', 0);
        } else {
            cand.detail = QStringLiteral("按该约定读，转轴偏离点动轴的偏差 %1°（超过 %2°）")
                .arg(cand.maxAxisErrorDeg, 0, 'f', 2)
                .arg(kAxisToleranceDeg, 0, 'f', 0);
        }
        out.push_back(cand);
    }

    std::stable_sort(out.begin(), out.end(),
                     [](const Candidate& a, const Candidate& b) {
                         if (a.axisAligned != b.axisAligned)
                             return a.axisAligned;
                         return a.maxAxisErrorDeg < b.maxAxisErrorDeg;
                     });
    return out;
}

} // namespace RobotDataFormats
