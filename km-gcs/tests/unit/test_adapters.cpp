#include <sstream>

#include "Check.hpp"
#include "adapters/autopilot/IAutopilotAdapter.hpp"

using namespace kmgcs;
using namespace kmgcs::adapters;

namespace {
domain::ProductType product(domain::AutopilotKind autopilot, domain::FrameKind frame) {
    domain::ProductType p;
    p.autopilot = autopilot;
    p.frame = frame;
    return p;
}
}  // namespace

KM_TEST(registry_picks_the_adapter_for_the_product) {
    AutopilotAdapterRegistry registry;
    registry.add(makePx4Adapter());
    registry.add(makeArduPilotAdapter());

    const auto px4 = registry.find(product(domain::AutopilotKind::Px4,
                                           domain::FrameKind::Quadrotor));
    KM_CHECK(px4 != nullptr);
    KM_CHECK_EQ(px4->name(), std::string("PX4"));

    const auto ardu = registry.find(product(domain::AutopilotKind::ArduPilot,
                                            domain::FrameKind::FixedWing));
    KM_CHECK(ardu != nullptr);
    KM_CHECK_EQ(ardu->name(), std::string("ArduPilot"));

    // An unknown autopilot gets no adapter; telemetry still flows, commands do not.
    KM_CHECK(registry.find(product(domain::AutopilotKind::Other,
                                   domain::FrameKind::Quadrotor)) == nullptr);
}

KM_TEST(the_same_mode_number_means_different_things_per_frame) {
    // This is the whole reason the adapter is chosen by (autopilot, frame).
    // ArduPilot mode 5 is Loiter on a Copter and FBWA on a Plane.
    const auto ardu = makeArduPilotAdapter();
    const auto copter = ardu->nameMode(5, product(domain::AutopilotKind::ArduPilot,
                                                  domain::FrameKind::Quadrotor));
    const auto plane = ardu->nameMode(5, product(domain::AutopilotKind::ArduPilot,
                                                 domain::FrameKind::FixedWing));
    KM_CHECK(copter.has_value());
    KM_CHECK(plane.has_value());
    KM_CHECK_EQ(copter->name, std::string("Loiter"));
    KM_CHECK_EQ(plane->name, std::string("FBWA"));
    KM_CHECK(copter->name != plane->name);
}

KM_TEST(an_unknown_frame_yields_no_mode_name_rather_than_a_wrong_one) {
    const auto ardu = makeArduPilotAdapter();
    const auto unknown = ardu->nameMode(5, product(domain::AutopilotKind::ArduPilot,
                                                   domain::FrameKind::Unknown));
    KM_CHECK(!unknown.has_value());
}

KM_TEST(an_unknown_mode_number_yields_no_name) {
    const auto ardu = makeArduPilotAdapter();
    KM_CHECK(!ardu->nameMode(9999, product(domain::AutopilotKind::ArduPilot,
                                           domain::FrameKind::Quadrotor)).has_value());
}

KM_TEST(px4_packs_main_and_sub_mode_where_ardupilot_does_not) {
    // Same MAVLink command, different parameter meaning. Getting this wrong is
    // what the two-adapter split exists to prevent.
    domain::VehicleCommand setMode;
    setMode.kind = domain::CommandKind::SetFlightMode;
    domain::FlightMode mode;
    mode.vendorCode = (4u << 16) | (4u << 24);  // PX4 auto/mission
    setMode.mode = mode;

    const auto px4Spec = makePx4Adapter()->specFor(
        setMode, product(domain::AutopilotKind::Px4, domain::FrameKind::Quadrotor));
    KM_CHECK_NEAR(px4Spec.params[1], 4.0, 1e-6);   // main mode
    KM_CHECK_NEAR(px4Spec.params[2], 4.0, 1e-6);   // sub mode

    domain::VehicleCommand arduCommand;
    arduCommand.kind = domain::CommandKind::SetFlightMode;
    domain::FlightMode arduMode;
    arduMode.vendorCode = 3;  // Copter Auto
    arduCommand.mode = arduMode;
    const auto arduSpec = makeArduPilotAdapter()->specFor(
        arduCommand, product(domain::AutopilotKind::ArduPilot, domain::FrameKind::Quadrotor));
    KM_CHECK_NEAR(arduSpec.params[1], 3.0, 1e-6);  // whole mode number
    KM_CHECK_NEAR(arduSpec.params[2], 0.0, 1e-6);
}

KM_TEST(arm_uses_the_force_magic_only_when_asked) {
    domain::VehicleCommand arm;
    arm.kind = domain::CommandKind::Arm;
    const auto adapter = makePx4Adapter();
    const auto normal = adapter->specFor(arm, product(domain::AutopilotKind::Px4,
                                                      domain::FrameKind::Quadrotor));
    KM_CHECK_NEAR(normal.params[0], 1.0, 1e-6);
    KM_CHECK_NEAR(normal.params[1], 0.0, 1e-6);

    arm.force = true;
    const auto forced = adapter->specFor(arm, product(domain::AutopilotKind::Px4,
                                                      domain::FrameKind::Quadrotor));
    KM_CHECK_NEAR(forced.params[1], 21196.0, 1e-6);
}

KM_TEST(known_modes_differ_by_frame) {
    const auto ardu = makeArduPilotAdapter();
    const auto copter = ardu->knownModes(product(domain::AutopilotKind::ArduPilot,
                                                 domain::FrameKind::Quadrotor));
    const auto rover = ardu->knownModes(product(domain::AutopilotKind::ArduPilot,
                                                domain::FrameKind::GroundRover));
    KM_CHECK(!copter.empty());
    KM_CHECK(!rover.empty());
    KM_CHECK(copter.size() != rover.size());
}

KM_MAIN("autopilot adapters")
