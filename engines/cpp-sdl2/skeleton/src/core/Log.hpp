// ---------------------------------------------------------------------------
// Log.hpp
// Purpose : Minimal channel-based logger. Header-only, SDL-free, thread-unsafe
//           on purpose (single-threaded game loop). Greppable output format.
// Usage   : LOG_INFO("core", "started " << name);
//           LOG_ERROR("save", "failed to open " << path);
//           Log::set_debug(true) turns LOG_DEBUG output on (main.cpp --debug).
// Notes   : "[ERROR]" lines are what `dev.py smoke` scans for. Keep that tag.
//           Swap this for spdlog later if needed; call sites will not change.
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <iostream>
#include <sstream>
#include <string>

namespace core {

class Log {
public:
    enum class Level { Debug, Info, Warn, Error };

    static void set_debug(bool on) { debug_enabled() = on; }
    static bool is_debug() { return debug_enabled(); }

    // Writes one formatted line. Errors and warnings go to stderr, the rest to stdout.
    static void write(Level level, const std::string& channel, const std::string& msg) {
        if (level == Level::Debug && !debug_enabled()) {
            return;
        }
        std::ostream& out = (level >= Level::Warn) ? std::cerr : std::cout;
        out << '[' << tag(level) << "][" << channel << "] " << msg << '\n';
    }

private:
    // Function-local static avoids a separate .cpp for one flag.
    static bool& debug_enabled() {
        static bool flag = false;
        return flag;
    }

    static const char* tag(Level level) {
        switch (level) {
            case Level::Debug: return "DEBUG";
            case Level::Info:  return "INFO";
            case Level::Warn:  return "WARN";
            case Level::Error: return "ERROR";
        }
        return "?";
    }
};

}  // namespace core

#define CORE_LOG_(level, channel, expr)                    \
    do {                                                   \
        std::ostringstream core_log_stream_;               \
        core_log_stream_ << expr;                          \
        ::core::Log::write(level, channel, core_log_stream_.str()); \
    } while (0)

#define LOG_DEBUG(channel, expr) CORE_LOG_(::core::Log::Level::Debug, channel, expr)
#define LOG_INFO(channel, expr)  CORE_LOG_(::core::Log::Level::Info, channel, expr)
#define LOG_WARN(channel, expr)  CORE_LOG_(::core::Log::Level::Warn, channel, expr)
#define LOG_ERROR(channel, expr) CORE_LOG_(::core::Log::Level::Error, channel, expr)

// {{FOOTER}}
