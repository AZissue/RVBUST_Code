add_library(pcsearch_core_data
    INTERFACE)
target_include_directories(pcsearch_core_data INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_link_libraries(pcsearch_core_data INTERFACE Eigen3::Eigen)

