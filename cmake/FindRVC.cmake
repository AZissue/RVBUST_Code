# Find RVC X2 Camera C++ SDK
#
# RVC_INCLUDE_DIR  - include directory
# RVC_LIBRARY      - RVC.lib path
# RVC_FOUND        - system has RVC

set(RVC_PATHS
    "${CMAKE_SOURCE_DIR}/third_party/RVC"
    "D:/Program Files/RVBUST/RVC/RVCSDK"
    "$ENV{RVC_SDK_DIR}"
)

find_path(RVC_INCLUDE_DIR
    NAMES RVC/RVC.h
    PATHS ${RVC_PATHS}
    PATH_SUFFIXES include
)

find_library(RVC_LIBRARY
    NAMES RVC
    PATHS ${RVC_PATHS}
    PATH_SUFFIXES lib
)

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(RVC DEFAULT_MSG RVC_INCLUDE_DIR RVC_LIBRARY)

if(RVC_FOUND)
    add_library(RVC::RVC UNKNOWN IMPORTED)
    set_target_properties(RVC::RVC PROPERTIES
        IMPORTED_LOCATION "${RVC_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${RVC_INCLUDE_DIR}"
    )
endif()
