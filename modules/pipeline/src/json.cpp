#include "pcsearch/pipeline/json.h"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <sstream>

namespace pcsearch::pipeline::json {

namespace {

const char* skipWs(const char* p, const char* end) {
    while (p < end && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')) ++p;
    return p;
}

class Parser {
public:
    explicit Parser(const std::string& text) : text_(text) {}

    Value parseDocument() {
        const Value v = parseValue();
        const char* p = skipWs(pos_, end_);
        if (p != end_) throw JsonError("trailing characters after JSON value");
        return v;
    }

private:
    Value parseValue() {
        const char* p = skipWs(pos_, end_);
        if (p >= end_) throw JsonError("unexpected end of input");
        switch (*p) {
            case '{': return parseObject();
            case '[': return parseArray();
            case '"': return Value::string(parseString());
            case 't':
                consume("true");
                return Value::boolean(true);
            case 'f':
                consume("false");
                return Value::boolean(false);
            case 'n':
                consume("null");
                return Value::null();
            default: return parseNumber();
        }
    }

    void consume(const char* word) {
        const std::size_t n = std::strlen(word);
        if (static_cast<std::size_t>(end_ - pos_) < n ||
            std::strncmp(pos_, word, n) != 0) {
            throw JsonError("invalid literal");
        }
        pos_ += n;
    }

    Value parseObject() {
        Value obj = Value::object();
        ++pos_;  // {
        pos_ = skipWs(pos_, end_);
        if (pos_ < end_ && *pos_ == '}') {
            ++pos_;
            return obj;
        }
        while (true) {
            pos_ = skipWs(pos_, end_);
            if (pos_ >= end_ || *pos_ != '"') throw JsonError("expected object key");
            std::string key = parseString();
            pos_ = skipWs(pos_, end_);
            if (pos_ >= end_ || *pos_ != ':') throw JsonError("expected ':'");
            ++pos_;
            obj.asObject()[key] = parseValue();
            pos_ = skipWs(pos_, end_);
            if (pos_ >= end_) throw JsonError("unterminated object");
            if (*pos_ == ',') {
                ++pos_;
                continue;
            }
            if (*pos_ == '}') {
                ++pos_;
                return obj;
            }
            throw JsonError("expected ',' or '}'");
        }
    }

    Value parseArray() {
        Value arr = Value::array();
        ++pos_;  // [
        pos_ = skipWs(pos_, end_);
        if (pos_ < end_ && *pos_ == ']') {
            ++pos_;
            return arr;
        }
        while (true) {
            arr.asArray().push_back(parseValue());
            pos_ = skipWs(pos_, end_);
            if (pos_ >= end_) throw JsonError("unterminated array");
            if (*pos_ == ',') {
                ++pos_;
                continue;
            }
            if (*pos_ == ']') {
                ++pos_;
                return arr;
            }
            throw JsonError("expected ',' or ']'");
        }
    }

    std::string parseString() {
        if (pos_ >= end_ || *pos_ != '"') throw JsonError("expected string");
        ++pos_;
        std::string out;
        while (pos_ < end_) {
            const char c = *pos_;
            if (c == '"') {
                ++pos_;
                return out;
            }
            if (c == '\\') {
                ++pos_;
                if (pos_ >= end_) throw JsonError("unterminated escape");
                const char e = *pos_++;
                switch (e) {
                    case '"': out.push_back('"'); break;
                    case '\\': out.push_back('\\'); break;
                    case '/': out.push_back('/'); break;
                    case 'b': out.push_back('\b'); break;
                    case 'f': out.push_back('\f'); break;
                    case 'n': out.push_back('\n'); break;
                    case 'r': out.push_back('\r'); break;
                    case 't': out.push_back('\t'); break;
                    case 'u': {
                        if (end_ - pos_ < 4) throw JsonError("bad \\u escape");
                        unsigned code = 0;
                        for (int i = 0; i < 4; ++i) {
                            const char h = pos_[i];
                            code <<= 4;
                            if (h >= '0' && h <= '9') code |= static_cast<unsigned>(h - '0');
                            else if (h >= 'a' && h <= 'f') code |= static_cast<unsigned>(h - 'a' + 10);
                            else if (h >= 'A' && h <= 'F') code |= static_cast<unsigned>(h - 'A' + 10);
                            else throw JsonError("bad \\u escape");
                        }
                        pos_ += 4;
                        if (code >= 0xD800 && code <= 0xDBFF && end_ - pos_ >= 6 &&
                            pos_[0] == '\\' && pos_[1] == 'u') {
                            unsigned lo = 0;
                            for (int i = 0; i < 4; ++i) {
                                const char h = pos_[2 + i];
                                lo <<= 4;
                                if (h >= '0' && h <= '9') lo |= static_cast<unsigned>(h - '0');
                                else if (h >= 'a' && h <= 'f') lo |= static_cast<unsigned>(h - 'a' + 10);
                                else if (h >= 'A' && h <= 'F') lo |= static_cast<unsigned>(h - 'A' + 10);
                                else throw JsonError("bad \\u escape");
                            }
                            pos_ += 6;
                            code = 0x10000 + ((code - 0xD800) << 10) + (lo - 0xDC00);
                        }
                        if (code < 0x80) {
                            out.push_back(static_cast<char>(code));
                        } else if (code < 0x800) {
                            out.push_back(static_cast<char>(0xC0 | (code >> 6)));
                            out.push_back(static_cast<char>(0x80 | (code & 0x3F)));
                        } else {
                            out.push_back(static_cast<char>(0xE0 | (code >> 12)));
                            out.push_back(static_cast<char>(0x80 | ((code >> 6) & 0x3F)));
                            out.push_back(static_cast<char>(0x80 | (code & 0x3F)));
                        }
                        break;
                    }
                    default: throw JsonError("unknown escape");
                }
                continue;
            }
            if (static_cast<unsigned char>(c) < 0x20) throw JsonError("control char in string");
            out.push_back(c);
            ++pos_;
        }
        throw JsonError("unterminated string");
    }

    Value parseNumber() {
        const char* start = skipWs(pos_, end_);
        const char* p = start;
        if (p < end_ && (*p == '-' || *p == '+')) ++p;
        bool has_digit = false;
        while (p < end_ && *p >= '0' && *p <= '9') {
            ++p;
            has_digit = true;
        }
        if (p < end_ && *p == '.') {
            ++p;
            while (p < end_ && *p >= '0' && *p <= '9') {
                ++p;
                has_digit = true;
            }
        }
        if (!has_digit) throw JsonError("invalid number");
        if (p < end_ && (*p == 'e' || *p == 'E')) {
            ++p;
            if (p < end_ && (*p == '-' || *p == '+')) ++p;
            bool exp_digit = false;
            while (p < end_ && *p >= '0' && *p <= '9') {
                ++p;
                exp_digit = true;
            }
            if (!exp_digit) throw JsonError("invalid exponent");
        }
        const std::string token(start, static_cast<std::size_t>(p - start));
        pos_ = p;
        return Value::number(std::strtod(token.c_str(), nullptr));
    }

    const std::string& text_;
    const char* pos_ = text_.c_str();
    const char* end_ = pos_ + text_.size();
};

void dumpValue(const Value& v, std::string& out) {
    switch (v.type()) {
        case Type::Null: out += "null"; break;
        case Type::Bool: out += v.asBool() ? "true" : "false"; break;
        case Type::Number: {
            const double d = v.asNumber();
            if (std::isfinite(d) && d == std::floor(d) && std::abs(d) < 1e15) {
                out += std::to_string(static_cast<long long>(d));
            } else {
                std::ostringstream ss;
                ss << std::setprecision(15) << d;
                out += ss.str();
            }
            break;
        }
        case Type::String: out += '"' + escapeString(v.asString()) + '"'; break;
        case Type::Array: {
            out += '[';
            const auto& arr = v.asArray();
            for (std::size_t i = 0; i < arr.size(); ++i) {
                if (i) out += ',';
                dumpValue(arr[i], out);
            }
            out += ']';
            break;
        }
        case Type::Object: {
            out += '{';
            const auto& obj = v.asObject();
            std::size_t i = 0;
            for (const auto& [key, val] : obj) {
                if (i++) out += ',';
                out += '"' + escapeString(key) + "\":";
                dumpValue(val, out);
            }
            out += '}';
            break;
        }
    }
}

}  // namespace

Value Value::null() { return Value(); }
Value Value::boolean(bool b) {
    Value v;
    v.type_ = Type::Bool;
    v.bool_ = b;
    return v;
}
Value Value::number(double d) {
    Value v;
    v.type_ = Type::Number;
    v.number_ = d;
    return v;
}
Value Value::string(std::string s) {
    Value v;
    v.type_ = Type::String;
    v.string_ = std::move(s);
    return v;
}
Value Value::array() {
    Value v;
    v.type_ = Type::Array;
    return v;
}
Value Value::object() {
    Value v;
    v.type_ = Type::Object;
    return v;
}

bool Value::asBool() const {
    if (type_ != Type::Bool) throw JsonError("not a boolean");
    return bool_;
}

double Value::asNumber() const {
    if (type_ != Type::Number) throw JsonError("not a number");
    return number_;
}

const std::string& Value::asString() const {
    if (type_ != Type::String) throw JsonError("not a string");
    return string_;
}

const Value* Value::find(const std::string& key) const {
    const auto it = object_.find(key);
    return it == object_.end() ? nullptr : &it->second;
}

Value& Value::operator[](const std::string& key) {
    if (type_ == Type::Null) {
        type_ = Type::Object;
    }
    if (type_ != Type::Object) throw JsonError("not an object");
    return object_[key];
}

Value& Value::operator[](std::size_t index) {
    if (type_ == Type::Null) {
        type_ = Type::Array;
    }
    if (type_ != Type::Array) throw JsonError("not an array");
    if (index >= array_.size()) array_.resize(index + 1);
    return array_[index];
}

const Value& Value::operator[](const std::string& key) const {
    if (type_ != Type::Object) throw JsonError("not an object");
    const auto it = object_.find(key);
    if (it == object_.end()) throw JsonError("missing key: " + key);
    return it->second;
}

const Value& Value::operator[](std::size_t index) const {
    if (type_ != Type::Array) throw JsonError("not an array");
    if (index >= array_.size()) throw JsonError("array index out of range");
    return array_[index];
}

std::string Value::dump() const {
    std::string out;
    dumpValue(*this, out);
    return out;
}

Value Value::parse(const std::string& text) {
    Parser parser(text);
    return parser.parseDocument();
}

std::string escapeString(const std::string& s) {
    std::string out;
    out.reserve(s.size() + 8);
    for (const unsigned char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\b': out += "\\b"; break;
            case '\f': out += "\\f"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else {
                    out.push_back(static_cast<char>(c));
                }
        }
    }
    return out;
}

std::string unescapeString(const std::string& s) {
    return Value::parse('"' + escapeString(s) + '"').asString();
}

}  // namespace pcsearch::pipeline::json
