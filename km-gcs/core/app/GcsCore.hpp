// Core orchestration.
//
// Owns the registry, the state store and the event subscriptions that keep them
// in step. Deliberately knows nothing about links or protocols: those are wired
// in by the composition root, which is the only place allowed to see every
// layer at once.

#pragma once

#include <memory>

#include "adapters/autopilot/IAutopilotAdapter.hpp"
#include "core/event/EventBus.hpp"
#include "core/vehicle/VehicleRegistry.hpp"
#include "core/vehicle/VehicleStateStore.hpp"

namespace kmgcs::core {

class GcsCore {
public:
    explicit GcsCore(event::EventBus& bus, RegistryConfig config = {});

    [[nodiscard]] VehicleRegistry& registry() { return registry_; }
    [[nodiscard]] VehicleStateStore& store() { return store_; }
    [[nodiscard]] adapters::AutopilotAdapterRegistry& adapters() { return adapters_; }

    /// Run one iteration: deliver queued events, then expire silent vehicles.
    std::size_t step(domain::TimePoint now, std::size_t eventBudget = 0);

private:
    void wireSubscriptions();
    /// Fill in a mode name from the product adapter when the vehicle did not
    /// enumerate its own modes.
    void nameModeIfPossible(domain::VehicleHandle vehicle);

    event::EventBus& bus_;
    VehicleRegistry registry_;
    VehicleStateStore store_;
    adapters::AutopilotAdapterRegistry adapters_;
};

}  // namespace kmgcs::core
