#include "test_geometry_tools.h"

#include "logic/GeometryTools.h"

#include <QtTest>
#include <cmath>

void TestGeometryTools::distance3dBasic()
{
    // Classic 3-4-5 triangle in the XY plane.
    QVERIFY(std::abs(GeometryTools::distance3d(0, 0, 0, 3, 4, 0) - 5.0) < 1e-9);
    // Same Z offset cancels out.
    QVERIFY(std::abs(GeometryTools::distance3d(1, 2, 3, 4, 6, 3) - 5.0) < 1e-9);
    // Identical points -> zero distance.
    QVERIFY(GeometryTools::distance3d(1.5, 2.5, 3.5, 1.5, 2.5, 3.5) == 0.0);
}

void TestGeometryTools::distance3dNegativeCoordinates()
{
    const double d = GeometryTools::distance3d(-10, -10, -10, 10, 10, 10);
    QVERIFY(std::abs(d - std::sqrt(1200.0)) < 1e-9);
}

void TestGeometryTools::convertLengthUnits()
{
    using U = GeometryTools::LengthUnit;
    QVERIFY(std::abs(GeometryTools::convertLength(1000, U::Millimeter, U::Centimeter) - 100.0) < 1e-9);
    QVERIFY(std::abs(GeometryTools::convertLength(1000, U::Millimeter, U::Meter) - 1.0) < 1e-9);
    QVERIFY(std::abs(GeometryTools::convertLength(1, U::Meter, U::Millimeter) - 1000.0) < 1e-9);
    QVERIFY(std::abs(GeometryTools::convertLength(2.5, U::Centimeter, U::Millimeter) - 25.0) < 1e-9);
    QVERIFY(std::abs(GeometryTools::convertLength(123.4, U::Millimeter, U::Millimeter) - 123.4) < 1e-9);
}

void TestGeometryTools::formatDistancePrecision()
{
    // formatDistance takes millimeters and converts to the requested unit.
    QCOMPARE(GeometryTools::formatDistance(12.3456, GeometryTools::LengthUnit::Millimeter),
             QStringLiteral("12.346 mm"));
    QCOMPARE(GeometryTools::formatDistance(1234.5, GeometryTools::LengthUnit::Centimeter),
             QStringLiteral("123.450 cm"));
    QCOMPARE(GeometryTools::formatDistance(1000.0, GeometryTools::LengthUnit::Meter),
             QStringLiteral("1.000 m"));
}
