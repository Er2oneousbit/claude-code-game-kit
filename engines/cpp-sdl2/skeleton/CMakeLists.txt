# ---------------------------------------------------------------------------
# CMakeLists.txt
# Purpose : Build definition for {{GAME_NAME}} (C++17 + SDL2).
# Usage   : cmake --preset debug && cmake --build --preset debug
#           (or just: python tools/dev.py check)
# Notes   : Explicit source lists (no file(GLOB)) so adds/removes show up in diffs.
#           Layering: `core` (no SDL) <- `game_lib` (SDL) <- exe. Tests link `core` only.
#           Dependencies come from vcpkg.json via the toolchain file in CMakePresets.json.
#           Each doctest TEST_CASE is its own CTest test (doctest_discover_tests), so `dev.py test` lists them;
#           the golden-vector tests read data/golden/*.json through the GOLDEN_DIR definition.
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# Updated : 2026-11-01 with Claude (Opus 5.5, claude-opus-5-5): core is a static library (juice and shell
#           logic, nlohmann-json), golden-vector and file tests, one CTest test per doctest case
# ---------------------------------------------------------------------------
cmake_minimum_required(VERSION 3.21)
project({{GAME_SLUG}} VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(BUILD_TESTS "Build unit tests" ON)
option(ENABLE_SANITIZERS "Enable ASan/UBSan (GCC/Clang only)" OFF)

# Single output folder for executables. Multi-config generators add a Debug/Release subfolder.
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

# ---- Warnings (applied via an interface target so every target gets them) ----
add_library(project_warnings INTERFACE)
if(MSVC)
  # /utf-8: sources (and the footer emoji) are UTF-8; without it MSVC on CJK code pages warns C4819 and garbles names
  target_compile_options(project_warnings INTERFACE /W4 /permissive- /utf-8)
else()
  target_compile_options(project_warnings INTERFACE -Wall -Wextra -Wpedantic)
  if(ENABLE_SANITIZERS)
    target_compile_options(project_warnings INTERFACE -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(project_warnings INTERFACE -fsanitize=address,undefined)
  endif()
endif()

# ---- core: SDL-free, unit tested (juice headers; settings, saves, bindings, i18n compiled here) ----
find_package(nlohmann_json CONFIG REQUIRED)

set(CORE_SOURCES
  src/core/AtomicFile.cpp
  src/core/Bindings.cpp
  src/core/I18n.cpp
  src/core/SaveStore.cpp
  src/core/Settings.cpp
)
add_library(core STATIC ${CORE_SOURCES})
target_include_directories(core PUBLIC ${CMAKE_SOURCE_DIR}/src)
target_link_libraries(core PUBLIC project_warnings nlohmann_json::nlohmann_json)
# One source of truth for the version (SOP-06): project(... VERSION) above, readable in code as GAME_VERSION
target_compile_definitions(core PUBLIC GAME_VERSION="${PROJECT_VERSION}")

# ---- game_lib: gameplay code that talks to SDL ----
find_package(SDL2 CONFIG REQUIRED)
# Optional add-ons (uncomment with matching vcpkg.json entries, record an ADR):
# find_package(SDL2_image CONFIG REQUIRED)
# find_package(SDL2_ttf CONFIG REQUIRED)
# find_package(SDL2_mixer CONFIG REQUIRED)

set(GAME_SOURCES
  src/game/Game.cpp
)
add_library(game_lib STATIC ${GAME_SOURCES})
target_link_libraries(game_lib PUBLIC core SDL2::SDL2)

# ---- executable ----
add_executable({{GAME_SLUG}} src/main.cpp)
# Release on Windows: a GUI-subsystem exe, so the shipped game does not open a console window.
# Debug keeps the console for logs and for dev.py smoke, which reads stdout.
set_target_properties({{GAME_SLUG}} PROPERTIES WIN32_EXECUTABLE $<CONFIG:Release>)
target_link_libraries({{GAME_SLUG}} PRIVATE game_lib)
if(TARGET SDL2::SDL2main)
  target_link_libraries({{GAME_SLUG}} PRIVATE SDL2::SDL2main)
endif()

# ---- tests ----
if(BUILD_TESTS)
  enable_testing()
  find_package(doctest CONFIG REQUIRED)
  add_executable(unit_tests
    tests/test_main.cpp
    tests/test_fixed_timestep.cpp
    tests/test_golden_vectors.cpp
    tests/test_shell_files.cpp
  )
  target_link_libraries(unit_tests PRIVATE core doctest::doctest)
  # The kit's golden vectors (reference: tools/golden_vectors.py). Override with -DGOLDEN_DIR=<folder>.
  set(GOLDEN_DIR "${CMAKE_SOURCE_DIR}/data/golden" CACHE PATH "Folder holding juice.json and shell.json")
  target_compile_definitions(unit_tests PRIVATE GOLDEN_DIR="${GOLDEN_DIR}")
  # One CTest test per TEST_CASE (listed at build time); without doctest's CMake module, one test for all
  if(EXISTS "${doctest_DIR}/doctest.cmake")
    include("${doctest_DIR}/doctest.cmake")
    doctest_discover_tests(unit_tests)
  else()
    add_test(NAME unit_tests COMMAND unit_tests)
  endif()
endif()

# {{FOOTER}}
