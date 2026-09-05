// Command model.
//
// The architecture document's send path treats COMMAND_ACK as completion. That
// is not safe, for three separate reasons:
//
//   1. COMMAND_ACK carries no correlation id. It is matched on (command, target),
//      so two in-flight instances of the same command are indistinguishable.
//      Commands therefore have to be serialised per (vehicle, command).
//   2. MAV_RESULT_IN_PROGRESS is an intermediate ack, not a result. Treating it
//      as terminal reports success while the vehicle is still working.
//   3. MAV_RESULT_ACCEPTED means "I will try", not "it happened". An arm command
//      is only really complete once the heartbeat reports SAFETY_ARMED.
//
// So a command has two outcomes, not one: it is Accepted when the vehicle
// acknowledges it, and Confirmed when the state it was supposed to change
// actually changed. This is exactly what the document's "Behavior" conformance
// axis is trying to test, so the model and the test agree by construction.
//
// See docs/architecture/adr/0004-command-lifecycle.md

#pragma once

#include <cstdint>
#include <functional>
#include <optional>
#include <string>

#include "Identity.hpp"
#include "Time.hpp"
#include "VehicleState.hpp"

namespace kmgcs::domain {

enum class CommandKind {
    Arm, Disarm, Takeoff, Land, ReturnToLaunch, SetFlightMode, SetStandardMode,
};

/// Protocol-neutral command. An autopilot adapter turns this into whatever the
/// product actually needs; the core never names a MAVLink command id.
struct VehicleCommand {
    CommandKind kind{CommandKind::Arm};
    std::optional<double> altitudeM;     ///< Takeoff
    std::optional<FlightMode> mode;      ///< SetFlightMode
    std::optional<StandardMode> standard;///< SetStandardMode
    bool force{false};                   ///< bypass vehicle-side preflight checks
};

enum class CommandStage {
    Pending,    ///< sent, nothing back yet
    InProgress, ///< vehicle acknowledged that it is working on it
    Accepted,   ///< vehicle accepted; the effect may not have happened yet
    Confirmed,  ///< the state the command targeted actually changed
    Rejected,   ///< vehicle refused
    Failed,     ///< vehicle tried and failed
    TimedOut,   ///< no response within the command's budget
    Superseded, ///< a newer command for the same target replaced this one
};

/// Why a command ended where it did, in words an operator can act on.
struct CommandOutcome {
    CommandStage stage{CommandStage::Pending};
    std::string detail;
    std::optional<int> vendorResult;  ///< raw MAV_RESULT etc., for logs
    std::optional<int> progressPercent;
    Timestamp stamp;

    [[nodiscard]] bool terminal() const {
        switch (stage) {
            case CommandStage::Confirmed:
            case CommandStage::Rejected:
            case CommandStage::Failed:
            case CommandStage::TimedOut:
            case CommandStage::Superseded:
                return true;
            default:
                return false;
        }
    }

    /// True once the vehicle has agreed to do it. Callers that only need to
    /// know "did the vehicle take the command" stop here; callers that need to
    /// know "did it happen" wait for Confirmed.
    [[nodiscard]] bool acknowledged() const {
        return stage == CommandStage::Accepted || stage == CommandStage::Confirmed;
    }
};

using CommandId = std::uint64_t;

/// Handle returned when a command is issued. Completion is delivered as an
/// event; this is the correlation key and the record of what was asked.
struct CommandHandle {
    CommandId id{0};
    VehicleHandle vehicle;
    CommandKind kind{CommandKind::Arm};
    TimePoint issued{};

    [[nodiscard]] bool valid() const { return id != 0; }
};

/// How long to wait, and what state change proves the command actually landed.
struct CommandPolicy {
    Duration ackTimeout{std::chrono::seconds(3)};
    /// Time allowed between Accepted and Confirmed. Arming is near-instant;
    /// a takeoff to altitude is not, so this is per command, not global.
    Duration confirmTimeout{std::chrono::seconds(10)};
    int maxRetries{2};
    /// When empty, Accepted is treated as final because no observable state
    /// change distinguishes success (e.g. a request for a one-off message).
    std::function<bool(const VehicleSnapshot&)> confirmed;
};

[[nodiscard]] const char* toString(CommandStage stage);
[[nodiscard]] const char* toString(CommandKind kind);

/// Default policies, including what counts as confirmation for each command.
[[nodiscard]] CommandPolicy defaultPolicyFor(const VehicleCommand& command);

}  // namespace kmgcs::domain
