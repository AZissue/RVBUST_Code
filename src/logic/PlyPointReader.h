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

// Declared scalar type of a vertex property.  The bytes must be decoded
// according to this, not merely according to their width: an "int32 x"
// reinterpreted as an IEEE float is a silent, plausible-looking garbage value.
enum class Scalar {
    Unknown,
    Int8, Uint8,
    Int16, Uint16,
    Int32, Uint32,
    Int64, Uint64,
    Float32, Float64
};

struct Property {
    std::string name;
    int size = 0;                 // bytes per scalar
    Scalar kind = Scalar::Unknown;
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
    if (type == "double" || type == "float64" || type == "int64"
            || type == "uint64" || type == "long" || type == "ulong")
        return 8;
    return 0;   // unsupported (e.g. list properties)
}

// Same string set as typeSize(); kept in lockstep so a property's declared
// type and its byte width can never disagree.
Scalar typeKind(const std::string& type)
{
    if (type == "char" || type == "int8") return Scalar::Int8;
    if (type == "uchar" || type == "uint8") return Scalar::Uint8;
    if (type == "short" || type == "int16") return Scalar::Int16;
    if (type == "ushort" || type == "uint16") return Scalar::Uint16;
    if (type == "int" || type == "int32") return Scalar::Int32;
    if (type == "uint" || type == "uint32") return Scalar::Uint32;
    if (type == "int64" || type == "long") return Scalar::Int64;
    if (type == "uint64" || type == "ulong") return Scalar::Uint64;
    if (type == "float" || type == "float32") return Scalar::Float32;
    if (type == "double" || type == "float64") return Scalar::Float64;
    return Scalar::Unknown;
}

// Gather `size` bytes at b into a host-order unsigned integer, honouring the
// file's endianness.
std::uint64_t readRaw(const unsigned char* b, int size, Format fmt)
{
    std::uint64_t raw = 0;
    if (fmt == Format::BinaryLittle) {
        for (int i = 0; i < size; ++i)
            raw |= static_cast<std::uint64_t>(b[i]) << (8 * i);
    } else {
        for (int i = 0; i < size; ++i)
            raw |= static_cast<std::uint64_t>(b[size - 1 - i]) << (8 * i);
    }
    return raw;
}

// Decode one scalar by its declared type.  Signed integers are reinterpreted
// as two's complement via memcpy (the raw bits are already host-order).
double readScalar(const unsigned char* b, Scalar kind, Format fmt)
{
    if (fmt == Format::Ascii)
        return 0.0;   // handled separately
    switch (kind) {
    case Scalar::Int8: {
        const std::uint8_t raw = static_cast<std::uint8_t>(readRaw(b, 1, fmt));
        std::int8_t v = 0;
        std::memcpy(&v, &raw, 1);
        return static_cast<double>(v);
    }
    case Scalar::Uint8:
        return static_cast<double>(static_cast<std::uint8_t>(readRaw(b, 1, fmt)));
    case Scalar::Int16: {
        const std::uint16_t raw = static_cast<std::uint16_t>(readRaw(b, 2, fmt));
        std::int16_t v = 0;
        std::memcpy(&v, &raw, 2);
        return static_cast<double>(v);
    }
    case Scalar::Uint16:
        return static_cast<double>(static_cast<std::uint16_t>(readRaw(b, 2, fmt)));
    case Scalar::Int32: {
        const std::uint32_t raw = static_cast<std::uint32_t>(readRaw(b, 4, fmt));
        std::int32_t v = 0;
        std::memcpy(&v, &raw, 4);
        return static_cast<double>(v);
    }
    case Scalar::Uint32:
        return static_cast<double>(static_cast<std::uint32_t>(readRaw(b, 4, fmt)));
    case Scalar::Int64: {
        const std::uint64_t raw = readRaw(b, 8, fmt);
        std::int64_t v = 0;
        std::memcpy(&v, &raw, 8);
        return static_cast<double>(v);
    }
    case Scalar::Uint64:
        return static_cast<double>(readRaw(b, 8, fmt));
    case Scalar::Float32: {
        const std::uint32_t raw = static_cast<std::uint32_t>(readRaw(b, 4, fmt));
        float f = 0.0f;
        static_assert(sizeof(f) == 4, "float must be 4 bytes");
        std::memcpy(&f, &raw, 4);
        return static_cast<double>(f);
    }
    case Scalar::Float64: {
        const std::uint64_t raw = readRaw(b, 8, fmt);
        double d = 0.0;
        std::memcpy(&d, &raw, 8);
        return d;
    }
    default:
        return 0.0;
    }
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
                p.kind = detail::typeKind(type);
                // A vertex property we cannot size must not be dropped here:
                // it would be left out of recordSize, silently shifting every
                // later property's offset and decoding x/y/z from the wrong
                // bytes.  Refuse the file instead (only x/y/z are ever read,
                // but every property still occupies space in the record).
                if (type == "list") {
                    r.error = "unsupported list property on vertex element";
                    return r;
                }
                if (p.size <= 0 || p.kind == detail::Scalar::Unknown) {
                    r.error = "unsupported vertex property type: " + type;
                    return r;
                }
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

    // The header's claimed vertex count is untrusted input: a corrupt file, or
    // one produced by another tool, can claim far more vertices than the body
    // can possibly hold (e.g. "element vertex 99999999999").  Reserving memory
    // for such a claim would throw std::bad_alloc into callers that do not
    // guard against it, so reject the file here, before touching the vector.
    const std::streampos bodyStart = f.tellg();
    if (bodyStart < 0) {
        r.error = "claimed vertex count exceeds file size";
        return r;
    }
    f.seekg(0, std::ios::end);
    const std::streampos fileEnd = f.tellg();
    f.seekg(bodyStart);
    const long long remainingBytes =
        static_cast<long long>(fileEnd - bodyStart);
    // Lower bound on the bytes each vertex must occupy in the remaining body:
    //  - binary: every record is exactly recordSize bytes;
    //  - ascii:  every vertex has vertexProps.size() whitespace-separated
    //            tokens and each token is at least one byte.  The bound is
    //            conservative (a real vertex takes >= this), so extra trailing
    //            elements (faces, etc.) only make remainingBytes larger and
    //            never cause a good file to be rejected.
    const long long minBytesPerVertex =
        (fmt == detail::Format::Ascii)
            ? static_cast<long long>(vertexProps.size())
            : static_cast<long long>(recordSize);
    if (minBytesPerVertex <= 0
            || vertexCount > remainingBytes / minBytesPerVertex) {
        r.error = "claimed vertex count exceeds file size";
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
            r.xyz.push_back(detail::readScalar(&record[offX], vertexProps[idxX].kind, fmt));
            r.xyz.push_back(detail::readScalar(&record[offY], vertexProps[idxY].kind, fmt));
            r.xyz.push_back(detail::readScalar(&record[offZ], vertexProps[idxZ].kind, fmt));
        }
    }
    r.ok = true;
    return r;
}

} // namespace PlyPointReader
