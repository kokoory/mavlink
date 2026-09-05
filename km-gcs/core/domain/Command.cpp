#include "Command.hpp"

namespace kmgcs::domain {

const char* toString(CommandStage stage) {
    switch (stage) {
        case CommandStage::Pending:    return "pending";
        case CommandStage::InProgress: return "in progress";
        case CommandStage::Accepted:   return "accepted";
        case CommandStage::Confirmed:  return "confirmed";
        case CommandStage::Rejected:   return "rejected";
        case CommandStage::Failed:     return "failed";
        case CommandStage::TimedOut:   return "timed out";
        case CommandStage::Superseded: return "superseded";
    }
    return "unknown";
}

const char* toString(CommandKind kind) {
    switch (kind) {
        case CommandKind::Arm:             return "arm";
        case CommandKind::Disarm:          return "disarm";
        case CommandKind::Takeoff:         return "takeoff";
        case CommandKind::Land:            return "land";
        case CommandKind::ReturnToLaunch:  return "return to launch";
        case CommandKind::SetFlightMode:   return "set flight mode";
        case CommandKind::SetStandardMode: return "set standard mode";
    }
    return "unknown";
}

CommandPolicy defaultPolicyFor(const VehicleCommand& command) {
    CommandPolicy policy;
    switch (command.kind) {
        case CommandKind::Arm:
            // An ACCEPTED arm does not mean the vehicle is armed; the heartbeat
            // does. This is the single most important confirmation in the set.
            policy.confirmTimeout = std::chrono::seconds(5);
            policy.confirmed = [](const VehicleSnapshot& s) { return s.armed.armed; };
            break;
        case CommandKind::Disarm:
            policy.confirmTimeout = std::chrono::seconds(5);
            policy.confirmed = [](const VehicleSnapshot& s) { return !s.armed.armed; };
            break;
        case CommandKind::Takeoff:
            // Climbing to altitude takes as long as it takes; confirmation is
            // arming plus leaving the ground, not reaching the target.
            policy.confirmTimeout = std::chrono::seconds(30);
            policy.confirmed = [](const VehicleSnapshot& s) { return s.armed.armed; };
            break;
        case CommandKind::Land:
        case CommandKind::ReturnToLaunch:
            policy.confirmTimeout = std::chrono::seconds(15);
            // No single state change proves it started, and waiting for touchdown
            // would block for minutes. Accepted is the honest terminal state.
            break;
        case CommandKind::SetFlightMode: {
            const auto wanted = command.mode;
            policy.confirmTimeout = std::chrono::seconds(5);
            policy.confirmed = [wanted](const VehicleSnapshot& s) {
                return wanted && s.mode.vendorCode == wanted->vendorCode;
            };
            break;
        }
        case CommandKind::SetStandardMode: {
            const auto wanted = command.standard;
            policy.confirmTimeout = std::chrono::seconds(5);
            policy.confirmed = [wanted](const VehicleSnapshot& s) {
                return wanted && s.mode.standard == *wanted;
            };
            break;
        }
    }
    return policy;
}

}  // namespace kmgcs::domain
