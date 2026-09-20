#include "test_camera_param_policy.h"

#include <QtTest>

#include "logic/CameraParamPolicy.h"

using namespace CameraParamPolicy;

namespace {

QMap<QString, float> sampleSaved()
{
    return { { QStringLiteral("exposure_time_2d"), 8000.0f },
             { QStringLiteral("gain_2d"), 2.0f } };
}

QMap<QString, float> sampleRead()
{
    return { { QStringLiteral("exposure_time_2d"), 12000.0f },
             { QStringLiteral("gain_2d"), 1.0f },
             { QStringLiteral("exposure_time_3d"), 5000.0f } };
}

} // namespace

void TestCameraParamPolicy::cameraInternalPushesNothing()
{
    const Decision d = decide(/*useCameraParams=*/true, sampleSaved(), sampleRead(),
                              /*userEdited=*/false);

    QCOMPARE(d.source, Source::CameraInternal);
    QVERIFY(!d.applySaved);            // ← no setParameter() call at all
    QVERIFY(d.appliedKeys.isEmpty());
    // The values read from the device are what the operator tuned in the vendor
    // tool, so they are also what 设置 must display from now on.
    QVERIFY(d.writeBackCamera);
    QVERIFY(d.logLine.contains(QStringLiteral("不下发任何参数")));
    QVERIFY(d.logLine.contains(QStringLiteral("3 项")));
}

void TestCameraParamPolicy::cameraInternalEmptyReadPushesNothing()
{
    // Reading the device values can fail (no device, SDK refusal).  The rule is
    // still "do not push": falling back to the saved values here would silently
    // undo the whole point of the switch.
    const Decision d = decide(true, sampleSaved(), {}, false);

    QCOMPARE(d.source, Source::CameraInternal);
    QVERIFY(!d.applySaved);
    QVERIFY(d.appliedKeys.isEmpty());
    QVERIFY(!d.writeBackCamera);       // nothing to persist
    QVERIFY(d.logLine.contains(QStringLiteral("读取失败")));
}

void TestCameraParamPolicy::savedConfigIsApplied()
{
    const Decision d = decide(/*useCameraParams=*/false, sampleSaved(), sampleRead(),
                              /*userEdited=*/false);

    QCOMPARE(d.source, Source::SavedConfig);
    QVERIFY(d.applySaved);
    QCOMPARE(d.appliedKeys.size(), 2);
    QVERIFY(d.appliedKeys.contains(QStringLiteral("exposure_time_2d")));
    // The camera's own values are not persisted over the operator's file.
    QVERIFY(!d.writeBackCamera);
    QVERIFY(d.logLine.contains(QStringLiteral("使用保存的参数")));
}

void TestCameraParamPolicy::savedConfigEmptyPushesNothing()
{
    const Decision d = decide(false, {}, {}, false);

    QCOMPARE(d.source, Source::SavedConfig);
    QVERIFY(!d.applySaved);            // nothing to push
    QVERIFY(d.appliedKeys.isEmpty());
    QVERIFY(!d.writeBackCamera);
}

void TestCameraParamPolicy::operatorEditBeatsTheCheckbox()
{
    // Editing a field switches the effective source to the saved values even
    // while use_camera_params is still on — the alternative is the silent
    // "I typed a value and the program ignored it" failure.
    const Decision d = decide(/*useCameraParams=*/true, sampleSaved(), sampleRead(),
                              /*userEdited=*/true);

    QCOMPARE(d.source, Source::SavedConfig);
    QVERIFY(d.applySaved);
    QCOMPARE(d.appliedKeys.size(), 2);
    QVERIFY(d.logLine.contains(QStringLiteral("操作员修改了拍摄参数")));
    QVERIFY(d.logLine.contains(QStringLiteral("已自动关闭 use_camera_params")));
}

void TestCameraParamPolicy::operatorEditWithEmptySavedPushesNothing()
{
    // Unreachable through the dialog (an edit stores every row), but the
    // decision must stay honest rather than claim it pushed something.
    const Decision d = decide(true, {}, sampleRead(), true);

    QCOMPARE(d.source, Source::SavedConfig);
    QVERIFY(d.appliedKeys.isEmpty());
    QVERIFY(!d.writeBackCamera);
}

void TestCameraParamPolicy::sourceAnnotationIsExplicit()
{
    // Four combinations; the "not connected" wording must never imply live
    // values, and the camera-internal wording must name the source.
    const QString ciOn = describeSource(Source::CameraInternal, true);
    const QString ciOff = describeSource(Source::CameraInternal, false);
    const QString svOn = describeSource(Source::SavedConfig, true);
    const QString svOff = describeSource(Source::SavedConfig, false);

    QVERIFY(ciOn.contains(QStringLiteral("相机内部参数")));
    QVERIFY(ciOn.contains(QStringLiteral("当前生效")));
    QVERIFY(ciOff.contains(QStringLiteral("相机未连接")));
    QVERIFY(ciOff.contains(QStringLiteral("上次读取值")));
    QVERIFY(svOn.contains(QStringLiteral("已下发到相机")));
    QVERIFY(svOff.contains(QStringLiteral("相机未连接")));

    QVERIFY(ciOn != svOn);
    QVERIFY(ciOff != svOff);
}
