// Throwaway probe: what does HandEyeSDK actually do with a robot pose line?
//
// TransformPointCloudsToRobotBase() with isEyeInHand=true and an identity
// hand-eye result applies  P_base = T_gripper2base * P_cam  -- i.e. the output
// point cloud is the robot pose line turned into a 4x4. Feeding a tiny known
// point cloud therefore reads the SDK's pose->matrix conversion back out,
// which the header comment ("whether the robot pose is in degree") does not
// specify.
//
//   he_sdk_probe <folder> <poseFile> <poseType> <isPoseMm> <isPoseDegree> <isEyeInHand> [matrix16...]
#include <cstdio>
#include <cstdlib>
#include <string>

#include "HandEye.h"

int main(int argc, char** argv)
{
    if (argc < 2) {
        std::printf("usage: he_sdk_probe <folder> <poseFile> <poseType> <isPoseMm> "
                    "<isPoseDegree> <isEyeInHand> [matrix16...]\n"
                    "       he_sdk_probe calib <folder> <poseFile> <poseType> <isPoseMm> <isPoseDegree>\n"
                    "       he_sdk_probe touch <folder> <poseType> <isPoseMm> <isPoseDegree>\n");
        return 2;
    }

    // Second mode: run the *calibration* entry point over a pose file with no
    // images/point clouds at all. It validates the pose file before doing any
    // detection, so -4 means "pose file rejected" and anything else means the
    // parser accepted this poseType.
    //   he_sdk_probe calib <folder> <poseFile> <poseType> <isPoseMm> <isPoseDegree>
    if (std::string(argv[1]) == "calib") {
        if (argc < 7) {
            std::printf("usage: he_sdk_probe calib <folder> <poseFile> <poseType> "
                        "<isPoseMm> <isPoseDegree>\n");
            return 2;
        }
        HandEyeParam p{};
        p.poseType = std::atoi(argv[4]);
        p.markerType = 1;
        p.isPointCloudMm = true;
        p.isPoseMm = std::atoi(argv[5]) != 0;
        p.isPoseDegree = std::atoi(argv[6]) != 0;
        p.isEyeInHand = true;
        for (int i = 0; i < 100; ++i)
            p.dataMask[i] = true;
        HandEyeResult r{};
        const int rc = HandEyeCalibrationMarker(argv[2], argv[3], p, r);
        std::printf("HandEyeCalibrationMarker -> %d  (-1 bad args, -3 count mismatch, "
                    "-4 pose file rejected)\n", rc);
        std::fflush(stdout);
        return 0;
    }

    // Third mode: HandEyeCalibrationTcpTouch, which needs no images at all.
    // Its -5 is literally "the data in robotPoseFilePath is invalid" and -7 is
    // "parsed fine, needs >= 2 poses" -- so this separates "the calibration
    // entry point accepts this pose format" from "it does not" without any
    // board detection. The caller writes camera.txt / pose.txt / tcp.txt.
    //   he_sdk_probe touch <folder> <poseType> <isPoseMm> <isPoseDegree>
    if (std::string(argv[1]) == "touch") {
        if (argc < 6) {
            std::printf("usage: he_sdk_probe touch <folder> <poseType> <isPoseMm> <isPoseDegree>\n");
            return 2;
        }
        HandEyeParam p{};
        p.poseType = std::atoi(argv[3]);
        p.markerType = 1;
        p.isPointCloudMm = true;
        p.isPoseMm = std::atoi(argv[4]) != 0;
        p.isPoseDegree = std::atoi(argv[5]) != 0;
        p.isEyeInHand = true;
        for (int i = 0; i < 100; ++i)
            p.dataMask[i] = true;
        HandEyeResult r{};
        const std::string cam = std::string(argv[2]) + "/camera.txt";
        const std::string tcp = std::string(argv[2]) + "/tcp.txt";
        const std::string pose = std::string(argv[2]) + "/pose.txt";
        const int rc = HandEyeCalibrationTcpTouch(cam.c_str(), pose.c_str(), tcp.c_str(), p, r);
        std::printf("HandEyeCalibrationTcpTouch -> %d  (-5 = pose file invalid, "
                    "-7 = parsed but < 2 poses, 0 = calibrated)\n", rc);
        if (rc == 0)
            std::printf("  totalMeanError=%.6f  error[0..3]=%.6f %.6f %.6f %.6f\n"
                        "  matrix row-major:\n"
                        "    %12.6f %12.6f %12.6f %12.6f\n"
                        "    %12.6f %12.6f %12.6f %12.6f\n"
                        "    %12.6f %12.6f %12.6f %12.6f\n"
                        "    %12.6f %12.6f %12.6f %12.6f\n",
                        r.totalMeanError, r.error[0], r.error[1], r.error[2], r.error[3],
                        r.matrix[0], r.matrix[1], r.matrix[2], r.matrix[3],
                        r.matrix[4], r.matrix[5], r.matrix[6], r.matrix[7],
                        r.matrix[8], r.matrix[9], r.matrix[10], r.matrix[11],
                        r.matrix[12], r.matrix[13], r.matrix[14], r.matrix[15]);
        std::fflush(stdout);
        return 0;
    }

    if (argc < 7) {
        std::printf("usage: he_sdk_probe <folder> <poseFile> <poseType> "
                    "<isPoseMm> <isPoseDegree> <isEyeInHand> [matrix16...]\n");
        return 2;
    }

    const char* folder = argv[1];
    const char* poseFile = argv[2];
    const int poseType = std::atoi(argv[3]);
    const bool isPoseMm = std::atoi(argv[4]) != 0;
    const bool isPoseDegree = std::atoi(argv[5]) != 0;
    const bool isEyeInHand = std::atoi(argv[6]) != 0;

    double m[16] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
    for (int i = 0; i < 16 && argc > 7 + i; ++i)
        m[i] = std::atof(argv[7 + i]);

    const int ret = TransformPointCloudsToRobotBase(
        folder, poseFile, poseType, /*isPointCloudMm=*/true, isPoseMm, isPoseDegree,
        isEyeInHand, m);
    std::printf("TransformPointCloudsToRobotBase -> %d\n", ret);
    std::fflush(stdout);
    return ret == 0 ? 0 : 1;
}
