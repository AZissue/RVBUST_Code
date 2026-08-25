cmake_minimum_required(VERSION 3.24)

project(PointCloudSearch
    VERSION 0.1.0
    DESCRIPTION "Modular point cloud search / analysis toolkit with node-based GUI and C++ SDK"
    LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(MSVC)
    # Sources are UTF-8 (including Chinese UI strings); MSVC defaults to the
    # system codepage (GBK on zh-CN) which breaks string literals.
    add_compile_options(/utf-8)
endif()
set(BUILD_SHARED_LIBS OFF CACHE BOOL "Build pcsearch modules as shared libraries" FORCE)

if(NOT DEFINED PCL_ROOT)
    set(PCL_ROOT "D:/Program Files/PCL 1.13.0")
endif()
list(APPEND CMAKE_PREFIX_PATH "${PCL_ROOT}")

find_package(PCL 1.13 REQUIRED
    COMPONENTS common kdtree search sample_consensus filters segmentation)

if(WIN32)
    set(PCL_RUNTIME_DIRS
        "${PCL_ROOT}/bin;${PCL_ROOT}/3rdParty/Boost/lib;${PCL_ROOT}/3rdParty/FLANN/bin;${PCL_ROOT}/3rdParty/Qhull/bin;${PCL_ROOT}/3rdParty/VTK/bin")
endif()

# PCL all-in-one bundles Eigen; expose it as an imported target.
add_library(pcsearch_eigen INTERFACE)
target_include_directories(pcsearch_eigen INTERFACE
    "${PCL_ROOT}/3rdParty/Eigen/eigen3")
add_library(Eigen3::Eigen ALIAS pcsearch_eigen)

enable_testing()

add_subdirectory(modules/core_data)
add_subdirectory(modules/io)
add_subdirectory(modules/filters)
add_subdirectory(modules/clustering)
add_subdirectory(modules/pipeline)
add_subdirectory(modules/segmentation)
add_subdirectory(tests/io)
add_subdirectory(tests/filters)
add_subdirectory(tests/clustering)
add_subdirectory(tests/pipeline)
add_subdirectory(tests/segmentation)

option(PCSEARCH_BUILD_APP "Build the Qt/VTK desktop application" ON)
if(PCSEARCH_BUILD_APP)
    if(EXISTS "D:/Program Files/Qt/6.8.3/msvc2022_64")
        list(APPEND CMAKE_PREFIX_PATH "D:/Program Files/Qt/6.8.3/msvc2022_64")
    endif()
    add_subdirectory(app)
    add_subdirectory(tests/app)
endif()

add_subdirectory(tools/pcinfo)
