#pragma once

#include <cctype>
#include <cstddef>
#include <cstdlib>
#include <string>
#include <vector>

// Parses ASCII comma/space-separated number lists pasted into text inputs.
// Chinese/full-width characters are rejected explicitly so the UI can prompt
// the user to switch to English separators.  No Qt/SDK dependency.
namespace ToolInputParser {

enum class ParseStatus {
    Ok,          // parsed exactly expectedCount numbers
    WrongCount,  // token count != expectedCount
    NonAscii,    // text contains non-ASCII chars (Chinese/full-width)
    InvalidToken // a token is not a parseable double
};

struct ParseResult {
    ParseStatus status = ParseStatus::Ok;
    std::vector<double> values;
    std::string badToken;      // offending token (InvalidToken) or raw text (NonAscii)
    std::size_t tokenCount = 0;
};

inline ParseResult parseNumberList(const std::string& text, std::size_t expectedCount)
{
    ParseResult r;

    for (unsigned char c : text)
        if (c > 0x7F) {
            r.status = ParseStatus::NonAscii;
            r.badToken = text;
            return r;
        }

    std::vector<std::string> tokens;
    std::string cur;
    for (char c : text) {
        if (c == ',' || std::isspace(static_cast<unsigned char>(c))) {
            if (!cur.empty()) {
                tokens.push_back(cur);
                cur.clear();
            }
        } else {
            cur.push_back(c);
        }
    }
    if (!cur.empty())
        tokens.push_back(cur);
    r.tokenCount = tokens.size();

    if (tokens.size() != expectedCount) {
        r.status = ParseStatus::WrongCount;
        return r;
    }

    r.values.reserve(tokens.size());
    for (const auto& t : tokens) {
        char* end = nullptr;
        const double v = std::strtod(t.c_str(), &end);
        if (end == t.c_str() || *end != '\0') {
            r.status = ParseStatus::InvalidToken;
            r.badToken = t;
            r.values.clear();
            return r;
        }
        r.values.push_back(v);
    }
    return r;
}

} // namespace ToolInputParser
