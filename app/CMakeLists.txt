set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

find_package(Qt6 6.5 QUIET COMPONENTS Widgets)
if(NOT Qt6_FOUND)
    message(WARNING "Qt6 not found; desktop application will not be built. "
                    "Set QT_DIR or CMAKE_PREFIX_PATH to a Qt 6 installation.")
    return()
endif()

find_package(VTK 9.4 QUIET COMPONENTS GUISupportQt InteractionStyle InteractionWidgets
    RenderingCore RenderingOpenGL2
    PATHS "D:/Program Files/VTK" NO_DEFAULT_PATH)

add_executable(pcsearch_app
    WIN32
    src/main.cpp
    src/main_window.cpp
    src/node_titles.cpp
    src/engine_runner.cpp
    src/node_flow_widget.cpp
    src/params_panel.cpp
    src/point_cloud_view.cpp
    src/roi_selector.cpp
    src/simple_translator.cpp
    src/themes.cpp
    src/toolbox_widget.cpp
    src/viewport_manager.cpp)
target_include_directories(pcsearch_app PRIVATE src)

target_link_libraries(pcsearch_app PRIVATE
    pcsearch_core_data
    pcsearch_io
    pcsearch_filters
    pcsearch_segmentation
    pcsearch_clustering
    pcsearch_pipeline
    Qt6::Widgets)

if(VTK_FOUND)
    target_compile_definitions(pcsearch_app PRIVATE PCSEARCH_HAS_VTK=1)
    target_link_libraries(pcsearch_app PRIVATE ${VTK_LIBRARIES})
endif()

if(WIN32)
    # Runtime DLLs are deployed next to the exe (see below); the VS debugger
    # environment additionally points at Qt/VTK so F5 works from any state.
    include("${CMAKE_CURRENT_SOURCE_DIR}/../cmake/deploy_runtime.cmake")
    pcsearch_deploy_runtime(pcsearch_app)
    set(PCS_DEBUG_PATH "${PCL_RUNTIME_DIRS}")
    if(PCS_QT_BIN)
        list(APPEND PCS_DEBUG_PATH "${PCS_QT_BIN}")
    endif()
    if(PCS_VTK_BIN)
        list(APPEND PCS_DEBUG_PATH "${PCS_VTK_BIN}")
    endif()
    string(JOIN ";" PCS_DEBUG_PATH ${PCS_DEBUG_PATH})
    set_target_properties(pcsearch_app PROPERTIES
        VS_DEBUGGER_ENVIRONMENT "PATH=${PCS_DEBUG_PATH};$(PATH)")
endif()
