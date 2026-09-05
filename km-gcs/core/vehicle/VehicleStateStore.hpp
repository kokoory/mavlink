// Latest canonical state per vehicle.
//
// Single-writer by design: only the core thread mutates. Readers get an
// immutable snapshot, which is what lets a UI refresh at 20 Hz while telemetry
// arrives at 200 Hz without any locking on the read path being visible to them.

#pragma once

#include <map>
#include <mutex>
#include <optional>
#include <vector>

#include "core/domain/VehicleState.hpp"
#include "core/event/DomainEvents.hpp"

namespace kmgcs::core {

class VehicleStateStore {
public:
    void applyIdentity(const domain::VehicleIdentity& identity);
    void apply(const event::VehicleAttitudeUpdated& update);
    void apply(const event::VehiclePositionUpdated& update);
    void apply(const event::GnssUpdated& update);
    void apply(const event::BatteryUpdated& update);
    void apply(const event::FlightModeChanged& update);
    void apply(const event::AvailableModesUpdated& update);
    void apply(const event::TimeBaseUpdated& update);
    void apply(const event::LinkQualityUpdated& update);
    void apply(const event::FaultRaised& fault);

    void noteHeard(domain::VehicleHandle vehicle, domain::TimePoint at);
    void remove(domain::VehicleHandle vehicle);

    [[nodiscard]] std::optional<domain::VehicleSnapshot> snapshot(
        domain::VehicleHandle vehicle) const;
    [[nodiscard]] std::vector<domain::VehicleSnapshot> snapshots() const;
    [[nodiscard]] std::size_t size() const;

private:
    domain::VehicleSnapshot& mutableFor(domain::VehicleHandle vehicle);

    mutable std::mutex mutex_;
    std::map<domain::VehicleHandle, domain::VehicleSnapshot> vehicles_;
};

}  // namespace kmgcs::core
