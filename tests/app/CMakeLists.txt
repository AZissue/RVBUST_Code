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

# MainWindow-level UI test: drives the cloud-properties tree / viewport state
# through the real app wiring. VTK is required to compile point_cloud_view.cpp
# (interactor style class); assertions only inspect Qt tree selection and
# display-layer state, so no GL frame is rendered.
if(EXISTS "D:/RVC_SRC/RvcVisionStudio/third_party/VTK-install/lib/cmake/vtk-9.2")
    set(VTK_DIR "D:/RVC_SRC/RvcVisionStudio/third_party/VTK-install/lib/cmake/vtk-9.2" CACHE PATH "" FORCE)
endif()

find_package(VTK 9.2 COMPONENTS GUISupportQt InteractionStyle InteractionWidgets
    RenderingCore RenderingOpenGL2 QUIET
    PATHS "D:/RVC_SRC/RvcVisionStudio/third_party/VTK-install"
            "D:/Program Files/VTK"
            "D:/Program Files/PCL 1.13.0/3rdParty/VTK"
    NO_DEFAULT_PATH)

if(NOT VTK_FOUND)
    message(WARNING "VTK not found; MainWindow UI tests skipped")
else()
    add_executable(test_main_window
        test_main_window.cpp
        ../../app/src/main_window.cpp
        ../../app/src/engine_runner.cpp
        ../../app/src/node_titles.cpp
        ../../app/src/node_flow_widget.cpp
        ../../app/src/params_panel.cpp
        ../../app/src/point_cloud_view.cpp
        ../../app/src/roi_selector.cpp
        ../../app/src/simple_translator.cpp
        ../../app/src/themes.cpp
        ../../app/src/toolbox_widget.cpp
        ../../app/src/viewport_manager.cpp)
    target_include_directories(test_main_window PRIVATE ../../app/src)
    target_link_libraries(test_main_window PRIVATE
        pcsearch_pipeline
        pcsearch_filters
        Qt6::Widgets
        Qt6::Test
        ${VTK_LIBRARIES})
    target_compile_definitions(test_main_window PRIVATE PCSEARCH_HAS_VTK=1)

    if(WIN32)
        include("${CMAKE_CURRENT_SOURCE_DIR}/../../cmake/deploy_runtime.cmake")
        pcsearch_deploy_runtime(test_main_window)
    endif()

    if(WIN32)
        set(MAIN_WINDOW_RUNNER "${CMAKE_CURRENT_BINARY_DIR}/run_main_window.cmake")
        file(GENERATE OUTPUT "${MAIN_WINDOW_RUNNER}"
            CONTENT "set(ENV{PATH} \"${PCL_RUNTIME_DIRS};D:/Program Files/Qt/6.8.3/msvc2022_64/bin;\$ENV{PATH}\")\nif(NOT DEFINED EXE)\n  message(FATAL_ERROR \"EXE not set\")\nendif()\nexecute_process(COMMAND \"\${EXE}\" RESULT_VARIABLE r)\nif(NOT r EQUAL 0)\n  message(FATAL_ERROR \"test_main_window failed with \${r}\")\nendif()\n")
        add_test(NAME main_window
            COMMAND ${CMAKE_COMMAND} -DEXE=$<TARGET_FILE:test_main_window>
                    -P "${MAIN_WINDOW_RUNNER}")
        set_tests_properties(main_window PROPERTIES
            ENVIRONMENT "PATH=${PCL_RUNTIME_DIRS};D:/Program Files/Qt/6.8.3/msvc2022_64/bin;$ENV{PATH}")
    else()
        add_test(NAME main_window COMMAND test_main_window)
    endif()
endif()
