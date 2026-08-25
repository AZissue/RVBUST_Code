#pragma once

// Technical runtime log.  Writes timestamped lines to stderr, which main.cpp
// redirects (unbuffered) to logs/runtime_<date>.log so crash tails survive.
// User-facing operations are logged separately by LogManager to app_<date>.log.
namespace RuntimeLog {
void log(const char* fmt, ...);
}
