#pragma once

#include <QString>
#include <algorithm>
#include <array>
#include <cmath>
#include <vector>

#include "logic/PoseGuide.h"
#include "logic/ToolInputParser.h"

// Batch quality check for a calibration session (stage 8).
//
// Runs five advisory checks over the collected records and produces a graded
// report with an overall conclusion.  Purely advisory — it reports, never
// blocks saving or calibration (see PROJECT.md "质量告警不拦截").
namespace DataQualityCheck {

struct Record {
    std::array<double, 3> xyz{};     // mm
    std::array<double, 3> rpyDeg{};  // degrees, static XYZ
    bool hasPose = false;            // pose present and parseable
    float errorPct = -1.0f;          // -1 = not applicable (concentric/TCP)
    int markerCount = 0;
};

struct Params {
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
};

enum class Level { Pass, Warn, Fail };

struct Check {
    Level level = Level::Pass;
    QString summary;                 // one-line Chinese summary
    std::vector<QString> details;    // per-problem human-readable lines
    std::vector<int> frames;         // 1-based offending frame indices
};

struct Report {
    Check count;       // 数量不足
    Check nearDup;     // 位姿近重复
    Check outlier;     // 离群位姿
    Check frameError;  // 单帧检测误差过大
    Check spread;      // 整体分散度不足
    QString overall;   // 总体结论
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
        for (int i = 0; i < 3; ++i) r.xyz[i] = parsed.values[static_cast<std::size_t>(i)];
        for (int i = 0; i < 3; ++i) r.rpyDeg[i] = parsed.values[static_cast<std::size_t>(3 + i)];
    }
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

} // namespace detail

inline Report run(const std::vector<Record>& records, const Params& p = Params{})
{
    Report rep;
    const int n = static_cast<int>(records.size());

    // Pose-bearing records (all pose-based checks operate on these).
    std::vector<int> pi;  // 0-based indices of records with a valid pose
    for (int i = 0; i < n; ++i)
        if (records[i].hasPose)
            pi.push_back(i);
    const int m = static_cast<int>(pi.size());

    auto distMm = [&](int a, int b) {
        PoseGuide::Pose pa{ records[a].xyz, records[a].rpyDeg };
        PoseGuide::Pose pb{ records[b].xyz, records[b].rpyDeg };
        return PoseGuide::translationMm(pa, pb);
    };
    auto angleDeg = [&](int a, int b) {
        PoseGuide::Pose pa{ records[a].xyz, records[a].rpyDeg };
        PoseGuide::Pose pb{ records[b].xyz, records[b].rpyDeg };
        return PoseGuide::rotationAngleDeg(pa, pb);
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

    // 2. 位姿近重复
    {
        Check& c = rep.nearDup;
        for (int a = 0; a < m; ++a) {
            for (int b = a + 1; b < m; ++b) {
                const double d = distMm(pi[a], pi[b]);
                if (d >= p.dupPosMm) continue;
                const double ang = angleDeg(pi[a], pi[b]);
                if (ang >= p.dupAngleDeg) continue;
                c.details.push_back(QStringLiteral("第 %1 组与第 %2 组位姿过于接近（间距 %3 mm / 角差 %4°）")
                    .arg(pi[a] + 1).arg(pi[b] + 1)
                    .arg(d, 0, 'f', 1).arg(ang, 0, 'f', 1));
                c.frames.push_back(pi[a] + 1);
                c.frames.push_back(pi[b] + 1);
            }
        }
        if (!c.details.empty()) {
            c.level = Level::Warn;
            c.summary = QStringLiteral("存在 %1 对位姿过于接近").arg(c.details.size());
        } else {
            c.summary = QStringLiteral("无位姿近重复");
        }
    }

    // 3. 离群位姿 (median-distance-to-others vs. factor * global median)
    {
        Check& c = rep.outlier;
        if (m >= 4) {
            std::vector<double> posMed(m), angMed(m);
            for (int i = 0; i < m; ++i) {
                std::vector<double> ds, as;
                ds.reserve(m - 1);
                as.reserve(m - 1);
                for (int j = 0; j < m; ++j) {
                    if (i == j) continue;
                    ds.push_back(distMm(pi[i], pi[j]));
                    as.push_back(angleDeg(pi[i], pi[j]));
                }
                posMed[i] = detail::median(ds);
                angMed[i] = detail::median(as);
            }
            const double pm = detail::median(posMed);
            const double am = detail::median(angMed);
            for (int i = 0; i < m; ++i) {
                if (posMed[i] > p.outlierFactor * pm && posMed[i] > p.outlierMinPosMm) {
                    c.details.push_back(QStringLiteral("第 %1 组位置离群（到其余位姿中位距离 %2 mm）")
                        .arg(pi[i] + 1).arg(posMed[i], 0, 'f', 1));
                    c.frames.push_back(pi[i] + 1);
                }
                if (angMed[i] > p.outlierFactor * am && angMed[i] > p.outlierMinAngleDeg) {
                    c.details.push_back(QStringLiteral("第 %1 组姿态离群（到其余位姿中位角度 %2°）")
                        .arg(pi[i] + 1).arg(angMed[i], 0, 'f', 1));
                    c.frames.push_back(pi[i] + 1);
                }
            }
        }
        if (!c.details.empty()) {
            c.level = Level::Warn;
            c.summary = QStringLiteral("存在 %1 项离群").arg(c.details.size());
        } else {
            c.summary = QStringLiteral("无离群位姿");
        }
    }

    // 4. 单帧检测误差过大
    {
        Check& c = rep.frameError;
        for (int i = 0; i < n; ++i) {
            const float e = records[i].errorPct;
            if (e < 0.0f) continue;  // N/A (concentric / TCP)
            if (e > static_cast<float>(p.maxErrorPct)) {
                c.details.push_back(QStringLiteral("第 %1 组检测误差 %2%，超过阈值 %3%")
                    .arg(i + 1).arg(e, 0, 'f', 2).arg(p.maxErrorPct, 0, 'f', 1));
                c.frames.push_back(i + 1);
            }
        }
        if (!c.details.empty()) {
            c.level = Level::Warn;
            c.summary = QStringLiteral("%1 帧检测误差过大").arg(c.details.size());
        } else {
            c.summary = QStringLiteral("单帧检测误差正常");
        }
    }

    // 5. 整体分散度不足
    {
        Check& c = rep.spread;
        if (m >= 2) {
            double maxPos = 0.0, maxAng = 0.0;
            for (int a = 0; a < m; ++a) {
                for (int b = a + 1; b < m; ++b) {
                    maxPos = (std::max)(maxPos, distMm(pi[a], pi[b]));
                    maxAng = (std::max)(maxAng, angleDeg(pi[a], pi[b]));
                }
            }
            if (maxPos < p.spreadMinPosMm)
                c.details.push_back(QStringLiteral("位置覆盖范围仅 %1 mm，分散不足").arg(maxPos, 0, 'f', 1));
            if (maxAng < p.spreadMinAngleDeg)
                c.details.push_back(QStringLiteral("姿态覆盖范围仅 %1°，分散不足").arg(maxAng, 0, 'f', 1));
        }
        if (!c.details.empty()) {
            c.level = Level::Warn;
            c.summary = QStringLiteral("位姿分散度不足");
        } else {
            c.summary = QStringLiteral("位姿分散度足够");
        }
    }

    // 总体结论
    if (n == 0) {
        rep.overall = QStringLiteral("尚无数据，请先采集并保存标定数据");
    } else if (n < p.minCount) {
        rep.overall = QStringLiteral("数据不足（%1 帧），至少需 %2 帧才能标定").arg(n).arg(p.minCount);
    } else {
        int warnCount = 0;
        const Check* checks[] = { &rep.nearDup, &rep.outlier, &rep.frameError, &rep.spread };
        for (const Check* c : checks)
            if (c->level != Level::Pass) ++warnCount;
        if (warnCount == 0)
            rep.overall = QStringLiteral("数据可用于标定（%1 帧）").arg(n);
        else
            rep.overall = QStringLiteral("存在 %1 项提示，建议处理后再标定").arg(warnCount);
    }

    return rep;
}

} // namespace DataQualityCheck
