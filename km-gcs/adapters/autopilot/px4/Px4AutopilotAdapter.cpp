#include <algorithm>

#include "adapters/autopilot/IAutopilotAdapter.hpp"

namespace kmgcs::adapters {
namespace {

// MAV_CMD values used here. Spelled out rather than included from the generated
// MAVLink headers, because this layer is forbidden from linking them: a product
// adapter must be compilable against any transport that can carry the command.
constexpr std::uint16_t kCmdComponentArmDisarm = 400;
constexpr std::uint16_t kCmdNavTakeoff = 22;
constexpr std::uint16_t kCmdNavLand = 21;
constexpr std::uint16_t kCmdNavReturnToLaunch = 20;
constexpr std::uint16_t kCmdDoSetMode = 176;
constexpr std::uint16_t kCmdDoSetStandardMode = 262;

constexpr float kModeFlagCustomEnabled = 1.0F;  // MAV_MODE_FLAG_CUSTOM_MODE_ENABLED

/// PX4 packs main mode and sub mode into the upper bytes of custom_mode.
struct Px4Mode {
    std::uint8_t main;
    std::uint8_t sub;
    domain::StandardMode standard;
    const char* name;
};

// PX4's main modes. This table exists only for firmware too old to answer
// AVAILABLE_MODES; anything that enumerates supersedes it.
constexpr Px4Mode kPx4Modes[] = {
    {1, 0, domain::StandardMode::NonStandard,  "Manual"},
    {2, 0, domain::StandardMode::AltitudeHold, "Altitude"},
    {3, 0, domain::StandardMode::PositionHold, "Position"},
    {4, 1, domain::StandardMode::Mission,      "Ready"},
    {4, 2, domain::StandardMode::Takeoff,      "Takeoff"},
    {4, 3, domain::StandardMode::PositionHold, "Hold"},
    {4, 4, domain::StandardMode::Mission,      "Mission"},
    {4, 5, domain::StandardMode::SafeRecovery, "Return"},
    {4, 6, domain::StandardMode::Land,         "Land"},
    {4, 8, domain::StandardMode::Orbit,        "Follow target"},
    {4, 10, domain::StandardMode::Orbit,       "Orbit"},
    {5, 0, domain::StandardMode::NonStandard,  "Acro"},
    {6, 0, domain::StandardMode::NonStandard,  "Offboard"},
    {7, 0, domain::StandardMode::NonStandard,  "Stabilized"},
    {8, 0, domain::StandardMode::NonStandard,  "Rattitude"},
};

std::uint8_t mainModeOf(std::uint32_t custom) {
    return static_cast<std::uint8_t>((custom >> 16) & 0xFF);
}
std::uint8_t subModeOf(std::uint32_t custom) {
    return static_cast<std::uint8_t>((custom >> 24) & 0xFF);
}

class Px4AutopilotAdapter final : public IAutopilotAdapter {
public:
    [[nodiscard]] std::string name() const override { return "PX4"; }
    [[nodiscard]] domain::AutopilotKind kind() const override {
        return domain::AutopilotKind::Px4;
    }

    [[nodiscard]] bool handles(const domain::ProductType& product) const override {
        // PX4 mode encoding is uniform across frame types, so unlike ArduPilot
        // one adapter really does cover every frame.
        return product.autopilot == domain::AutopilotKind::Px4;
    }

    [[nodiscard]] CommandSpec specFor(const domain::VehicleCommand& command,
                                      const domain::ProductType&) const override {
        CommandSpec spec;
        switch (command.kind) {
            case domain::CommandKind::Arm:
                spec.commandId = kCmdComponentArmDisarm;
                spec.params[0] = 1.0F;
                // 21196 is the documented force magic value; without it the
                // vehicle applies its own preflight checks, which is what we
                // want unless the operator explicitly overrode them.
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
                spec.commandId = kCmdDoSetMode;
                spec.params[0] = kModeFlagCustomEnabled;
                if (command.mode) {
                    spec.params[1] = static_cast<float>(mainModeOf(command.mode->vendorCode));
                    spec.params[2] = static_cast<float>(subModeOf(command.mode->vendorCode));
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
        std::uint32_t vendorCode, const domain::ProductType&) const override {
        const auto main = mainModeOf(vendorCode);
        const auto sub = subModeOf(vendorCode);
        for (const auto& entry : kPx4Modes) {
            if (entry.main != main) {
                continue;
            }
            // Auto modes (main 4) are distinguished by sub mode; every other
            // main mode ignores it.
            if (main == 4 && entry.sub != sub) {
                continue;
            }
            domain::FlightMode mode;
            mode.name = entry.name;
            mode.standard = entry.standard;
            mode.vendorCode = vendorCode;
            mode.source = domain::ModeSource::VendorTable;
            return mode;
        }
        return std::nullopt;
    }

    [[nodiscard]] std::vector<domain::AvailableMode> knownModes(
        const domain::ProductType&) const override {
        std::vector<domain::AvailableMode> modes;
        modes.reserve(std::size(kPx4Modes));
        for (const auto& entry : kPx4Modes) {
            domain::AvailableMode mode;
            mode.vendorCode = (static_cast<std::uint32_t>(entry.main) << 16) |
                              (static_cast<std::uint32_t>(entry.sub) << 24);
            mode.standard = entry.standard;
            mode.name = entry.name;
            modes.push_back(mode);
        }
        return modes;
    }
};

}  // namespace

std::shared_ptr<IAutopilotAdapter> makePx4Adapter() {
    return std::make_shared<Px4AutopilotAdapter>();
}

void AutopilotAdapterRegistry::add(std::shared_ptr<IAutopilotAdapter> adapter) {
    adapters_.push_back(std::move(adapter));
}

std::shared_ptr<IAutopilotAdapter> AutopilotAdapterRegistry::find(
    const domain::ProductType& product) const {
    for (const auto& adapter : adapters_) {
        if (adapter->handles(product)) {
            return adapter;
        }
    }
    return nullptr;
}

}  // namespace kmgcs::adapters
