#pragma once

#include <QString>

#include <array>
#include <vector>

#include "logic/TransformTools.h"

// 机器人数据格式（位姿里旋转部分的表示法）的唯一目录。
//
// 为什么单独一层：坐标转换页、手眼标定页、位姿格式推算工具都要用同一份
// “有哪些格式 / 怎么念 / 怎么算”。以前这三个地方各自维护枚举、文案和数学，
// 结果出现了两处名不副实（WPR 被当成 FANUC 标准、ZYX 内旋其实是 XYZ 内旋）
// 和一处缺失（ZYZ 内旋）。这里只保留一个定义，UI 只负责投影。
//
// 约定记号（与学界一致）：
//   * 名字里的轴顺序 = 三个值依次对应的轴；
//   * s = static（外旋，绕固定基轴转），r = rotating（内旋，绕随动轴转）；
//   * 三轴互异（Tait-Bryan）12 种，首尾同轴（proper Euler）12 种，共 24 种。
//
// Id 的整数是持久化值（AppConfig::calib_pose_format）：0..6 与旧枚举
// TransformTools::RotationFormat 完全一致，**只能追加，不能重排或复用**。
namespace RobotDataFormats {

enum class Id : int {
    EulerSxyz = 0,      // 旧 EulerRpy：R = Rz(c)·Ry(b)·Rx(a)
    EulerRzyx = 1,      // 旧 EulerWpr：R = Rz(a)·Ry(b)·Rx(c)（KUKA ABC）
    EulerRxyz = 2,      // 旧 EulerZyxIntrinsic（旧名字是错的）：R = Rx(a)·Ry(b)·Rz(c)
    QuatWxyz = 3,       // 旧 QuatWxyz
    QuatXyzw = 4,       // 旧 QuatXyzw
    Matrix3x3Row = 5,   // 旧 RotationMatrix9
    RotationVector = 6, // 旧 RotationVector
    EulerRzyz = 7,      // R = Rz(a)·Ry(b)·Rz(c)
    EulerSzyx = 8,
    EulerSxzy = 9,
    EulerSyxz = 10,
    EulerSyzx = 11,
    EulerSzxy = 12,
    EulerRxzy = 13,
    EulerRyxz = 14,
    EulerRyzx = 15,
    EulerRzxy = 16,
    Matrix3x3Col = 17,
    EulerRxyx = 18,
    EulerRxzx = 19,
    EulerRyxy = 20,
    EulerRyzy = 21,
    EulerRzxz = 22,
    EulerSxyx = 23,
    EulerSxzx = 24,
    EulerSyxy = 25,
    EulerSyzy = 26,
    EulerSzxz = 27,
    EulerSzyz = 28,
    Matrix4x4Row = 29,  // 4×4 姿态变换矩阵（16 数，行主序）= HandEyeSDK poseType=3
};

enum class Axis { X, Y, Z };
enum class Kind { Euler, RotationVector, Quaternion, Matrix3x3, Matrix4x4 };
enum class Tier { Common, Advanced };

struct Entry {
    Id id = Id::EulerSxyz;
    QString key;          // "sxyz" / "rzyx" / "quat_wxyz" / "matrix_row"
    QString name;         // 下拉框里的几何名（不含品牌）
    QString brands;       // 提示第 1 行：常见机器人品牌
    QString principle;    // 提示第 2 行：原理（含公式）
    QString reading;      // 提示第 3 行：三个值怎么读
    Kind kind = Kind::Euler;
    Axis first = Axis::X;   // Euler：第 1 个值对应的轴
    Axis second = Axis::Y;  // Euler：第 2 个值对应的轴
    Axis third = Axis::Z;   // Euler：第 3 个值对应的轴
    bool intrinsic = false; // Euler：true = 内旋，false = 外旋
    int valueCount = 3;     // 旋转部分的原始数值个数
    bool usesAngleUnit = true;
    bool cardUsable = false; // 标定卡片固定 6 个数 → 只有 3 个旋转数的格式能用
    Tier tier = Tier::Common;
};

// 整个目录（显示顺序：常用的在前，首尾同轴的高级项在后）。
const std::vector<Entry>& entries();

// 某一档（常用 / 高级）里的显示顺序。常用档 = 12 种三轴互异 + 旋转矢量
// + 两种四元数 + 4×4 姿态变换矩阵 + 两种 3×3 旋转矩阵；高级档 = 12 种
// 首尾同轴（proper Euler）。勾选框写的就是「首尾同轴」，两档不重叠。
std::vector<Id> ids(Tier tier);

// 查找。isValidId 接受任何合法整数，越界返回 false。
const Entry& entry(Id id);
const Entry* findEntry(int raw);
bool isValidId(int raw);

// 简表
QString displayName(Id id);       // 下拉框文字
QString hint(Id id);              // 三行：常见机器人 / 原理 / 读法
int valueCount(Id id);
bool usesAngleUnit(Id id);
bool cardUsable(Id id);           // 3 个旋转数 → 能写进标定卡片
bool isEuler(Id id);
Tier tier(Id id);

// ── 旋转数学 ─────────────────────────────────────────────────────────
// 3×3 行主序。buildRotation 对任何格式都适用；数值个数不符时抛
// std::invalid_argument（与旧 TransformTools::rotationFromValues 一致）。
TransformTools::Rot3 buildRotation(Id id, TransformTools::AngleUnit unit,
                                   const std::vector<double>& values);

// 4×4 齐次矩阵（行主序）：位置 + 旋转值。
// Matrix4x4Row 例外：rotValues 本身就是 16 个矩阵元素，直接返回它，
// px/py/pz 不参与（位置在第 4 列里，调用方负责单位换算）。
TransformTools::Mat4 poseToMat4(double px, double py, double pz, Id id,
                                TransformTools::AngleUnit unit,
                                const std::vector<double>& rotValues);

// 欧拉角逆解：已知旋转矩阵，求该约定的三个角（单位同 unit）。
// 用于位姿格式推算的测试与“把同一姿态换成另一种写法”的展示。
// 万向节锁时返回一个合法分支；无法验证时返回 false。
bool eulerAngles(Id id, TransformTools::AngleUnit unit,
                 const TransformTools::Rot3& rot, double out[3]);

// ── 位姿格式推算（只回答“24 种欧拉约定里是哪一种”）──────────────
// 角度单位与四元数顺序不在这里推断：现场一般有明确标注（用户 2026-10 决定）。
//
// 原理：机器人绕**基坐标**某一根轴转 θ 时，两组位姿满足
//     R2 = R_axis(θ) · R1   ⇒   D = R2 · R1ᵀ = R_axis(θ)
// 只有“把卡片上的 3 个数读成正确约定”时，D 才会恰好是绕 ±X/±Y/±Z 的旋转；
// 读错约定算出来的 D 几乎不可能是轴对齐的。绕**工具坐标**点动时同理，用
//     R2 = R1 · R_axis(θ)   ⇒   D = R1ᵀ · R2 = R_axis(θ)
// 判据与起始姿态的绝对朝向无关，所以不需要知道机器人当前在世界里的姿态。
enum class JogFrame { Base, Tool };

struct PosePair {
    std::array<double, 3> before{};  // 点动前示教器上的 3 个旋转数
    std::array<double, 3> after{};   // 点动后
    // 用户实际绕哪根轴点的（基坐标或工具坐标，与 JogFrame 一致）。
    // 必须给：只看“相对旋转是不是落在某根基轴上”不够 —— 轴顺序循环
    // 换名（如 sXYZ / sYZX / sZXY）得到的相对旋转同样是轴对齐的，
    // 只有把“你点的是 X”也作为条件才能把它们分开。
    Axis jogAxis = Axis::X;
};

struct Candidate {
    Id id = Id::EulerSxyz;
    bool axisAligned = false;        // 所有实验的 D 都落在 ±X/±Y/±Z 的容差内
    double maxAxisErrorDeg = 180.0;  // 所有实验里最大的转轴偏差
    double minRotationDeg = 0.0;     // 所有实验里最小的相对转角
    double maxRotationDeg = 0.0;
    QString detail;                  // 给界面显示的一句话
};

// 对 24 种欧拉约定逐一打分，按“先看轴对齐、再看轴向偏差”排序。
// 判据：按该约定读出来的相对旋转，必须正好绕 PosePair::jogAxis 那一根轴
// （偏差 ≤ kAxisToleranceDeg），且转角在 5°~175°。空输入返回空。
std::vector<Candidate> inferEulerConventions(const std::vector<PosePair>& pairs,
                                             TransformTools::AngleUnit unit,
                                             JogFrame frame);

// 判据容差（度）：转轴偏离最近基轴超过该值即判为该约定不成立。
constexpr double kAxisToleranceDeg = 2.0;
// 有效实验的转角范围：太小的角度对轴向噪声敏感，接近 180° 时轴向病态。
constexpr double kMinJogDeg = 5.0;
constexpr double kMaxJogDeg = 175.0;

} // namespace RobotDataFormats
