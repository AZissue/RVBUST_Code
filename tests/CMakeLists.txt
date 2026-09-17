find_package(Qt5 REQUIRED COMPONENTS Test Core Gui)

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
)

target_include_directories(unit_tests PRIVATE ${CMAKE_SOURCE_DIR}/src)

target_compile_definitions(unit_tests PRIVATE
    TEST_DATA_DIR="${CMAKE_SOURCE_DIR}/tests/data")

target_link_libraries(unit_tests PRIVATE
    Qt5::Test
    Qt5::Core
    Qt5::Gui
    Qt5::Network
    RVC::RVC
    HandEyeSDK::HandEyeSDK
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
