add_executable(test_io test_io.cpp)
target_link_libraries(test_io PRIVATE pcsearch_io)
add_test(NAME io_roundtrip COMMAND test_io)

