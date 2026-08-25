# Deploy Qt (windeployqt), PCL and VTK runtime DLLs next to a Windows target
# so the executable can be launched directly (double-click / VS debugger)
# without manual PATH setup. Also strips any bundled MSVC runtime DLLs: PCL
# and Qt bundles ship stale msvcp140/vcruntime140 that crash apps built with a
# newer toolset; the system VC redist provides the correct ones.
#
# Expects: PCL_ROOT, optional VTK_DIR and Qt6_DIR (set by find_package).
function(pcsearch_deploy_runtime target)
    if(NOT WIN32)
        return()
    endif()

    if(Qt6_DIR)
        # Qt6_DIR = <qt>/lib/cmake/Qt6 -> <qt>/bin
        get_filename_component(QT_BIN "${Qt6_DIR}/../../../bin" ABSOLUTE)
    else()
        set(QT_BIN "D:/Program Files/Qt/6.8.3/msvc2022_64/bin")
    endif()
    set(PCS_QT_BIN "${QT_BIN}" PARENT_SCOPE)

    find_program(QT_WINDEPLOYQT windeployqt HINTS "${QT_BIN}")
    if(QT_WINDEPLOYQT)
        add_custom_command(TARGET ${target} POST_BUILD
            COMMAND ${QT_WINDEPLOYQT} --release --no-translations
                    --no-compiler-runtime $<TARGET_FILE:${target}>
            COMMENT "Deploying Qt runtime next to ${target}")
    endif()

    set(deploy_dirs
        "${PCL_ROOT}/bin"
        "${PCL_ROOT}/3rdParty/Boost/lib"
        "${PCL_ROOT}/3rdParty/FLANN/bin"
        "${PCL_ROOT}/3rdParty/Qhull/bin")
    if(VTK_DIR)
        get_filename_component(VTK_BIN "${VTK_DIR}/../../../bin" ABSOLUTE)
        list(APPEND deploy_dirs "${VTK_BIN}")
        set(PCS_VTK_BIN "${VTK_BIN}" PARENT_SCOPE)
    endif()
    foreach(dir IN LISTS deploy_dirs)
        if(EXISTS "${dir}")
            add_custom_command(TARGET ${target} POST_BUILD
                COMMAND ${CMAKE_COMMAND} -E copy_directory "${dir}"
                        $<TARGET_FILE_DIR:${target}>
                COMMENT "Copying runtime DLLs from ${dir}")
        endif()
    endforeach()

    add_custom_command(TARGET ${target} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E rm -f
            $<TARGET_FILE_DIR:${target}>/concrt140.dll
            $<TARGET_FILE_DIR:${target}>/msvcp140.dll
            $<TARGET_FILE_DIR:${target}>/msvcp140_1.dll
            $<TARGET_FILE_DIR:${target}>/msvcp140_2.dll
            $<TARGET_FILE_DIR:${target}>/msvcp140_atomic_wait.dll
            $<TARGET_FILE_DIR:${target}>/msvcp140_codecvt_ids.dll
            $<TARGET_FILE_DIR:${target}>/vcruntime140.dll
            $<TARGET_FILE_DIR:${target}>/vcruntime140_1.dll
        COMMENT "Removing bundled MSVC runtime (system VC redist provides it)")
endfunction()
