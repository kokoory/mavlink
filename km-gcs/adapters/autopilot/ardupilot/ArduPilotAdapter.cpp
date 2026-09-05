#include <algorithm>

#include "adapters/autopilot/IAutopilotAdapter.hpp"

namespace kmgcs::adapters {
namespace {

constexpr std::uint16_t kCmdComponentArmDisarm = 400;
constexpr std::uint16_t kCmdNavTakeoff = 22;
constexpr std::uint16_t kCmdNavLand = 21;
constexpr std::uint16_t kCmdNavReturnToLaunch = 20;
constexpr std::uint16_t kCmdDoSetMode = 176;
constexpr std::uint16_t kCmdDoSetStandardMode = 262;

constexpr float kModeFlagCustomEnabled = 1.0F;

struct ModeEntry {
    std::uint32_t code;
    domain::StandardMode standard;
    const char* name;
};

// ArduPilot's custom_mode means different things per vehicle type, which is
// precisely why the adapter is chosen by (autopilot, frame) rather than by
// autopilot alone. These are the modes an operator actually reaches for; the
// full sets are 26/26/14/11/7 entries and a vehicle that answers
// AVAILABLE_MODES supersedes all of them anyway.
constexpr ModeEntry kCopterModes[] = {
    {0, domain::StandardMode::NonStandard,  "Stabilize"},
    {1, domain::StandardMode::NonStandard,  "Acro"},
    {2, domain::StandardMode::AltitudeHold, "AltHold"},
    {3, domain::StandardMode::Mission,      "Auto"},
    {4, domain::StandardMode::Orbit,        "Guided"},
    {5, domain::StandardMode::PositionHold, "Loiter"},
    {6, domain::StandardMode::SafeRecovery, "RTL"},
    {7, domain::StandardMode::NonStandard,  "Circle"},
    {9, domain::StandardMode::Land,         "Land"},
    {16, domain::StandardMode::PositionHold, "PosHold"},
    {17, domain::StandardMode::NonStandard, "Brake"},
    {20, domain::StandardMode::NonStandard, "Guided_NoGPS"},
    {21, domain::StandardMode::NonStandard, "Smart_RTL"},
};

constexpr ModeEntry kPlaneModes[] = {
    {0, domain::StandardMode::NonStandard,  "Manual"},
    {1, domain::StandardMode::NonStandard,  "Circle"},
    {2, domain::StandardMode::NonStandard,  "Stabilize"},
    {5, domain::StandardMode::AltitudeHold, "FBWA"},
    {6, domain::StandardMode::Cruise,       "FBWB"},
    {7, domain::StandardMode::Cruise,       "Cruise"},
    {10, domain::StandardMode::Mission,     "Auto"},
    {11, domain::StandardMode::SafeRecovery, "RTL"},
    {12, domain::StandardMode::PositionHold, "Loiter"},
    {15, domain::StandardMode::Orbit,       "Guided"},
    {17, domain::StandardMode::Takeoff,     "Takeoff"},
    {19, domain::StandardMode::Takeoff,     "QLoiter"},
    {20, domain::StandardMode::Land,        "QLand"},
};

constexpr ModeEntry kRoverModes[] = {
    {0, domain::StandardMode::NonStandard,  "Manual"},
    {3, domain::StandardMode::NonStandard,  "Steering"},
    {4, domain::StandardMode::PositionHold, "Hold"},
    {5, domain::StandardMode::PositionHold, "Loiter"},
    {10, domain::StandardMode::Mission,     "Auto"},
    {11, domain::StandardMode::SafeRecovery, "RTL"},
    {15, domain::StandardMode::Orbit,       "Guided"},
};

struct ModeTable {
    const ModeEntry* entries;
    std::size_t count;
};

ModeTable tableFor(const domain::ProductType& product) {
    switch (product.frame) {
        case domain::FrameKind::FixedWing:
        case domain::FrameKind::Vtol:
            return {kPlaneModes, std::size(kPlaneModes)};
        case domain::FrameKind::GroundRover:
        case domain::FrameKind::SurfaceBoat:
            return {kRoverModes, std::size(kRoverModes)};
        case domain::FrameKind::Quadrotor:
        case domain::FrameKind::Hexarotor:
        case domain::FrameKind::Octorotor:
        case domain::FrameKind::Coaxial:
        case domain::FrameKind::Helicopter:
            return {kCopterModes, std::size(kCopterModes)};
        default:
            // Frame unknown: no table can be right, so offer none rather than
            // labelling a Plane mode with a Copter name.
            return {nullptr, 0};
    }
}

class ArduPilotAdapter final : public IAutopilotAdapter {
public:
    [[nodiscard]] std::string name() const override { return "ArduPilot"; }
    [[nodiscard]] domain::AutopilotKind kind() const override {
        return domain::AutopilotKind::ArduPilot;
    }

    [[nodiscard]] bool handles(const domain::ProductType& product) const override {
        return product.autopilot == domain::AutopilotKind::ArduPilot;
    }

    [[nodiscard]] CommandSpec specFor(const domain::VehicleCommand& command,
                                      const domain::ProductType&) const override {
        CommandSpec spec;
        switch (command.kind) {
            case domain::CommandKind::Arm:
                spec.commandId = kCmdComponentArmDisarm;
                spec.params[0] = 1.0F;
                spec.params[1] = command.force ? 21196.0F : 0.0F;
                break;
            case domain::CommandKind::Disarm:
                spec.commandId = kCmdComponentArmDisarm;
                spec.params[0] = 0.0F;
                spec.params[1] = command.force ? 21196.0F : 0.0F;
                break;
            case domain::CommandKind::Takeoff:
                spec.commandId = kCmdNavTakeoff;
                spec.params[6] = static_cast<float>(command.altitudeM.value_or(10.0));
                break;
            case domain::CommandKind::Land:
                spec.commandId = kCmdNavLand;
                break;
            case domain::CommandKind::ReturnToLaunch:
                spec.commandId = kCmdNavReturnToLaunch;
                break;
            case domain::CommandKind::SetFlightMode:
                // ArduPilot puts the whole mode number in param2, unlike PX4's
                // packed main/sub encoding. Same MAVLink command, different
                // meaning: exactly the assumption the two-adapter split exists
                // to prevent.
                spec.commandId = kCmdDoSetMode;
                spec.params[0] = kModeFlagCustomEnabled;
                if (command.mode) {
                    spec.params[1] = static_cast<float>(command.mode->vendorCode);
                }
                break;
            case domain::CommandKind::SetStandardMode:
                spec.commandId = kCmdDoSetStandardMode;
                spec.params[0] = static_cast<float>(
                    command.standard ? static_cast<int>(*command.standard) : 0);
                break;
        }
        return spec;
    }

    [[nodiscard]] std::optional<domain::FlightMode> nameMode(
        std::uint32_t vendorCode, const domain::ProductType& product) const override {
        const auto table = tableFor(product);
        for (std::size_t i = 0; i < table.count; ++i) {
            if (table.entries[i].code != vendorCode) {
                continue;
            }
            domain::FlightMode mode;
            mode.name = table.entries[i].name;
            mode.standard = table.entries[i].standard;
            mode.vendorCode = vendorCode;
            mode.source = domain::ModeSource::VendorTable;
            return mode;
        }
        return std::nullopt;
    }

    [[nodiscard]] std::vector<domain::AvailableMode> knownModes(
        const domain::ProductType& product) const override {
        const auto table = tableFor(product);
        std::vector<domain::AvailableMode> modes;
        modes.reserve(table.count);
        for (std::size_t i = 0; i < table.count; ++i) {
            domain::AvailableMode mode;
            mode.vendorCode = table.entries[i].code;
            mode.standard = table.entries[i].standard;
            mode.name = table.entries[i].name;
            modes.push_back(mode);
        }
        return modes;
    }
};

}  // namespace

std::shared_ptr<IAutopilotAdapter> makeArduPilotAdapter() {
    return std::make_shared<ArduPilotAdapter>();
}

}  // namespace kmgcs::adapters
