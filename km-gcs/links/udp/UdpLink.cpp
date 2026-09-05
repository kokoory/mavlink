#include "UdpLink.hpp"

#include <arpa/inet.h>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

namespace kmgcs::links {
namespace {

std::string systemError() {
    return std::strerror(errno);
}

}  // namespace

UdpLink::UdpLink(LinkId id, UdpLinkConfig config)
    : id_(id), config_(std::move(config)) {
    buffer_.resize(config_.receiveBufferBytes);
}

UdpLink::~UdpLink() {
    stop();
}

std::string UdpLink::description() const {
    std::string text = "udp:" + config_.listenAddress + ":" +
                       std::to_string(boundPort_ != 0 ? boundPort_ : config_.listenPort);
    if (config_.peer) {
        text += " -> " + config_.peer->toString();
    }
    return text;
}

void UdpLink::setState(LinkState state, const std::string& detail) {
    if (state_ == state) {
        return;
    }
    state_ = state;
    if (stateHandler_) {
        stateHandler_(id_, state, detail);
    }
}

bool UdpLink::start(std::string& error) {
    if (socket_ >= 0) {
        return true;
    }
    setState(LinkState::Connecting, "binding");

    socket_ = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (socket_ < 0) {
        error = "socket(): " + systemError();
        setState(LinkState::Failed, error);
        return false;
    }

    int reuse = 1;
    ::setsockopt(socket_, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));

    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_port = htons(config_.listenPort);
    if (::inet_pton(AF_INET, config_.listenAddress.c_str(), &address.sin_addr) != 1) {
        error = "bad listen address '" + config_.listenAddress + "'";
        ::close(socket_);
        socket_ = -1;
        setState(LinkState::Failed, error);
        return false;
    }

    if (::bind(socket_, reinterpret_cast<sockaddr*>(&address), sizeof(address)) < 0) {
        error = "bind(" + config_.listenAddress + ":" +
                std::to_string(config_.listenPort) + "): " + systemError();
        ::close(socket_);
        socket_ = -1;
        setState(LinkState::Failed, error);
        return false;
    }

    // Read back the bound port so that a configured port of 0 still tells the
    // caller where to send. Tests rely on this to avoid fixed ports.
    sockaddr_in bound{};
    socklen_t boundLength = sizeof(bound);
    if (::getsockname(socket_, reinterpret_cast<sockaddr*>(&bound), &boundLength) == 0) {
        boundPort_ = ntohs(bound.sin_port);
    }

    const int flags = ::fcntl(socket_, F_GETFL, 0);
    ::fcntl(socket_, F_SETFL, flags | O_NONBLOCK);

    setState(LinkState::Up, description());
    return true;
}

void UdpLink::stop() {
    if (socket_ >= 0) {
        ::close(socket_);
        socket_ = -1;
    }
    boundPort_ = 0;
    setState(LinkState::Down, "stopped");
}

bool UdpLink::send(std::span<const std::byte> bytes) {
    // Prefer the configured peer; otherwise answer whoever last spoke to us.
    // A vehicle that has never been heard from has no address to send to.
    if (config_.peer) {
        return sendTo(bytes, *config_.peer);
    }
    if (lastPeer_) {
        return sendTo(bytes, *lastPeer_);
    }
    ++stats_.sendErrors;
    return false;
}

bool UdpLink::sendTo(std::span<const std::byte> bytes, const Endpoint& to) {
    if (socket_ < 0) {
        ++stats_.sendErrors;
        return false;
    }
    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_port = htons(to.port);
    if (::inet_pton(AF_INET, to.host.c_str(), &address.sin_addr) != 1) {
        ++stats_.sendErrors;
        return false;
    }
    const auto sent = ::sendto(socket_, bytes.data(), bytes.size(), 0,
                               reinterpret_cast<sockaddr*>(&address), sizeof(address));
    if (sent < 0) {
        ++stats_.sendErrors;
        return false;
    }
    stats_.bytesSent += static_cast<std::uint64_t>(sent);
    return true;
}

std::size_t UdpLink::poll(domain::Duration timeout, std::size_t budget) {
    if (socket_ < 0) {
        return 0;
    }

    pollfd descriptor{};
    descriptor.fd = socket_;
    descriptor.events = POLLIN;
    const auto timeoutMs = static_cast<int>(
        std::chrono::duration_cast<std::chrono::milliseconds>(timeout).count());
    if (::poll(&descriptor, 1, timeoutMs) <= 0) {
        return 0;
    }

    std::size_t handled = 0;
    while (handled < budget) {
        sockaddr_in from{};
        socklen_t fromLength = sizeof(from);
        const auto received = ::recvfrom(socket_, buffer_.data(), buffer_.size(), 0,
                                         reinterpret_cast<sockaddr*>(&from), &fromLength);
        if (received < 0) {
            if (errno != EAGAIN && errno != EWOULDBLOCK) {
                ++stats_.receiveErrors;
            }
            break;
        }

        char host[INET_ADDRSTRLEN]{};
        ::inet_ntop(AF_INET, &from.sin_addr, host, sizeof(host));
        Endpoint endpoint{host, ntohs(from.sin_port)};
        lastPeer_ = endpoint;

        stats_.bytesReceived += static_cast<std::uint64_t>(received);
        ++stats_.datagramsReceived;
        ++handled;

        if (bytesHandler_) {
            bytesHandler_(id_,
                          std::span<const std::byte>(buffer_.data(),
                                                     static_cast<std::size_t>(received)),
                          endpoint, domain::now());
        }
    }
    return handled;
}

}  // namespace kmgcs::links
