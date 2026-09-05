// Composition root.
//
// The one place that is allowed to see every layer at once. Everything else
// depends only on the abstractions below it; here the concrete UdpLink, the
// concrete MAVLink adapter and the core are wired together.

#pragma once

#include <memory>
#include <string>
#include <vector>

#include "adapters/autopilot/IAutopilotAdapter.hpp"
#include "core/app/GcsCore.hpp"
#include "core/event/EventBus.hpp"
#include "links/udp/UdpLink.hpp"
#include "protocols/mavlink/MavlinkProtocolAdapter.hpp"
#include "protocols/mavlink/MavlinkTranslator.hpp"

namespace kmgcs::app {

struct StationConfig {
    links::UdpLinkConfig udp;
    core::RegistryConfig registry;
    std::uint8_t localSystem{255};
    std::uint8_t localComponent{190};
};

/// A running ground station: one link, one protocol, one core.
class Station {
public:
    explicit Station(StationConfig config = {});
    ~Station();

    bool start(std::string& error);
    void stop();

    /// Pump links, then deliver events. Returns the number of datagrams read.
    std::size_t poll(domain::Duration timeout);

    [[nodiscard]] core::GcsCore& core() { return core_; }
    [[nodiscard]] event::EventBus& bus() { return bus_; }
    [[nodiscard]] links::UdpLink& link() { return *link_; }
    [[nodiscard]] protocols::mavlink::MavlinkProtocolAdapter& protocol() {
        return *protocol_;
    }
    [[nodiscard]] protocols::mavlink::MavlinkTranslator& translator() {
        return *translator_;
    }

    /// Issue a command. Returns an invalid handle when no adapter can speak for
    /// the vehicle's product type.
    domain::CommandHandle send(domain::VehicleHandle vehicle,
                               const domain::VehicleCommand& command);

private:
    void wire();

    StationConfig config_;
    event::EventBus bus_;
    core::GcsCore core_;
    std::unique_ptr<links::UdpLink> link_;
    std::unique_ptr<protocols::mavlink::MavlinkProtocolAdapter> protocol_;
    std::unique_ptr<protocols::mavlink::MavlinkTranslator> translator_;
    std::uint64_t nextCommandId_{1};
};

}  // namespace kmgcs::app
