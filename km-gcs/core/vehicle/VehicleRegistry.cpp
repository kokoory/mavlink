#include "VehicleRegistry.hpp"

#include <vector>

#include "core/event/DomainEvents.hpp"

namespace kmgcs::core {

VehicleRegistry::VehicleRegistry(event::EventBus& bus, RegistryConfig config)
    : bus_(bus), config_(config) {}

domain::VehicleHandle VehicleRegistry::resolve(const domain::SystemAddress& address,
                                               const domain::ProductType& product,
                                               domain::TimePoint at) {
    bool discovered = false;
    domain::VehicleHandle handle;
    domain::ProductType resolvedProduct;

    {
        std::lock_guard<std::mutex> lock(mutex_);
        const auto known = byAddress_.find(address);
        if (known != byAddress_.end()) {
            handle = known->second;
            auto& entry = entries_[handle];
            entry.lastHeartbeat = at;
            if (product.autopilot != domain::AutopilotKind::Unknown) {
                entry.identity.product = product;
            }
            resolvedProduct = entry.identity.product;
        } else {
            if (product.autopilot == domain::AutopilotKind::Unknown &&
                product.frame == domain::FrameKind::Unknown) {
                return domain::VehicleHandle{};
            }
            handle = domain::VehicleHandle{nextHandle_++};
            Entry entry;
            entry.identity.handle = handle;
            entry.identity.address = address;
            entry.identity.product = product;
            entry.identity.displayName =
                "Vehicle " + std::to_string(address.system);
            entry.lastHeartbeat = at;
            entries_.emplace(handle, entry);
            byAddress_.emplace(address, handle);
            resolvedProduct = product;
            discovered = true;
        }
    }

    if (discovered) {
        event::VehicleDiscovered event;
        event.vehicle = handle;
        event.address = address;
        event.product = resolvedProduct;
        event.at = at;
        bus_.publish(event);
    }
    return handle;
}

void VehicleRegistry::enrich(domain::VehicleHandle vehicle,
                             const domain::HardwareId& hardware) {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto found = entries_.find(vehicle);
    if (found != entries_.end()) {
        found->second.identity.hardware = hardware;
    }
}

std::size_t VehicleRegistry::expire(domain::TimePoint now) {
    std::vector<event::VehicleLost> lost;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        for (auto it = entries_.begin(); it != entries_.end();) {
            const auto silent = now - it->second.lastHeartbeat;
            if (silent <= config_.heartbeatTimeout) {
                ++it;
                continue;
            }
            event::VehicleLost event;
            event.vehicle = it->first;
            event.silentFor = std::chrono::duration_cast<domain::Duration>(silent);
            event.at = now;
            lost.push_back(event);

            byAddress_.erase(it->second.identity.address);
            it = entries_.erase(it);
        }
    }
    for (const auto& event : lost) {
        bus_.publish(event);
    }
    return lost.size();
}

std::optional<domain::VehicleIdentity> VehicleRegistry::identity(
    domain::VehicleHandle vehicle) const {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto found = entries_.find(vehicle);
    if (found == entries_.end()) {
        return std::nullopt;
    }
    return found->second.identity;
}

std::vector<domain::VehicleIdentity> VehicleRegistry::all() const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<domain::VehicleIdentity> result;
    result.reserve(entries_.size());
    for (const auto& [handle, entry] : entries_) {
        result.push_back(entry.identity);
    }
    return result;
}

std::size_t VehicleRegistry::size() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return entries_.size();
}

}  // namespace kmgcs::core
