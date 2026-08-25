add_library(pcsearch_segmentation
    src/plane_detector.cpp)
target_include_directories(pcsearch_segmentation PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_link_libraries(pcsearch_segmentation
    PUBLIC pcsearch_core_data
    PRIVATE ${PCL_LIBRARIES})

