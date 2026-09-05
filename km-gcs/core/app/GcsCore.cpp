#include "GcsCore.hpp"

#include "core/event/DomainEvents.hpp"

namespace kmgcs::core {

GcsCore::GcsCore(event::EventBus& bus, RegistryConfig config)
    : bus_(bus), registry_(bus, config) {
    wireSubscriptions();
}

void GcsCore::wireSubscriptions() {
    using namespace kmgcs::event;

    // State telemetry coalesces: a 200 Hz attitude stream must not build a
    // queue the consumer can never drain. Commands and faults never do.
    const SubscriptionOptions latest{DeliveryPolicy::LatestValue, 0};
    const SubscriptionOptions lossless{DeliveryPolicy::Lossless, 0};

    bus_.subscribe<VehicleDiscovered>([this](const VehicleDiscovered& event) {
        const auto identity = registry_.identity(event.vehicle);
        if (identity) {
            store_.applyIdentity(*identity);
        }
        store_.noteHeard(event.vehicle, event.at);
    }, lossless);

    bus_.subscribe<VehicleLost>([this](const VehicleLost& event) {
        store_.remove(event.vehicle);
    }, lossless);

    bus_.subscribe<VehicleAttitudeUpdated>([this](const VehicleAttitudeUpdated& event) {
        store_.apply(event);
        // Staleness is "how long since we heard", so it is measured on our
        // clock. Using the vehicle's claimed timestamp would make age depend on
        // clock sync quality, which is exactly backwards.
        store_.noteHeard(event.vehicle, domain::now());
    }, latest);

    bus_.subscribe<VehiclePositionUpdated>([this](const VehiclePositionUpdated& event) {
        store_.apply(event);
    }, latest);

    bus_.subscribe<GnssUpdated>([this](const GnssUpdated& event) {
        store_.apply(event);
    }, latest);

    bus_.subscribe<BatteryUpdated>([this](const BatteryUpdated& event) {
        store_.apply(event);
    }, latest);

    bus_.subscribe<FlightModeChanged>([this](const FlightModeChanged& event) {
        store_.apply(event);
        nameModeIfPossible(event.vehicle);
    }, lossless);

    bus_.subscribe<AvailableModesUpdated>([this](const AvailableModesUpdated& event) {
        store_.apply(event);
    }, lossless);

    bus_.subscribe<TimeBaseUpdated>([this](const TimeBaseUpdated& event) {
        store_.apply(event);
    }, lossless);

    bus_.subscribe<LinkQualityUpdated>([this](const LinkQualityUpdated& event) {
        store_.apply(event);
    }, latest);

    bus_.subscribe<FaultRaised>([this](const FaultRaised& event) {
        store_.apply(event);
    }, lossless);
}

void GcsCore::nameModeIfPossible(domain::VehicleHandle vehicle) {
    const auto snapshot = store_.snapshot(vehicle);
    if (!snapshot || snapshot->mode.known()) {
        return;  // the vehicle already told us, which always wins
    }
    const auto adapter = adapters_.find(snapshot->identity.product);
    if (!adapter) {
        return;
    }
    const auto named = adapter->nameMode(snapshot->mode.vendorCode,
                                         snapshot->identity.product);
    if (!named) {
        return;  // unknown mode stays unnamed rather than mislabelled
    }
    event::FlightModeChanged changed;
    changed.vehicle = vehicle;
    changed.mode = *named;
    store_.apply(changed);
}

std::size_t GcsCore::step(domain::TimePoint now, std::size_t eventBudget) {
    const auto delivered = bus_.drain(eventBudget);
    registry_.expire(now);
    return delivered;
}

}  // namespace kmgcs::core
