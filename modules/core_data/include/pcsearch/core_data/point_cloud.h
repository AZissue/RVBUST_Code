#pragma once

#include <Eigen/Core>

#include <cstdint>
#include <string>
#include <vector>

namespace pcsearch::core {

// Internal length unit: everything is Millimeter inside the pipeline.
// Conversion to/from other units happens only in the IO layer.
enum class LengthUnit {
    Millimeter,
    Meter,
};

inline double toMillimeters(double value, LengthUnit unit) {
    switch (unit) {
        case LengthUnit::Millimeter: return value;
        case LengthUnit::Meter: return value * 1000.0;
    }
    return value;
}

// Dense point cloud representation, decoupled from PCL/Open3D types.
// Rows in all matrices are parallel: points(i), colors(i), normals(i).
struct PointCloudData {
    // N x 3 coordinates (mm).
    Eigen::MatrixXf points;
    // N x 3 RGB in [0, 1]; empty (0 rows) when absent.
    Eigen::MatrixXf colors;
    // N x 3 unit normals; empty when absent.
    Eigen::MatrixXf normals;
    // Optional per-point scalar channels (e.g. intensity, confidence).
    std::vector<std::vector<float>> scalar_channels;
    std::vector<std::string> scalar_channel_names;

    bool organized = false;  // points come from an image-like grid (width x height)
    std::int64_t width = 0;
    std::int64_t height = 0;

    LengthUnit unit = LengthUnit::Millimeter;
    std::string source_path;
    std::string frame_id;

    std::int64_t size() const { return static_cast<std::int64_t>(points.rows()); }
    bool hasColors() const { return colors.rows() == points.rows() && colors.rows() > 0; }
    bool hasNormals() const { return normals.rows() == points.rows() && normals.rows() > 0; }
};

}  // namespace pcsearch::core

