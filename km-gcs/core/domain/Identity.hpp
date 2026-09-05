// Vehicle identity.
//
// The architecture document carried two incompatible definitions: section 6
// lists Identity as {VehicleUuid, SystemAddress, ProductType}, while the code
// sketch in section 20 reduces it to a bare 16-byte UUID and the MVP plan keys
// vehicles by sysid. Those cannot all be right, because MAVLink does not hand
// out UUIDs: a heartbeat carries a one-byte system id that is reused across
// power cycles and reassigned by the operator, and the only durable hardware
// identifier (AUTOPILOT_VERSION.uid2) arrives later and only if asked for.
//
// So identity is three separate things with three different lifetimes:
//
//   VehicleHandle  stable for as long as this GCS process (and its recordings)
//                  refers to the vehicle. Minted locally on discovery. Never
//                  derived from anything on the wire, so it cannot change under
//                  us when the operator renumbers a vehicle mid-flight.
//   SystemAddress  the routing key: which (system, component) to address.
//                  Changes if the vehicle is renumbered.
//   HardwareId     the durable identity, when the vehicle tells us. Optional,
//                  arrives late, used to recognise a vehicle across sessions.
//
// See docs/architecture/adr/0002-vehicle-identity.md

#pragma once

#include <cstdint>
#include <optional>
#include <string>

namespace kmgcs::domain {

/// Locally minted, process-stable reference to a vehicle.
class VehicleHandle {
public:
    VehicleHandle() = default;
    explicit VehicleHandle(std::uint64_t value) : value_(value) {}

    [[nodiscard]] std::uint64_t value() const { return value_; }
    [[nodiscard]] bool valid() const { return value_ != 0; }

    friend bool operator==(VehicleHandle a, VehicleHandle b) { return a.value_ == b.value_; }
    friend bool operator!=(VehicleHandle a, VehicleHandle b) { return !(a == b); }
    friend bool operator<(VehicleHandle a, VehicleHandle b) { return a.value_ < b.value_; }

private:
    std::uint64_t value_{0};
};

/// Where to send: the routing key. Not an identity -- it can be reassigned.
struct SystemAddress {
    std::uint8_t system{0};
    std::uint8_t component{0};

    friend bool operator==(SystemAddress a, SystemAddress b) {
        return a.system == b.system && a.component == b.component;
    }
    friend bool operator!=(SystemAddress a, SystemAddress b) { return !(a == b); }
    friend bool operator<(SystemAddress a, SystemAddress b) {
        return a.system != b.system ? a.system < b.system : a.component < b.component;
    }
};

/// Durable hardware identity, when the vehicle reports one. Optional by nature.
struct HardwareId {
    std::uint64_t uid{0};
    std::string uid2Hex;  ///< empty when the vehicle only reported the legacy uid

    [[nodiscard]] bool known() const { return uid != 0 || !uid2Hex.empty(); }
};

/// What kind of vehicle this is. Both halves matter: flight-mode meaning
/// depends on the pair, not on the autopilot alone.
enum class AutopilotKind { Unknown, Px4, ArduPilot, Generic, Other };

enum class FrameKind {
    Unknown, FixedWing, Quadrotor, Hexarotor, Octorotor, Coaxial, Helicopter,
    Vtol, GroundRover, SurfaceBoat, Submarine, Antenna, Other,
};

struct ProductType {
    AutopilotKind autopilot{AutopilotKind::Unknown};
    FrameKind frame{FrameKind::Unknown};
    /// Raw wire values, kept so an adapter can reason about types we have no
    /// enumerator for without the core having to grow one.
    std::uint8_t rawAutopilot{0};
    std::uint8_t rawType{0};
};

struct VehicleIdentity {
    VehicleHandle handle;
    SystemAddress address;
    ProductType product;
    HardwareId hardware;
    std::string displayName;  ///< operator-facing; falls back to "Vehicle N"
};

}  // namespace kmgcs::domain
