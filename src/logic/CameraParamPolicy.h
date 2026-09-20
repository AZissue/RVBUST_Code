#pragma once

// ── Capture-parameter source policy (第 5 回合 任务 1) ──
//
// The operator normally tunes exposure/gain in the camera vendor's own tool
// first, so the app must be able to run on the parameters the *camera* holds
// instead of overwriting them with whatever it has in its own config file.
// CameraManager already reads the device's values back through
// LoadCaptureOptionParameters(); what was missing was the decision whether to
// keep them or to push the saved ones over them.
//
// That decision is pure — no camera, no SDK, no widgets — so both branches and
// the "operator edited a value" case are unit-testable.

#include <QMap>
#include <QString>
#include <QStringList>

namespace CameraParamPolicy {

enum class Source {
    CameraInternal,   // keep what LoadCaptureOptionParameters() read back
    SavedConfig,      // push the values stored in AppConfig
};

// What a connect (or a settings-dialog accept) has to do.
struct Decision {
    Source source = Source::CameraInternal;
    bool applySaved = false;       // call setParameter() for appliedKeys
    bool writeBackCamera = false;  // persist the camera-read values to AppConfig
    QStringList appliedKeys;       // keys handed to setParameter()
    QString logLine;               // one runtime-log line naming the source
};

// useCameraParams : AppConfig "use_camera_params"
// savedParams     : AppConfig "camera_params"
// cameraRead      : values read back from the device (empty when the device
//                   reported none)
// userEdited      : the operator changed at least one field in 设置 after the
//                   values were loaded.  An explicit edit always wins over the
//                   checkbox, so a change can never be silently ignored.
inline Decision decide(bool useCameraParams,
                       const QMap<QString, float>& savedParams,
                       const QMap<QString, float>& cameraRead,
                       bool userEdited)
{
    Decision d;
    if (userEdited) {
        d.source = Source::SavedConfig;
        d.applySaved = true;
        d.writeBackCamera = false;
        d.appliedKeys = savedParams.keys();
        d.logLine = QStringLiteral("[CAM] params: 操作员修改了拍摄参数 → 使用保存的参数"
                                   "（下发 %1 项，已自动关闭 use_camera_params）")
                        .arg(d.appliedKeys.size());
        return d;
    }
    if (useCameraParams) {
        // The whole point of the setting: touch nothing, so the very values the
        // vendor tool wrote stay in effect for the next capture.
        d.source = Source::CameraInternal;
        d.applySaved = false;
        d.writeBackCamera = !cameraRead.isEmpty();
        d.logLine = QStringLiteral("[CAM] params: use_camera_params=1 → 使用相机内部参数，"
                                   "不下发任何参数（设备返回 %1 项%2）")
                        .arg(cameraRead.size())
                        .arg(cameraRead.isEmpty()
                                 ? QStringLiteral("，读取失败，沿用 SDK 默认值")
                                 : QString());
        return d;
    }
    d.source = Source::SavedConfig;
    d.applySaved = !savedParams.isEmpty();
    d.writeBackCamera = false;
    d.appliedKeys = savedParams.keys();
    d.logLine = QStringLiteral("[CAM] params: use_camera_params=0 → 使用保存的参数（下发 %1 项）")
                    .arg(d.appliedKeys.size());
    return d;
}

// Origin of the numbers currently shown in 设置 → 拍摄参数.  Stated explicitly
// so "设置里显示的是什么值" is never ambiguous.
inline QString describeSource(Source source, bool cameraConnected)
{
    if (source == Source::CameraInternal) {
        return cameraConnected
            ? QStringLiteral("来源：相机内部参数（连接时读取，当前生效）")
            : QStringLiteral("来源：相机内部参数（相机未连接，显示上次读取值）");
    }
    return cameraConnected
        ? QStringLiteral("来源：保存的参数（本次连接已下发到相机）")
        : QStringLiteral("来源：上次保存的参数（相机未连接）");
}

} // namespace CameraParamPolicy
