// ---------------------------------------------------------------------------
// main.cpp
// Purpose : Program entry. Parses args, sets up SDL, runs the fixed-step loop.
// Usage   : {{GAME_SLUG}} [--debug] [--smoke N] [--screenshot FILE] [--record DIR] [--version] [--help] [-- game args]
//             --debug     verbose logging (LOG_DEBUG lines)
//             --smoke N   run N frames headless (dummy video/audio, software
//                         renderer), print BOOT_OK and exit 0. Used by dev.py smoke.
//                         Outside smoke runs the renderer is SDL's GPU renderer, which runs the kit's
//                         shader recipes (src/gfx/KitShaders.hpp); without a GPU backend, the default one.
//             --screenshot FILE  save the last frame as BMP;  --record DIR  save every Nth frame
//                         (--record-every N, default 4) as BMP for tools/art/frames_to_gif.py
//             --          everything after it goes to Game::configure() (autoplay, cheats, seeds),
//                         so games add their own options without editing this file
// Notes   : Must be `int main(int, char**)` and include <SDL3/SDL_main.h> here so SDL's
//           main redirection works on Windows. RAII wrappers below guarantee
//           destroy order: renderer, window, then SDL_Quit.
//           Crash files (#275): an exception that reaches the top of the loop, an uncaught one anywhere
//           (std::terminate) and a fatal signal (a bad pointer, abort, a failed assert) write
//           crashes/crash_<time>.txt in the user-data folder (core/Report.hpp) and print CRASH_WRITTEN <path>;
//           the run exits 1 (a fatal signal keeps the signal's own exit). Outside smoke runs a message box says
//           where the file is.
//
// Pseudocode:
//   install the crash handlers -> parse args (main's own, then `--` game args) -> (smoke? set dummy drivers)
//   -> SDL_Init -> create window + renderer (RAII) -> loop (inside try):
//        poll events -> steps = timestep.advance(frame_dt)
//        run `steps` updates -> render -> (smoke: count frames, exit at N)
//        (screenshot / record: read the frame back before presenting)
//   -> an exception: crash file, CRASH_WRITTEN, (message box), exit 1
//   -> RAII cleanup
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// Updated : 2026-10-21 with Claude (Opus 5.5, claude-opus-5-5): strict --smoke parsing (1..100000);
//           in smoke mode, MSVC assert/CRT reports go to stderr instead of a modal dialog
// Updated : 2026-11-02 with Claude (Opus 5.5, claude-opus-5-5): a failed --record frame is an error; an
//           early quit in smoke mode says so ("smoke ended early"), for dev.py's end-of-run check
// Updated : 2026-11-06 with Claude (Opus 5.5, claude-opus-5-5): SDL3 (was SDL2); the GPU renderer outside smoke
// Updated : 2026-11-09 with Claude (Fable 5.1, claude-fable-5-1): gamepads; the game learns about a smoke run and is
//           set up after the renderer exists (the shell's screens, #168)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): crash files from the loop's exceptions, std::terminate
//           and fatal signals (#275); save_frame moved to shell/Draw.hpp (the F8 bug report uses it too)
// ---------------------------------------------------------------------------
#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>

#include <atomic>
#include <cerrno>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <filesystem>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

#if defined(_WIN32) && defined(_DEBUG)
#include <crtdbg.h>
#endif

#include "core/AtomicFile.hpp"
#include "core/FixedTimestep.hpp"
#include "core/Log.hpp"
#include "core/Report.hpp"
#include "game/Game.hpp"
#include "gfx/KitShaders.hpp"
#include "shell/Draw.hpp"

namespace {

// Tunables: window size, the logical resolution the game draws in, and the simulation rate
constexpr int kWindowWidth = 1280;
constexpr int kWindowHeight = 720;
constexpr double kTickSeconds = 1.0 / 60.0;

// RAII deleters so SDL objects are always destroyed, even on early return.
struct WindowDeleter   { void operator()(SDL_Window* w) const   { if (w) SDL_DestroyWindow(w); } };
struct RendererDeleter {
    void operator()(SDL_Renderer* r) const {
        if (r) {
            gfx::release_kit_shaders(r);   // the kit's shaders go before their device (gfx/KitShaders.hpp)
            SDL_DestroyRenderer(r);
        }
    }
};
using WindowPtr   = std::unique_ptr<SDL_Window, WindowDeleter>;
using RendererPtr = std::unique_ptr<SDL_Renderer, RendererDeleter>;

// Keeps SDL_Quit() last: declared first in main, so destroyed last.
struct SdlSession {
    bool ok = false;
    explicit SdlSession(SDL_InitFlags flags) : ok(SDL_Init(flags)) {}
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
    std::cout << "{{GAME_NAME}} " GAME_VERSION "\n"
                 "Usage: {{GAME_SLUG}} [options] [-- game options]\n"
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

// ---- Crash files (#275) --------------------------------------------------------------------------------------
std::atomic<bool> g_crashing{false};   // one crash file per run: a handler that runs during another does nothing

// Writes the crash file and says where: CRASH_WRITTEN <path> on stdout (dev.py smoke echoes it). Returns the path
// ("" when no file could be written; the [ERROR] line says why).
std::string report_crash(const std::string& error) {
    std::string why;
    const auto file = core::report::write_crash(error, false, &why);
    if (!file) {
        LOG_ERROR("core", "the game stopped: " << error << " (no crash file: " << why << ")");
        return "";
    }
    const std::string path = core::path_to_utf8(*file);
    std::cout << "CRASH_WRITTEN " << path << "\n" << std::flush;
    LOG_ERROR("core", "the game stopped: " << error << " (crash file " << path << ")");
    return path;
}

// std::terminate: an exception nobody caught (outside the loop, in a destructor, on another thread)
[[noreturn]] void on_terminate() {
    if (!g_crashing.exchange(true)) {
        std::string what = "std::terminate (no exception)";
        if (const std::exception_ptr ep = std::current_exception()) {
            try {
                std::rethrow_exception(ep);
            } catch (const std::exception& e) {
                what = std::string("uncaught exception: ") + e.what();
            } catch (...) {
                what = "uncaught exception of an unknown type";
            }
        }
        report_crash(what);
    }
    std::abort();
}

// A fatal signal: best effort (see core/Report.hpp), then the signal's default action ends the process
void on_fatal_signal(int sig) {
    if (!g_crashing.exchange(true)) {
        const char* name = sig == SIGSEGV ? "SIGSEGV (bad memory access)" : sig == SIGABRT ? "SIGABRT (abort, a failed assert)"
                         : sig == SIGFPE ? "SIGFPE (arithmetic error)" : sig == SIGILL ? "SIGILL (illegal instruction)" : "a signal";
        const auto file = core::report::write_crash(std::string("fatal signal ") + name, true);
        if (file) {
            std::fprintf(stdout, "CRASH_WRITTEN %s\n", core::path_to_utf8(*file).c_str());
            std::fflush(stdout);
        }
        std::fprintf(stderr, "[ERROR][core] the game stopped: fatal signal %s\n", name);
        std::fflush(stderr);
    }
    std::signal(sig, SIG_DFL);
    std::raise(sig);
}

void install_crash_handlers() {
    std::set_terminate(on_terminate);
    for (const int sig : {SIGSEGV, SIGABRT, SIGFPE, SIGILL}) {
        std::signal(sig, on_fatal_signal);
    }
}

// An exception reached the top of the loop: crash file, and outside smoke a message box that says where it is
int stop_on_exception(const std::string& error, SDL_Window* window, bool smoke) {
    g_crashing = true;
    const std::string path = report_crash(error);
    if (!smoke) {
        const std::string text = "The game stopped because of an error:\n" + error +
                                 (path.empty() ? std::string("\n\nNo crash file could be written (see the log).")
                                               : "\n\nA crash report was saved to:\n" + path +
                                                     "\n\nPlease attach it when you report the problem.");
        SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR, "{{GAME_NAME}}", text.c_str(), window);
    }
    return 1;
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
    install_crash_handlers();
    Options opts;
    if (!parse_args(argc, argv, opts)) {
        return 2;
    }
    if (opts.help) {
        print_help();
        return 0;
    }
    if (opts.version) {
        std::cout << "{{GAME_NAME}} " << GAME_VERSION << "\n";
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

    SdlSession sdl(SDL_INIT_VIDEO | SDL_INIT_EVENTS | SDL_INIT_GAMEPAD);
    if (!sdl.ok) {
        LOG_ERROR("core", "SDL_Init failed: " << SDL_GetError());
        return 1;
    }

    WindowPtr window(SDL_CreateWindow("{{GAME_NAME}}", kWindowWidth, kWindowHeight, SDL_WINDOW_RESIZABLE));
    if (!window) {
        LOG_ERROR("core", "SDL_CreateWindow failed: " << SDL_GetError());
        return 1;
    }

    // Hardware renderers fail under the dummy driver, so smoke uses software. Otherwise the GPU renderer (the
    // kit's shaders need it), else whatever SDL picks.
    RendererPtr renderer(smoke ? SDL_CreateRenderer(window.get(), SDL_SOFTWARE_RENDERER)
                               : gfx::create_gpu_renderer(window.get()));
    if (!renderer && !smoke) {
        LOG_WARN("core", "no GPU renderer (" << SDL_GetError() << "), so no shaders: using SDL's default");
        renderer.reset(SDL_CreateRenderer(window.get(), nullptr));
        if (renderer) {
            SDL_SetRenderVSync(renderer.get(), 1);
        }
    }
    if (!renderer) {
        LOG_ERROR("core", "SDL_CreateRenderer failed: " << SDL_GetError());
        return 1;
    }
    // Game logic runs in its own logical space (Game::kWidth x kHeight), SDL scales it to the window.
    SDL_SetRenderLogicalPresentation(renderer.get(), game::Game::kWidth, game::Game::kHeight,
                                     SDL_LOGICAL_PRESENTATION_LETTERBOX);

    game::Game game;
    game.set_automated(smoke);
    if (!game.configure(opts.game_args)) {
        return 2;  // Game::configure logged what was wrong
    }
    if (!game.init(window.get(), renderer.get())) {
        return 1;  // the shell logged what was wrong (settings folder, data files)
    }
    if (!opts.record_dir.empty()) {
        std::error_code ec;
        std::filesystem::create_directories(opts.record_dir, ec);
    }
    core::FixedTimestep timestep(kTickSeconds);

    LOG_INFO("core", "BOOT_OK {{GAME_NAME}} v" << GAME_VERSION);

    const double freq = static_cast<double>(SDL_GetPerformanceFrequency());
    Uint64 last = SDL_GetPerformanceCounter();
    int frames = 0;

    // The top of the loop: an exception from anywhere in a frame stops the game with a crash file (#275). A game
    // that can recover from an error catches it closer to where it happens.
    try {
        while (!game.quit_requested()) {
            SDL_Event event;
            while (SDL_PollEvent(&event)) {
                // Mouse positions in the game's logical space (SDL2's logical size did this by itself; SDL3 asks)
                SDL_ConvertEventToRenderCoordinates(renderer.get(), &event);
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
                if (!shell::save_frame(renderer.get(), (std::filesystem::path(opts.record_dir) / name).string())) {
                    LOG_ERROR("core", "could not record frame " << frames << ": " << SDL_GetError());
                }
            }
            if (!opts.screenshot.empty() && (last_frame || (!smoke && game.quit_requested()))) {
                if (!shell::save_frame(renderer.get(), opts.screenshot)) {
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
    } catch (const std::exception& e) {
        return stop_on_exception(std::string("exception: ") + e.what(), window.get(), smoke);
    } catch (...) {
        return stop_on_exception("an exception of an unknown type", window.get(), smoke);
    }
    if (smoke && frames < opts.smoke_frames) {
        // dev.py smoke passes this only when --until saw its marker: an early quit is not a full run
        LOG_INFO("core", "smoke ended early: the game quit after " << frames << " of " << opts.smoke_frames << " frames");
    }
    return 0;
}

// {{FOOTER}}
