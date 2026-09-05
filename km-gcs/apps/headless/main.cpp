// Headless ground station.
//
// The first vertical slice, with no UI in the way: bind a UDP port, parse
// MAVLink, translate to canonical state, print what the core believes. This is
// what proves Link -> Protocol -> Translation -> Domain Event -> Vehicle State
// actually holds before any QML exists.

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <cmath>
#include <cstdio>
#include <string>

#include "core/app/Composition.hpp"

namespace {

std::atomic<bool> g_running{true};

void handleSignal(int) {
    g_running = false;
}

// M_PI is a POSIX extension, not ISO C++, and -std=c++20 does not define it.
constexpr double kPi = 3.14159265358979323846;

std::string degrees(double radians) {
    char buffer[32];
    std::snprintf(buffer, sizeof(buffer), "%7.1f", radians * 180.0 / kPi);
    return buffer;
}

void printSnapshot(const kmgcs::domain::VehicleSnapshot& vehicle,
                   kmgcs::domain::TimePoint now) {
    using namespace kmgcs::domain;
    const auto euler = toEuler(vehicle.attitude.orientation);
    const auto ageMs = std::chrono::duration_cast<std::chrono::milliseconds>(
                           vehicle.ageAt(now)).count();

    std::cout << "  [" << vehicle.identity.handle.value() << "] "
              << vehicle.identity.displayName
              << "  sys=" << static_cast<int>(vehicle.identity.address.system)
              << "/" << static_cast<int>(vehicle.identity.address.component)
              << "  " << toString(vehicle.identity.product.autopilot)
              << "  " << (vehicle.armed.armed ? "ARMED" : "disarmed")
              << "  mode=" << (vehicle.mode.known()
                                   ? vehicle.mode.name
                                   : "#" + std::to_string(vehicle.mode.vendorCode))
              << "\n";
    std::cout << "        rpy " << degrees(euler.rollRad) << degrees(euler.pitchRad)
              << degrees(euler.yawRad) << " deg";
    if (vehicle.position.global) {
        std::cout << "   pos " << std::fixed << std::setprecision(6)
                  << vehicle.position.global->latitudeDeg << ", "
                  << vehicle.position.global->longitudeDeg << std::setprecision(1)
                  << "  alt " << vehicle.position.global->altitudeAmslM << " m";
    }
    std::cout << "\n        gnss " << toString(vehicle.gnss.fix) << " ("
              << vehicle.gnss.satellitesVisible << " sats)";
    if (vehicle.battery.voltageV) {
        std::cout << "   batt " << std::setprecision(2) << *vehicle.battery.voltageV << " V";
    }
    if (vehicle.battery.remainingFraction) {
        std::cout << " " << std::setprecision(0)
                  << (*vehicle.battery.remainingFraction * 100.0) << "%";
    }
    std::cout << "   age " << ageMs << " ms   time "
              << (vehicle.timeQuality == TimeQuality::Synchronised ? "synced"
                  : vehicle.timeQuality == TimeQuality::Coarse     ? "coarse"
                  : vehicle.timeQuality == TimeQuality::Arrival    ? "arrival"
                                                                   : "none")
              << "\n";
}

}  // namespace

int main(int argc, char** argv) {
    kmgcs::app::StationConfig config;
    config.udp.listenPort = 14550;
    int seconds = 0;

    for (int i = 1; i < argc; ++i) {
        const std::string argument = argv[i];
        if (argument == "--port" && i + 1 < argc) {
            config.udp.listenPort = static_cast<std::uint16_t>(std::atoi(argv[++i]));
        } else if (argument == "--seconds" && i + 1 < argc) {
            seconds = std::atoi(argv[++i]);
        } else if (argument == "--help") {
            std::cout << "usage: km-gcs-headless [--port N] [--seconds N]\n";
            return 0;
        }
    }

    std::signal(SIGINT, handleSignal);
    std::signal(SIGTERM, handleSignal);

    kmgcs::app::Station station(config);
    std::string error;
    if (!station.start(error)) {
        std::cerr << "km-gcs: " << error << "\n";
        return 1;
    }
    std::cout << "km-gcs headless: " << station.link().description() << "\n"
              << "waiting for MAVLink...\n";

    const auto started = kmgcs::domain::now();
    auto lastPrint = started;

    while (g_running) {
        station.poll(std::chrono::milliseconds(100));
        const auto now = kmgcs::domain::now();

        if (now - lastPrint >= std::chrono::seconds(1)) {
            lastPrint = now;
            const auto vehicles = station.core().store().snapshots();
            const auto stats = station.protocol().stats();
            std::cout << "-- " << vehicles.size() << " vehicle(s), "
                      << stats.framesParsed << " frames, "
                      << stats.parseErrors << " parse errors, "
                      << station.translator().translatedCount() << " translated\n";
            for (const auto& vehicle : vehicles) {
                printSnapshot(vehicle, now);
            }
        }

        if (seconds > 0 && now - started >= std::chrono::seconds(seconds)) {
            break;
        }
    }

    const auto untranslated = station.translator().untranslated();
    if (!untranslated.empty()) {
        std::cout << "\nmessages seen but not translated (profile coverage gap):\n";
        for (const auto& [id, count] : untranslated) {
            std::cout << "  msgid " << id << " x" << count << "\n";
        }
    }
    station.stop();
    return 0;
}
