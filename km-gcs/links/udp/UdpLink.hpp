// UDP transport.
//
// Plain BSD sockets rather than QUdpSocket, so that nothing below the UI needs
// Qt. That is not a stylistic preference: it is what lets the layering check
// forbid Qt in the core, and what lets every test below run headless.

#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <string>

#include "links/common/Link.hpp"

namespace kmgcs::links {

struct UdpLinkConfig {
    std::uint16_t listenPort{14550};
    std::string listenAddress{"0.0.0.0"};
    /// Where to send when no explicit endpoint is given. When absent, the link
    /// replies to whoever last talked to it -- the usual autopilot arrangement,
    /// where the vehicle initiates and the GCS answers.
    std::optional<Endpoint> peer;
    std::size_t receiveBufferBytes{64 * 1024};
};

class UdpLink final : public ILink {
public:
    UdpLink(LinkId id, UdpLinkConfig config);
    ~UdpLink() override;

    UdpLink(const UdpLink&) = delete;
    UdpLink& operator=(const UdpLink&) = delete;

    [[nodiscard]] LinkId id() const override { return id_; }
    [[nodiscard]] std::string description() const override;
    [[nodiscard]] LinkState state() const override { return state_; }
    [[nodiscard]] LinkStats stats() const override { return stats_; }

    bool start(std::string& error) override;
    void stop() override;
    bool send(std::span<const std::byte> bytes) override;
    bool sendTo(std::span<const std::byte> bytes, const Endpoint& to) override;
    std::size_t poll(domain::Duration timeout, std::size_t budget) override;

    /// The port actually bound. Differs from the configured port when 0 was
    /// requested, which is how tests get an ephemeral port.
    [[nodiscard]] std::uint16_t boundPort() const { return boundPort_; }

private:
    void setState(LinkState state, const std::string& detail);

    LinkId id_;
    UdpLinkConfig config_;
    int socket_{-1};
    std::uint16_t boundPort_{0};
    LinkState state_{LinkState::Down};
    LinkStats stats_;
    std::optional<Endpoint> lastPeer_;
    std::vector<std::byte> buffer_;
};

}  // namespace kmgcs::links
