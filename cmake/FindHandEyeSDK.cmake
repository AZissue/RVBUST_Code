# Find HandEyeSDK (HandEyeSDK.lib + HandEye.h)
#
# HANDEYESDK_INCLUDE_DIR - include directory
# HANDEYESDK_LIBRARY     - HandEyeSDK.lib path
# HANDEYESDK_FOUND       - system has HandEyeSDK

set(HANDEYESDK_PATHS
    "${CMAKE_SOURCE_DIR}/third_party/HandEyeSDK"
    "$ENV{HANDEYESDK_DIR}"
)

find_path(HANDEYESDK_INCLUDE_DIR
    NAMES HandEye.h
    PATHS ${HANDEYESDK_PATHS}
    PATH_SUFFIXES include
)

find_library(HANDEYESDK_LIBRARY
    NAMES HandEyeSDK
    PATHS ${HANDEYESDK_PATHS}
    PATH_SUFFIXES lib
)

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(HandEyeSDK DEFAULT_MSG HANDEYESDK_INCLUDE_DIR HANDEYESDK_LIBRARY)

if(HandEyeSDK_FOUND)
    add_library(HandEyeSDK::HandEyeSDK UNKNOWN IMPORTED)
    set_target_properties(HandEyeSDK::HandEyeSDK PROPERTIES
        IMPORTED_LOCATION "${HANDEYESDK_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${HANDEYESDK_INCLUDE_DIR}"
    )
endif()
