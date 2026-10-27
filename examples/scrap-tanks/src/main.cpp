// ---------------------------------------------------------------------------
// main.cpp
// Purpose : Program entry. Parses args, sets up SDL, runs the fixed-step loop.
// Usage   : scrap_tanks [--debug] [--smoke N] [--screenshot FILE] [--record DIR] [--version] [--help] [-- game args]
//             --debug     verbose logging (LOG_DEBUG lines)
//             --smoke N   run N frames headless (dummy video/audio, software
//                         renderer), print BOOT_OK and exit 0. Used by dev.py smoke.
//             --screenshot FILE  save the last frame as BMP;  --record DIR  save every Nth frame
//                         (--record-every N, default 4) as BMP for tools/art/frames_to_gif.py
//             --          everything after it goes to Game::configure() (autoplay, cheats, seeds),
//                         so games add their own options without editing this file
// Notes   : Must be `int main(int, char**)` and include <SDL.h> here so SDL's
//           main redirection works on Windows. RAII wrappers below guarantee
//           destroy order: renderer, window, then SDL_Quit.
//
// Pseudocode:
//   parse args (main's own, then `--` game args) -> (smoke? set dummy drivers) -> SDL_Init
//   -> create window + renderer (RAII) -> loop:
//        poll events -> steps = timestep.advance(frame_dt)
//        run `steps` updates -> render -> (smoke: count frames, exit at N)
//        (screenshot / record: read the frame back before presenting)
//   -> RAII cleanup
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// Updated : 2026-10-21 with Claude (Opus 5.5, claude-opus-5-5): strict --smoke parsing (1..100000);
//           in smoke mode, MSVC assert/CRT reports go to stderr instead of a modal dialog
// ---------------------------------------------------------------------------
#include <SDL.h>

#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

#if defined(_WIN32) && defined(_DEBUG)
#include <crtdbg.h>
#endif

#include "core/FixedTimestep.hpp"
#include "core/Log.hpp"
#include "game/Game.hpp"

namespace {

// Tunables: window size, the logical resolution the game draws in, and the simulation rate
constexpr int kWindowWidth = 1280;
constexpr int kWindowHeight = 720;
constexpr double kTickSeconds = 1.0 / 60.0;

// RAII deleters so SDL objects are always destroyed, even on early return.
struct WindowDeleter   { void operator()(SDL_Window* w) const   { if (w) SDL_DestroyWindow(w); } };
struct RendererDeleter { void operator()(SDL_Renderer* r) const { if (r) SDL_DestroyRenderer(r); } };
using WindowPtr   = std::unique_ptr<SDL_Window, WindowDeleter>;
using RendererPtr = std::unique_ptr<SDL_Renderer, RendererDeleter>;

// Keeps SDL_Quit() last: declared first in main, so destroyed last.
struct SdlSession {
    bool ok = false;
    explicit SdlSession(Uint32 flags) : ok(SDL_Init(flags) == 0) {}
    ~SdlSession() { if (ok) SDL_Quit(); }
};

constexpr long kMaxSmokeFrames = 100000;  // matches dev.py's --frames bound

struct Options {
    bool debug = false;
    int smoke_frames = 0;  // 0 = normal interactive run
    bool help = false;
    bool version = false;
    std::string screenshot;          // save the last frame here (BMP)
    std::string record_dir;          // save frames here (BMP)
    int record_every = 4;            // ... every Nth frame
    std::vector<std::string> game_args;  // after `--`, for Game::configure()
};

void print_help() {
    std::cout << "Scrap Tanks " GAME_VERSION "\n"
                 "Usage: scrap_tanks [options] [-- game options]\n"
                 "  --debug            verbose logging\n"
                 "  --smoke N          run N frames headless and exit (used by dev.py smoke)\n"
                 "  --screenshot FILE  save the last frame as BMP\n"
                 "  --record DIR       save frames as BMP (--record-every N, default 4)\n"
                 "  --version          print the version\n"
                 "  --help             show this help\n"
                 "Game options (after --):\n" << game::Game::options_help();
}

// Returns false on a malformed argument (message already logged).
bool parse_args(int argc, char** argv, Options& opts) {
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--debug") == 0) {
            opts.debug = true;
        } else if (std::strcmp(argv[i], "--help") == 0 || std::strcmp(argv[i], "-h") == 0) {
            opts.help = true;
        } else if (std::strcmp(argv[i], "--version") == 0) {
            opts.version = true;
        } else if (std::strcmp(argv[i], "--") == 0) {
            opts.game_args.assign(argv + i + 1, argv + argc);
            break;
        } else if ((std::strcmp(argv[i], "--screenshot") == 0 || std::strcmp(argv[i], "--record") == 0) && i + 1 < argc) {
            (argv[i][2] == 's' ? opts.screenshot : opts.record_dir) = argv[i + 1];
            ++i;
        } else if (std::strcmp(argv[i], "--record-every") == 0 && i + 1 < argc) {
            opts.record_every = std::atoi(argv[++i]);
            if (opts.record_every < 1) {
                LOG_ERROR("core", "--record-every needs a number of frames, 1 or more");
                return false;
            }
        } else if (std::strcmp(argv[i], "--smoke") == 0) {
            if (i + 1 >= argc) {
                LOG_ERROR("core", "--smoke needs a frame count, e.g. --smoke 120");
                return false;
            }
            // strtol, not atoi: atoi accepts "5x" and overflows into a run that never ends
            const char* text = argv[++i];
            char* end = nullptr;
            errno = 0;
            const long n = std::strtol(text, &end, 10);
            if (errno != 0 || end == text || *end != '\0' || n < 1 || n > kMaxSmokeFrames) {
                LOG_ERROR("core", "--smoke needs a whole number from 1 to " << kMaxSmokeFrames << ", got: " << text);
                return false;
            }
            opts.smoke_frames = static_cast<int>(n);
        } else {
            LOG_ERROR("core", "unknown argument: " << argv[i] << " (try --help)");
            return false;
        }
    }
    return true;
}

// Headless runs have nobody to click a dialog. Route Debug-build assert and CRT reports to stderr,
// so a failed assert ends the run with "Assertion failed" (which dev.py smoke scans for) instead of hanging.
void route_crash_reports_to_stderr() {
#ifdef _WIN32
#ifdef _DEBUG
    for (int type : {_CRT_WARN, _CRT_ERROR, _CRT_ASSERT}) {
        _CrtSetReportMode(type, _CRTDBG_MODE_FILE);
        _CrtSetReportFile(type, _CRTDBG_FILE_STDERR);
    }
#endif
    _set_error_mode(_OUT_TO_STDERR);
    _set_abort_behavior(0, _WRITE_ABORT_MSG | _CALL_REPORTFAULT);
#endif
}

// Saves what the renderer drew this frame as a BMP (call before SDL_RenderPresent). SDL alone writes BMP;
// tools/art/frames_to_gif.py reads it.
bool save_frame(SDL_Renderer* renderer, const std::string& path) {
    int w = 0;
    int h = 0;
    if (SDL_GetRendererOutputSize(renderer, &w, &h) != 0) {
        return false;
    }
    SDL_Surface* surface = SDL_CreateRGBSurfaceWithFormat(0, w, h, 32, SDL_PIXELFORMAT_ARGB8888);
    if (!surface) {
        return false;
    }
    // Read in output pixels: switch off the logical scaling for the read, then restore it
    int lw = 0;
    int lh = 0;
    SDL_RenderGetLogicalSize(renderer, &lw, &lh);
    SDL_RenderSetLogicalSize(renderer, 0, 0);
    const bool ok = SDL_RenderReadPixels(renderer, nullptr, SDL_PIXELFORMAT_ARGB8888, surface->pixels, surface->pitch) == 0
                    && SDL_SaveBMP(surface, path.c_str()) == 0;
    SDL_RenderSetLogicalSize(renderer, lw, lh);
    SDL_FreeSurface(surface);
    return ok;
}

void set_env(const char* key, const char* value) {
#ifdef _WIN32
    _putenv_s(key, value);
#else
    setenv(key, value, 1);
#endif
}

}  // namespace

int main(int argc, char** argv) {
    Options opts;
    if (!parse_args(argc, argv, opts)) {
        return 2;
    }
    if (opts.help) {
        print_help();
        return 0;
    }
    if (opts.version) {
        std::cout << "Scrap Tanks " << GAME_VERSION << "\n";
        return 0;
    }
    core::Log::set_debug(opts.debug);
    const bool smoke = opts.smoke_frames > 0;

    // Headless: no window system or audio device needed (CI, dev.py smoke).
    if (smoke) {
        route_crash_reports_to_stderr();
        set_env("SDL_VIDEODRIVER", "dummy");
        set_env("SDL_AUDIODRIVER", "dummy");
    }

    SdlSession sdl(SDL_INIT_VIDEO | SDL_INIT_EVENTS);
    if (!sdl.ok) {
        LOG_ERROR("core", "SDL_Init failed: " << SDL_GetError());
        return 1;
    }

    WindowPtr window(SDL_CreateWindow("Scrap Tanks", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                                      kWindowWidth, kWindowHeight, SDL_WINDOW_RESIZABLE));
    if (!window) {
        LOG_ERROR("core", "SDL_CreateWindow failed: " << SDL_GetError());
        return 1;
    }

    // Hardware renderer fails under the dummy driver, so smoke uses software.
    const Uint32 renderer_flags = smoke ? SDL_RENDERER_SOFTWARE
                                        : (SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    RendererPtr renderer(SDL_CreateRenderer(window.get(), -1, renderer_flags));
    if (!renderer) {
        LOG_ERROR("core", "SDL_CreateRenderer failed: " << SDL_GetError());
        return 1;
    }
    // Game logic runs in its own logical space (Game::kWidth x kHeight), SDL scales it to the window.
    SDL_RenderSetLogicalSize(renderer.get(), game::Game::kWidth, game::Game::kHeight);

    game::Game game;
    if (!game.configure(opts.game_args)) {
        return 2;  // Game::configure logged what was wrong
    }
    if (!opts.record_dir.empty()) {
        std::error_code ec;
        std::filesystem::create_directories(opts.record_dir, ec);
    }
    core::FixedTimestep timestep(kTickSeconds);

    LOG_INFO("core", "BOOT_OK Scrap Tanks v" << GAME_VERSION);

    const double freq = static_cast<double>(SDL_GetPerformanceFrequency());
    Uint64 last = SDL_GetPerformanceCounter();
    int frames = 0;

    while (!game.quit_requested()) {
        SDL_Event event;
        while (SDL_PollEvent(&event)) {
            game.handle_event(event);
        }

        const Uint64 now = SDL_GetPerformanceCounter();
        // Smoke runs unthrottled (no vsync), so wall-clock time would give only a few updates in N frames:
        // feed exactly one tick per frame there, so N smoke frames always mean N game updates.
        const double frame_dt = smoke ? timestep.step() : static_cast<double>(now - last) / freq;
        last = now;

        const int steps = timestep.advance(frame_dt);
        for (int i = 0; i < steps; ++i) {
            game.update(timestep.step());
        }
        if (timestep.dropped_time()) {
            LOG_DEBUG("core", "simulation fell behind, dropped time");
        }

        game.render(renderer.get());
        const bool last_frame = smoke && (frames + 1 >= opts.smoke_frames || game.quit_requested());
        if (!opts.record_dir.empty() && frames % opts.record_every == 0) {
            char name[32];
            std::snprintf(name, sizeof name, "frame_%06d.bmp", frames);
            if (!save_frame(renderer.get(), (std::filesystem::path(opts.record_dir) / name).string())) {
                LOG_WARN("core", "could not record frame " << frames << ": " << SDL_GetError());
            }
        }
        if (!opts.screenshot.empty() && (last_frame || (!smoke && game.quit_requested()))) {
            if (!save_frame(renderer.get(), opts.screenshot)) {
                LOG_ERROR("core", "screenshot failed: " << SDL_GetError());
            }
        }
        SDL_RenderPresent(renderer.get());

        ++frames;
        if (smoke && frames >= opts.smoke_frames) {
            LOG_INFO("core", "smoke complete after " << frames << " frames");
            break;
        }
    }
    return 0;
}
