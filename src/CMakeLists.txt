set(SOURCES
    main.cpp
    app/MainWindow.cpp
    models/CalibrationMode.h
    models/CaptureRecord.h
    logic/AppConfig.cpp
    logic/LogManager.cpp
    logic/DataManager.cpp
    logic/CameraManager.cpp
    logic/RuntimeLog.cpp
    logic/DetectionEngine.cpp
    logic/CaptureFlow.cpp
    logic/FrameBuffer.cpp
    logic/UiStallWatchdog.cpp
    logic/PointCloudUtils.cpp
    logic/CalibrationService.cpp
    logic/RobotPose.cpp
    logic/URRealtimeReader.cpp
    logic/NrcJsonReader.cpp
    # 埃夫特（EFORT）机器人通信适配器（用户反馈 7，第四种协议）
    logic/EfortPoseReader.cpp
    logic/MeasureTools.cpp
    logic/PixelTo3DService.cpp
    # 测量方法目录（P3 ROI 需求 / P4 说明）— 纯数据，无 Qt 依赖
    logic/MeasureMethods.h
    logic/GeometryTools.h
    sdk/HandEyeSDKBridge.cpp
    ui/Theme.cpp
    ui/ToastOverlay.cpp
    ui/DataInputCard.cpp
    ui/DataInputArea.cpp
    ui/ActionButtons.cpp
    ui/TopNavBar.cpp
    ui/ModeSelector.cpp
    ui/SidePanel.cpp
    ui/Image2DView.cpp
    ui/VisSceneView.cpp
    ui/ToolsPanel.cpp
    # 测量页基类 + 8 个方法页（P3：左侧列表各一项，共用同一基类）
    ui/MeasurePage.cpp
    ui/MeasurePages.cpp
    ui/DeviceListDialog.cpp
    ui/SettingsDialog.cpp
    # 使用说明窗口（左侧章节 + 右侧正文）；正文在 logic/HelpContent.h
    ui/HelpDialog.cpp
)

add_executable(${PROJECT_NAME} ${SOURCES})

target_include_directories(${PROJECT_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/..
)

target_link_libraries(${PROJECT_NAME} PRIVATE
    Qt5::Widgets
    Qt5::Core
    Qt5::Gui
    Qt5::Concurrent
    Qt5::Network
    RVC::RVC
    HandEyeSDK::HandEyeSDK
    EfortSDK::EfortSDK
)

set(THIRD_PARTY "${CMAKE_SOURCE_DIR}/third_party")

if(RVBUSTVis_FOUND)
    target_link_libraries(${PROJECT_NAME} PRIVATE RVBUSTVis::Vis)

    if(WIN32)
        file(GLOB OSG_DLLS      "${THIRD_PARTY}/OSG/bin/*.dll")
        file(GLOB OSG_PLUGINS   "${THIRD_PARTY}/OSG/bin/osgPlugins-3.6.5/*.dll")

        add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different ${OSG_DLLS} $<TARGET_FILE_DIR:${PROJECT_NAME}>
            COMMAND ${CMAKE_COMMAND} -E make_directory
                "$<TARGET_FILE_DIR:${PROJECT_NAME}>/osgPlugins-3.6.5"
            COMMAND ${CMAKE_COMMAND} -E copy_if_different
                ${OSG_PLUGINS}
                "$<TARGET_FILE_DIR:${PROJECT_NAME}>/osgPlugins-3.6.5/"
            COMMENT "Deploying OSG 3.6.5 runtime DLLs..."
        )
    endif()
endif()

if(WIN32)
    set_target_properties(${PROJECT_NAME} PROPERTIES
        WIN32_EXECUTABLE TRUE
    )

    file(GLOB QT5_DLLS      "${THIRD_PARTY}/Qt5/bin/*.dll")
    file(GLOB RVC_DLLS      "${THIRD_PARTY}/RVC/runtime/*.dll")
    file(GLOB HANDEYE_DLLS  "${THIRD_PARTY}/HandEyeSDK/bin/*.dll")
    # EftSdk.dll + 它的依赖（log4cpp / rlibcpp*）。third_party 已在 .gitignore
    # 里，这些二进制不会进 git。
    file(GLOB EFORT_DLLS    "${THIRD_PARTY}/EfortSDK/bin/*.dll")

    # 埃夫特 SDK 内部用 log4cpp，连接前会读**工作目录**下的 log4cpp.conf，
    # 缺文件时 EftSdk.dll 直接抛异常（这就是 008 整程序崩溃的根因，009 之后
    # 变成一条可读的「连接失败」）。所以它必须和 exe 一起部署。
    # 源文件缺失时明确报错，不静默跳过（否则真机上只会看到连接失败）。
    set(EFORT_LOG_CONF "${THIRD_PARTY}/EfortSDK/bin/log4cpp.conf")
    if(NOT EXISTS "${EFORT_LOG_CONF}")
        message(FATAL_ERROR
            "找不到 EfortSDK 的日志配置 ${EFORT_LOG_CONF}：EftSdk.dll 在连接前需要"
            "可执行文件旁边的 log4cpp.conf。请把 SDK 自带的 log4cpp 样例配置放到 "
            "third_party/EfortSDK/bin/log4cpp.conf（或把 EFORTSDK_DIR 指向含该文件的 SDK）。")
    endif()

    add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
        # Qt5 runtime DLLs (Release + Debug)
        COMMAND ${CMAKE_COMMAND} -E copy_if_different ${QT5_DLLS} $<TARGET_FILE_DIR:${PROJECT_NAME}>
        # Qt5 platform plugin
        COMMAND ${CMAKE_COMMAND} -E make_directory
            "$<TARGET_FILE_DIR:${PROJECT_NAME}>/platforms"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${THIRD_PARTY}/Qt5/plugins/platforms/qwindows$<$<CONFIG:Debug>:d>.dll"
            "$<TARGET_FILE_DIR:${PROJECT_NAME}>/platforms/"
        # RVC + HandEyeSDK
        COMMAND ${CMAKE_COMMAND} -E copy_if_different ${RVC_DLLS} $<TARGET_FILE_DIR:${PROJECT_NAME}>
        COMMAND ${CMAKE_COMMAND} -E copy_if_different ${HANDEYE_DLLS} $<TARGET_FILE_DIR:${PROJECT_NAME}>
        # EfortSDK（埃夫特）
        COMMAND ${CMAKE_COMMAND} -E copy_if_different ${EFORT_DLLS} $<TARGET_FILE_DIR:${PROJECT_NAME}>
        # EfortSDK 的 log4cpp 配置：必须躺在 exe 旁边（见上面的 EXISTS 检查）
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${EFORT_LOG_CONF}" "$<TARGET_FILE_DIR:${PROJECT_NAME}>"
        COMMENT "Deploying Qt5 + RVC + HandEyeSDK + EfortSDK runtime DLLs..."
    )

    # VC++ runtime (app-local deployment): the target PC needs no vc_redist.
    # The exe requires MSVCP140/VCRUNTIME140/VCRUNTIME140_1; HandEyeSDK.dll
    # additionally needs MSVCP140_2, VCOMP140 and CONCRT140.
    foreach(_vcrt msvcp140.dll msvcp140_2.dll vcruntime140.dll vcruntime140_1.dll
                  VCOMP140.dll CONCRT140.dll)
        if(EXISTS "C:/Windows/System32/${_vcrt}")
            add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
                COMMAND ${CMAKE_COMMAND} -E copy_if_different
                    "C:/Windows/System32/${_vcrt}" "$<TARGET_FILE_DIR:${PROJECT_NAME}>"
                COMMENT "Deploying VC runtime ${_vcrt}")
        endif()
    endforeach()
endif()
