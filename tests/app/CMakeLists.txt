set(CMAKE_AUTOMOC ON)

find_package(Qt6 6.5 QUIET COMPONENTS Widgets Test)
if(NOT Qt6_FOUND OR NOT Qt6Test_FOUND)
    message(WARNING "Qt6 Test not found; canvas interaction tests skipped")
    return()
endif()

add_executable(test_node_flow test_node_flow.cpp
    ../../app/src/node_flow_widget.cpp
    ../../app/src/node_titles.cpp
    ../../app/src/params_panel.cpp)
target_include_directories(test_node_flow PRIVATE ../../app/src)
target_link_libraries(test_node_flow PRIVATE
    pcsearch_pipeline
    Qt6::Widgets
    Qt6::Test)

if(WIN32)
    # Deploy Qt/PCL runtime next to the test exe so it can be launched and
    # debugged directly (double-click / VS) without PATH setup.
    include("${CMAKE_CURRENT_SOURCE_DIR}/../../cmake/deploy_runtime.cmake")
    pcsearch_deploy_runtime(test_node_flow)
endif()

if(WIN32)
    # Direct CreateProcess from ctest hangs on this machine while the loader
    # resolves PCL DLLs (all threads blocked in ALPC); a cmake -P wrapper
    # spawns the test through execute_process instead, which works reliably.
    set(NODE_FLOW_RUNNER "${CMAKE_CURRENT_BINARY_DIR}/run_node_flow.cmake")
    file(GENERATE OUTPUT "${NODE_FLOW_RUNNER}"
        CONTENT "set(ENV{PATH} \"${PCL_RUNTIME_DIRS};D:/Program Files/Qt/6.8.3/msvc2022_64/bin;\$ENV{PATH}\")\nif(NOT DEFINED EXE)\n  message(FATAL_ERROR \"EXE not set\")\nendif()\nexecute_process(COMMAND \"\${EXE}\" RESULT_VARIABLE r)\nif(NOT r EQUAL 0)\n  message(FATAL_ERROR \"test_node_flow failed with \${r}\")\nendif()\n")
    add_test(NAME node_flow
        COMMAND ${CMAKE_COMMAND} -DEXE=$<TARGET_FILE:test_node_flow>
                -P "${NODE_FLOW_RUNNER}")
else()
    add_test(NAME node_flow COMMAND test_node_flow)
endif()

if(WIN32)
    set_tests_properties(node_flow PROPERTIES
        ENVIRONMENT "PATH=${PCL_RUNTIME_DIRS};D:/Program Files/Qt/6.8.3/msvc2022_64/bin;$ENV{PATH}")
endif()
