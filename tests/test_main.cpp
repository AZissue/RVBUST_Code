#include <QCoreApplication>
#include <QtTest>

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
#include "test_pose_guide.h"
#include "test_data_quality_check.h"
#include "test_board_pose_fit.h"

int main(int argc, char** argv)
{
    QCoreApplication app(argc, argv);

    int status = 0;
    {
        TestPointCloudUtils t1;
        status |= QTest::qExec(&t1, argc, argv);
    }
    {
        TestGeometryTools t1b;
        status |= QTest::qExec(&t1b, argc, argv);
    }
    {
        TestDetectionEngine t2;
        status |= QTest::qExec(&t2, argc, argv);
    }
    {
        TestCaptureFlowValidation t3;
        status |= QTest::qExec(&t3, argc, argv);
    }
    {
        TestDataManager t4;
        status |= QTest::qExec(&t4, argc, argv);
    }
    {
        TestTransformTools t5;
        status |= QTest::qExec(&t5, argc, argv);
    }
    {
        TestToolInputParser t6;
        status |= QTest::qExec(&t6, argc, argv);
    }
    {
        TestPixelTo3D t7;
        status |= QTest::qExec(&t7, argc, argv);
    }
    {
        TestCalibrationService t8;
        status |= QTest::qExec(&t8, argc, argv);
    }
    {
        TestRobotPose t9;
        status |= QTest::qExec(&t9, argc, argv);
    }
    {
        TestPoseGuide t10;
        status |= QTest::qExec(&t10, argc, argv);
    }
    {
        TestDataQualityCheck t11;
        status |= QTest::qExec(&t11, argc, argv);
    }
    {
        TestBoardPoseFit t12;
        status |= QTest::qExec(&t12, argc, argv);
    }
    return status;
}
