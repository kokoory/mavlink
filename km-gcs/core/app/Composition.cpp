#include "Composition.hpp"

namespace kmgcs::app {

Station::Station(StationConfig config)
    : config_(std::move(config)),
      core_(bus_, config_.registry),
      link_(std::make_unique<links::UdpLink>(1, config_.udp)),
      protocol_(std::make_unique<protocols::mavlink::MavlinkProtocolAdapter>()),
      translator_(std::make_unique<protocols::mavlink::MavlinkTranslator>(bus_)) {
    core_.adapters().add(adapters::makePx4Adapter());
    core_.adapters().add(adapters::makeArduPilotAdapter());
    wire();
}

Station::~Station() {
    stop();
}

void Station::wire() {
    protocol_->setLocalAddress(config_.localSystem, config_.localComponent);

    // bytes -> frames
    link_->onBytes([this](links::LinkId id, std::span<const std::byte> bytes,
                          const links::Endpoint& from, domain::TimePoint at) {
        protocol_->consume(id, bytes, from, at);
    });

    // frames -> domain events
    protocol_->onFrame([this](const protocols::mavlink::MavlinkFrame& frame) {
        translator_->translate(frame);
    });

    // The translator asks for identity; only the registry hands it out.
    translator_->setHandleResolver(
        [this](const domain::SystemAddress& address,
               const domain::ProductType& product,
               domain::TimePoint at) {
            return core_.registry().resolve(address, product, at);
        });

    translator_->setTimesyncRequester([this](const domain::SystemAddress& address) {
        const auto request = protocol_->encodeTimesyncRequest(
            address.system, address.component,
            domain::now().time_since_epoch().count());
        link_->send(request);
    });
}

bool Station::start(std::string& error) {
    return link_->start(error);
}

void Station::stop() {
    if (link_) {
        link_->stop();
    }
}

std::size_t Station::poll(domain::Duration timeout) {
    // Producers first, then the core drains what they published. Keeping the
    // order explicit is what makes a single-threaded run deterministic and a
    // multi-threaded one a drop-in change later.
    const auto datagrams = link_->poll(timeout, 64);
    core_.step(domain::now());
    return datagrams;
}

domain::CommandHandle Station::send(domain::VehicleHandle vehicle,
                                    const domain::VehicleCommand& command) {
    const auto identity = core_.registry().identity(vehicle);
    if (!identity) {
        return {};
    }
    const auto adapter = core_.adapters().find(identity->product);
    if (!adapter) {
        return {};
    }
    const auto spec = adapter->specFor(command, identity->product);
    if (!spec.supported) {
        return {};
    }

    protocols::ProtocolCommand wire;
    wire.command = spec.commandId;
    wire.targetSystem = identity->address.system;
    wire.targetComponent = identity->address.component;
    for (std::size_t i = 0; i < 7; ++i) {
        wire.params[i] = spec.params[i];
    }

    const auto bytes = protocol_->encode(wire);
    if (!link_->send(bytes)) {
        return {};
    }

    domain::CommandHandle handle;
    handle.id = nextCommandId_++;
    handle.vehicle = vehicle;
    handle.kind = command.kind;
    handle.issued = domain::now();
    return handle;
}

}  // namespace kmgcs::app
