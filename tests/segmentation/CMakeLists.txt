add_executable(test_plane_detector test_plane_detector.cpp)
target_link_libraries(test_plane_detector
    PRIVATE pcsearch_segmentation)
add_test(NAME plane_detector COMMAND test_plane_detector)

if(WIN32)
    set_tests_properties(plane_detector PROPERTIES
        ENVIRONMENT "PATH=${PCL_RUNTIME_DIRS};$ENV{PATH}")
endif()
