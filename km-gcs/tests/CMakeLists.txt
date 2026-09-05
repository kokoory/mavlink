# A tiny assertion header rather than a framework dependency. The point of the
# first slice is to prove the architecture, and pulling in GoogleTest before the
# first line of domain code works would be the wrong order.
add_library(kmgcs_testing INTERFACE)
target_include_directories(kmgcs_testing INTERFACE ${CMAKE_CURRENT_SOURCE_DIR})

function(kmgcs_add_test name)
    add_executable(${name} ${ARGN})
    target_link_libraries(${name} PRIVATE kmgcs_testing kmgcs_warnings)
    add_test(NAME ${name} COMMAND ${name})
endfunction()

kmgcs_add_test(test_domain unit/test_domain.cpp)
target_link_libraries(test_domain PRIVATE kmgcs_domain)

kmgcs_add_test(test_event_bus unit/test_event_bus.cpp)
target_link_libraries(test_event_bus PRIVATE kmgcs_event)

kmgcs_add_test(test_registry unit/test_registry.cpp)
target_link_libraries(test_registry PRIVATE kmgcs_core)

kmgcs_add_test(test_adapters unit/test_adapters.cpp)
target_link_libraries(test_adapters PRIVATE kmgcs_autopilot)

kmgcs_add_test(test_pipeline integration/test_pipeline.cpp)
target_link_libraries(test_pipeline PRIVATE kmgcs_composition)
# The fake vehicle packs real frames, so this one test sees the generated
# headers. Everything else in the tree is checked for exactly that leaking.
kmgcs_mavlink_headers(test_pipeline)
