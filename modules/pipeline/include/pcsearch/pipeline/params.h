#pragma once

#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <variant>
#include <vector>

namespace pcsearch::pipeline {

enum class ParamType { Double, Int, Bool, String, Enum, File, Directory };

using ParamValue = std::variant<double, int, bool, std::string>;

struct ParamDef {
    std::string name;
    ParamType type = ParamType::Double;
    std::string label;
    std::string unit;
    std::string description;
    // Default value applied when the parameter is first defined. Helpers such
    // as doubleParam(..., dflt, ...) populate this; it is what users see
    // before any explicit set.
    ParamValue default_value = 0.0;
    double dmin = -std::numeric_limits<double>::max();
    double dmax = std::numeric_limits<double>::max();
    int imin = std::numeric_limits<int>::min();
    int imax = std::numeric_limits<int>::max();
    std::vector<std::string> enum_values;
};

class ParamsError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

class Params {
public:
    void define(const std::vector<ParamDef>& defs);

    bool has(const std::string& name) const;
    bool isDefined(const std::string& name) const;

    void set(const std::string& name, ParamValue value);
    double getDouble(const std::string& name) const;
    int getInt(const std::string& name) const;
    bool getBool(const std::string& name) const;
    std::string getString(const std::string& name) const;
    std::string getEnum(const std::string& name) const;

    const std::vector<ParamDef>& defs() const { return defs_; }
    const std::map<std::string, ParamValue>& values() const { return values_; }

private:
    const ParamDef& def(const std::string& name) const;

    std::vector<ParamDef> defs_;
    std::map<std::string, ParamValue> values_;
};

}  // namespace pcsearch::pipeline
