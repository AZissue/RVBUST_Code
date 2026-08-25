add_executable(test_clustering test_clustering.cpp)
target_link_libraries(test_clustering PRIVATE pcsearch_clustering)
add_test(NAME clustering COMMAND test_clustering)

if(WIN32)
    set_tests_properties(clustering PROPERTIES
        ENVIRONMENT "PATH=${PCL_RUNTIME_DIRS};$ENV{PATH}")
endif()

