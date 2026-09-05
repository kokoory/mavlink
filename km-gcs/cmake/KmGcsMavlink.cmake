# MAVLink header generation.
#
# The headers KM-GCS compiles against are generated from the mavstudio profile,
# not checked in. That is the point of the whole exercise: the message set the
# ground station speaks is decided by the interface profile, so turning a
# capability off in the profile removes it from the GCS build too, and the two
# cannot drift.
#
# Falls back to generating from the base dialect when no profile build exists,
# so a fresh clone still configures.

function(kmgcs_mavlink_headers target)
    set(_generated "${CMAKE_BINARY_DIR}/mavlink_generated")
    set(_stamp "${_generated}/.stamp")

    # Which dialect to generate from. A profile build is preferred; it is the
    # pruned image that matches what the vehicle is actually built with.
    file(GLOB _profile_dialects
         "${KMGCS_MAVLINK_REPO}/build/mavstudio/*_*.xml")
    if(_profile_dialects)
        list(GET _profile_dialects 0 _dialect)
        set(_source "mavstudio profile build")
    else()
        set(_dialect "${KMGCS_MAVLINK_DEFINITIONS}/my_uav.xml")
        if(NOT EXISTS "${_dialect}")
            set(_dialect "${KMGCS_MAVLINK_DEFINITIONS}/common.xml")
        endif()
        set(_source "dialect XML directly")
    endif()

    if(NOT EXISTS "${_dialect}")
        message(FATAL_ERROR
            "km-gcs: no MAVLink dialect found.\n"
            "  Looked for a mavstudio profile build under\n"
            "    ${KMGCS_MAVLINK_REPO}/build/mavstudio/\n"
            "  and for ${KMGCS_MAVLINK_DEFINITIONS}/common.xml\n"
            "  Set -DKMGCS_MAVLINK_REPO=<path to the mavlink repository>.")
    endif()

    get_filename_component(_dialect_name "${_dialect}" NAME_WE)
    message(STATUS "km-gcs: MAVLink headers from ${_dialect_name}.xml (${_source})")

    find_package(Python3 COMPONENTS Interpreter REQUIRED)

    # Generation happens once per build tree, however many targets consume the
    # headers.
    if(TARGET kmgcs_mavlink_generate)
        add_dependencies(${target} kmgcs_mavlink_generate)
        # SYSTEM: generated third-party headers do not compile clean under our
        # warning set, and relaxing our own warnings to accommodate them would
        # be the wrong trade.
        target_include_directories(${target} SYSTEM PRIVATE
            "${_generated}" "${_generated}/${_dialect_name}")
        target_compile_definitions(${target} PRIVATE
            KMGCS_MAVLINK_DIALECT_HEADER="${_dialect_name}/mavlink.h"
            MAVLINK_USE_MESSAGE_INFO=0)
        return()
    endif()

    # mavgen lives in three different places depending on how pymavlink was
    # installed; mavstudio already solved that, so ask it rather than guessing.
    add_custom_command(
        OUTPUT "${_stamp}"
        COMMAND ${CMAKE_COMMAND} -E make_directory "${_generated}"
        COMMAND ${CMAKE_COMMAND} -E env
                "PYTHONPATH=${KMGCS_MAVSTUDIO}"
                ${Python3_EXECUTABLE} -c
                "import sys; from mavstudio.build import generate_sources; ok, out = generate_sources(sys.argv[1], 'C', sys.argv[2]); print(out); sys.exit(0 if ok else 1)"
                "${_dialect}" "${_generated}"
        COMMAND ${CMAKE_COMMAND} -E touch "${_stamp}"
        DEPENDS "${_dialect}"
        COMMENT "Generating MAVLink C headers from ${_dialect_name}.xml"
        VERBATIM)

    add_custom_target(kmgcs_mavlink_generate DEPENDS "${_stamp}")
    add_dependencies(${target} kmgcs_mavlink_generate)

    target_include_directories(${target} SYSTEM PRIVATE
        "${_generated}"
        "${_generated}/${_dialect_name}")
    target_compile_definitions(${target} PRIVATE
        KMGCS_MAVLINK_DIALECT_HEADER="${_dialect_name}/mavlink.h"
        MAVLINK_USE_MESSAGE_INFO=0)

    set(KMGCS_MAVLINK_GENERATED_DIR "${_generated}" PARENT_SCOPE)
    set(KMGCS_MAVLINK_DIALECT_NAME "${_dialect_name}" PARENT_SCOPE)
endfunction()
