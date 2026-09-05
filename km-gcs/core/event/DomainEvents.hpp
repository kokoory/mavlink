// Core domain events.
//
// These are plain structs, not variant alternatives, so a plugin can add its
// own without recompiling the core. The set below is what the core itself
// publishes and consumes.

#pragma once

#include <string>
#include <vector>

#include "core/domain/Command.hpp"
#include "core/domain/Identity.hpp"
#include "core/domain/Time.hpp"
#include "core/domain/VehicleState.hpp"

namespace kmgcs::event {

using domain::AvailableMode;
using domain::CommandHandle;
using domain::CommandOutcome;
using domain::SystemAddress;
using domain::TimePoint;
using domain::VehicleHandle;

struct VehicleDiscovered {
    VehicleHandle vehicle;
    SystemAddress address;
    domain::ProductType product;
    TimePoint at{};
};

struct VehicleLost {
    VehicleHandle vehicle;
    domain::Duration silentFor{};
    TimePoint at{};
};

struct VehicleAttitudeUpdated {
    VehicleHandle vehicle;
    domain::AttitudeState attitude;
};

struct VehiclePositionUpdated {
    VehicleHandle vehicle;
    domain::PositionState position;
    domain::VelocityState velocity;
};

struct GnssUpdated {
    VehicleHandle vehicle;
    domain::GnssState gnss;
};

struct BatteryUpdated {
    VehicleHandle vehicle;
    domain::BatteryState battery;
};

struct FlightModeChanged {
    VehicleHandle vehicle;
    domain::FlightMode mode;
    domain::ArmedState armed;
};

/// Emitted when the vehicle enumerates its own modes. The presence of this
/// event is what lets the UI offer modes no adapter has a table for.
struct AvailableModesUpdated {
    VehicleHandle vehicle;
    std::vector<AvailableMode> modes;
    bool complete{false};  ///< false while the list is still arriving
};

struct CommandProgressed {
    CommandHandle handle;
    CommandOutcome outcome;
};

struct LinkQualityUpdated {
    VehicleHandle vehicle;
    domain::LinkQuality quality;
};

struct TimeBaseUpdated {
    VehicleHandle vehicle;
    domain::TimeQuality quality;
    domain::Duration offset{};
    domain::Duration roundTrip{};
};

struct FaultRaised {
    VehicleHandle vehicle;
    domain::HealthLevel level{domain::HealthLevel::Error};
    std::string source;
    std::string detail;
    TimePoint at{};
};

/// A frame arrived that the protocol layer could not parse. Kept as an event
/// rather than a silent counter so that link health and conformance can both
/// observe it.
struct ProtocolParseFailed {
    std::string protocol;
    std::string reason;
    std::size_t bytes{0};
    TimePoint at{};
};

}  // namespace kmgcs::event
