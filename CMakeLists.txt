cmake_minimum_required(VERSION 3.20)
project(HandEyeCalibrationTool VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

# UTF-8 source encoding for Chinese string literals
if(MSVC)
    add_compile_options("/utf-8")
endif()

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")

# ── Qt5 ──
find_package(Qt5 REQUIRED COMPONENTS Widgets Core Gui Concurrent Network)

# ── RVC X2 SDK ──
find_package(RVC REQUIRED)

# ── HandEyeSDK ──
find_package(HandEyeSDK REQUIRED)

# ── RVBUST Vis (optional for Phase 2) ──
find_package(RVBUSTVis QUIET)
if(RVBUSTVis_FOUND)
    message(STATUS "RVBUST Vis found — 3D visualization enabled")
else()
    message(STATUS "RVBUST Vis not found — 3D view stays as placeholder")
endif()

add_subdirectory(src)

# ── Unit tests (Qt Test + test_data regression) ──
enable_testing()
add_subdirectory(tests)
