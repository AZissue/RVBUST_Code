find_package(Qt5 REQUIRED COMPONENTS Test Core Gui Concurrent)

set(TEST_SOURCES
    test_main.cpp
    test_point_cloud_utils.cpp
    test_geometry_tools.cpp
    test_detection_engine.cpp
    test_capture_flow_validation.cpp
    test_data_manager.cpp
    test_transform_tools.cpp
    test_tool_input_parser.cpp
    test_pixel_to_3d.cpp
    test_calibration_service.cpp
    test_robot_pose.cpp
    test_nrc_json_reader.cpp
    test_pose_guide.cpp
    test_data_quality_check.cpp
    test_board_pose_fit.cpp
    test_frame_buffer.cpp
    test_ui_stall_watchdog.cpp
    test_measure_tools.cpp
    test_auto_flow_policy.cpp
    test_camera_recovery.cpp
    test_camera_manager_release.cpp
    # 第 7 回合 P3/P4：方法目录（src/logic/MeasureMethods.h，header-only）的
    # ROI 需求 / 拖框策略 / 说明与结果文案。
    test_measure_methods.cpp
    # 第 10 回合 P4：操作日志的落屏规则（src/logic/LogPresentation.h，
    # 级别 → 标签/配色 + 哪些条目上屏）。
    test_log_presentation.cpp
    # 第 11 回合任务 001（Codex 验收测试）：像素→3D 共享服务的分派顺序与
    # 结果一致性（src/logic/PixelTo3DService.cpp）。
    test_pixel_to_3d_service.cpp
    # 第 11 回合任务 008（Codex 验收测试）：埃夫特适配器的位姿归一化与
    # SDK 返回码映射（真机不可用，这里钉住"我们自己的换算"）。
    test_efort_pose_reader.cpp
    # T-005（Codex 验收测试）：保存路径的"假成功"——导出文件写失败必须能被
    # 上报（DataManager 返回值 + 原因），CaptureFlow 不许报"保存成功"；
    # 备份必须是原子写、带 version、恢复时跳过损坏文件。
    test_save_export.cpp
    # 2026-10-08：程序名与版本号的唯一出处（src/AppInfo.h，header-only）。
    # 用户在 2.0 版本里还看到 V1.0 —— 那句话当时硬编码在窗口标题/顶栏/帮助三处。
    test_app_info.cpp
    # 2026-10-08：使用说明的内容表（src/logic/HelpContent.h，header-only）。
    # 说明里逐字写着界面上的按钮名 —— 改名而说明没跟上，用户会照着说明找不到
    # 东西。这里钉住章节完整性、测量方法一章必须覆盖每个方法、以及"正文不许
    # 写死版本号"。
    test_help_content.cpp
)

add_executable(unit_tests ${TEST_SOURCES}
    ${CMAKE_SOURCE_DIR}/src/logic/FrameBuffer.cpp
    ${CMAKE_SOURCE_DIR}/src/logic/UiStallWatchdog.cpp
    ${CMAKE_SOURCE_DIR}/src/logic/PointCloudUtils.cpp
    ${CMAKE_SOURCE_DIR}/src/logic/DetectionEngine.cpp
    ${CMAKE_SOURCE_DIR}/src/sdk/HandEyeSDKBridge.cpp
    ${CMAKE_SOURCE_DIR}/src/logic/DataManager.cpp
    ${CMAKE_SOURCE_DIR}/src/logic/CalibrationService.cpp
    ${CMAKE_SOURCE_DIR}/src/logic/RobotPose.cpp
    ${CMAKE_SOURCE_DIR}/src/logic/URRealtimeReader.cpp
    ${CMAKE_SOURCE_DIR}/src/logic/NrcJsonReader.cpp
    # NrcJsonReader logs every raw response through RuntimeLog.
    ${CMAKE_SOURCE_DIR}/src/logic/RuntimeLog.cpp
    # Measurement kernel: pure computation, no Qt, no SDK.
    ${CMAKE_SOURCE_DIR}/src/logic/MeasureTools.cpp
    # Pixel -> 3D shared service (used by the tool page offline and, later, by
    # the online click-to-pick path).
    ${CMAKE_SOURCE_DIR}/src/logic/PixelTo3DService.cpp
    # Efort (EFORT) robot adapter: readPose needs the vendor SDK, but the
    # normalisation helpers are what the tests exercise.
    ${CMAKE_SOURCE_DIR}/src/logic/EfortPoseReader.cpp
    # CameraManager itself, so "call shutdown() twice" is tested against the
    # real object and not only against the pure CameraRelease::plan.  The tests
    # never connect, so no RVC call is reached.
    ${CMAKE_SOURCE_DIR}/src/logic/CameraManager.cpp
    # T-005：CaptureFlow::save()/undo() 的导出失败上报要在真对象上验。
    ${CMAKE_SOURCE_DIR}/src/logic/CaptureFlow.cpp
)

target_include_directories(unit_tests PRIVATE ${CMAKE_SOURCE_DIR}/src)

target_compile_definitions(unit_tests PRIVATE
    TEST_DATA_DIR="${CMAKE_SOURCE_DIR}/tests/data")

target_link_libraries(unit_tests PRIVATE
    Qt5::Test
    Qt5::Core
    Qt5::Gui
    Qt5::Network
    # CameraManager.cpp uses QtConcurrent for its capture/scan workers.
    Qt5::Concurrent
    RVC::RVC
    HandEyeSDK::HandEyeSDK
    # EfortPoseReader.cpp links the EFORT SDK; the include dir comes from the
    # imported target so the test can also read SdkConstDef.h's return codes.
    EfortSDK::EfortSDK
    ws2_32
)

if(WIN32)
    # Drop the test binary next to the app exe so every deployed runtime DLL
    # (RVC, HandEyeSDK, Qt5, OSG) resolves at run time.
    set_target_properties(unit_tests PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY "$<TARGET_FILE_DIR:HandEyeCalibrationTool>")

    # Qt5Test is not deployed by the main app; copy it (Release + Debug).
    get_target_property(_qt5core_loc Qt5::Core IMPORTED_LOCATION_RELEASE)
    if(NOT _qt5core_loc)
        get_target_property(_qt5core_loc Qt5::Core IMPORTED_LOCATION)
    endif()
    get_filename_component(_qt5_bin "${_qt5core_loc}" DIRECTORY)
    add_custom_command(TARGET unit_tests POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${_qt5_bin}/Qt5Test$<$<CONFIG:Debug>:d>.dll"
            "$<TARGET_FILE_DIR:unit_tests>"
        COMMENT "Deploying Qt5Test runtime")
endif()

# The console output of a crashed/failed run is not always captured by the
# launcher, so QTest also writes a machine-readable report next to the build.
# Real-time console output is kept via "-o -,txt".
add_test(NAME unit_tests COMMAND unit_tests
    -o "${CMAKE_BINARY_DIR}/unit_tests_report.txt,txt"
    -o "-,txt")

# ── known-truth measurement harness (round 7, P1/P2) ───────────────────
# Generates codex_testData/ and then verifies every measurement against the
# truth recorded in its manifest, through the full chain
#   ROI 像素矩形 -> roiImageToGrid -> pointsInRoiIndexed -> 测量算法.
# No Qt GUI, no camera, no SDK: pure computation over files, so it is a normal
# headless ctest case.  The data is generated in place under the source tree so
# a human (and Codex's acceptance scripts) can find it where the round-7 spec
# asks for it; the binary carriers are gitignored and only manifest.json —
# every truth, tolerance and criterion — plus README.md are tracked.
add_executable(measure_truth
    measure_truth.cpp
    measure_truth_scenes.cpp
    ${CMAKE_SOURCE_DIR}/src/logic/MeasureTools.cpp
)
target_include_directories(measure_truth PRIVATE ${CMAKE_SOURCE_DIR}/src ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(measure_truth PRIVATE Qt5::Core)

if(WIN32)
    set_target_properties(measure_truth PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY "$<TARGET_FILE_DIR:HandEyeCalibrationTool>")
endif()

add_test(NAME measurement_truth COMMAND measure_truth
    --data-dir "${CMAKE_SOURCE_DIR}/codex_testData")
