// Product semantics.
//
// Two adapters are not enough on their own. ArduPilot defines 84 flight modes
// across five vehicle-type enums (COPTER 26, PLANE 26, ROVER 14, SUB 11,
// TRACKER 7) and the meaning of a custom_mode value depends on which of those
// applies. So an adapter is selected by the pair (autopilot, frame), and mode
// naming takes the vehicle's own AVAILABLE_MODES list in preference to any
// table we maintain. See ADR 0006.

#pragma once

#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "core/domain/Command.hpp"
#include "core/domain/Identity.hpp"
#include "core/domain/VehicleState.hpp"

namespace kmgcs::adapters {

/// Protocol-neutral command specification. The protocol adapter turns this into
/// bytes; nothing here names a MAVLink identifier by its C symbol.
struct CommandSpec {
    std::uint16_t commandId{0};
    float params[7]{};
    bool supported{true};
    std::string unsupportedReason;
};

class IAutopilotAdapter {
public:
    virtual ~IAutopilotAdapter() = default;

    [[nodiscard]] virtual std::string name() const = 0;
    [[nodiscard]] virtual domain::AutopilotKind kind() const = 0;

    /// Can this adapter speak for that product? Frame type is part of the
    /// question, not an afterthought.
    [[nodiscard]] virtual bool handles(const domain::ProductType& product) const = 0;

    [[nodiscard]] virtual CommandSpec specFor(const domain::VehicleCommand& command,
                                              const domain::ProductType& product) const = 0;

    /// Name a mode from the vendor code, when the vehicle has not enumerated
    /// its own modes. Returns nullopt when the adapter has no table entry, and
    /// the mode is then shown by its numeric code rather than a wrong name.
    [[nodiscard]] virtual std::optional<domain::FlightMode> nameMode(
        std::uint32_t vendorCode, const domain::ProductType& product) const = 0;

    /// Modes the adapter knows about, for vehicles that cannot enumerate.
    [[nodiscard]] virtual std::vector<domain::AvailableMode> knownModes(
        const domain::ProductType& product) const = 0;
};

/// Picks the adapter for a product, or nullptr when nothing matches. A vehicle
/// with no adapter still flies telemetry; it just cannot be commanded by name.
class AutopilotAdapterRegistry {
public:
    void add(std::shared_ptr<IAutopilotAdapter> adapter);
    [[nodiscard]] std::shared_ptr<IAutopilotAdapter> find(
        const domain::ProductType& product) const;
    [[nodiscard]] std::size_t size() const { return adapters_.size(); }

private:
    std::vector<std::shared_ptr<IAutopilotAdapter>> adapters_;
};

std::shared_ptr<IAutopilotAdapter> makePx4Adapter();
std::shared_ptr<IAutopilotAdapter> makeArduPilotAdapter();

}  // namespace kmgcs::adapters
