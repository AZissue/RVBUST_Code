cmake_minimum_required(VERSION 3.16)
project(he_sdk_probe LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
if(MSVC)
    add_compile_options("/utf-8")
endif()
set(SDK "D:/MyCode/MyHandEyeTools/third_party/HandEyeSDK")
add_executable(he_sdk_probe main.cpp)
target_include_directories(he_sdk_probe PRIVATE ${SDK}/include)
target_link_directories(he_sdk_probe PRIVATE ${SDK}/lib)
target_link_libraries(he_sdk_probe PRIVATE HandEyeSDK)

# 端到端探针：直接用程序自己的 CalibrationService 跑合成数据。
find_package(Qt5 REQUIRED COMPONENTS Core)
set(APP "D:/MyCode/MyHandEyeTools/src")
add_executable(he_app_e2e e2e_main.cpp
    ${APP}/logic/CalibrationService.cpp
    ${APP}/sdk/HandEyeSDKBridge.cpp)
target_include_directories(he_app_e2e PRIVATE ${APP} ${SDK}/include)
target_link_directories(he_app_e2e PRIVATE ${SDK}/lib)
target_link_libraries(he_app_e2e PRIVATE HandEyeSDK Qt5::Core)
