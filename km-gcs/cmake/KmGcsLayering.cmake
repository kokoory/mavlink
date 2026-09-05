# Layering enforcement.
#
# Design principle P1 says the core must stay protocol-independent, and P2 says
# the core must not know about the UI toolkit. A principle nobody can violate by
# accident is worth far more than a principle written in a document, so both are
# enforced here as build failures rather than review comments.
#
# Two independent checks, because they catch different mistakes:
#
#   kmgcs_forbid_link()   catches a target that links a forbidden library, even
#                         transitively (A links B links mavlink).
#   kmgcs_forbid_symbols() catches a target whose sources mention a forbidden
#                         pattern at all -- copying a mavlink enum value into
#                         the domain by hand does not create a link edge.
#
# Both run at build time, not configure time, so they see the final link graph.

# Recursively collect the link closure of a target into ${out_var}.
function(_kmgcs_link_closure target out_var)
    set(_seen "")
    set(_stack "${target}")
    while(_stack)
        list(POP_FRONT _stack _current)
        if(_current IN_LIST _seen)
            continue()
        endif()
        if(NOT TARGET ${_current})
            continue()
        endif()
        list(APPEND _seen "${_current}")
        get_target_property(_type ${_current} TYPE)
        if(_type STREQUAL "INTERFACE_LIBRARY")
            get_target_property(_deps ${_current} INTERFACE_LINK_LIBRARIES)
        else()
            get_target_property(_deps ${_current} LINK_LIBRARIES)
        endif()
        if(_deps)
            foreach(_dep IN LISTS _deps)
                # Strip generator expressions and namespaces we cannot resolve.
                string(REGEX REPLACE "^\\$<.*:(.*)>$" "\\1" _dep "${_dep}")
                list(APPEND _stack "${_dep}")
            endforeach()
        endif()
    endwhile()
    list(REMOVE_ITEM _seen "${target}")
    set(${out_var} "${_seen}" PARENT_SCOPE)
endfunction()

# kmgcs_forbid_link(<target> FROM <lib>...)
#
# Fails the build if <target> ends up linking any of <lib>, directly or through
# any number of intermediate targets.
function(kmgcs_forbid_link target)
    cmake_parse_arguments(ARG "" "" "FROM" ${ARGN})
    if(NOT ARG_FROM)
        message(FATAL_ERROR "kmgcs_forbid_link(${target}) needs FROM <lib>...")
    endif()
    set_property(TARGET ${target} APPEND PROPERTY KMGCS_FORBIDDEN_LINKS ${ARG_FROM})
    # Deferred to the end of configuration so that targets declared later are
    # still visible in the closure.
    cmake_language(EVAL CODE
        "cmake_language(DEFER DIRECTORY \"${CMAKE_SOURCE_DIR}\" CALL _kmgcs_check_forbidden_link ${target})")
endfunction()

function(_kmgcs_check_forbidden_link target)
    get_target_property(_forbidden ${target} KMGCS_FORBIDDEN_LINKS)
    if(NOT _forbidden)
        return()
    endif()
    _kmgcs_link_closure(${target} _closure)
    set(_violations "")
    foreach(_lib IN LISTS _forbidden)
        if(_lib IN_LIST _closure)
            list(APPEND _violations "${_lib}")
        endif()
    endforeach()
    if(_violations)
        message(FATAL_ERROR
            "LAYERING VIOLATION: target '${target}' links ${_violations}.\n"
            "  Full link closure: ${_closure}\n"
            "  ${target} is below the boundary that owns those libraries. Move the\n"
            "  code, or translate at the adapter boundary instead of linking across it.\n"
            "  See km-gcs/docs/architecture/adr/0001-layering.md")
    endif()
endfunction()

# kmgcs_forbid_symbols(<target> PATTERNS <regex>... [REASON <text>])
#
# Adds a build-time step that greps the target's own sources and fails if any
# pattern appears. Catches leakage that never shows up as a link edge, such as
# a hand-copied MAVLink constant or a stray Qt include.
function(kmgcs_forbid_symbols target)
    cmake_parse_arguments(ARG "" "REASON" "PATTERNS" ${ARGN})
    if(NOT ARG_PATTERNS)
        message(FATAL_ERROR "kmgcs_forbid_symbols(${target}) needs PATTERNS <regex>...")
    endif()
    if(NOT ARG_REASON)
        set(ARG_REASON "forbidden symbols for this layer")
    endif()
    get_target_property(_sources ${target} SOURCES)
    get_target_property(_dir ${target} SOURCE_DIR)

    # Scan the directories the target's sources live in, not just the sources
    # themselves: a violation is at least as likely to be in a header, and
    # headers never appear in SOURCES. Header-only targets have no SOURCES at
    # all, and fall back to the target's own directory.
    set(_dirs "")
    foreach(_source IN LISTS _sources)
        if(IS_ABSOLUTE "${_source}")
            get_filename_component(_parent "${_source}" DIRECTORY)
        else()
            get_filename_component(_parent "${_dir}/${_source}" DIRECTORY)
        endif()
        list(APPEND _dirs "${_parent}")
    endforeach()
    if(NOT _dirs)
        list(APPEND _dirs "${_dir}")
    endif()
    list(REMOVE_DUPLICATES _dirs)

    set(_files "")
    foreach(_scan IN LISTS _dirs)
        file(GLOB_RECURSE _found "${_scan}/*.hpp" "${_scan}/*.h" "${_scan}/*.cpp")
        list(APPEND _files ${_found})
    endforeach()
    list(REMOVE_DUPLICATES _files)
    if(NOT _files)
        return()
    endif()
    # Joined here rather than with $<JOIN:>: a CMake list expands into separate
    # COMMAND arguments before the generator expression is ever evaluated, which
    # silently produces a command that runs but checks nothing.
    list(JOIN _files "|" _fileArgument)
    list(JOIN ARG_PATTERNS "|" _patternArgument)

    add_custom_command(
        TARGET ${target} POST_BUILD
        COMMAND ${CMAKE_COMMAND}
                "-DKMGCS_FILES=${_fileArgument}"
                "-DKMGCS_PATTERNS=${_patternArgument}"
                "-DKMGCS_TARGET=${target}"
                "-DKMGCS_REASON=${ARG_REASON}"
                -P ${CMAKE_CURRENT_FUNCTION_LIST_DIR}/KmGcsGrepGuard.cmake
        COMMENT "Layering check: ${target}"
        VERBATIM)
endfunction()

# Convenience: the standard rule for every target below the UI layer.
function(kmgcs_core_layer target)
    kmgcs_forbid_link(${target} FROM
        kmgcs_mavlink kmgcs_px4 kmgcs_ardupilot kmgcs_ui
        Qt6::Core Qt6::Gui Qt6::Quick Qt6::Qml Qt6::Network)
    kmgcs_forbid_symbols(${target}
        PATTERNS "mavlink_" "MAVLINK_" "_MAV_" "#include <Q" "#include \"Q" "QObject"
        REASON "protocol or Qt leakage below the adapter boundary")
endfunction()
