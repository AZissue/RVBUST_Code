# Find RVBUST Vis C++ SDK + all transitive dependencies (Vis.lib is a static library)
#
# RVBUSTVIS_FOUND        — all required components found
# RVBUSTVis::Vis         — imported target with all transitive link deps
#
# All third-party files are under ${CMAKE_SOURCE_DIR}/third_party/:
#   third_party/Vis/    — Vis.h + Vis.lib + externals (fmt, spdlog, libgizmo)
#   third_party/OSG/    — OSG 3.6.5 (include, lib, bin)

set(VIS_ROOT "${CMAKE_SOURCE_DIR}/third_party/Vis")
set(OSG_ROOT "${CMAKE_SOURCE_DIR}/third_party/OSG")

# ── Vis header ──
find_path(RVBUSTVIS_INCLUDE_DIR
    NAMES Vis/Vis.h
    PATHS "${VIS_ROOT}/include"
    NO_DEFAULT_PATH
)

# ── Vis library ──
find_library(RVBUSTVIS_LIBRARY
    NAMES Vis
    PATHS "${VIS_ROOT}/lib"
    NO_DEFAULT_PATH
)

# ── OSG headers ──
find_path(OSG_INCLUDE_DIR
    NAMES osg/Node
    PATHS "${OSG_ROOT}/include"
    NO_DEFAULT_PATH
)

# ── OSG libraries ──
set(OSG_LIBS)
foreach(_lib osg osgViewer osgGA osgText osgDB osgUtil osgFX OpenThreads)
    find_library(OSG_${_lib}_LIBRARY
        NAMES ${_lib}
        PATHS "${OSG_ROOT}/lib"
        NO_DEFAULT_PATH
    )
    if(OSG_${_lib}_LIBRARY)
        list(APPEND OSG_LIBS "${OSG_${_lib}_LIBRARY}")
    endif()
endforeach()

# ── RVBUST_Vis externals (fmt, spdlog, libgizmo) — shipped alongside Vis.lib ──
find_library(EXTERN_FMT_LIBRARY
    NAMES fmt
    PATHS "${VIS_ROOT}/lib"
    NO_DEFAULT_PATH
)
find_library(EXTERN_SPDLOG_LIBRARY
    NAMES spdlog
    PATHS "${VIS_ROOT}/lib"
    NO_DEFAULT_PATH
)
find_library(EXTERN_LIBGIZMO_LIBRARY
    NAMES libgizmo
    PATHS "${VIS_ROOT}/lib"
    NO_DEFAULT_PATH
)

# ── Validation ──
include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(RVBUSTVis
    DEFAULT_MSG
    RVBUSTVIS_INCLUDE_DIR
    RVBUSTVIS_LIBRARY
    OSG_INCLUDE_DIR
    OSG_osg_LIBRARY
    OSG_osgViewer_LIBRARY
    EXTERN_FMT_LIBRARY
    EXTERN_LIBGIZMO_LIBRARY
)

if(NOT RVBUSTVis_FOUND)
    return()
endif()

# ── Create imported target with ALL transitive dependencies ──
add_library(RVBUSTVis::Vis UNKNOWN IMPORTED)

set(_vis_transitive_libs
    ${OSG_LIBS}
    "${EXTERN_FMT_LIBRARY}"
    "${EXTERN_SPDLOG_LIBRARY}"
    "${EXTERN_LIBGIZMO_LIBRARY}"
    opengl32
    winmm
)

set_target_properties(RVBUSTVis::Vis PROPERTIES
    IMPORTED_LOCATION               "${RVBUSTVIS_LIBRARY}"
    INTERFACE_INCLUDE_DIRECTORIES   "${RVBUSTVIS_INCLUDE_DIR};${OSG_INCLUDE_DIR}"
    INTERFACE_COMPILE_DEFINITIONS   "HAS_RVBUST_VIS"
    INTERFACE_LINK_LIBRARIES        "${_vis_transitive_libs}"
)
