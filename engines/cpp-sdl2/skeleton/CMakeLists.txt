# ---------------------------------------------------------------------------
# CMakeLists.txt
# Purpose : Build definition for {{GAME_NAME}} (C++17 + SDL2).
# Usage   : cmake --preset debug && cmake --build --preset debug
#           (or just: python tools/dev.py check)
# Notes   : Explicit source lists (no file(GLOB)) so adds/removes show up in diffs.
#           Layering: `core` (no SDL) <- `game_lib` (SDL) <- exe. Tests link `core` only.
#           Dependencies come from vcpkg.json via the toolchain file in CMakePresets.json.
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
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

# ---- core: SDL-free, header-only for now, unit tested ----
add_library(core INTERFACE)
target_include_directories(core INTERFACE ${CMAKE_SOURCE_DIR}/src)
target_link_libraries(core INTERFACE project_warnings)
# One source of truth for the version (SOP-06): project(... VERSION) above, readable in code as GAME_VERSION
target_compile_definitions(core INTERFACE GAME_VERSION="${PROJECT_VERSION}")

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
  )
  target_link_libraries(unit_tests PRIVATE core doctest::doctest)
  add_test(NAME unit_tests COMMAND unit_tests)
endif()

# {{FOOTER}}
