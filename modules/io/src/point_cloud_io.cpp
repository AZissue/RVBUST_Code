#include "pcsearch/io/point_cloud_io.h"

#include <Eigen/Core>

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <string>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#endif

namespace pcsearch::io {

namespace {

using core::LengthUnit;
using core::PointCloudData;

std::string toLower(const std::string& s) {
    std::string out = s;
    for (auto& c : out) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return out;
}

std::string trim(const std::string& s) {
    const auto b = s.find_first_not_of(" \t\r\n");
    if (b == std::string::npos) return {};
    const auto e = s.find_last_not_of(" \t\r\n");
    return s.substr(b, e - b + 1);
}

// Convert a filesystem path back to the project's UTF-8 narrow-string
// convention (paths enter the pipeline as UTF-8; std::filesystem on Windows
// hands out wide strings).
std::string toUtf8(const std::filesystem::path& p) {
#ifdef _WIN32
    const std::wstring w = p.wstring();
    if (w.empty()) return {};
    const int len = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), -1, nullptr, 0,
                                        nullptr, nullptr);
    if (len <= 0) return p.string();
    std::string s(static_cast<std::size_t>(len - 1), '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.c_str(), -1, s.data(), len, nullptr, nullptr);
    return s;
#else
    return p.string();
#endif
}

// On Windows, narrow std::string paths are UTF-8 in this project. Convert
// them to wide explicitly so non-ASCII (e.g. Chinese) paths open correctly
// instead of being mangled through the ANSI codepage.
std::filesystem::path utf8Path(const std::string& s) {
#ifdef _WIN32
    if (s.empty()) return {};
    const int len = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), -1, nullptr, 0);
    if (len <= 0) return std::filesystem::path(s);
    std::wstring w(static_cast<std::size_t>(len - 1), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.c_str(), -1, w.data(),
                        static_cast<int>(w.size()));
    return std::filesystem::path(w);
#else
    return std::filesystem::path(s);
#endif
}

Format formatFromPath(const std::string& path) {
    const auto dot = path.find_last_of('.');
    if (dot == std::string::npos) return Format::Auto;
    const std::string ext = toLower(path.substr(dot + 1));
    if (ext == "pcd") return Format::Pcd;
    if (ext == "ply") return Format::Ply;
    if (ext == "xyz") return Format::Xyz;
    if (ext == "csv" || ext == "txt") return Format::Csv;
    return Format::Auto;
}

// Natural (numeric-aware) comparison of two file paths: digit runs compare
// numerically so shot_2.ply sorts before shot_10.ply. Everything else falls
// back to a case-insensitive character comparison for deterministic order.
bool naturalLess(const std::string& a, const std::string& b) {
    std::size_t i = 0, j = 0;
    while (i < a.size() && j < b.size()) {
        const bool da = std::isdigit(static_cast<unsigned char>(a[i])) != 0;
        const bool db = std::isdigit(static_cast<unsigned char>(b[j])) != 0;
        if (da && db) {
            // Skip leading zeros so "007" == "7" for ordering purposes.
            while (i < a.size() && a[i] == '0') ++i;
            while (j < b.size() && b[j] == '0') ++j;
            std::size_t ai = i, bj = j;
            while (ai < a.size() && std::isdigit(static_cast<unsigned char>(a[ai]))) ++ai;
            while (bj < b.size() && std::isdigit(static_cast<unsigned char>(b[bj]))) ++bj;
            const std::size_t alen = ai - i, blen = bj - j;
            if (alen != blen) return alen < blen;
            for (std::size_t k = 0; k < alen; ++k) {
                if (a[i + k] != b[j + k]) return a[i + k] < b[j + k];
            }
            i = ai;
            j = bj;
        } else if (da != db) {
            return da;  // digit runs sort before letters
        } else {
            const char ca = static_cast<char>(
                std::tolower(static_cast<unsigned char>(a[i])));
            const char cb = static_cast<char>(
                std::tolower(static_cast<unsigned char>(b[j])));
            if (ca != cb) return ca < cb;
            ++i;
            ++j;
        }
    }
    // One string is a prefix of the other: the shorter one sorts first.
    return i == a.size() && j < b.size();
}

double unitFactorFrom(LengthUnit unit) {
    switch (unit) {
        case LengthUnit::Millimeter: return 1.0;
        case LengthUnit::Meter: return 1000.0;
    }
    return 1.0;
}

// ---------------------------------------------------------------------------
// PLY
// ---------------------------------------------------------------------------

struct PlyHeader {
    bool binary = false;
    std::int64_t vertex_count = 0;
    std::vector<std::pair<std::string, std::string>> properties;  // name, type
    std::vector<std::pair<std::string, std::string>> comments;
};

PlyHeader parsePlyHeader(std::istream& in) {
    PlyHeader h;
    std::string line;
    if (!std::getline(in, line) || trim(line) != "ply") {
        throw IoError("not a PLY file");
    }
    bool in_vertex = false;
    while (std::getline(in, line)) {
        const std::string t = trim(line);
        if (t == "end_header") break;
        std::istringstream ss(t);
        std::string kw;
        ss >> kw;
        if (kw == "format") {
            std::string fmt;
            ss >> fmt;
            h.binary = (fmt.find("binary") != std::string::npos);
        } else if (kw == "comment") {
            const std::string rest = trim(t.substr(t.find(' ') + 1));
            h.comments.emplace_back(rest, "");
        } else if (kw == "element") {
            std::string name;
            std::int64_t count = 0;
            ss >> name >> count;
            in_vertex = (name == "vertex");
            if (in_vertex) h.vertex_count = count;
        } else if (kw == "property") {
            std::string type, name;
            ss >> type >> name;
            if (in_vertex) h.properties.emplace_back(name, type);
        } else if (kw == "obj_info") {
            // ignore
        }
    }
    return h;
}

std::size_t plyTypeSize(const std::string& type) {
    if (type == "float" || type == "int32" || type == "uint32") return 4;
    if (type == "double" || type == "int64" || type == "uint64") return 8;
    if (type == "uchar" || type == "uint8" || type == "char" || type == "int8") return 1;
    if (type == "short" || type == "int16" || type == "uint16") return 2;
    return 0;
}

template <typename T>
T readBinary(std::istream& in) {
    T v{};
    in.read(reinterpret_cast<char*>(&v), sizeof(T));
    return v;
}

double readPlyScalar(std::istream& in, const std::string& type, bool binary) {
    if (!binary) {
        double v = 0.0;
        in >> v;
        return v;
    }
    if (type == "float") return static_cast<double>(readBinary<float>(in));
    if (type == "double") return readBinary<double>(in);
    if (type == "uchar" || type == "uint8") return static_cast<double>(readBinary<std::uint8_t>(in));
    if (type == "char" || type == "int8") return static_cast<double>(readBinary<std::int8_t>(in));
    if (type == "short" || type == "int16") return static_cast<double>(readBinary<std::int16_t>(in));
    if (type == "ushort" || type == "uint16") return static_cast<double>(readBinary<std::uint16_t>(in));
    if (type == "int" || type == "int32") return static_cast<double>(readBinary<std::int32_t>(in));
    if (type == "uint" || type == "uint32") return static_cast<double>(readBinary<std::uint32_t>(in));
    throw IoError("unsupported PLY scalar type: " + type);
}

PointCloudData readPly(const std::string& path, const ReadOptions& options) {
    std::ifstream in(utf8Path(path), std::ios::binary);
    if (!in) throw IoError("cannot open file: " + path);
    const PlyHeader h = parsePlyHeader(in);

    PointCloudData cloud;
    cloud.unit = LengthUnit::Millimeter;
    cloud.source_path = path;
    cloud.points.resize(h.vertex_count, 3);
    cloud.colors.resize(0, 3);

    // Auto-detect unit from "length unit = meter" comments.
    LengthUnit detected = options.source_unit;
    for (const auto& c : h.comments) {
        const std::string lower = toLower(c.first);
        if (lower.find("length unit") != std::string::npos && lower.find("meter") != std::string::npos) {
            detected = LengthUnit::Meter;
        }
        if (lower.find("length unit") != std::string::npos && lower.find("millimeter") != std::string::npos) {
            detected = LengthUnit::Millimeter;
        }
    }
    const double factor = unitFactorFrom(detected);

    bool has_x = false, has_y = false, has_z = false, has_r = false, has_g = false, has_b = false;
    std::vector<int> prop_sizes;
    for (const auto& p : h.properties) {
        const std::string n = toLower(p.first);
        has_x = has_x || n == "x";
        has_y = has_y || n == "y";
        has_z = has_z || n == "z";
        has_r = has_r || n == "red";
        has_g = has_g || n == "green";
        has_b = has_b || n == "blue";
        prop_sizes.push_back(static_cast<int>(plyTypeSize(p.second)));
    }
    const bool has_rgb = has_r && has_g && has_b;
    if (has_rgb) cloud.colors.resize(h.vertex_count, 3);
    if (!(has_x && has_y && has_z)) throw IoError("PLY vertex has no x/y/z properties");

    for (std::int64_t i = 0; i < h.vertex_count; ++i) {
        double x = 0, y = 0, z = 0, r = 0, g = 0, b = 0;
        int rgb_idx = 0;
        for (std::size_t p = 0; p < h.properties.size(); ++p) {
            const std::string n = toLower(h.properties[p].first);
            const double v = readPlyScalar(in, h.properties[p].second, h.binary);
            if (n == "x") x = v;
            else if (n == "y") y = v;
            else if (n == "z") z = v;
            else if (has_rgb && n == "red") r = v;
            else if (has_rgb && n == "green") g = v;
            else if (has_rgb && n == "blue") b = v;
            (void)rgb_idx;
        }
        cloud.points(i, 0) = static_cast<float>(x * factor);
        cloud.points(i, 1) = static_cast<float>(y * factor);
        cloud.points(i, 2) = static_cast<float>(z * factor);
        if (has_rgb) {
            cloud.colors(i, 0) = static_cast<float>(r / 255.0);
            cloud.colors(i, 1) = static_cast<float>(g / 255.0);
            cloud.colors(i, 2) = static_cast<float>(b / 255.0);
        }
    }
    return cloud;
}

void writePly(const std::string& path, const PointCloudData& cloud, LengthUnit target_unit) {
    const double factor = 1.0 / unitFactorFrom(target_unit);
    const bool has_rgb = cloud.hasColors();
    std::ofstream out(utf8Path(path), std::ios::binary);
    if (!out) throw IoError("cannot open file for writing: " + path);
    out << "ply\n";
    out << "format binary_little_endian 1.0\n";
    out << "comment Created by PointCloudSearch. length unit = "
        << (target_unit == LengthUnit::Meter ? "meter" : "millimeter") << "\n";
    out << "element vertex " << cloud.size() << "\n";
    out << "property float x\nproperty float y\nproperty float z\n";
    if (has_rgb) {
        out << "property uchar red\nproperty uchar green\nproperty uchar blue\n";
    }
    out << "end_header\n";
    for (std::int64_t i = 0; i < cloud.size(); ++i) {
        const float x = static_cast<float>(cloud.points(i, 0) * factor);
        const float y = static_cast<float>(cloud.points(i, 1) * factor);
        const float z = static_cast<float>(cloud.points(i, 2) * factor);
        out.write(reinterpret_cast<const char*>(&x), 4);
        out.write(reinterpret_cast<const char*>(&y), 4);
        out.write(reinterpret_cast<const char*>(&z), 4);
        if (has_rgb) {
            const std::uint8_t r = static_cast<std::uint8_t>(cloud.colors(i, 0) * 255.0 + 0.5);
            const std::uint8_t g = static_cast<std::uint8_t>(cloud.colors(i, 1) * 255.0 + 0.5);
            const std::uint8_t b = static_cast<std::uint8_t>(cloud.colors(i, 2) * 255.0 + 0.5);
            out.put(static_cast<char>(r));
            out.put(static_cast<char>(g));
            out.put(static_cast<char>(b));
        }
    }
}

// ---------------------------------------------------------------------------
// PCD
// ---------------------------------------------------------------------------

PointCloudData readPcd(const std::string& path, const ReadOptions& options) {
    std::ifstream in(utf8Path(path), std::ios::binary);
    if (!in) throw IoError("cannot open file: " + path);
    std::string line;
    if (!std::getline(in, line) || trim(line) != "VERSION .7" && trim(line) != "VERSION .6") {
        throw IoError("unsupported PCD version");
    }
    std::vector<std::string> fields;
    std::vector<int> sizes;
    std::vector<std::string> types;
    std::int64_t width = 0, height = 1, points = 0;
    bool binary = false;
    while (std::getline(in, line)) {
        std::istringstream ss(line);
        std::string kw;
        ss >> kw;
        if (kw == "FIELDS") {
            std::string f;
            while (ss >> f) fields.push_back(f);
        } else if (kw == "SIZE") {
            int v;
            while (ss >> v) sizes.push_back(v);
        } else if (kw == "TYPE") {
            std::string v;
            while (ss >> v) types.push_back(v);
        } else if (kw == "WIDTH") {
            ss >> width;
        } else if (kw == "HEIGHT") {
            ss >> height;
        } else if (kw == "POINTS") {
            ss >> points;
        } else if (kw == "DATA") {
            std::string mode;
            ss >> mode;
            binary = (mode == "binary");
            break;
        }
    }
    if (points == 0) points = width * height;
    if (fields.empty() || types.empty()) throw IoError("PCD header incomplete");
    const double factor = unitFactorFrom(options.source_unit);

    PointCloudData cloud;
    cloud.unit = LengthUnit::Millimeter;
    cloud.source_path = path;
    cloud.organized = (height > 1);
    cloud.width = width;
    cloud.height = height;
    cloud.points.resize(points, 3);
    cloud.colors.resize(0, 3);

    auto col = [&](const std::string& n) -> int {
        for (std::size_t i = 0; i < fields.size(); ++i) {
            if (toLower(fields[i]) == n) return static_cast<int>(i);
        }
        return -1;
    };
    const int ix = col("x"), iy = col("y"), iz = col("z"), irgb = col("rgb");
    if (ix < 0 || iy < 0 || iz < 0) throw IoError("PCD has no x/y/z fields");

    std::vector<std::int64_t> byte_offsets;
    std::int64_t acc = 0;
    for (std::size_t i = 0; i < fields.size(); ++i) {
        byte_offsets.push_back(acc);
        acc += sizes[i];
    }
    const std::int64_t stride = acc;

    std::vector<char> row(static_cast<std::size_t>(stride));
    for (std::int64_t i = 0; i < points; ++i) {
        double x = 0, y = 0, z = 0, rgb = 0;
        if (binary) {
            in.read(row.data(), stride);
            if (!in) throw IoError("PCD binary data truncated");
            auto get = [&](int f) -> double {
                if (f < 0) return 0.0;
                const char* p = row.data() + byte_offsets[f];
                if (types[f] == "F" && sizes[f] == 4) {
                    float v;
                    std::memcpy(&v, p, 4);
                    return v;
                }
                if (types[f] == "F" && sizes[f] == 8) {
                    double v;
                    std::memcpy(&v, p, 8);
                    return v;
                }
                if (types[f] == "U" && sizes[f] == 4) {
                    std::uint32_t v;
                    std::memcpy(&v, p, 4);
                    return v;
                }
                throw IoError("unsupported PCD field type");
            };
            x = get(ix);
            y = get(iy);
            z = get(iz);
            if (irgb >= 0) rgb = get(irgb);
        } else {
            std::string token;
            for (std::size_t f = 0; f < fields.size(); ++f) {
                if (!(in >> token)) throw IoError("PCD ascii data truncated");
                const double v = std::stod(token);
                if (static_cast<int>(f) == ix) x = v;
                if (static_cast<int>(f) == iy) y = v;
                if (static_cast<int>(f) == iz) z = v;
                if (static_cast<int>(f) == irgb) rgb = v;
            }
        }
        cloud.points(i, 0) = static_cast<float>(x * factor);
        cloud.points(i, 1) = static_cast<float>(y * factor);
        cloud.points(i, 2) = static_cast<float>(z * factor);
        if (irgb >= 0) {
            if (cloud.colors.rows() == 0) cloud.colors.resize(points, 3);
            const std::uint32_t packed = static_cast<std::uint32_t>(rgb);
            cloud.colors(i, 0) = static_cast<float>((packed >> 16 & 0xFF)) / 255.0f;
            cloud.colors(i, 1) = static_cast<float>((packed >> 8 & 0xFF)) / 255.0f;
            cloud.colors(i, 2) = static_cast<float>((packed & 0xFF)) / 255.0f;
        }
    }
    return cloud;
}

void writePcd(const std::string& path, const PointCloudData& cloud, LengthUnit target_unit) {
    const double factor = 1.0 / unitFactorFrom(target_unit);
    std::ofstream out(utf8Path(path));
    if (!out) throw IoError("cannot open file for writing: " + path);
    out << "VERSION .7\n";
    out << "FIELDS x y z" << (cloud.hasColors() ? " rgb" : "") << "\n";
    out << "SIZE 4 4 4" << (cloud.hasColors() ? " 4" : "") << "\n";
    out << "TYPE F F F" << (cloud.hasColors() ? " F" : "") << "\n";
    out << "COUNT 1 1 1" << (cloud.hasColors() ? " 1" : "") << "\n";
    out << "WIDTH " << cloud.size() << "\n";
    out << "HEIGHT 1\n";
    out << "POINTS " << cloud.size() << "\n";
    out << "DATA ascii\n";
    out << std::setprecision(9);
    for (std::int64_t i = 0; i < cloud.size(); ++i) {
        out << cloud.points(i, 0) * factor << " " << cloud.points(i, 1) * factor << " "
            << cloud.points(i, 2) * factor;
        if (cloud.hasColors()) {
            const std::uint32_t packed =
                (static_cast<std::uint32_t>(cloud.colors(i, 0) * 255.0 + 0.5) << 16) |
                (static_cast<std::uint32_t>(cloud.colors(i, 1) * 255.0 + 0.5) << 8) |
                static_cast<std::uint32_t>(cloud.colors(i, 2) * 255.0 + 0.5);
            out << " " << packed;
        }
        out << "\n";
    }
}

// ---------------------------------------------------------------------------
// XYZ / CSV
// ---------------------------------------------------------------------------

PointCloudData readDelimited(const std::string& path, const ReadOptions& options, bool csv) {
    std::ifstream in(utf8Path(path));
    if (!in) throw IoError("cannot open file: " + path);
    PointCloudData cloud;
    cloud.unit = LengthUnit::Millimeter;
    cloud.source_path = path;
    cloud.points.resize(0, 3);
    cloud.colors.resize(0, 3);
    const double factor = unitFactorFrom(options.source_unit);

    std::string line;
    bool first = true;
    while (std::getline(in, line)) {
        const std::string t = trim(line);
        if (t.empty() || t[0] == '#') continue;
        if (first && csv) {
            // Header detection: if the first token is not a number, skip it.
            std::istringstream probe(line);
            std::string tok;
            probe >> tok;
            try {
                (void)std::stod(tok);
            } catch (...) {
                first = false;
                continue;
            }
        }
        first = false;
        std::replace(line.begin(), line.end(), ',', ' ');
        std::replace(line.begin(), line.end(), ';', ' ');
        std::istringstream ss(line);
        std::vector<double> vals;
        double v;
        while (ss >> v) vals.push_back(v);
        if (vals.size() < 3) continue;
        cloud.points.conservativeResize(cloud.points.rows() + 1, 3);
        const std::int64_t r = cloud.points.rows() - 1;
        cloud.points(r, 0) = static_cast<float>(vals[0] * factor);
        cloud.points(r, 1) = static_cast<float>(vals[1] * factor);
        cloud.points(r, 2) = static_cast<float>(vals[2] * factor);
        if (vals.size() >= 6) {
            if (cloud.colors.rows() < cloud.points.rows()) {
                cloud.colors.resize(cloud.points.rows(), 3);
            }
            cloud.colors(r, 0) = static_cast<float>(vals[3] / 255.0);
            cloud.colors(r, 1) = static_cast<float>(vals[4] / 255.0);
            cloud.colors(r, 2) = static_cast<float>(vals[5] / 255.0);
        }
    }
    return cloud;
}

void writeDelimited(const std::string& path, const PointCloudData& cloud,
                    LengthUnit target_unit, bool csv) {
    const double factor = 1.0 / unitFactorFrom(target_unit);
    std::ofstream out(utf8Path(path));
    if (!out) throw IoError("cannot open file for writing: " + path);
    const char sep = csv ? ',' : ' ';
    if (csv) out << "x,y,z" << (cloud.hasColors() ? ",r,g,b" : "") << "\n";
    out << std::setprecision(9);
    for (std::int64_t i = 0; i < cloud.size(); ++i) {
        out << cloud.points(i, 0) * factor << sep << cloud.points(i, 1) * factor << sep
            << cloud.points(i, 2) * factor;
        if (cloud.hasColors()) {
            out << sep << static_cast<int>(cloud.colors(i, 0) * 255.0 + 0.5) << sep
                << static_cast<int>(cloud.colors(i, 1) * 255.0 + 0.5) << sep
                << static_cast<int>(cloud.colors(i, 2) * 255.0 + 0.5);
        }
        out << "\n";
    }
}

}  // namespace

std::vector<std::string> listPointCloudFiles(const std::string& folder) {
    std::vector<std::string> out;
    std::error_code ec;
    const std::filesystem::path dir = utf8Path(folder);
    if (!std::filesystem::is_directory(dir, ec)) return out;
    std::filesystem::directory_iterator it(dir, ec), end;
    for (; it != end && !ec; it.increment(ec)) {
        const std::filesystem::directory_entry& entry = *it;
        if (!entry.is_regular_file(ec) || ec) continue;
        const std::string path = toUtf8(entry.path());
        if (formatFromPath(path) != Format::Auto) out.push_back(path);
    }
    std::sort(out.begin(), out.end(), naturalLess);
    return out;
}

core::PointCloudData readPointCloud(const std::string& path, const ReadOptions& options) {
    Format fmt = options.format;
    if (fmt == Format::Auto) fmt = formatFromPath(path);
    core::PointCloudData cloud;
    switch (fmt) {
        case Format::Pcd: cloud = readPcd(path, options); break;
        case Format::Ply: cloud = readPly(path, options); break;
        case Format::Xyz: cloud = readDelimited(path, options, false); break;
        case Format::Csv: cloud = readDelimited(path, options, true); break;
        case Format::Auto:
            throw IoError("cannot determine format from extension: " + path);
    }
    // Frame identity = file-name stem (PROJECT §8.5 / §9). Computed here with
    // the UTF-8 -> wide conversion so non-ASCII (e.g. Chinese) file names do
    // not go through the ANSI codepage.
    cloud.frame_id = toUtf8(utf8Path(path).stem());
    return cloud;
}

void writePointCloud(const std::string& path, const core::PointCloudData& cloud,
                     const WriteOptions& options) {
    Format fmt = options.format;
    if (fmt == Format::Auto) fmt = formatFromPath(path);
    switch (fmt) {
        case Format::Pcd: writePcd(path, cloud, options.target_unit); return;
        case Format::Ply: writePly(path, cloud, options.target_unit); return;
        case Format::Xyz: writeDelimited(path, cloud, options.target_unit, false); return;
        case Format::Csv: writeDelimited(path, cloud, options.target_unit, true); return;
        case Format::Auto:
            throw IoError("cannot determine format from extension: " + path);
    }
}

}  // namespace pcsearch::io
