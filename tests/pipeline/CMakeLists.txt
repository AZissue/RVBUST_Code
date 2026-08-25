add_executable(test_pipeline test_pipeline.cpp)
target_link_libraries(test_pipeline
    PRIVATE pcsearch_pipeline pcsearch_io)
add_test(NAME pipeline COMMAND test_pipeline)

if(WIN32)
    set_tests_properties(pipeline PROPERTIES
        ENVIRONMENT "PATH=${PCL_RUNTIME_DIRS};$ENV{PATH}")
endif()

