add_library(pcsearch_clustering
    src/clustering.cpp)
target_include_directories(pcsearch_clustering PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_link_libraries(pcsearch_clustering
    PUBLIC pcsearch_core_data
    PRIVATE ${PCL_LIBRARIES})

