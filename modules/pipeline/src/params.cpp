#include "pcsearch/pipeline/params.h"

#include <cmath>
#include <stdexcept>

namespace pcsearch::pipeline {

namespace {

double toDouble(const ParamValue& v) {
    if (std::holds_alternative<double>(v)) return std::get<double>(v);
    if (std::holds_alternative<int>(v)) return static_cast<double>(std::get<int>(v));
    if (std::holds_alternative<bool>(v)) return std::get<bool>(v) ? 1.0 : 0.0;
    return std::stod(std::get<std::string>(v));
}

int toInt(const ParamValue& v) {
    if (std::holds_alternative<int>(v)) return std::get<int>(v);
    return static_cast<int>(std::llround(toDouble(v)));
}

}  // namespace

const ParamDef& Params::def(const std::string& name) const {
    for (const auto& d : defs_) {
        if (d.name == name) return d;
    }
    throw ParamsError("unknown parameter: " + name);
}

namespace {

// Normalize a declared default value to the variant alternative that matches
// the parameter type. Guards against helpers that forget to populate
// `default_value` (e.g. a File param defaulting to a double would make the UI
// throw std::bad_variant_access when rendering the editor).
ParamValue defaultForType(const ParamDef& d) {
    switch (d.type) {
        case ParamType::Double:
            return std::holds_alternative<double>(d.default_value)
                       ? d.default_value
                       : ParamValue{toDouble(d.default_value)};
        case ParamType::Int:
            return std::holds_alternative<int>(d.default_value)
                       ? d.default_value
                       : ParamValue{toInt(d.default_value)};
        case ParamType::Bool:
            return std::holds_alternative<bool>(d.default_value)
                       ? d.default_value
                       : ParamValue{toDouble(d.default_value) != 0.0};
        case ParamType::String:
        case ParamType::File:
        case ParamType::Directory:
            return std::holds_alternative<std::string>(d.default_value)
                       ? d.default_value
                       : ParamValue{std::string{}};
        case ParamType::Enum:
            if (std::holds_alternative<std::string>(d.default_value)) {
                return d.default_value;
            }
            return d.enum_values.empty() ? ParamValue{std::string{}}
                                         : ParamValue{d.enum_values.front()};
    }
    return d.default_value;
}

}  // namespace

void Params::define(const std::vector<ParamDef>& defs) {
    defs_ = defs;
    for (const auto& d : defs_) {
        if (!values_.count(d.name)) {
            values_[d.name] = defaultForType(d);
        }
    }
}

bool Params::has(const std::string& name) const { return values_.count(name) > 0; }
bool Params::isDefined(const std::string& name) const {
    for (const auto& d : defs_) {
        if (d.name == name) return true;
    }
    return false;
}

void Params::set(const std::string& name, ParamValue value) {
    const ParamDef& d = def(name);
    switch (d.type) {
        case ParamType::Double: {
            const double v = toDouble(value);
            // NaN/Inf must never enter parameters: NaN passes a naive range
            // check (every comparison is false) and later shows up as garbage
            // (e.g. ±1e9 after UI clamping) or an invisible box.
            if (!std::isfinite(v) || v < d.dmin || v > d.dmax) {
                throw ParamsError("parameter out of range: " + name);
            }
            values_[name] = v;
            break;
        }
        case ParamType::Int: {
            const int v = toInt(value);
            if (v < d.imin || v > d.imax) {
                throw ParamsError("parameter out of range: " + name);
            }
            values_[name] = v;
            break;
        }
        case ParamType::Bool: values_[name] = toDouble(value) != 0.0; break;
        case ParamType::String:
        case ParamType::File:
        case ParamType::Directory: values_[name] = std::get<std::string>(value); break;
        case ParamType::Enum: {
            const std::string s = std::get<std::string>(value);
            for (const auto& e : d.enum_values) {
                if (e == s) {
                    values_[name] = s;
                    return;
                }
            }
            throw ParamsError("invalid enum value for " + name + ": " + s);
        }
    }
}

double Params::getDouble(const std::string& name) const {
    return toDouble(values_.at(name));
}

int Params::getInt(const std::string& name) const { return toInt(values_.at(name)); }

bool Params::getBool(const std::string& name) const {
    return toDouble(values_.at(name)) != 0.0;
}

std::string Params::getString(const std::string& name) const {
    const auto& v = values_.at(name);
    if (std::holds_alternative<std::string>(v)) return std::get<std::string>(v);
    if (std::holds_alternative<double>(v)) return std::to_string(std::get<double>(v));
    if (std::holds_alternative<int>(v)) return std::to_string(std::get<int>(v));
    return std::get<bool>(v) ? "true" : "false";
}

std::string Params::getEnum(const std::string& name) const {
    const auto& v = values_.at(name);
    return std::get<std::string>(v);
}

}  // namespace pcsearch::pipeline
