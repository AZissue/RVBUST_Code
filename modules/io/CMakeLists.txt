add_library(pcsearch_io
    src/point_cloud_io.cpp)
target_include_directories(pcsearch_io PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_link_libraries(pcsearch_io
    PUBLIC pcsearch_core_data)

