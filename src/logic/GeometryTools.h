#pragma once

#include <QString>
#include <cmath>

// Pure geometry helpers for the Tools panel (unit-tested, no SDK dependency).
namespace GeometryTools {

enum class LengthUnit { Millimeter, Centimeter, Meter };

// Euclidean distance between two 3D points (unit-agnostic: whatever unit the
// inputs use, the result is in the same unit).
inline double distance3d(double x1, double y1, double z1,
                         double x2, double y2, double z2)
{
    const double dx = x2 - x1;
    const double dy = y2 - y1;
    const double dz = z2 - z1;
    return std::sqrt(dx * dx + dy * dy + dz * dz);
}

// Convert a length between mm / cm / m.
inline double convertLength(double value, LengthUnit from, LengthUnit to)
{
    // Normalize to millimeters first.
    double mm = value;
    if (from == LengthUnit::Centimeter) mm = value * 10.0;
    else if (from == LengthUnit::Meter)  mm = value * 1000.0;

    if (to == LengthUnit::Centimeter) return mm / 10.0;
    if (to == LengthUnit::Meter)      return mm / 1000.0;
    return mm;
}

// Format a length given in millimeters, converted to `unit`, with 3 decimals
// + unit suffix.
inline QString formatDistance(double valueMm, LengthUnit unit)
{
    const double value = convertLength(valueMm, LengthUnit::Millimeter, unit);
    const char* suffix = "mm";
    if (unit == LengthUnit::Centimeter) suffix = "cm";
    else if (unit == LengthUnit::Meter) suffix = "m";
    return QString::number(value, 'f', 3) + QStringLiteral(" ") + QString::fromLatin1(suffix);
}

} // namespace GeometryTools
