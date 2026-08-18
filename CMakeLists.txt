cmake_minimum_required(VERSION 3.20)
project(RvcVisionStudio VERSION 0.1.0 LANGUAGES CXX)

# --------------------------------------------------
# 全局设置
# --------------------------------------------------
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTOUIC ON)
set(CMAKE_AUTORCC ON)

# 必须 x64（PCL/RVC 均为 64 位预编译库）
if(NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR "RvcVisionStudio requires a 64-bit (x64) build. Use -A x64.")
endif()

if(MSVC)
    add_compile_options(/utf-8 /EHsc /MP /bigobj)
    add_compile_definitions(_CRT_SECURE_NO_WARNINGS NOMINMAX WIN32_LEAN_AND_MEAN)
endif()

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")

# --------------------------------------------------
# 依赖：Qt6 / PCL(+VTK) / RVC SDK
#
# VTK 用自编译的 9.2.2（带 GUISupportQt，third_party/VTK-install），
# 与 PCL 捆绑 VTK 同版本同名 DLL、ABI 兼容：PCLConfig 复用我们的 VTK，
# 运行时 pcl_visualization.dll 解析到我们部署的同名 VTK DLL。
# 若自编译 VTK 不存在，退回 PCL 3rdParty（无 Qt 支持，Viewport3D 将无法编译）。
# --------------------------------------------------
set(RVS_VTK_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/third_party/VTK-install"
    CACHE PATH "Custom VTK build with GUISupportQt")
if(EXISTS "${RVS_VTK_ROOT}/lib/cmake/vtk-9.2")
    set(VTK_DIR "${RVS_VTK_ROOT}/lib/cmake/vtk-9.2" CACHE PATH "VTK with Qt support" FORCE)
    set(RVS_HAS_QT_VTK ON)
    message(STATUS "Using custom VTK (with GUISupportQt): ${VTK_DIR}")
else()
    message(FATAL_ERROR
        "Custom VTK with GUISupportQt not found at ${RVS_VTK_ROOT}.\n"
        "Build it first (see README: third_party/VTK-src v9.2.2 with VTK_GROUP_ENABLE_Qt=YES).")
endif()

find_package(Qt6 REQUIRED COMPONENTS Widgets OpenGL OpenGLWidgets)
find_package(PCL 1.13 REQUIRED COMPONENTS common io visualization filters segmentation sample_consensus kdtree search)
find_package(RVC REQUIRED)

add_definitions(${PCL_DEFINITIONS})

# --------------------------------------------------
# 第三方：QtNodes v3.0.9（commit 0a3a9318，BSD-3）
# GitHub 直连不可用，经 gitclone.com 镜像克隆至 third_party 并锁定 commit。
# QtNodes 头文件硬编码 NODE_EDITOR_SHARED，必须保持动态库构建。
# --------------------------------------------------
set(BUILD_SHARED_LIBS ON CACHE BOOL "QtNodes is built as a shared library" FORCE)
set(BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(BUILD_DOCS OFF CACHE BOOL "" FORCE)
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
add_subdirectory(third_party/nodeeditor)
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)

# --------------------------------------------------
# 第三方：Catch2 v3.9.1（单测框架）
# --------------------------------------------------
set(CATCH_INSTALL_DOCS OFF CACHE BOOL "" FORCE)
set(CATCH_INSTALL_EXTRAS OFF CACHE BOOL "" FORCE)
set(CATCH_DEVELOPMENT_BUILD OFF CACHE BOOL "" FORCE)
add_subdirectory(third_party/Catch2)
list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/third_party/Catch2/extras")

enable_testing()

# --------------------------------------------------
# 运行时 DLL 收集（PCL/VTK/OpenNI2，排除 Debug 变体）
# --------------------------------------------------
get_filename_component(PCL_ROOT_DIR "${PCL_DIR}/.." ABSOLUTE)

file(GLOB RVS_PCL_DLLS "${PCL_ROOT_DIR}/bin/*.dll")
list(FILTER RVS_PCL_DLLS EXCLUDE REGEX "d\.dll$")          # pcl_*d.dll 为 Debug

if(RVS_HAS_QT_VTK)
    get_filename_component(VTK_BIN_DIR "${RVS_VTK_ROOT}/bin" ABSOLUTE)
elseif(VTK_DIR)
    get_filename_component(VTK_BIN_DIR "${VTK_DIR}/../../../bin" ABSOLUTE)
endif()
if(VTK_BIN_DIR)
    file(GLOB RVS_VTK_DLLS "${VTK_BIN_DIR}/*.dll")
    list(FILTER RVS_VTK_DLLS EXCLUDE REGEX "-gd\.dll$")    # vtk*-gd.dll 为 Debug
endif()

# OpenNI2：PCLConfig 可能指向系统级安装（C:/Program Files/OpenNI2），
# 也可能指向 PCL 3rdParty，两处 Redist 都尝试收集
file(GLOB RVS_OPENNI2_DLLS
    "${PCL_ROOT_DIR}/3rdParty/OpenNI2/Redist/*.dll"
    "C:/Program Files/OpenNI2/Redist/*.dll")

set(RVS_RUNTIME_DLLS ${RVS_PCL_DLLS} ${RVS_VTK_DLLS} ${RVS_OPENNI2_DLLS})
list(LENGTH RVS_RUNTIME_DLLS RVS_RUNTIME_DLL_COUNT)
message(STATUS "Runtime DLLs to deploy: ${RVS_RUNTIME_DLL_COUNT}")

find_program(WINDEPLOYQT_EXECUTABLE NAMES windeployqt
    HINTS "${Qt6_DIR}/../../../bin" NO_DEFAULT_PATH)
if(NOT WINDEPLOYQT_EXECUTABLE)
    message(WARNING "windeployqt not found; Qt DLLs must be deployed manually")
endif()

# 部署运行时：RVC DLL + PCL/VTK DLL + windeployqt（可选拷 QtNodes.dll）
function(rvs_deploy_runtime target)
    rvc_copy_runtime_dlls(${target})
    if(RVS_RUNTIME_DLLS)
        add_custom_command(TARGET ${target} POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different
                ${RVS_RUNTIME_DLLS} "$<TARGET_FILE_DIR:${target}>"
            COMMENT "Deploying PCL/VTK runtime DLLs for ${target}"
            VERBATIM)
    endif()
    if(TARGET QtNodes)
        add_custom_command(TARGET ${target} POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different
                "$<TARGET_FILE:QtNodes>" "$<TARGET_FILE_DIR:${target}>"
            VERBATIM)
    endif()
    if(WINDEPLOYQT_EXECUTABLE)
        # 本工程仅构建/验证 Release 配置
        add_custom_command(TARGET ${target} POST_BUILD
            COMMAND "${WINDEPLOYQT_EXECUTABLE}" --release --no-translations
                "$<TARGET_FILE:${target}>"
            COMMENT "windeployqt ${target}"
            VERBATIM)
    endif()
endfunction()

# --------------------------------------------------
# 目标
# --------------------------------------------------

# core 层：不依赖 QWidget，可无头运行
add_library(rvc_core STATIC
    src/core/DataTypes.h
    src/core/ModuleBase.h
    src/core/ModuleRegistry.h
    src/core/Process.h
    src/core/Process.cpp
    src/core/Solution.h
    src/core/Solution.cpp
    src/core/Engine.h
    src/core/Engine.cpp
)
target_include_directories(rvc_core PUBLIC src ${PCL_INCLUDE_DIRS})
target_link_libraries(rvc_core PUBLIC Qt6::Core pcl_common)
target_link_directories(rvc_core PUBLIC ${PCL_LIBRARY_DIRS})

# RVC 相机封装（M0 骨架）
add_library(rvc_camera STATIC
    src/camera/RvcCamera.h
    src/camera/RvcCamera.cpp
)
target_include_directories(rvc_camera PUBLIC src)
target_link_libraries(rvc_camera PUBLIC RVC::RVC pcl_common)

# 内置模块
add_library(rvc_modules STATIC
    src/modules/Modules.h
    src/modules/Modules.cpp
    src/modules/CloudUtils.h
    src/modules/acquisition/LoadPlyModule.h
    src/modules/acquisition/LoadPlyModule.cpp
    src/modules/preprocess/BoxRoiModule.h
    src/modules/preprocess/BoxRoiModule.cpp
    src/modules/preprocess/VoxelDownsampleModule.h
    src/modules/preprocess/VoxelDownsampleModule.cpp
    src/modules/preprocess/StatisticalDenoiseModule.h
    src/modules/preprocess/StatisticalDenoiseModule.cpp
    src/modules/fit/FitUtils.h
    src/modules/fit/FitPlaneModule.h
    src/modules/fit/FitPlaneModule.cpp
    src/modules/fit/FitLineModule.h
    src/modules/fit/FitLineModule.cpp
    src/modules/fit/FitCircleModule.h
    src/modules/fit/FitCircleModule.cpp
    src/modules/measure/PointToPlaneDistanceModule.h
    src/modules/measure/PointToPlaneDistanceModule.cpp
    src/modules/measure/PlaneToPlaneModule.h
    src/modules/measure/PlaneToPlaneModule.cpp
    src/modules/measure/BoundingBoxMeasureModule.h
    src/modules/measure/BoundingBoxMeasureModule.cpp
    src/modules/measure/CircleMeasureModule.h
    src/modules/measure/CircleMeasureModule.cpp
    src/modules/io/SavePlyModule.h
    src/modules/io/SavePlyModule.cpp
    src/modules/display/Display3DModule.h
    src/modules/display/Display3DModule.cpp
)
target_include_directories(rvc_modules PUBLIC src)
target_link_libraries(rvc_modules PUBLIC rvc_core pcl_io pcl_filters pcl_segmentation)

# GUI 应用
add_executable(RvcVisionStudio WIN32
    src/app/main.cpp
    src/ui/MainWindow.h
    src/ui/MainWindow.cpp
    src/ui/FlowModel.h
    src/ui/FlowModel.cpp
    src/ui/FlowView.h
    src/ui/FlowView.cpp
    src/ui/Toolbox.h
    src/ui/Toolbox.cpp
    src/ui/PropertyPanel.h
    src/ui/PropertyPanel.cpp
    src/ui/Roi2DView.h
    src/ui/Roi2DView.cpp
    src/ui/RoiEditDialog.h
    src/ui/RoiEditDialog.cpp
    src/ui/Theme.h
    src/ui/Theme.cpp
    src/ui/Viewport3D.h
    src/ui/Viewport3D.cpp
    src/ui/ViewportManager.h
    src/ui/ViewportManager.cpp
    src/ui/EngineRunner.h
    src/ui/EngineRunner.cpp
)
target_include_directories(RvcVisionStudio PRIVATE src)
target_link_libraries(RvcVisionStudio PRIVATE
    Qt6::Widgets QtNodes
    rvc_core rvc_modules rvc_camera
    pcl_visualization
)
if(RVS_HAS_QT_VTK)
    target_link_libraries(RvcVisionStudio PRIVATE VTK::GUISupportQt)
endif()
rvs_deploy_runtime(RvcVisionStudio)

# 应用字体（Geist / JetBrains Mono，OFL）部署到 exe 目录 fonts/
add_custom_command(TARGET RvcVisionStudio POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${CMAKE_CURRENT_SOURCE_DIR}/resources/fonts"
        "$<TARGET_FILE_DIR:RvcVisionStudio>/fonts"
    COMMENT "Deploying app fonts"
    VERBATIM)

# --------------------------------------------------
# 单元测试（Catch2）
# --------------------------------------------------
set(RVC_TEST_PLY "D:/Kimi_WorkSpace/Test/captured_data/offline_visualize.ply"
    CACHE FILEPATH "PLY file used by LoadPlyModule test")

add_executable(unit_tests tests/test_core.cpp)
target_include_directories(unit_tests PRIVATE src)
target_link_libraries(unit_tests PRIVATE rvc_core rvc_modules Catch2::Catch2WithMain)
target_compile_definitions(unit_tests PRIVATE RVC_TEST_PLY_PATH="${RVC_TEST_PLY}")
rvs_deploy_runtime(unit_tests)

include(Catch)
catch_discover_tests(unit_tests DISCOVERY_MODE PRE_TEST)
