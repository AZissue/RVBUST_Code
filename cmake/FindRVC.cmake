# FindRVC.cmake — 定位 RVC SDK v1.15（RVBUST RVC 3D 相机 SDK）
#
# 导出：
#   RVC::RVC                 — 导入目标（include + RVC.lib）
#   rvc_copy_runtime_dlls()  — 函数：POST_BUILD 拷贝 runtime/*.dll 到目标输出目录
#
# 可用 -DRVC_SDK_ROOT=<路径> 覆盖默认安装位置。

if(NOT DEFINED RVC_SDK_ROOT)
    set(RVC_SDK_ROOT "D:/Program Files/RVBUST/RVC/RVCSDK" CACHE PATH "RVC SDK root directory")
endif()

find_path(RVC_INCLUDE_DIR
    NAMES RVC/RVC.h
    HINTS "${RVC_SDK_ROOT}/include"
    NO_DEFAULT_PATH)

find_library(RVC_LIBRARY
    NAMES RVC
    HINTS "${RVC_SDK_ROOT}/lib"
    NO_DEFAULT_PATH)

set(RVC_RUNTIME_DIR "${RVC_SDK_ROOT}/runtime")

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(RVC
    REQUIRED_VARS RVC_LIBRARY RVC_INCLUDE_DIR
    FAIL_MESSAGE "RVC SDK not found. Set -DRVC_SDK_ROOT=<sdk path>.")

if(RVC_FOUND AND NOT TARGET RVC::RVC)
    add_library(RVC::RVC SHARED IMPORTED GLOBAL)
    set_target_properties(RVC::RVC PROPERTIES
        IMPORTED_IMPLIB "${RVC_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${RVC_INCLUDE_DIR}")
    message(STATUS "RVC SDK Root : ${RVC_SDK_ROOT}")
    message(STATUS "RVC Include  : ${RVC_INCLUDE_DIR}")
    message(STATUS "RVC Library  : ${RVC_LIBRARY}")
    message(STATUS "RVC Runtime  : ${RVC_RUNTIME_DIR}")
endif()

# POST_BUILD 拷贝 RVC runtime 全部 DLL 到目标 exe 目录
function(rvc_copy_runtime_dlls target)
    if(WIN32 AND EXISTS "${RVC_RUNTIME_DIR}")
        file(GLOB _rvc_dlls "${RVC_RUNTIME_DIR}/*.dll")
        if(_rvc_dlls)
            add_custom_command(TARGET ${target} POST_BUILD
                COMMAND ${CMAKE_COMMAND} -E copy_if_different
                    ${_rvc_dlls} "$<TARGET_FILE_DIR:${target}>"
                COMMENT "Copying RVC runtime DLLs"
                VERBATIM)
        endif()
    endif()
endfunction()
