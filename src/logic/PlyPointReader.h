#pragma once

#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

// Minimal PLY vertex reader: extracts x/y/z only, in the unit stored in the
// file (RVC saves point clouds in millimeters).  Handles ascii and
// binary_little_endian / binary_big_endian files with the common scalar
// property types.  All non-vertex elements (e.g. faces) and non-xyz vertex
// properties are skipped.
namespace PlyPointReader {

struct Result {
    bool ok = false;
    std::string error;
    std::vector<double> xyz;   // n*3, in file units
};

namespace detail {

enum class Format { Ascii, BinaryLittle, BinaryBig };

struct Property {
    std::string name;
    int size = 0;   // bytes per scalar
    int num = 1;    // list not supported; always 1 here
};

int typeSize(const std::string& type)
{
    if (type == "char" || type == "int8" || type == "uchar"
            || type == "uint8")
        return 1;
    if (type == "short" || type == "int16" || type == "ushort"
            || type == "uint16")
        return 2;
    if (type == "int" || type == "int32" || type == "uint"
            || type == "uint32" || type == "float" || type == "float32")
        return 4;
    if (type == "double" || type == "float64")
        return 8;
    return 0;   // unsupported (e.g. list properties)
}

double readScalar(const unsigned char* b, int size, Format fmt)
{
    if (fmt == Format::Ascii)
        return 0.0;   // handled separately
    if (size == 4) {
        std::uint32_t raw = 0;
        if (fmt == Format::BinaryLittle) {
            raw = static_cast<std::uint32_t>(b[0])
                | (static_cast<std::uint32_t>(b[1]) << 8)
                | (static_cast<std::uint32_t>(b[2]) << 16)
                | (static_cast<std::uint32_t>(b[3]) << 24);
        } else {
            raw = (static_cast<std::uint32_t>(b[0]) << 24)
                | (static_cast<std::uint32_t>(b[1]) << 16)
                | (static_cast<std::uint32_t>(b[2]) << 8)
                | static_cast<std::uint32_t>(b[3]);
        }
        float f = 0.0f;
        static_assert(sizeof(f) == 4, "float must be 4 bytes");
        std::memcpy(&f, &raw, 4);
        return static_cast<double>(f);
    }
    if (size == 8) {
        std::uint64_t raw = 0;
        if (fmt == Format::BinaryLittle) {
            for (int i = 0; i < 8; ++i)
                raw |= static_cast<std::uint64_t>(b[i]) << (8 * i);
        } else {
            for (int i = 0; i < 8; ++i)
                raw |= static_cast<std::uint64_t>(b[i]) << (8 * (7 - i));
        }
        double d = 0.0;
        std::memcpy(&d, &raw, 8);
        return d;
    }
    return 0.0;   // ints not needed for x/y/z of our files
}

} // namespace detail

inline Result read(const std::string& path)
{
    Result r;
    std::ifstream f(path, std::ios::binary);
    if (!f) {
        r.error = "cannot open file";
        return r;
    }

    std::string line;
    if (!std::getline(f, line)) {
        r.error = "not a PLY file (missing 'ply' magic)";
        return r;
    }
    if (!line.empty() && line.back() == '\r')
        line.pop_back();   // tolerate CRLF files
    if (line != "ply") {
        r.error = "not a PLY file (missing 'ply' magic)";
        return r;
    }

    detail::Format fmt = detail::Format::Ascii;
    long long vertexCount = -1;
    bool inVertex = false;   // only collect properties while inside "element vertex"
    std::vector<detail::Property> vertexProps;
    bool headerDone = false;
    while (std::getline(f, line)) {
        if (!line.empty() && line.back() == '\r')
            line.pop_back();
        std::istringstream ls(line);
        std::string token;
        ls >> token;
        if (token == "format") {
            std::string name;
            ls >> name;
            if (name == "ascii")
                fmt = detail::Format::Ascii;
            else if (name == "binary_little_endian")
                fmt = detail::Format::BinaryLittle;
            else if (name == "binary_big_endian")
                fmt = detail::Format::BinaryBig;
            else {
                r.error = "unsupported PLY format";
                return r;
            }
        } else if (token == "element") {
            std::string name;
            long long count = 0;
            ls >> name >> count;
            inVertex = (name == "vertex");
            if (inVertex)
                vertexCount = count;
            // non-vertex elements are skipped entirely
        } else if (token == "property") {
            if (inVertex) {
                std::string type, name;
                ls >> type >> name;
                detail::Property p;
                p.name = name;
                p.size = detail::typeSize(type);
                if (p.size > 0)
                    vertexProps.push_back(p);
            }
        } else if (token == "end_header") {
            headerDone = true;
            break;
        }
    }
    if (!headerDone || vertexCount < 0) {
        r.error = "invalid PLY header";
        return r;
    }

    // Locate x/y/z offsets (binary record) and property indices (ascii).
    int offX = -1, offY = -1, offZ = -1;
    int idxX = -1, idxY = -1, idxZ = -1;
    int recordSize = 0;
    for (std::size_t i = 0; i < vertexProps.size(); ++i) {
        const auto& p = vertexProps[i];
        if (p.size == 0) {
            r.error = "unsupported list property on vertex element";
            return r;
        }
        if (p.name == "x") { offX = recordSize; idxX = static_cast<int>(i); }
        else if (p.name == "y") { offY = recordSize; idxY = static_cast<int>(i); }
        else if (p.name == "z") { offZ = recordSize; idxZ = static_cast<int>(i); }
        recordSize += p.size;
    }
    if (offX < 0 || offY < 0 || offZ < 0 || recordSize <= 0
            || idxX < 0 || idxY < 0 || idxZ < 0) {
        r.error = "missing x/y/z vertex properties";
        return r;
    }

    r.xyz.reserve(static_cast<std::size_t>(vertexCount) * 3);
    if (fmt == detail::Format::Ascii) {
        std::string word;
        std::vector<std::string> props;   // per vertex in header order
        long long vertices = 0;
        while (f >> word) {
            props.push_back(word);
            if (props.size() == static_cast<std::size_t>(vertexProps.size())) {
                if (vertices < vertexCount) {
                    const double x = std::strtod(props[idxX].c_str(), nullptr);
                    const double y = std::strtod(props[idxY].c_str(), nullptr);
                    const double z = std::strtod(props[idxZ].c_str(), nullptr);
                    r.xyz.push_back(x);
                    r.xyz.push_back(y);
                    r.xyz.push_back(z);
                    ++vertices;
                }
                props.clear();
            }
        }
        if (vertices != vertexCount) {
            r.error = "vertex count mismatch";
            return r;
        }
    } else {
        std::vector<unsigned char> record(static_cast<std::size_t>(recordSize));
        for (long long i = 0; i < vertexCount; ++i) {
            if (!f.read(reinterpret_cast<char*>(record.data()), record.size())) {
                r.error = "truncated vertex data";
                return r;
            }
            r.xyz.push_back(detail::readScalar(&record[offX], vertexProps[idxX].size, fmt));
            r.xyz.push_back(detail::readScalar(&record[offY], vertexProps[idxY].size, fmt));
            r.xyz.push_back(detail::readScalar(&record[offZ], vertexProps[idxZ].size, fmt));
        }
    }
    r.ok = true;
    return r;
}

} // namespace PlyPointReader
