#pragma once

#include <QString>
#include <algorithm>
#include <array>
#include <cmath>
#include <map>
#include <vector>

#include "logic/PoseGuide.h"
#include "logic/ToolInputParser.h"

// Batch quality check for a calibration session (stage 8).
//
// Runs a set of advisory checks over the collected records and produces a graded
// report with an overall conclusion.  Purely advisory — it reports, never
// blocks saving or calibration (see PROJECT.md "质量告警不拦截").
//
// ── 为什么"用哪一列"必须显式给进来 ────────────────────────────────────
// 判定分散度的数据列是**标定方式**的属性，不是记录的属性：
//   * 标定板（同心圆 / 黑底白圆），两种安装方式 → robot_capture_pose（6 值，带姿态）
//   * 戳点标定 + 眼在手上                      → robot_capture_pose（6 值，带姿态）
//   * 戳点标定 + 眼在手外                      → 不采拍照位姿！只有 robot_target_xyz（3 值，仅位置）
// 以前这里固定读 robot_capture_pose，于是"眼在手外 + 戳点"下所有记录都是空位姿：
// 全部检查落在空集合上，逐项报"正常"，用户看到一份与数据无关的假报告。
// 现在列由调用方按模式给出（见 sourceFor），报告里也会写明用的是哪一列，
// 并且"没数据可判"会报成 NotApplicable（不适用）而不是 Pass（通过）。
namespace DataQualityCheck {

// 本方式用来判定「近重复 / 离群 / 分散度」的数据列。
enum class PoseSource {
    RobotCapturePose,   // robot_capture_pose：6 值 x y z rx ry rz
    RobotTargetXyz      // robot_target_xyz：3 值 x y z（无姿态）
};

// 该列是否带姿态分量 —— 决定姿态类判据（角差 / 角度离群 / 姿态分散度）是否适用。
inline bool sourceHasOrientation(PoseSource s)
{
    return s == PoseSource::RobotCapturePose;
}

inline QString sourceName(PoseSource s)
{
    return s == PoseSource::RobotTargetXyz
        ? QStringLiteral("机器人目标点") : QStringLiteral("机器人拍照位姿");
}

// 模式 → 数据列。判据与 DataInputArea::updateVisibility() 的 hidePose 同源：
//   hidePose = !eyeInHand && !isMarkerCalib
// 即"眼在手外 + 戳点"不采拍照位姿。两处必须一致，sourceForModeAgreesWithInputCards()
// 把这条一致性钉成了单测。
inline PoseSource sourceFor(bool eyeInHand, bool isMarkerCalib)
{
    return (!eyeInHand && !isMarkerCalib) ? PoseSource::RobotTargetXyz
                                          : PoseSource::RobotCapturePose;
}

struct Record {
    std::array<double, 3> xyz{};     // mm, from the selected PoseSource column
    std::array<double, 3> rpyDeg{};  // degrees, static XYZ; all-zero when the source has none
    bool hasPose = false;            // selected column present and parseable
    std::array<double, 3> cameraXyz{};   // camera_target_xyz (mm)
    bool hasCameraTarget = false;        // camera target present and parseable
    float errorPct = -1.0f;          // -1 = not applicable (concentric/TCP)
    int markerCount = 0;
};

struct Params {
    PoseSource source = PoseSource::RobotCapturePose;
    int minCount = 6;                // absolute lower bound for calibration
    int recommendedCount = 15;       // advisory target
    double dupPosMm = PoseGuide::DEFAULT_MIN_POS_MM;    // near-duplicate
    double dupAngleDeg = PoseGuide::DEFAULT_MIN_ANGLE_DEG;
    double maxErrorPct = 5.0f;       // per-frame detection-error warn threshold
    double outlierFactor = 3.0;      // > factor * median -> outlier
    double outlierMinPosMm = 50.0;   // floor below which no position outlier
    double outlierMinAngleDeg = 15.0;
    double spreadMinPosMm = 50.0;    // overall position spread warn threshold
    double spreadMinAngleDeg = 30.0;
    double cameraOutlierFactor = 3.0;      // 相机目标点离群（位置）
    double cameraOutlierMinPosMm = 50.0;
};

// NotApplicable = 本标定方式下这一项没有可判定的数据。它必须和 Pass 分开：
// 把"无从判定"显示成"通过"正是假报告的来源。
enum class Level { Pass, Warn, Fail, NotApplicable };

struct Check {
    Level level = Level::Pass;
    QString summary;                 // one-line Chinese summary
    std::vector<QString> details;    // per-problem human-readable lines
    std::vector<int> frames;         // 1-based offending frame indices
};

struct Report {
    Check count;         // 数量
    Check source;        // 位姿源（本方式用哪一列 / 有多少帧带它）
    Check nearDup;       // 近重复
    Check outlier;       // 离群
    Check cameraTarget;  // 相机目标点
    Check frameError;    // 单帧检测误差
    Check detection;     // 标记点数
    Check spread;        // 分散度
    QString overall;     // 总体结论
};

// Parse a "x y z rx ry rz" pose text into a Record (hasPose false on bad input).
inline Record recordFromText(const QString& poseText, float errorPct, int markerCount)
{
    Record r;
    r.errorPct = errorPct;
    r.markerCount = markerCount;
    const auto parsed = ToolInputParser::parseNumberList(poseText.toStdString(), 6);
    if (parsed.status == ToolInputParser::ParseStatus::Ok) {
        r.hasPose = true;
        for (int i = 0; i < 3; ++i) r.xyz[static_cast<std::size_t>(i)] = parsed.values[static_cast<std::size_t>(i)];
        for (int i = 0; i < 3; ++i) r.rpyDeg[static_cast<std::size_t>(i)] = parsed.values[static_cast<std::size_t>(3 + i)];
    }
    return r;
}

// Parse a "x y z" text (robot target point / camera target point).
inline bool parseXyzText(const QString& text, std::array<double, 3>& out)
{
    const auto parsed = ToolInputParser::parseNumberList(text.toStdString(), 3);
    if (parsed.status != ToolInputParser::ParseStatus::Ok)
        return false;
    for (int i = 0; i < 3; ++i)
        out[static_cast<std::size_t>(i)] = parsed.values[static_cast<std::size_t>(i)];
    return true;
}

// 按当前标定方式组装一条记录：source 决定哪一列当"位姿"，相机目标点始终单独带上
// （两列应当同步变化，只有一列不对劲往往就是那一帧录错了）。
inline Record makeRecord(PoseSource source, const QString& poseText,
                         const QString& targetText, const QString& cameraText,
                         float errorPct, int markerCount)
{
    Record r;
    if (source == PoseSource::RobotTargetXyz) {
        r.errorPct = errorPct;
        r.markerCount = markerCount;
        r.hasPose = parseXyzText(targetText, r.xyz);
    } else {
        r = recordFromText(poseText, errorPct, markerCount);
    }
    r.hasCameraTarget = parseXyzText(cameraText, r.cameraXyz);
    return r;
}

namespace detail {

inline double median(std::vector<double> v)
{
    if (v.empty()) return 0.0;
    std::sort(v.begin(), v.end());
    const std::size_t n = v.size();
    return (n % 2) ? v[n / 2] : 0.5 * (v[n / 2 - 1] + v[n / 2]);
}

inline double distanceMm(const std::array<double, 3>& a, const std::array<double, 3>& b)
{
    return std::hypot(std::hypot(a[0] - b[0], a[1] - b[1]), a[2] - b[2]);
}

// 位置离群：某样本到其余样本的**中位距离** > factor × 全局中位距离，且 > 下限。
// 返回 idx 里被判定为离群的下标（相对 idx 的位置）。
// 下限 minMm 是必须的：数据本来就聚得很紧时全局中位距离≈0，没有下限会全体报离群。
template<typename PointAt>
inline std::vector<int> positionOutliers(const std::vector<int>& idx, PointAt&& point,
                                         double factor, double minMm)
{
    std::vector<int> found;
    const int k = static_cast<int>(idx.size());
    if (k < 4) return found;

    std::vector<double> med(static_cast<std::size_t>(k));
    for (int i = 0; i < k; ++i) {
        std::vector<double> ds;
        ds.reserve(static_cast<std::size_t>(k - 1));
        for (int j = 0; j < k; ++j) {
            if (i == j) continue;
            ds.push_back(distanceMm(point(idx[i]), point(idx[j])));
        }
        med[static_cast<std::size_t>(i)] = median(ds);
    }
    const double g = median(med);
    for (int i = 0; i < k; ++i)
        if (med[static_cast<std::size_t>(i)] > factor * g
                && med[static_cast<std::size_t>(i)] > minMm)
            found.push_back(i);
    return found;
}

} // namespace detail

inline Report run(const std::vector<Record>& records, const Params& p = Params{})
{
    Report rep;
    const int n = static_cast<int>(records.size());
    const bool hasOri = sourceHasOrientation(p.source);
    const QString srcName = sourceName(p.source);

    // Index sets the checks operate on: records carrying the selected source
    // column, and records carrying a camera target point.
    std::vector<int> pi;
    for (int i = 0; i < n; ++i)
        if (records[i].hasPose) pi.push_back(i);
    const int m = static_cast<int>(pi.size());

    std::vector<int> ci;
    for (int i = 0; i < n; ++i)
        if (records[i].hasCameraTarget) ci.push_back(i);
    const int mc = static_cast<int>(ci.size());

    auto distMm = [&](int a, int b) {
        return PoseGuide::translationMm(
            PoseGuide::Pose{ records[a].xyz, records[a].rpyDeg },
            PoseGuide::Pose{ records[b].xyz, records[b].rpyDeg });
    };
    auto angleDeg = [&](int a, int b) {
        return PoseGuide::rotationAngleDeg(
            PoseGuide::Pose{ records[a].xyz, records[a].rpyDeg },
            PoseGuide::Pose{ records[b].xyz, records[b].rpyDeg });
    };
    auto frameList = [](const std::vector<int>& f) {
        const std::size_t cap = 8;
        QString s;
        for (std::size_t i = 0; i < f.size() && i < cap; ++i) {
            if (!s.isEmpty()) s += QStringLiteral("、");
            s += QString::number(f[i]);
        }
        if (f.size() > cap)
            s += QStringLiteral(" 等 %1 组").arg(f.size());
        return s;
    };
    // 明细行封顶：15 组完全相同的位姿会产生 105 对重复，逐条铺开会把面板刷满。
    // 计数（summary 里的数字）仍然是真的，只是不再逐条列出。
    auto addDetail = [](Check& c, const QString& line) {
        constexpr std::size_t cap = 12;
        if (c.details.size() < cap)
            c.details.push_back(line);
        else if (c.details.size() == cap)
            c.details.push_back(QStringLiteral("（同类问题较多，其余未逐条列出）"));
    };

    // 1. 数量不足
    {
        Check& c = rep.count;
        if (n == 0) {
            c.level = Level::Fail;
            c.summary = QStringLiteral("无数据");
        } else if (n < p.minCount) {
            c.level = Level::Fail;
            c.summary = QStringLiteral("仅 %1 帧，低于标定下限 %2 帧").arg(n).arg(p.minCount);
        } else if (n < p.recommendedCount) {
            c.level = Level::Warn;
            c.summary = QStringLiteral("%1 帧，建议补采至 %2 帧以上").arg(n).arg(p.recommendedCount);
        } else {
            c.level = Level::Pass;
            c.summary = QStringLiteral("%1 帧，数量充足").arg(n);
        }
    }

    // 2. 位姿源（本方式判定用的那一列到底有没有值）
    {
        Check& c = rep.source;
        std::vector<int> missing;
        for (int i = 0; i < n; ++i)
            if (!records[i].hasPose) missing.push_back(i + 1);

        if (n == 0) {
            c.level = Level::NotApplicable;
            c.summary = QStringLiteral("暂无数据");
        } else if (m == 0) {
            c.level = Level::Fail;
            c.summary = QStringLiteral("本方式用「%1」判定，但 %2 帧全部缺少这一列")
                            .arg(srcName).arg(n);
        } else if (!missing.empty()) {
            c.level = Level::Warn;
            c.summary = QStringLiteral("本方式用「%1」判定，%2 帧中 %3 帧有值")
                            .arg(srcName).arg(n).arg(m);
            addDetail(c, QStringLiteral("第 %1 组缺少%2")
                           .arg(frameList(missing)).arg(srcName));
            c.frames = missing;
        } else {
            c.level = Level::Pass;
            c.summary = QStringLiteral("本方式用「%1」判定，%2 帧全部有值")
                            .arg(srcName).arg(n);
        }
    }

    // 3. 近重复（源列过于接近：位置近 **且** 姿态近；源列无姿态时只看位置）
    {
        Check& c = rep.nearDup;
        if (m < 2) {
            c.level = Level::NotApplicable;
            c.summary = QStringLiteral("有效帧不足 2 组，无法判定近重复");
        } else {
            int pairCount = 0;
            for (int a = 0; a < m; ++a) {
                for (int b = a + 1; b < m; ++b) {
                    const double d = distMm(pi[a], pi[b]);
                    if (d >= p.dupPosMm) continue;
                    if (hasOri) {
                        const double ang = angleDeg(pi[a], pi[b]);
                        if (ang >= p.dupAngleDeg) continue;
                        addDetail(c,
                            QStringLiteral("%1第 %2 组与第 %3 组过于接近（间距 %4 mm / 角差 %5°）")
                                .arg(srcName).arg(pi[a] + 1).arg(pi[b] + 1)
                                .arg(d, 0, 'f', 1).arg(ang, 0, 'f', 1));
                    } else {
                        addDetail(c,
                            QStringLiteral("%1第 %2 组与第 %3 组过于接近（间距 %4 mm）")
                                .arg(srcName).arg(pi[a] + 1).arg(pi[b] + 1)
                                .arg(d, 0, 'f', 1));
                    }
                    ++pairCount;
                    c.frames.push_back(pi[a] + 1);
                    c.frames.push_back(pi[b] + 1);
                }
            }
            if (pairCount > 0) {
                c.level = Level::Warn;
                c.summary = QStringLiteral("存在 %1 对%2过于接近").arg(pairCount).arg(srcName);
            } else {
                c.summary = QStringLiteral("无%1近重复").arg(srcName);
            }
        }
    }

    // 4. 离群（median-distance-to-others vs. factor * global median）
    {
        Check& c = rep.outlier;
        if (m < 4) {
            c.level = Level::NotApplicable;
            c.summary = QStringLiteral("有效帧不足 4 组，无法判定离群");
        } else {
            std::vector<double> posMed(static_cast<std::size_t>(m));
            std::vector<double> angMed(static_cast<std::size_t>(m), 0.0);
            for (int i = 0; i < m; ++i) {
                std::vector<double> ds, as;
                ds.reserve(static_cast<std::size_t>(m - 1));
                as.reserve(static_cast<std::size_t>(m - 1));
                for (int j = 0; j < m; ++j) {
                    if (i == j) continue;
                    ds.push_back(distMm(pi[i], pi[j]));
                    if (hasOri) as.push_back(angleDeg(pi[i], pi[j]));
                }
                posMed[static_cast<std::size_t>(i)] = detail::median(ds);
                if (hasOri) angMed[static_cast<std::size_t>(i)] = detail::median(as);
            }
            const double pm = detail::median(posMed);
            const double am = hasOri ? detail::median(angMed) : 0.0;
            int outlierCount = 0;
            for (int i = 0; i < m; ++i) {
                const double pmi = posMed[static_cast<std::size_t>(i)];
                if (pmi > p.outlierFactor * pm && pmi > p.outlierMinPosMm) {
                    addDetail(c, QStringLiteral("第 %1 组%2离群（到其余样本中位距离 %3 mm）")
                        .arg(pi[i] + 1).arg(srcName).arg(pmi, 0, 'f', 1));
                    c.frames.push_back(pi[i] + 1);
                    ++outlierCount;
                }
                if (!hasOri) continue;
                const double ami = angMed[static_cast<std::size_t>(i)];
                if (ami > p.outlierFactor * am && ami > p.outlierMinAngleDeg) {
                    addDetail(c, QStringLiteral("第 %1 组姿态离群（到其余样本中位角度 %2°）")
                        .arg(pi[i] + 1).arg(ami, 0, 'f', 1));
                    c.frames.push_back(pi[i] + 1);
                    ++outlierCount;
                }
            }
            if (outlierCount > 0) {
                c.level = Level::Warn;
                c.summary = QStringLiteral("存在 %1 项离群").arg(outlierCount);
            } else {
                c.summary = QStringLiteral("无离群%1").arg(srcName);
            }
        }
    }

    // 5. 相机目标点（与源列应当同步变化；只有一列不对劲 = 那一帧多半录错了）
    {
        Check& c = rep.cameraTarget;
        if (mc == 0) {
            c.level = Level::NotApplicable;
            c.summary = QStringLiteral("本方式未采集相机目标点");
        } else if (mc < 4) {
            c.level = Level::NotApplicable;
            c.summary = QStringLiteral("相机目标点不足 4 组，无法判定离群");
        } else {
            auto point = [&](int i) { return records[i].cameraXyz; };
            const auto far = detail::positionOutliers(ci, point, p.cameraOutlierFactor,
                                                      p.cameraOutlierMinPosMm);
            for (int k : far) {
                const int i = ci[static_cast<std::size_t>(k)];
                std::vector<double> ds;
                for (int j : ci) {
                    if (j == i) continue;
                    ds.push_back(detail::distanceMm(records[i].cameraXyz, records[j].cameraXyz));
                }
                addDetail(c,
                    QStringLiteral("第 %1 组相机目标点离群（到其余目标点中位距离 %2 mm）")
                        .arg(i + 1).arg(detail::median(ds), 0, 'f', 1));
                c.frames.push_back(i + 1);
            }
            if (!far.empty()) {
                c.level = Level::Warn;
                c.summary = QStringLiteral("%1 帧相机目标点偏离其余帧").arg(far.size());
            } else {
                c.summary = QStringLiteral("相机目标点无离群");
            }
        }
    }

    // 6. 单帧检测误差（同心圆 / 戳点标定不产生这个误差，以前会被当成"正常"报出来）
    {
        Check& c = rep.frameError;
        int scored = 0, overCount = 0;
        for (int i = 0; i < n; ++i) {
            const float e = records[i].errorPct;
            if (e < 0.0f) continue;  // N/A (concentric / TCP)
            ++scored;
            if (e > static_cast<float>(p.maxErrorPct)) {
                addDetail(c, QStringLiteral("第 %1 组检测误差 %2%，超过阈值 %3%")
                    .arg(i + 1).arg(e, 0, 'f', 2).arg(p.maxErrorPct, 0, 'f', 1));
                c.frames.push_back(i + 1);
                ++overCount;
            }
        }
        if (scored == 0) {
            c.level = Level::NotApplicable;
            c.summary = QStringLiteral("本标定方式没有单帧识别误差");
        } else if (overCount > 0) {
            c.level = Level::Warn;
            c.summary = QStringLiteral("%1 帧检测误差过大").arg(overCount);
        } else {
            c.summary = QStringLiteral("%1 帧检测误差正常").arg(scored);
        }
    }

    // 7. 标记点数（同心圆/标定板识别出来的点数应当各帧一致；少数帧掉点 = 识别不全）
    {
        Check& c = rep.detection;
        std::map<int, int> hist;
        for (int i = 0; i < n; ++i)
            if (records[i].markerCount > 0)
                ++hist[records[i].markerCount];

        if (hist.empty()) {
            c.level = Level::NotApplicable;
            c.summary = QStringLiteral("没有标记点数记录");
        } else {
            int ref = hist.begin()->first;
            for (const auto& kv : hist)
                if (kv.second >= hist[ref]) ref = kv.first;

            int mismatchCount = 0;
            for (int i = 0; i < n; ++i) {
                const int k = records[i].markerCount;
                if (k == ref) continue;
                if (k <= 0)
                    addDetail(c, QStringLiteral("第 %1 组没有识别到标记物（多数帧为 %2 个）")
                                    .arg(i + 1).arg(ref));
                else
                    addDetail(c, QStringLiteral("第 %1 组识别到 %2 个标记物，与多数帧的 %3 个不一致")
                                    .arg(i + 1).arg(k).arg(ref));
                c.frames.push_back(i + 1);
                ++mismatchCount;
            }
            if (mismatchCount > 0) {
                c.level = Level::Warn;
                c.summary = QStringLiteral("%1 帧标记点数异常（基准 %2 个）")
                                .arg(mismatchCount).arg(ref);
            } else {
                c.summary = QStringLiteral("各帧标记点数一致（%1 个）").arg(ref);
            }
        }
    }

    // 8. 整体分散度不足
    {
        Check& c = rep.spread;
        if (m < 2) {
            c.level = Level::NotApplicable;
            c.summary = QStringLiteral("有效帧不足 2 组，无法判定分散度");
        } else {
            double maxPos = 0.0, maxAng = 0.0;
            for (int a = 0; a < m; ++a) {
                for (int b = a + 1; b < m; ++b) {
                    maxPos = (std::max)(maxPos, distMm(pi[a], pi[b]));
                    if (hasOri)
                        maxAng = (std::max)(maxAng, angleDeg(pi[a], pi[b]));
                }
            }
            if (maxPos < p.spreadMinPosMm)
                c.details.push_back(QStringLiteral("%1覆盖范围仅 %2 mm，分散不足")
                                        .arg(srcName).arg(maxPos, 0, 'f', 1));
            if (hasOri && maxAng < p.spreadMinAngleDeg)
                c.details.push_back(QStringLiteral("姿态覆盖范围仅 %1°，分散不足")
                                        .arg(maxAng, 0, 'f', 1));
            if (!c.details.empty()) {
                c.level = Level::Warn;
                c.summary = QStringLiteral("分散度不足（按%1判定）").arg(srcName);
            } else {
                c.summary = QStringLiteral("分散度足够（按%1判定）").arg(srcName);
            }
        }
    }

    // 总体结论
    if (n == 0) {
        rep.overall = QStringLiteral("尚无数据，请先采集并保存标定数据");
    } else if (n < p.minCount) {
        rep.overall = QStringLiteral("数据不足（%1 帧），至少需 %2 帧才能标定").arg(n).arg(p.minCount);
    } else {
        int warnCount = 0, failCount = 0, naCount = 0;
        const Check* checks[] = { &rep.source, &rep.nearDup, &rep.outlier,
                                  &rep.cameraTarget, &rep.frameError, &rep.detection,
                                  &rep.spread };
        for (const Check* c : checks) {
            switch (c->level) {
            case Level::Pass:          break;
            case Level::Warn:          ++warnCount; break;
            case Level::Fail:          ++failCount; break;
            case Level::NotApplicable: ++naCount;   break;
            }
        }
        if (failCount > 0)
            rep.overall = QStringLiteral("数据存在问题（%1 项），请先处理再标定").arg(failCount);
        else if (warnCount > 0)
            rep.overall = QStringLiteral("存在 %1 项提示，建议处理后再标定").arg(warnCount);
        else if (naCount > 0)
            rep.overall = QStringLiteral("数据可用于标定（%1 帧）；其中 %2 项本方式不适用")
                              .arg(n).arg(naCount);
        else
            rep.overall = QStringLiteral("数据可用于标定（%1 帧）").arg(n);
    }

    return rep;
}

} // namespace DataQualityCheck
