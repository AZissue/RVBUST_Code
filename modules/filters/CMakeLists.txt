add_library(pcsearch_filters
    src/filters.cpp)
target_include_directories(pcsearch_filters PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_link_libraries(pcsearch_filters
    PUBLIC pcsearch_core_data)

