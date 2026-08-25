add_executable(test_filters test_filters.cpp)
target_link_libraries(test_filters PRIVATE pcsearch_filters)
add_test(NAME filters COMMAND test_filters)

