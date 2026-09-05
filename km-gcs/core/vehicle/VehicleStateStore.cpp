#include "VehicleStateStore.hpp"

namespace kmgcs::core {

domain::VehicleSnapshot& VehicleStateStore::mutableFor(domain::VehicleHandle vehicle) {
    auto& snapshot = vehicles_[vehicle];
    snapshot.identity.handle = vehicle;
    return snapshot;
}

void VehicleStateStore::applyIdentity(const domain::VehicleIdentity& identity) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto& snapshot = mutableFor(identity.handle);
    // Merge rather than replace: hardware identity arrives long after discovery
    // and must not wipe the display name, and vice versa.
    snapshot.identity.address = identity.address;
    if (identity.product.autopilot != domain::AutopilotKind::Unknown) {
        snapshot.identity.product = identity.product;
    }
    if (identity.hardware.known()) {
        snapshot.identity.hardware = identity.hardware;
    }
    if (!identity.displayName.empty()) {
        snapshot.identity.displayName = identity.displayName;
    }
}

void VehicleStateStore::apply(const event::VehicleAttitudeUpdated& update) {
    std::lock_guard<std::mutex> lock(mutex_);
    mutableFor(update.vehicle).attitude = update.attitude;
}

void VehicleStateStore::apply(const event::VehiclePositionUpdated& update) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto& snapshot = mutableFor(update.vehicle);
    snapshot.position = update.position;
    snapshot.velocity = update.velocity;
}

void VehicleStateStore::apply(const event::GnssUpdated& update) {
    std::lock_guard<std::mutex> lock(mutex_);
    mutableFor(update.vehicle).gnss = update.gnss;
}

void VehicleStateStore::apply(const event::BatteryUpdated& update) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto& battery = mutableFor(update.vehicle).battery;
    // SYS_STATUS and BATTERY_STATUS both report power, each with gaps. Merging
    // field by field keeps whichever source actually had the value.
    if (update.battery.voltageV)          battery.voltageV = update.battery.voltageV;
    if (update.battery.currentA)          battery.currentA = update.battery.currentA;
    if (update.battery.remainingFraction) battery.remainingFraction = update.battery.remainingFraction;
    if (update.battery.consumedMah)       battery.consumedMah = update.battery.consumedMah;
    if (update.battery.temperatureC)      battery.temperatureC = update.battery.temperatureC;
    battery.id = update.battery.id;
    battery.stamp = update.battery.stamp;
}

void VehicleStateStore::apply(const event::FlightModeChanged& update) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto& snapshot = mutableFor(update.vehicle);
    if (update.armed.stamp.value.time_since_epoch().count() != 0) {
        snapshot.armed = update.armed;
    }
    // A heartbeat knows the vendor code but not the name; CURRENT_MODE and
    // AVAILABLE_MODES know the name. Never let the poorer source erase a name
    // we already have for the same mode.
    if (update.mode.known() || snapshot.mode.vendorCode != update.mode.vendorCode) {
        if (!update.mode.known() && !snapshot.availableModes.empty()) {
            for (const auto& available : snapshot.availableModes) {
                if (available.vendorCode == update.mode.vendorCode) {
                    snapshot.mode = update.mode;
                    snapshot.mode.name = available.name;
                    snapshot.mode.standard = available.standard;
                    snapshot.mode.source = domain::ModeSource::Enumerated;
                    return;
                }
            }
        }
        snapshot.mode = update.mode;
    }
}

void VehicleStateStore::apply(const event::AvailableModesUpdated& update) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto& snapshot = mutableFor(update.vehicle);
    snapshot.availableModes = update.modes;
    // Backfill the current mode's name now that the vehicle has told us.
    for (const auto& available : snapshot.availableModes) {
        if (available.vendorCode == snapshot.mode.vendorCode) {
            snapshot.mode.name = available.name;
            snapshot.mode.standard = available.standard;
            snapshot.mode.source = domain::ModeSource::Enumerated;
            break;
        }
    }
}

void VehicleStateStore::apply(const event::TimeBaseUpdated& update) {
    std::lock_guard<std::mutex> lock(mutex_);
    mutableFor(update.vehicle).timeQuality = update.quality;
}

void VehicleStateStore::apply(const event::LinkQualityUpdated& update) {
    std::lock_guard<std::mutex> lock(mutex_);
    mutableFor(update.vehicle).link = update.quality;
}

void VehicleStateStore::apply(const event::FaultRaised& fault) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto& health = mutableFor(fault.vehicle).health;
    health.level = fault.level;
    health.summary = fault.detail;
    health.stamp = domain::Timestamp{fault.at, domain::TimeQuality::Arrival};
}

void VehicleStateStore::noteHeard(domain::VehicleHandle vehicle, domain::TimePoint at) {
    std::lock_guard<std::mutex> lock(mutex_);
    mutableFor(vehicle).lastHeard = at;
}

void VehicleStateStore::remove(domain::VehicleHandle vehicle) {
    std::lock_guard<std::mutex> lock(mutex_);
    vehicles_.erase(vehicle);
}

std::optional<domain::VehicleSnapshot> VehicleStateStore::snapshot(
    domain::VehicleHandle vehicle) const {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto found = vehicles_.find(vehicle);
    if (found == vehicles_.end()) {
        return std::nullopt;
    }
    return found->second;
}

std::vector<domain::VehicleSnapshot> VehicleStateStore::snapshots() const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<domain::VehicleSnapshot> all;
    all.reserve(vehicles_.size());
    for (const auto& [handle, snapshot] : vehicles_) {
        all.push_back(snapshot);
    }
    return all;
}

std::size_t VehicleStateStore::size() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return vehicles_.size();
}

}  // namespace kmgcs::core
