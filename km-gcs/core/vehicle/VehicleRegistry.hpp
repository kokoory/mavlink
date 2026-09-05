// Vehicle discovery and lifetime.
//
// The registry is the only writer of identity. Handles are minted here, never
// derived from the wire, so renumbering a vehicle mid-session changes its
// address without invalidating every reference to it. See ADR 0002.

#pragma once

#include <chrono>
#include <map>
#include <mutex>
#include <optional>
#include <vector>

#include "core/domain/Identity.hpp"
#include "core/domain/Time.hpp"
#include "core/event/EventBus.hpp"

namespace kmgcs::core {

struct RegistryConfig {
    /// A vehicle is declared lost after this long without a heartbeat. One
    /// second is the nominal heartbeat rate, so this tolerates several misses.
    domain::Duration heartbeatTimeout{std::chrono::seconds(5)};
};

class VehicleRegistry {
public:
    explicit VehicleRegistry(event::EventBus& bus, RegistryConfig config = {});

    /// Find or create the vehicle at @p address.
    ///
    /// A vehicle is only created when the product type is known, i.e. from a
    /// heartbeat. Telemetry arriving before the first heartbeat returns an
    /// invalid handle rather than creating a half-identified vehicle whose
    /// stream cannot be interpreted correctly.
    domain::VehicleHandle resolve(const domain::SystemAddress& address,
                                  const domain::ProductType& product,
                                  domain::TimePoint at);

    /// Attach hardware identity once the vehicle reports it.
    void enrich(domain::VehicleHandle vehicle, const domain::HardwareId& hardware);

    /// Publish VehicleLost for anything silent past the timeout.
    std::size_t expire(domain::TimePoint now);

    [[nodiscard]] std::optional<domain::VehicleIdentity> identity(
        domain::VehicleHandle vehicle) const;
    [[nodiscard]] std::vector<domain::VehicleIdentity> all() const;
    [[nodiscard]] std::size_t size() const;

private:
    struct Entry {
        domain::VehicleIdentity identity;
        domain::TimePoint lastHeartbeat{};
    };

    event::EventBus& bus_;
    RegistryConfig config_;
    mutable std::mutex mutex_;
    std::map<domain::SystemAddress, domain::VehicleHandle> byAddress_;
    std::map<domain::VehicleHandle, Entry> entries_;
    std::uint64_t nextHandle_{1};
};

}  // namespace kmgcs::core
