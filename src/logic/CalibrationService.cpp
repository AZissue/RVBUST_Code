#include "logic/CalibrationService.h"

#include "logic/ToolInputParser.h"
#include "sdk/HandEyeSDKBridge.h"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QSaveFile>
#include <QStringList>
#include <QTextStream>
#include <algorithm>

namespace CalibrationService {

namespace {

// <temp>/HandEyeCalib/<tag>_<stamp> — 每次调用一个新的目录，跑完立刻删掉。
// 文件名补零（1.png → 0001.png）让 SDK 的遍历顺序和采集顺序严格一致。
QString makeTempDir(const QString& tag)
{
    const QString stamp = QDateTime::currentDateTime().toString(
        QStringLiteral("yyyyMMdd_HHmmss_zzz"));
    return QDir::tempPath() + QStringLiteral("/HandEyeCalib/") + tag
        + QLatin1Char('_') + stamp;
}

bool writeLines(const QString& path, const QStringList& lines, QString& err)
{
    QSaveFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
        err = QStringLiteral("无法写入临时文件 %1").arg(QFileInfo(path).fileName());
        return false;
    }
    QTextStream ts(&file);
    ts.setCodec("UTF-8");
    for (const QString& line : lines)
        ts << line << QLatin1Char('\n');
    if (!file.commit()) {
        err = QStringLiteral("临时文件 %1 写入失败").arg(QFileInfo(path).fileName());
        return false;
    }
    return true;
}

} // namespace

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

QString normalizeXyzLine(const QString& raw)
{
    const auto r = ToolInputParser::parseNumberList(raw.toStdString(), 3);
    if (r.status != ToolInputParser::ParseStatus::Ok)
        return {};
    return QStringLiteral("%1,%2,%3")
        .arg(r.values[0], 0, 'g', 10)
        .arg(r.values[1], 0, 'g', 10)
        .arg(r.values[2], 0, 'g', 10);
}

QString toSdkPoseLine(const QString& raw, TransformTools::RotationFormat fmt,
                      TransformTools::AngleUnit unit, int& poseTypeOut)
{
    const auto r = ToolInputParser::parseNumberList(raw.toStdString(), 6);
    if (r.status != ToolInputParser::ParseStatus::Ok)
        return {};

    if (fmt == TransformTools::RotationFormat::EulerRpy) {
        poseTypeOut = 0;         // euler x y z rx ry rz — 与改动前逐字节一致
        return normalizePoseLine(raw);
    }

    // 卡片只有 3 个旋转数，四元数(4)与 3x3 矩阵(9)在这里无法表示。
    if (TransformTools::rotationValueCount(fmt) != 3)
        return {};

    const std::vector<double> rot{ r.values[3], r.values[4], r.values[5] };
    const TransformTools::Mat4 m = TransformTools::poseToMat4(
        r.values[0], r.values[1], r.values[2], fmt, unit, rot);

    QString out;
    for (int i = 0; i < 16; ++i) {
        if (i)
            out += QLatin1Char(',');
        out += QString::number(m[static_cast<std::size_t>(i)], 'g', 10);
    }
    poseTypeOut = 3;             // matrix, row-major 16 values
    return out;
}

QString poseFormatName(TransformTools::RotationFormat fmt)
{
    switch (fmt) {
    case TransformTools::RotationFormat::EulerRpy:
        return QStringLiteral("欧拉角 RPY（Static XYZ）");
    case TransformTools::RotationFormat::EulerWpr:
        return QStringLiteral("欧拉角 WPR（FANUC / KUKA ABC）");
    case TransformTools::RotationFormat::EulerZyxIntrinsic:
        return QStringLiteral("欧拉角 ZYX 内旋（Rx·Ry·Rz）");
    case TransformTools::RotationFormat::QuatWxyz:
        return QStringLiteral("四元数（w x y z）");
    case TransformTools::RotationFormat::QuatXyzw:
        return QStringLiteral("四元数（x y z w）");
    case TransformTools::RotationFormat::RotationMatrix9:
        return QStringLiteral("旋转矩阵（3×3，行主序）");
    case TransformTools::RotationFormat::RotationVector:
        return QStringLiteral("旋转矢量（轴角，UR 优傲）");
    }
    return QStringLiteral("未知格式");
}

QString poseFormatDescription(TransformTools::RotationFormat fmt)
{
    switch (fmt) {
    case TransformTools::RotationFormat::EulerRpy:
        return QStringLiteral(
            "Static XYZ / RPY（外旋）：R = Rz·Ry·Rx，按 (rx, ry, rz) = (X, Y, Z) 直填；"
            "Yaskawa 安川 RX/RY/RZ、珞石（官方 SDK 标 XYZ 欧拉角，单位弧度）、"
            "FANUC 标准手册（W绕X、P绕Y、R绕Z）均按此直填");
    case TransformTools::RotationFormat::EulerWpr:
        return QStringLiteral(
            "按 (W, P, R) 直填：R = Rz(W)·Ry(P)·Rx(R)，即角度顺序 = 绕 Z、Y、X；"
            "KUKA ABC 同此顺序；RVC 官方软件导出的 FANUC 位姿文件实测适用");
    case TransformTools::RotationFormat::EulerZyxIntrinsic:
        return QStringLiteral(
            "ZYX 内旋：R = Rx·Ry·Rz，按 (rx, ry, rz) = (X, Y, Z) 输入；"
            "与 Static XYZ（Rz·Ry·Rx）一般不相等");
    case TransformTools::RotationFormat::QuatWxyz:
        return QStringLiteral(
            "四元数顺序 w x y z（标量在前）；ABB（RAPID Q1..Q4）、"
            "RVC HandEyeSDK poseType=1");
    case TransformTools::RotationFormat::QuatXyzw:
        return QStringLiteral(
            "四元数顺序 x y z w（标量在后）；ROS、RVC HandEyeSDK poseType=2");
    case TransformTools::RotationFormat::RotationMatrix9:
        return QStringLiteral("3×3 旋转矩阵，行主序 9 个值");
    case TransformTools::RotationFormat::RotationVector:
        return QStringLiteral(
            "旋转矢量（轴角）：方向 = 转轴，长度 = 转角；UR 优傲，长度单位随角度单位");
    }
    return {};
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
    case HandEyeSDKBridge::kSdkInternalError:
        return QStringLiteral("SDK 内部异常（标定接口调用崩溃，输入参数未必有问题），"
                              "请附带日志联系技术支持");
    default: return QStringLiteral("标定失败（返回码 %1）").arg(retCode);
    }
}

QString tcpErrorText(int retCode)
{
    switch (retCode) {
    case 0:  return QStringLiteral("成功");
    case -1: return QStringLiteral("参数无效（相机点位文件/参数）");
    case -2: return QStringLiteral("相机目标点数据无效，请检查相机目标点坐标");
    case -3: return QStringLiteral("机器人目标点数据无效，请检查机器人目标点坐标");
    case -4: return QStringLiteral("相机目标点数与机器人目标点数不一致");
    case -5: return QStringLiteral("机器人拍照位姿数据无效，请检查拍照位姿格式");
    case -6: return QStringLiteral("相机目标点数与机器人拍照位姿数不一致");
    case -7: return QStringLiteral("机器人拍照位姿不足 2 组有效数据，请调整姿态后重采");
    case HandEyeSDKBridge::kSdkInternalError:
        return QStringLiteral("SDK 内部异常（标定接口调用崩溃，输入参数未必有问题），"
                              "请附带日志联系技术支持");
    default: return QStringLiteral("标定失败（返回码 %1）").arg(retCode);
    }
}

QString formatResult(const Result& r)
{
    if (!r.ok)
        return QStringLiteral("标定失败：%1").arg(r.error);

    QString text = QStringLiteral("标定成功（使用 %1 组数据）\n"
                                  "总平均误差: %2 mm\n\n"
                                  "4×4 矩阵（行主序）:\n")
        .arg(r.usedCount).arg(r.totalMeanError, 0, 'f', 3);
    for (int row = 0; row < 4; ++row) {
        QStringList vals;
        for (int col = 0; col < 4; ++col)
            vals << QString::number(
                r.matrix[static_cast<std::size_t>(row * 4 + col)], 'f', 6);
        text += vals.join(QStringLiteral("  ")) + QLatin1Char('\n');
    }

    if (!r.errors.empty()) {
        text += QStringLiteral("\n逐组误差:\n");
        const std::size_t n = r.errors.size();
        for (std::size_t i = 0; i < n; ++i) {
            // success2D/3D 为空 = 本接口不报告识别状态（戳点标定），此时不标注。
            const bool failed2d = static_cast<std::size_t>(r.success2D.size()) > i
                && r.success2D[i] != 1;
            const bool failed3d = static_cast<std::size_t>(r.success3D.size()) > i
                && r.success3D[i] != 1;
            text += QStringLiteral("  第 %1 组: %2 mm%3\n")
                .arg(i + 1).arg(r.errors[i], 0, 'f', 3)
                .arg((failed2d || failed3d) ? QStringLiteral("（识别失败）") : QString());
        }
    }
    return text;
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
    const QString tmpDir = makeTempDir(QStringLiteral("calib"));
    QDir().mkpath(tmpDir);

    auto cleanup = [tmpDir]() {
        QDir(tmpDir).removeRecursively();
    };

    QStringList poseOut;
    // 与 toSdkPoseLine 的规则一致：欧拉 RPY 走 SDK 的 poseType=0 老路，其余格式转矩阵。
    int poseType = params.poseFormat == TransformTools::RotationFormat::EulerRpy ? 0 : 3;
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
        const QString norm = toSdkPoseLine(poseLines[static_cast<std::size_t>(i)],
                                           params.poseFormat, params.poseAngleUnit, poseType);
        if (norm.isEmpty()) {
            cleanup();
            out.error = QStringLiteral("第 %1 组机器人拍照位姿格式无效（应为 6 个数值）")
                            .arg(i + 1);
            return out;
        }
        poseOut.push_back(norm);
    }

    const QString posePath = tmpDir + QStringLiteral("/pose.txt");
    QString werr;
    if (!writeLines(posePath, poseOut, werr)) {
        cleanup();
        out.error = werr;
        return out;
    }

    HandEyeParam param{};
    param.poseType = poseType;         // 0 = euler x y z rx ry rz, 3 = 矩阵 16 数
    param.markerType = params.markerType;
    param.isPointCloudMm = true;       // our PLY files are mm
    param.isPoseMm = params.isPoseMm;
    param.isPoseDegree = params.poseAngleUnit == TransformTools::AngleUnit::Degree;
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
    // The SDK's per-frame result arrays are fixed at 100 entries (HandEye.h);
    // clamp the copy to that bound so more than 100 sets never reads past them.
    const std::size_t n = std::min(
        poseLines.size(), static_cast<std::size_t>(100));
    out.errors.assign(sdkResult.error, sdkResult.error + n);
    out.success2D.assign(sdkResult.success2D, sdkResult.success2D + n);
    out.success3D.assign(sdkResult.success3D, sdkResult.success3D + n);
    out.usedCount = static_cast<int>(n);
    out.ok = true;
    cleanup();
    return out;
}

Result calibrateTcpTouch(const std::vector<QString>& cameraLines,
                         const std::vector<QString>& poseLines,
                         const std::vector<QString>& tcpLines,
                         const Params& params)
{
    Result out;

    // 先做一遍可读的字段完整性校验：SDK 的返回码只说"数据无效"，现场看不出
    // 是哪一列、哪一组出的问题。
    if (cameraLines.empty()) {
        out.error = QStringLiteral("没有可用的相机目标点数据");
        return out;
    }
    if (tcpLines.empty()) {
        out.error = QStringLiteral("没有可用的机器人目标点数据（戳点）");
        return out;
    }
    if (cameraLines.size() != tcpLines.size()) {
        out.error = QStringLiteral("相机目标点数（%1）与机器人目标点数（%2）不一致")
                        .arg(cameraLines.size()).arg(tcpLines.size());
        return out;
    }
    if (params.eyeInHand) {
        // 眼在手上：相机跟着手走，必须每条数据配一个机器人拍照位姿。
        if (poseLines.empty()) {
            out.error = QStringLiteral("眼在手上戳点标定还需要机器人拍照位姿");
            return out;
        }
        if (poseLines.size() != cameraLines.size()) {
            out.error = QStringLiteral("机器人拍照位姿数（%1）与相机目标点数（%2）不一致")
                            .arg(poseLines.size()).arg(cameraLines.size());
            return out;
        }
    }

    QStringList camOut, tcpOut, poseOut;
    // 眼在手外没有拍照位姿，poseType 对 SDK 无意义；仍按格式算出来保持一致。
    int poseType = params.poseFormat == TransformTools::RotationFormat::EulerRpy ? 0 : 3;
    const int n = static_cast<int>(cameraLines.size());
    for (int i = 0; i < n; ++i) {
        const QString cam = normalizeXyzLine(cameraLines[static_cast<std::size_t>(i)]);
        if (cam.isEmpty()) {
            out.error = QStringLiteral("第 %1 组相机目标点格式无效（应为 3 个数值）").arg(i + 1);
            return out;
        }
        camOut.push_back(cam);

        const QString tcp = normalizeXyzLine(tcpLines[static_cast<std::size_t>(i)]);
        if (tcp.isEmpty()) {
            out.error = QStringLiteral("第 %1 组机器人目标点格式无效（应为 3 个数值）").arg(i + 1);
            return out;
        }
        tcpOut.push_back(tcp);

        if (params.eyeInHand) {
            const QString pose = toSdkPoseLine(poseLines[static_cast<std::size_t>(i)],
                                               params.poseFormat, params.poseAngleUnit,
                                               poseType);
            if (pose.isEmpty()) {
                out.error = QStringLiteral("第 %1 组机器人拍照位姿格式无效（应为 6 个数值）")
                                .arg(i + 1);
                return out;
            }
            poseOut.push_back(pose);
        }
    }

    const QString tmpDir = makeTempDir(QStringLiteral("tcp"));
    QDir().mkpath(tmpDir);
    auto cleanup = [tmpDir]() {
        QDir(tmpDir).removeRecursively();
    };

    const QString camPath = tmpDir + QStringLiteral("/cameraCapturePointXyz.txt");
    const QString tcpPath = tmpDir + QStringLiteral("/tcp.txt");
    // 眼在手外没有拍照位姿这一列：不落文件，交给桥接层传 nullptr。
    const QString posePath = params.eyeInHand
        ? tmpDir + QStringLiteral("/cameraCaptureRobotPose.txt") : QString();

    QString werr;
    if (!writeLines(camPath, camOut, werr) || !writeLines(tcpPath, tcpOut, werr)
            || (params.eyeInHand && !writeLines(posePath, poseOut, werr))) {
        cleanup();
        out.error = werr;
        return out;
    }

    HandEyeParam param{};
    param.poseType = poseType;         // 0 = euler x y z rx ry rz, 3 = 矩阵 16 数
    param.markerType = params.markerType;   // 戳点标定忽略该参数
    param.isPointCloudMm = true;
    param.isPoseMm = params.isPoseMm;
    param.isPoseDegree = params.poseAngleUnit == TransformTools::AngleUnit::Degree;
    param.isEyeInHand = params.eyeInHand;
    param.autoRemoveLargeErrorData = params.autoRemoveLargeError;
    for (int i = 0; i < 100; ++i)
        param.dataMask[i] = true;

    HandEyeResult sdkResult{};
    const int ret = HandEyeSDKBridge::handEyeCalibrationTcpTouch(
        camPath.toStdString(),
        params.eyeInHand ? posePath.toStdString() : std::string(),
        tcpPath.toStdString(),
        param, sdkResult);

    out.retCode = ret;
    if (ret != 0) {
        cleanup();
        out.error = tcpErrorText(ret);
        return out;
    }

    for (int i = 0; i < 16; ++i)
        out.matrix[static_cast<std::size_t>(i)] = sdkResult.matrix[i];
    out.totalMeanError = sdkResult.totalMeanError;
    const std::size_t k = std::min(
        cameraLines.size(), static_cast<std::size_t>(100));
    out.errors.assign(sdkResult.error, sdkResult.error + k);
    // success2D/success3D 对戳点标定无意义（HandEye.h: "ignore this field"）。
    // 留空：formatResult 只在数组非空时才标注「识别失败」，照抄数组会把每一组
    // 都标成失败（SDK 不会写这两个字段，值初始化后全是 0）。
    out.usedCount = static_cast<int>(k);
    out.ok = true;
    cleanup();
    return out;
}

Result calibrate(const QString& folder,
                 const std::vector<QString>& cameraLines,
                 const std::vector<QString>& poseLines,
                 const std::vector<QString>& tcpLines,
                 const Params& params)
{
    if (params.calibType == CalibType::TcpTouch)
        return calibrateTcpTouch(cameraLines, poseLines, tcpLines, params);
    return calibrateMarker(folder, poseLines, params);
}

} // namespace CalibrationService
