#pragma once

#include "pcsearch/core_data/point_cloud.h"

#include <filesystem>
#include <string>
#include <vector>

namespace pcsearch::io {

// Supported input/output formats.
enum class Format { Auto, Pcd, Ply, Xyz, Csv };

// Result of reading a file. The returned cloud is always in millimeters.
struct ReadOptions {
    Format format = Format::Auto;
    // Override the source unit. When AutoUnit, the unit is auto-detected
    // (e.g. from a PLY comment "length unit = meter"), defaulting to Meter.
    core::LengthUnit source_unit = core::LengthUnit::Meter;
};

// Load a point cloud file. Throws IoError on failure.
core::PointCloudData readPointCloud(const std::string& path,
                                    const ReadOptions& options = {});

struct WriteOptions {
    Format format = Format::Auto;  // derived from file extension when Auto
    core::LengthUnit target_unit = core::LengthUnit::Millimeter;
};

// Save a point cloud file. Throws IoError on failure.
void writePointCloud(const std::string& path, const core::PointCloudData& cloud,
                     const WriteOptions& options = {});

// List supported point-cloud files (pcd/ply/xyz/csv/txt) inside `folder`,
// sorted by file name in natural order (numeric runs compare numerically,
// e.g. shot_2.ply < shot_10.ply). Returns an empty list when `folder` is not
// a directory or contains no supported files. Paths are returned as UTF-8.
std::vector<std::string> listPointCloudFiles(const std::string& folder);

// Convert a UTF-8 narrow-string path to a std::filesystem::path. On Windows
// this avoids the ANSI codepage so Chinese paths survive the round-trip.
std::filesystem::path pathFromUtf8(const std::string& utf8);

// Convert a std::filesystem::path back to the project's UTF-8 narrow-string
// convention. On Windows this converts from the native wide path.
std::string pathToUtf8(const std::filesystem::path& p);

class IoError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

}  // namespace pcsearch::io

