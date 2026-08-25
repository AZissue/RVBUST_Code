#pragma once

#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace pcsearch::pipeline::json {

// Minimal JSON value type used for solution serialization. Intentionally
// dependency-free so the pipeline core stays usable headless (Qt-free).
enum class Type { Null, Bool, Number, String, Array, Object };

class JsonError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

class Value {
public:
    Value() = default;

    static Value null();
    static Value boolean(bool b);
    static Value number(double d);
    static Value string(std::string s);
    static Value array();
    static Value object();

    Type type() const { return type_; }
    bool isNull() const { return type_ == Type::Null; }
    bool isBool() const { return type_ == Type::Bool; }
    bool isNumber() const { return type_ == Type::Number; }
    bool isString() const { return type_ == Type::String; }
    bool isArray() const { return type_ == Type::Array; }
    bool isObject() const { return type_ == Type::Object; }

    bool asBool() const;
    double asNumber() const;
    const std::string& asString() const;
    const std::vector<Value>& asArray() const { return array_; }
    std::vector<Value>& asArray() { return array_; }
    const std::map<std::string, Value>& asObject() const { return object_; }
    std::map<std::string, Value>& asObject() { return object_; }

    const Value* find(const std::string& key) const;
    Value& operator[](const std::string& key);
    Value& operator[](std::size_t index);
    const Value& operator[](const std::string& key) const;
    const Value& operator[](std::size_t index) const;

    // Compact JSON text.
    std::string dump() const;
    // Parse JSON text; throws JsonError on malformed input.
    static Value parse(const std::string& text);

private:
    Type type_ = Type::Null;
    bool bool_ = false;
    double number_ = 0.0;
    std::string string_;
    std::vector<Value> array_;
    std::map<std::string, Value> object_;
};

std::string escapeString(const std::string& s);
std::string unescapeString(const std::string& s);

}  // namespace pcsearch::pipeline::json
