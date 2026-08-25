add_library(pcsearch_pipeline
    src/params.cpp
    src/node.cpp
    src/registry.cpp
    src/graph.cpp
    src/json.cpp
    src/solution.cpp
    src/nodes/core_nodes.cpp)
target_include_directories(pcsearch_pipeline PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_link_libraries(pcsearch_pipeline
    PUBLIC pcsearch_core_data
    PRIVATE pcsearch_io pcsearch_filters pcsearch_segmentation pcsearch_clustering)
