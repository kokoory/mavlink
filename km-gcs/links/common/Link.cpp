#include "Link.hpp"

namespace kmgcs::links {

std::string Endpoint::toString() const {
    return host + ":" + std::to_string(port);
}

const char* toString(LinkState state) {
    switch (state) {
        case LinkState::Down:       return "down";
        case LinkState::Connecting: return "connecting";
        case LinkState::Up:         return "up";
        case LinkState::Failed:     return "failed";
    }
    return "unknown";
}

}  // namespace kmgcs::links
