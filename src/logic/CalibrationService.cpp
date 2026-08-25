#include "logic/CalibrationService.h"

#include "logic/ToolInputParser.h"
#include "sdk/HandEyeSDKBridge.h"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QSaveFile>
#include <QTextStream>

namespace CalibrationService {

QString normalizePoseLine(const QString& raw)
{
    const auto r = ToolInputParser::parseNumberList(raw.toStdString(), 6);
    if (r.status != ToolInputParser::ParseStatus::Ok)
        return {};
    return QStringLiteral("%1,%2,%3,%4,%5,%6")
        .arg(r.values[0], 0, 'g', 10)
        .arg(r.values[1], 0, 'g', 10)
        .arg(r.values[2], 0, 'g', 10)
        .arg(r.values[3], 0, 'g', 10)
        .arg(r.values[4], 0, 'g', 10)
        .arg(r.values[5], 0, 'g', 10);
}

QString errorText(int retCode)
{
    switch (retCode) {
    case 0:  return QStringLiteral("成功");
    case -1: return QStringLiteral("参数无效（文件夹/位姿文件/参数）");
    case -2: return QStringLiteral("有效数据不足 6 组，请继续采集");
    case -3: return QStringLiteral("点云文件数与图像文件数不一致");
    case -4: return QStringLiteral("位姿文件数据无效，请检查机器人拍照位姿格式");
    case -5: return QStringLiteral("位姿数量与点云文件数不一致");
    case -6: return QStringLiteral("部分图像/点云未能识别出标定板（见逐组结果）");
    case -7: return QStringLiteral("位姿旋转轴不足两组非平行轴，请调整姿态后重采");
    default: return QStringLiteral("标定失败（返回码 %1）").arg(retCode);
    }
}

Result calibrateMarker(const QString& folder,
                       const std::vector<QString>& poseLines,
                       const Params& params)
{
    Result out;
    if (poseLines.empty()) {
        out.error = QStringLiteral("没有可用的标定数据，请先采集并保存");
        return out;
    }
    if (!QFileInfo::exists(folder) || !QDir(folder).exists()) {
        out.error = QStringLiteral("数据文件夹不存在: %1").arg(folder);
        return out;
    }

    // Stage files with zero-padded names so the SDK's file iteration order
    // matches record order exactly.
    const QString stamp = QDateTime::currentDateTime().toString(
        QStringLiteral("yyyyMMdd_HHmmss_zzz"));
    const QString tmpDir = QDir::tempPath() + QStringLiteral("/HandEyeCalib/calib_")
        + stamp;
    QDir().mkpath(tmpDir);

    auto cleanup = [tmpDir]() {
        QDir(tmpDir).removeRecursively();
    };

    QStringList poseOut;
    for (int i = 0; i < static_cast<int>(poseLines.size()); ++i) {
        const QString name = QStringLiteral("%1").arg(i + 1, 4, 10, QLatin1Char('0'));
        const QString srcPng = QStringLiteral("%1/%2.png").arg(folder).arg(i + 1);
        const QString srcPly = QStringLiteral("%1/%2.ply").arg(folder).arg(i + 1);
        if (!QFile::copy(srcPng, tmpDir + QLatin1Char('/') + name + QStringLiteral(".png"))
                || !QFile::copy(srcPly, tmpDir + QLatin1Char('/') + name + QStringLiteral(".ply"))) {
            cleanup();
            out.error = QStringLiteral("第 %1 组数据文件缺失（%2 / %3）")
                            .arg(i + 1)
                            .arg(QFileInfo(srcPng).fileName())
                            .arg(QFileInfo(srcPly).fileName());
            return out;
        }
        const QString norm = normalizePoseLine(poseLines[static_cast<std::size_t>(i)]);
        if (norm.isEmpty()) {
            cleanup();
            out.error = QStringLiteral("第 %1 组机器人拍照位姿格式无效（应为 6 个数值）")
                            .arg(i + 1);
            return out;
        }
        poseOut.push_back(norm);
    }

    const QString posePath = tmpDir + QStringLiteral("/pose.txt");
    {
        QSaveFile file(posePath);
        if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
            cleanup();
            out.error = QStringLiteral("无法写入临时位姿文件");
            return out;
        }
        QTextStream ts(&file);
        ts.setCodec("UTF-8");
        for (const QString& line : poseOut)
            ts << line << QLatin1Char('\n');
        if (!file.commit()) {
            cleanup();
            out.error = QStringLiteral("临时位姿文件写入失败");
            return out;
        }
    }

    HandEyeParam param{};
    param.poseType = 0;   // euler x y z rx ry rz
    param.markerType = params.markerType;
    param.isPointCloudMm = true;       // our PLY files are mm
    param.isPoseMm = params.isPoseMm;
    param.isPoseDegree = params.isPoseDegree;
    param.isEyeInHand = params.eyeInHand;
    param.autoRemoveLargeErrorData = params.autoRemoveLargeError;
    for (int i = 0; i < 100; ++i)
        param.dataMask[i] = true;

    HandEyeResult sdkResult{};
    const int ret = HandEyeSDKBridge::handEyeCalibrationMarker(
        tmpDir.toStdString(), "pose.txt", param, sdkResult);

    out.retCode = ret;
    if (ret != 0) {
        cleanup();
        out.error = errorText(ret);
        return out;
    }

    for (int i = 0; i < 16; ++i)
        out.matrix[static_cast<std::size_t>(i)] = sdkResult.matrix[i];
    out.totalMeanError = sdkResult.totalMeanError;
    const std::size_t n = poseLines.size();
    out.errors.assign(sdkResult.error, sdkResult.error + n);
    out.success2D.assign(sdkResult.success2D, sdkResult.success2D + n);
    out.success3D.assign(sdkResult.success3D, sdkResult.success3D + n);
    out.usedCount = static_cast<int>(n);
    out.ok = true;
    cleanup();
    return out;
}

} // namespace CalibrationService
