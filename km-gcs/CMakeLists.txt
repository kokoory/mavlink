cmake_minimum_required(VERSION 3.22)
project(km-gcs VERSION 0.1.0 LANGUAGES CXX)

# KM-GCS builds standalone. It happens to live inside a MAVLink definitions
# repository, but nothing here is pulled into that repository's build: the root
# CMakeLists.txt installs MAVLink headers and never calls add_subdirectory.
#
# The MAVLink definitions it consumes are addressed through one variable, so
# moving this tree into its own repository later means changing that variable
# and adding a submodule, not rewriting the build.
set(KMGCS_MAVLINK_REPO "${CMAKE_CURRENT_SOURCE_DIR}/.."
    CACHE PATH "Root of the MAVLink definitions repository")
set(KMGCS_MAVLINK_DEFINITIONS "${KMGCS_MAVLINK_REPO}/message_definitions/v1.0"
    CACHE PATH "Directory holding the MAVLink dialect XML")
set(KMGCS_MAVSTUDIO "${KMGCS_MAVLINK_REPO}/tools"
    CACHE PATH "Directory containing the mavstudio Python package")

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
include(KmGcsLayering)
include(KmGcsMavlink)

option(KMGCS_BUILD_TESTS "Build the test suite" ON)
option(KMGCS_BUILD_UI "Build the Qt/QML user interface" AUTO)
option(KMGCS_WERROR "Treat warnings as errors" ON)

add_library(kmgcs_warnings INTERFACE)
target_compile_options(kmgcs_warnings INTERFACE
    -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wsign-conversion
    -Wnon-virtual-dtor -Wold-style-cast -Woverloaded-virtual)
if(KMGCS_WERROR)
    target_compile_options(kmgcs_warnings INTERFACE -Werror)
endif()

# ---------------------------------------------------------------------------
# Layer 1: domain. Pure C++. No Qt, no MAVLink, no I/O.
# ---------------------------------------------------------------------------
add_library(kmgcs_domain
    core/domain/Time.cpp
    core/domain/VehicleState.cpp
    core/domain/Command.cpp)
target_include_directories(kmgcs_domain PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(kmgcs_domain PRIVATE kmgcs_warnings)
kmgcs_core_layer(kmgcs_domain)

# ---------------------------------------------------------------------------
# Layer 2: events.
# ---------------------------------------------------------------------------
add_library(kmgcs_event core/event/EventBus.cpp)
target_include_directories(kmgcs_event PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(kmgcs_event PUBLIC kmgcs_domain PRIVATE kmgcs_warnings)
kmgcs_core_layer(kmgcs_event)

# ---------------------------------------------------------------------------
# Layer 3: links. Transport only; a link never knows what a frame is.
#
# The architecture document specified QUdpSocket here. Plain sockets keep Qt out
# of everything below the UI, which makes the whole core testable headlessly and
# turns principle P2 into something the build can check.
# ---------------------------------------------------------------------------
add_library(kmgcs_link
    links/common/Link.cpp
    links/udp/UdpLink.cpp)
target_include_directories(kmgcs_link PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(kmgcs_link PUBLIC kmgcs_domain kmgcs_event
                                 PRIVATE kmgcs_warnings)
kmgcs_core_layer(kmgcs_link)

# ---------------------------------------------------------------------------
# Layer 4: protocol. Framing and parsing. Knows MAVLink, knows nothing about PX4.
# ---------------------------------------------------------------------------
add_library(kmgcs_mavlink
    protocols/mavlink/MavlinkProtocolAdapter.cpp
    protocols/mavlink/MavlinkTranslator.cpp)
target_include_directories(kmgcs_mavlink PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(kmgcs_mavlink PUBLIC kmgcs_domain kmgcs_event kmgcs_link
                                    PRIVATE kmgcs_warnings)
kmgcs_mavlink_headers(kmgcs_mavlink)
# Deliberately not kmgcs_core_layer(): this is the layer that is allowed to
# know MAVLink. It is still forbidden from knowing PX4 or Qt.
kmgcs_forbid_link(kmgcs_mavlink FROM kmgcs_px4 kmgcs_ardupilot kmgcs_ui
                                     Qt6::Core Qt6::Quick)

# ---------------------------------------------------------------------------
# Layer 5: product adapters. Know PX4/ArduPilot semantics, not sockets.
# ---------------------------------------------------------------------------
add_library(kmgcs_autopilot
    adapters/autopilot/px4/Px4AutopilotAdapter.cpp
    adapters/autopilot/ardupilot/ArduPilotAdapter.cpp)
target_include_directories(kmgcs_autopilot PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(kmgcs_autopilot PUBLIC kmgcs_domain PRIVATE kmgcs_warnings)
kmgcs_forbid_link(kmgcs_autopilot FROM kmgcs_link kmgcs_ui Qt6::Core Qt6::Quick)

# ---------------------------------------------------------------------------
# Layer 6: core services.
# ---------------------------------------------------------------------------
add_library(kmgcs_core
    core/vehicle/VehicleStateStore.cpp
    core/vehicle/VehicleRegistry.cpp
    core/app/GcsCore.cpp)
target_include_directories(kmgcs_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(kmgcs_core
    PUBLIC kmgcs_domain kmgcs_event kmgcs_autopilot
    PRIVATE kmgcs_warnings)
kmgcs_core_layer(kmgcs_core)

# The composition root is the one place allowed to see every layer at once.
add_library(kmgcs_composition core/app/Composition.cpp)
target_include_directories(kmgcs_composition PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(kmgcs_composition
    PUBLIC kmgcs_core kmgcs_link kmgcs_mavlink kmgcs_autopilot
    PRIVATE kmgcs_warnings)

# ---------------------------------------------------------------------------
# Headless demo: proves the whole receive path without a UI.
# ---------------------------------------------------------------------------
add_executable(km-gcs-headless apps/headless/main.cpp)
target_link_libraries(km-gcs-headless PRIVATE kmgcs_composition kmgcs_warnings)

# ---------------------------------------------------------------------------
# UI, only when Qt is present. Everything above builds without it.
# ---------------------------------------------------------------------------
if(KMGCS_BUILD_UI)
    find_package(Qt6 6.4 COMPONENTS Core Gui Quick QUIET)
    if(Qt6_FOUND)
        message(STATUS "km-gcs: Qt6 ${Qt6_VERSION} found, building the UI")
        add_subdirectory(ui)
    else()
        message(STATUS "km-gcs: Qt6 not found, skipping the UI "
                       "(core, links, protocol and tests still build)")
    endif()
endif()

if(KMGCS_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()

message(STATUS "km-gcs: MAVLink definitions from ${KMGCS_MAVLINK_DEFINITIONS}")
