# Find EfortSDK (EftSdk.lib + EfortSdk.h) — 埃夫特机器人 SDK
#
# 与 cmake/FindHandEyeSDK.cmake 同构：先查仓库内的 third_party 拷贝，
# 再查环境变量 EFORTSDK_DIR，最后回落到用户机器上的原始 SDK 目录。
#
# EFORTSDK_INCLUDE_DIR - include directory
# EFORTSDK_LIBRARY     - EftSdk.lib path
# EFORTSDK_FOUND       - system has EfortSDK

set(EFORTSDK_PATHS
    "${CMAKE_SOURCE_DIR}/third_party/EfortSDK"
    "$ENV{EFORTSDK_DIR}"
    "D:/MyCode/EfortSDK"
)

find_path(EFORTSDK_INCLUDE_DIR
    NAMES EfortSdk.h
    PATHS ${EFORTSDK_PATHS}
    PATH_SUFFIXES include
)

find_library(EFORTSDK_LIBRARY
    NAMES EftSdk
    PATHS ${EFORTSDK_PATHS}
    PATH_SUFFIXES lib
)

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(EfortSDK DEFAULT_MSG EFORTSDK_INCLUDE_DIR EFORTSDK_LIBRARY)

if(EfortSDK_FOUND)
    add_library(EfortSDK::EfortSDK UNKNOWN IMPORTED)
    set_target_properties(EfortSDK::EfortSDK PROPERTIES
        IMPORTED_LOCATION "${EFORTSDK_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${EFORTSDK_INCLUDE_DIR}"
    )
endif()
