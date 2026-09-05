// Canonical vehicle state.
//
// Every value here is expressed in a frame and unit the core chose, not the one
// the wire happened to use. Adapters convert; the core never guesses.

#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "Identity.hpp"
#include "Time.hpp"

namespace kmgcs::domain {

// ---------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------

struct Vector3 {
    double x{0}, y{0}, z{0};
};

struct Quaternion {
    double w{1}, x{0}, y{0}, z{0};
};

/// Named explicitly on every value so that a NED vector can never be silently
/// consumed as ENU. The document calls for this; making it part of the type
/// rather than a comment is what actually prevents the mistake.
enum class ReferenceFrame {
    Unknown, Wgs84, Ecef, Ned, Enu, BodyFrd, BodyFlu,
};

struct EulerAngles {
    double rollRad{0}, pitchRad{0}, yawRad{0};
};

/// Euler angles are a derived view for display, never the stored form.
[[nodiscard]] EulerAngles toEuler(const Quaternion& q);

// ---------------------------------------------------------------------------
// Kinematics
// ---------------------------------------------------------------------------

struct GlobalPosition {
    double latitudeDeg{0};
    double longitudeDeg{0};
    double altitudeAmslM{0};      ///< above mean sea level
    std::optional<double> altitudeRelativeM;  ///< above home, when known
};

struct AttitudeState {
    Quaternion orientation;
    Vector3 angularVelocityRadS;
    ReferenceFrame bodyFrame{ReferenceFrame::BodyFrd};
    Timestamp stamp;
};

struct PositionState {
    std::optional<GlobalPosition> global;
    std::optional<Vector3> local;          ///< metres in @c localFrame
    ReferenceFrame localFrame{ReferenceFrame::Ned};
    Timestamp stamp;
};

struct VelocityState {
    Vector3 velocityMS;
    ReferenceFrame frame{ReferenceFrame::Ned};
    std::optional<double> groundSpeedMS;
    std::optional<double> airSpeedMS;
    Timestamp stamp;
};

// ---------------------------------------------------------------------------
// Navigation and power
// ---------------------------------------------------------------------------

enum class GnssFix { NoGps, NoFix, Fix2D, Fix3D, Dgps, RtkFloat, RtkFixed, Static, Other };

struct GnssState {
    GnssFix fix{GnssFix::NoGps};
    int satellitesVisible{0};
    std::optional<double> horizontalAccuracyM;
    std::optional<double> verticalAccuracyM;
    std::optional<double> hdop;
    Timestamp stamp;
};

struct BatteryState {
    std::optional<double> voltageV;
    std::optional<double> currentA;
    std::optional<double> remainingFraction;   ///< 0.0 - 1.0, not a percentage
    std::optional<double> consumedMah;
    std::optional<double> temperatureC;
    int id{0};
    Timestamp stamp;
};

// ---------------------------------------------------------------------------
// Flight mode
// ---------------------------------------------------------------------------

/// The subset of modes MAVLink itself standardises (MAV_STANDARD_MODE). Only
/// these can be reasoned about generically; everything else is vendor detail.
enum class StandardMode {
    NonStandard, PositionHold, Orbit, Cruise, AltitudeHold,
    SafeRecovery, Mission, Land, Takeoff,
};

/// Canonical flight mode.
///
/// The document modelled this as "canonical mode + optional vendor detail",
/// which is the right shape but under-estimates the problem: ArduPilot alone
/// defines 84 modes across five vehicle-type enums (COPTER 26, PLANE 26,
/// ROVER 14, SUB 11, TRACKER 7), and their meaning depends on the frame type,
/// not just the autopilot. Two product adapters cannot cover that by table.
///
/// So the vendor name is carried as a string, and the source records where it
/// came from. Modern firmware enumerates its own modes over AVAILABLE_MODES,
/// which is both more accurate and less work than maintaining tables; a vendor
/// table is the fallback for firmware that does not. Crucially, the UI can
/// render and select a mode it has never heard of, which a closed enum forbids.
enum class ModeSource {
    Unknown,
    VendorTable,      ///< adapter recognised the custom_mode value
    Enumerated,       ///< the vehicle told us, via AVAILABLE_MODES
    StandardCommand,  ///< the vehicle reported a MAV_STANDARD_MODE
};

struct FlightMode {
    StandardMode standard{StandardMode::NonStandard};
    std::string name;              ///< operator-facing; never empty once known
    std::uint32_t vendorCode{0};   ///< custom_mode as sent by the vehicle
    ModeSource source{ModeSource::Unknown};

    [[nodiscard]] bool known() const { return !name.empty(); }
    friend bool operator==(const FlightMode& a, const FlightMode& b) {
        return a.vendorCode == b.vendorCode && a.name == b.name;
    }
};

/// One entry of a vehicle's self-reported mode list.
struct AvailableMode {
    std::uint32_t vendorCode{0};
    StandardMode standard{StandardMode::NonStandard};
    std::string name;
    /// MAV_MODE_PROPERTY_ADVANCED: the UI may hide these from basic operators.
    bool advanced{false};
    /// Cleared by MAV_MODE_PROPERTY_NOT_USER_SELECTABLE. The FC may still
    /// enter the mode itself, e.g. as part of a failsafe.
    bool selectable{true};
};

struct ArmedState {
    bool armed{false};
    Timestamp stamp;
};

// ---------------------------------------------------------------------------
// Link and health
// ---------------------------------------------------------------------------

struct LinkQuality {
    std::optional<double> packetLossFraction;
    std::optional<int> rssi;
    double messagesPerSecond{0};
    Timestamp stamp;
};

enum class HealthLevel { Ok, Warning, Error, Critical, Unknown };

struct HealthStatus {
    HealthLevel level{HealthLevel::Unknown};
    std::string summary;
    Timestamp stamp;
};

// ---------------------------------------------------------------------------
// Aggregate
// ---------------------------------------------------------------------------

/// Immutable snapshot handed to readers outside the core thread.
struct VehicleSnapshot {
    VehicleIdentity identity;
    AttitudeState attitude;
    PositionState position;
    VelocityState velocity;
    GnssState gnss;
    BatteryState battery;
    FlightMode mode;
    ArmedState armed;
    LinkQuality link;
    HealthStatus health;
    std::vector<AvailableMode> availableModes;
    TimeQuality timeQuality{TimeQuality::None};
    TimePoint lastHeard{};

    /// How stale the newest telemetry is. The document asks for staleness on
    /// every state; deriving it from one place keeps the answer consistent.
    [[nodiscard]] Duration ageAt(TimePoint reference) const {
        return reference - lastHeard;
    }
};

[[nodiscard]] const char* toString(GnssFix fix);
[[nodiscard]] const char* toString(StandardMode mode);
[[nodiscard]] const char* toString(ReferenceFrame frame);
[[nodiscard]] const char* toString(AutopilotKind kind);

}  // namespace kmgcs::domain
