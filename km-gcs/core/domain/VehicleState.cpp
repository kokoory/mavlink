#include "VehicleState.hpp"

#include <cmath>

namespace kmgcs::domain {

EulerAngles toEuler(const Quaternion& q) {
    EulerAngles e;
    // ZYX intrinsic, matching the convention MAVLink's ATTITUDE uses.
    const double sinrCosp = 2.0 * (q.w * q.x + q.y * q.z);
    const double cosrCosp = 1.0 - 2.0 * (q.x * q.x + q.y * q.y);
    e.rollRad = std::atan2(sinrCosp, cosrCosp);

    const double sinp = 2.0 * (q.w * q.y - q.z * q.x);
    // Clamp rather than let asin return NaN at the poles; a gimbal-locked
    // attitude should read +-90 degrees, not blank out the display.
    e.pitchRad = std::abs(sinp) >= 1.0 ? std::copysign(M_PI / 2.0, sinp)
                                       : std::asin(sinp);

    const double sinyCosp = 2.0 * (q.w * q.z + q.x * q.y);
    const double cosyCosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z);
    e.yawRad = std::atan2(sinyCosp, cosyCosp);
    return e;
}

const char* toString(GnssFix fix) {
    switch (fix) {
        case GnssFix::NoGps:    return "No GPS";
        case GnssFix::NoFix:    return "No fix";
        case GnssFix::Fix2D:    return "2D";
        case GnssFix::Fix3D:    return "3D";
        case GnssFix::Dgps:     return "DGPS";
        case GnssFix::RtkFloat: return "RTK float";
        case GnssFix::RtkFixed: return "RTK fixed";
        case GnssFix::Static:   return "Static";
        case GnssFix::Other:    return "Other";
    }
    return "Unknown";
}

const char* toString(StandardMode mode) {
    switch (mode) {
        case StandardMode::NonStandard:  return "Non-standard";
        case StandardMode::PositionHold: return "Position hold";
        case StandardMode::Orbit:        return "Orbit";
        case StandardMode::Cruise:       return "Cruise";
        case StandardMode::AltitudeHold: return "Altitude hold";
        case StandardMode::SafeRecovery: return "Safe recovery";
        case StandardMode::Mission:      return "Mission";
        case StandardMode::Land:         return "Land";
        case StandardMode::Takeoff:      return "Takeoff";
    }
    return "Unknown";
}

const char* toString(ReferenceFrame frame) {
    switch (frame) {
        case ReferenceFrame::Wgs84:   return "WGS84";
        case ReferenceFrame::Ecef:    return "ECEF";
        case ReferenceFrame::Ned:     return "NED";
        case ReferenceFrame::Enu:     return "ENU";
        case ReferenceFrame::BodyFrd: return "Body FRD";
        case ReferenceFrame::BodyFlu: return "Body FLU";
        case ReferenceFrame::Unknown: return "Unknown";
    }
    return "Unknown";
}

const char* toString(AutopilotKind kind) {
    switch (kind) {
        case AutopilotKind::Px4:       return "PX4";
        case AutopilotKind::ArduPilot: return "ArduPilot";
        case AutopilotKind::Generic:   return "Generic";
        case AutopilotKind::Other:     return "Other";
        case AutopilotKind::Unknown:   return "Unknown";
    }
    return "Unknown";
}

}  // namespace kmgcs::domain
