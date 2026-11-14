// ---------------------------------------------------------------------------
// CaptureFormat.hpp
// Purpose : Which picture format a capture file name asks for (#314): `.png` is PNG, `.bmp` is BMP (letter case
//           ignored), anything else is refused. main.cpp checks --screenshot with it at startup, and
//           shell::save_frame (shell/Draw.cpp) picks SDL_SavePNG or SDL_SaveBMP with it.
// Usage   : if (core::capture_format_of("captures/a.png") == core::CaptureFormat::png) ...
//           core::capture_formats_help() names the accepted extensions for an error message.
// Notes   : Header-only, no SDL (tests/test_capture_format.cpp). Before #314 every capture was BMP bytes whatever
//           the name, so a .png file held a BMP. tools/dev.py refuses the same extensions before the build.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <cctype>
#include <string>

namespace core {

enum class CaptureFormat { unknown, png, bmp };

// The format a file name's extension names; unknown for any other extension or none ("shot", "shot.", "a.png/").
inline CaptureFormat capture_format_of(const std::string& path) {
    const auto slash = path.find_last_of("/\\");
    const auto dot = path.find_last_of('.');
    if (dot == std::string::npos || (slash != std::string::npos && dot < slash)) {
        return CaptureFormat::unknown;
    }
    std::string ext = path.substr(dot + 1);
    for (char& c : ext) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    if (ext == "png") return CaptureFormat::png;
    if (ext == "bmp") return CaptureFormat::bmp;
    return CaptureFormat::unknown;
}

inline const char* capture_formats_help() {
    return ".png (PNG) or .bmp (BMP)";
}

}  // namespace core
