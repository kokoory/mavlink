#include <sstream>

#include "Check.hpp"
#include "core/app/GcsCore.hpp"
#include "core/event/DomainEvents.hpp"

using namespace kmgcs;

namespace {
domain::ProductType px4Quad() {
    domain::ProductType product;
    product.autopilot = domain::AutopilotKind::Px4;
    product.frame = domain::FrameKind::Quadrotor;
    return product;
}
}  // namespace

KM_TEST(telemetry_before_a_heartbeat_creates_nothing) {
    // Product type decides how the rest of the stream is read, so a vehicle
    // must not be created from a message that does not carry it.
    event::EventBus bus;
    core::VehicleRegistry registry(bus);
    const auto handle = registry.resolve(domain::SystemAddress{1, 1},
                                         domain::ProductType{}, domain::now());
    KM_CHECK(!handle.valid());
    KM_CHECK_EQ(registry.size(), std::size_t{0});
}

KM_TEST(a_heartbeat_discovers_a_vehicle_once) {
    event::EventBus bus;
    core::VehicleRegistry registry(bus);
    int discoveries = 0;
    bus.subscribe<event::VehicleDiscovered>(
        [&](const event::VehicleDiscovered&) { ++discoveries; });

    const auto first = registry.resolve(domain::SystemAddress{1, 1}, px4Quad(),
                                        domain::now());
    const auto second = registry.resolve(domain::SystemAddress{1, 1}, px4Quad(),
                                         domain::now());
    bus.drain();
    KM_CHECK(first.valid());
    KM_CHECK(first == second);
    KM_CHECK_EQ(discoveries, 1);
    KM_CHECK_EQ(registry.size(), std::size_t{1});
}

KM_TEST(two_system_ids_are_two_vehicles) {
    event::EventBus bus;
    core::VehicleRegistry registry(bus);
    const auto a = registry.resolve(domain::SystemAddress{1, 1}, px4Quad(), domain::now());
    const auto b = registry.resolve(domain::SystemAddress{2, 1}, px4Quad(), domain::now());
    KM_CHECK(a != b);
    KM_CHECK_EQ(registry.size(), std::size_t{2});
}

KM_TEST(a_silent_vehicle_expires) {
    event::EventBus bus;
    core::RegistryConfig config;
    config.heartbeatTimeout = std::chrono::milliseconds(100);
    core::VehicleRegistry registry(bus, config);

    const auto start = domain::now();
    registry.resolve(domain::SystemAddress{1, 1}, px4Quad(), start);
    bus.drain();

    KM_CHECK_EQ(registry.expire(start + std::chrono::milliseconds(50)), std::size_t{0});
    KM_CHECK_EQ(registry.expire(start + std::chrono::milliseconds(500)), std::size_t{1});
    KM_CHECK_EQ(registry.size(), std::size_t{0});
}

KM_TEST(hardware_identity_arrives_late_without_disturbing_the_handle) {
    event::EventBus bus;
    core::VehicleRegistry registry(bus);
    const auto handle = registry.resolve(domain::SystemAddress{1, 1}, px4Quad(),
                                         domain::now());
    domain::HardwareId hardware;
    hardware.uid2Hex = "deadbeef";
    registry.enrich(handle, hardware);

    const auto identity = registry.identity(handle);
    KM_CHECK(identity.has_value());
    KM_CHECK(identity->handle == handle);
    KM_CHECK(identity->hardware.known());
}

KM_TEST(store_merges_battery_from_two_sources) {
    // SYS_STATUS and BATTERY_STATUS each report part of the picture; neither
    // may erase what the other supplied.
    core::VehicleStateStore store;
    const domain::VehicleHandle vehicle{1};

    event::BatteryUpdated fromSysStatus;
    fromSysStatus.vehicle = vehicle;
    fromSysStatus.battery.voltageV = 22.2;
    store.apply(fromSysStatus);

    event::BatteryUpdated fromBatteryStatus;
    fromBatteryStatus.vehicle = vehicle;
    fromBatteryStatus.battery.temperatureC = 31.5;
    store.apply(fromBatteryStatus);

    const auto snapshot = store.snapshot(vehicle);
    KM_CHECK(snapshot.has_value());
    KM_CHECK(snapshot->battery.voltageV.has_value());
    KM_CHECK_NEAR(*snapshot->battery.voltageV, 22.2, 1e-9);
    KM_CHECK(snapshot->battery.temperatureC.has_value());
}

KM_TEST(enumerated_mode_names_backfill_the_current_mode) {
    // A heartbeat knows the number but not the name; AVAILABLE_MODES knows the
    // name. The store must end up with both.
    core::VehicleStateStore store;
    const domain::VehicleHandle vehicle{1};

    event::FlightModeChanged fromHeartbeat;
    fromHeartbeat.vehicle = vehicle;
    fromHeartbeat.mode.vendorCode = 5;
    store.apply(fromHeartbeat);
    KM_CHECK(!store.snapshot(vehicle)->mode.known());

    event::AvailableModesUpdated modes;
    modes.vehicle = vehicle;
    modes.modes.push_back({5, domain::StandardMode::PositionHold, "Loiter", false, true});
    modes.complete = true;
    store.apply(modes);

    const auto snapshot = store.snapshot(vehicle);
    KM_CHECK(snapshot->mode.known());
    KM_CHECK_EQ(snapshot->mode.name, std::string("Loiter"));
    KM_CHECK(snapshot->mode.source == domain::ModeSource::Enumerated);
}

KM_TEST(a_later_heartbeat_does_not_erase_a_known_mode_name) {
    core::VehicleStateStore store;
    const domain::VehicleHandle vehicle{1};

    event::AvailableModesUpdated modes;
    modes.vehicle = vehicle;
    modes.modes.push_back({5, domain::StandardMode::PositionHold, "Loiter", false, true});
    store.apply(modes);

    event::FlightModeChanged heartbeat;
    heartbeat.vehicle = vehicle;
    heartbeat.mode.vendorCode = 5;  // same mode, no name
    store.apply(heartbeat);

    KM_CHECK_EQ(store.snapshot(vehicle)->mode.name, std::string("Loiter"));
}

KM_MAIN("registry and store")
