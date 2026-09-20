#include <QCoreApplication>
#include <QString>
#include <QtTest>

#include <string>
#include <vector>

#include "test_point_cloud_utils.h"
#include "test_geometry_tools.h"
#include "test_detection_engine.h"
#include "test_capture_flow_validation.h"
#include "test_data_manager.h"
#include "test_transform_tools.h"
#include "test_tool_input_parser.h"
#include "test_pixel_to_3d.h"
#include "test_calibration_service.h"
#include "test_robot_pose.h"
#include "test_nrc_json_reader.h"
#include "test_pose_guide.h"
#include "test_data_quality_check.h"
#include "test_board_pose_fit.h"
#include "test_frame_buffer.h"
#include "test_ui_stall_watchdog.h"
#include "test_measure_tools.h"
#include "test_camera_param_policy.h"
#include "test_auto_flow_policy.h"
#include "test_camera_recovery.h"
#include "test_camera_manager_release.h"
#include "test_measure_methods.h"
#include "test_log_presentation.h"
#include "test_pixel_to_3d_service.h"

namespace {

// QTest truncates the file passed to "-o" every time qExec() runs, so a single
// "report.txt" only ever holds the *last* class's result — the other 14 classes
// were silently lost, which is precisely the kind of missing evidence this run
// must produce.  Each class therefore writes its own file, with the tag inserted
// before the extension:
//     "unit_tests_report.txt,txt" -> "unit_tests_report.frame_buffer.txt,txt"
// A "-" filename (stdout) is passed through untouched.
std::vector<std::string> reportArgsFor(int argc, char** argv, const char* tag)
{
    std::vector<std::string> args;
    args.reserve(static_cast<std::size_t>(argc) + 2);
    for (int i = 1; i < argc; ++i) {
        const QString arg = QString::fromLocal8Bit(argv[i]);
        if (arg == QLatin1String("-o") && i + 1 < argc) {
            QString spec = QString::fromLocal8Bit(argv[++i]);
            const int comma = spec.lastIndexOf(QLatin1Char(','));
            QString path = comma > 0 ? spec.left(comma) : spec;
            const QString format = comma > 0 ? spec.mid(comma) : QString();
            if (!path.isEmpty() && path != QLatin1String("-")) {
                const QString suffix = QStringLiteral(".%1").arg(QLatin1String(tag));
                const int dot = path.lastIndexOf(QLatin1Char('.'));
                const int slash = path.lastIndexOf(QLatin1Char('/'));
                path = (dot > slash) ? path.left(dot) + suffix + path.mid(dot)
                                     : path + suffix;
            }
            args.push_back("-o");
            args.push_back((path + format).toStdString());
        } else {
            args.push_back(arg.toStdString());
        }
    }
    return args;
}

// Runs one test class with the per-class report file substituted in.
int runClass(QObject* test, int argc, char** argv, const char* tag)
{
    const std::vector<std::string> owned = reportArgsFor(argc, argv, tag);
    std::vector<char*> args;
    args.reserve(owned.size() + 1);
    args.push_back(argv[0]);
    for (const std::string& s : owned)
        args.push_back(const_cast<char*>(s.c_str()));
    return QTest::qExec(test, static_cast<int>(args.size()), args.data());
}

} // namespace

int main(int argc, char** argv)
{
    QCoreApplication app(argc, argv);

    int status = 0;
    {
        TestPointCloudUtils t1;
        status |= runClass(&t1, argc, argv, "point_cloud_utils");
    }
    {
        TestGeometryTools t1b;
        status |= runClass(&t1b, argc, argv, "geometry_tools");
    }
    {
        TestDetectionEngine t2;
        status |= runClass(&t2, argc, argv, "detection_engine");
    }
    {
        TestCaptureFlowValidation t3;
        status |= runClass(&t3, argc, argv, "capture_flow_validation");
    }
    {
        TestDataManager t4;
        status |= runClass(&t4, argc, argv, "data_manager");
    }
    {
        TestTransformTools t5;
        status |= runClass(&t5, argc, argv, "transform_tools");
    }
    {
        TestToolInputParser t6;
        status |= runClass(&t6, argc, argv, "tool_input_parser");
    }
    {
        TestPixelTo3D t7;
        status |= runClass(&t7, argc, argv, "pixel_to_3d");
    }
    {
        TestCalibrationService t8;
        status |= runClass(&t8, argc, argv, "calibration_service");
    }
    {
        TestRobotPose t9;
        status |= runClass(&t9, argc, argv, "robot_pose");
    }
    {
        TestPoseGuide t10;
        status |= runClass(&t10, argc, argv, "pose_guide");
    }
    {
        TestDataQualityCheck t11;
        status |= runClass(&t11, argc, argv, "data_quality_check");
    }
    {
        TestBoardPoseFit t12;
        status |= runClass(&t12, argc, argv, "board_pose_fit");
    }
    {
        TestFrameBuffer t13;
        status |= runClass(&t13, argc, argv, "frame_buffer");
    }
    {
        TestUiStallWatchdog t14;
        status |= runClass(&t14, argc, argv, "ui_stall_watchdog");
    }
    {
        TestNrcJsonReader t15;
        status |= runClass(&t15, argc, argv, "nrc_json_reader");
    }
    {
        TestMeasureTools t16;
        status |= runClass(&t16, argc, argv, "measure_tools");
    }
    {
        TestCameraParamPolicy t17;
        status |= runClass(&t17, argc, argv, "camera_param_policy");
    }
    {
        TestAutoFlowPolicy t18;
        status |= runClass(&t18, argc, argv, "auto_flow_policy");
    }
    {
        TestCameraRecovery t19;
        status |= runClass(&t19, argc, argv, "camera_recovery");
    }
    {
        TestCameraManagerRelease t20;
        status |= runClass(&t20, argc, argv, "camera_manager_release");
    }
    {
        // 第 7 回合 P3/P4：方法目录的 ROI 需求与说明文案（纯逻辑，无界面）。
        TestMeasureMethods t21;
        status |= runClass(&t21, argc, argv, "measure_methods");
    }
    {
        // 第 10 回合 P4：操作日志的落屏规则（级别 → 标签/配色、哪些条目上屏）。
        TestLogPresentation t22;
        status |= runClass(&t22, argc, argv, "log_presentation");
    }
    {
        // 第 11 回合任务 001（Codex 验收）：像素→3D 共享服务（在线/离线共用）
        // 的分派顺序、失败状态与结果一致性。
        TestPixelTo3DService t23;
        status |= runClass(&t23, argc, argv, "pixel_to_3d_service");
    }
    return status;
}
