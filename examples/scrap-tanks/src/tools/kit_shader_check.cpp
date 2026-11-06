// ---------------------------------------------------------------------------
// kit_shader_check.cpp
// Purpose : Draws every kit shader recipe with SDL3's GPU renderer into a 64x64 target and saves <out>/<name>.png
//           for tools/shaders/shader_ref.py compare. `python tools/dev.py smoke --shaders` builds and runs it.
// Usage   : kit_shader_check <out folder>
// Exit    : 0 all drawn, 1 a recipe failed, 2 no GPU renderer here or no input pictures
// Notes   : Pseudocode
//             a hidden window and the GPU renderer (the recipes need its custom render states)
//             per recipe (shaders/kit/kit_shaders.hpp): its inputs from data/shaders/inputs (nearest), a 64x64
//             RGBA target texture cleared to transparent, blend mode none (the shader's output is written as is),
//             KitShader::begin, draw the main picture over the whole target, end, read back -> PNG
//           Prints SHADER_OK <name> / SHADER_FAIL <name> <why>, then SHADER_CHECK_DONE <recipes> <failed>.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>

#include <cstdio>
#include <filesystem>
#include <string>

#include "gfx/KitShaders.hpp"
#include "kit_shaders.hpp"

namespace {

constexpr int kSize = 64;   // the check canvas (tools/shaders/recipes.json)

// An input picture as a nearest-filtered texture ("sphere" is the sphere's normal map)
SDL_Texture* load_input(SDL_Renderer* renderer, const std::string& name) {
    const std::string file = std::string(KIT_INPUT_DIR) + "/" + (name == "sphere" ? "sphere_normal" : name) + ".png";
    SDL_Surface* loaded = SDL_LoadPNG(file.c_str());
    if (!loaded) {
        std::printf("[error] cannot read %s: %s\n", file.c_str(), SDL_GetError());
        return nullptr;
    }
    SDL_Surface* rgba = SDL_ConvertSurface(loaded, SDL_PIXELFORMAT_ABGR8888);   // bytes R, G, B, A
    SDL_DestroySurface(loaded);
    if (!rgba) {
        return nullptr;
    }
    SDL_Texture* texture = SDL_CreateTextureFromSurface(renderer, rgba);
    SDL_DestroySurface(rgba);
    if (texture) {
        SDL_SetTextureScaleMode(texture, SDL_SCALEMODE_NEAREST);
        SDL_SetTextureBlendMode(texture, SDL_BLENDMODE_NONE);
    }
    return texture;
}

std::string draw(SDL_Renderer* renderer, const kit_shaders::Recipe& recipe, const std::string& out) {
    SDL_Texture* main = load_input(renderer, recipe.main);
    SDL_Texture* aux = recipe.aux ? load_input(renderer, recipe.aux) : nullptr;
    if (!main || (recipe.aux && !aux)) {
        if (main) SDL_DestroyTexture(main);
        if (aux) SDL_DestroyTexture(aux);
        return "cannot load its input pictures";
    }
    std::string why;
    auto shader = gfx::KitShader::load(renderer, recipe.name, aux);
    SDL_Texture* target = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_ABGR8888, SDL_TEXTUREACCESS_TARGET, kSize, kSize);
    if (!shader) {
        why = "the shader did not load (see the error above)";
    } else if (!target) {
        why = std::string("no render target: ") + SDL_GetError();
    } else if (!shader->set_params(recipe.defaults, recipe.size)) {
        why = std::string("parameters: ") + SDL_GetError();
    } else {
        // Every call is checked: a draw that failed would leave the cleared target, which must not pass as a picture
        const SDL_FRect whole{0.0f, 0.0f, static_cast<float>(kSize), static_cast<float>(kSize)};
        bool drawn = SDL_SetRenderTarget(renderer, target) && SDL_SetRenderDrawColor(renderer, 0, 0, 0, 0) &&
                     SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_NONE) && SDL_RenderClear(renderer);
        if (drawn) {
            shader->begin(renderer);
            drawn = SDL_RenderTexture(renderer, main, nullptr, &whole);
            gfx::KitShader::end(renderer);
        }
        SDL_Surface* pixels = drawn ? SDL_RenderReadPixels(renderer, nullptr) : nullptr;
        if (!drawn) {
            why = std::string("draw: ") + SDL_GetError();
        }
        SDL_SetRenderTarget(renderer, nullptr);
        if (drawn && !pixels) {
            why = std::string("read back: ") + SDL_GetError();
        } else if (drawn) {
            // UTF-8 paths both ways (a project folder named José on Windows)
            const std::string file =
                (std::filesystem::u8path(out) / (std::string(recipe.name) + ".png")).u8string();
            if (!SDL_SavePNG(pixels, file.c_str())) {
                why = std::string("cannot write ") + file + ": " + SDL_GetError();
            }
            SDL_DestroySurface(pixels);
        }
    }
    shader.reset();
    if (target) SDL_DestroyTexture(target);
    if (aux) SDL_DestroyTexture(aux);
    SDL_DestroyTexture(main);
    return why;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::printf("usage: kit_shader_check <out folder>\n");
        return 2;
    }
    std::error_code ec;
    std::filesystem::create_directories(std::filesystem::u8path(argv[1]), ec);
    if (!SDL_Init(SDL_INIT_VIDEO)) {
        std::printf("[error] SDL_Init failed: %s\n", SDL_GetError());
        return 2;
    }
    SDL_Window* window = SDL_CreateWindow("kit_shader_check", kSize, kSize, SDL_WINDOW_HIDDEN);
    SDL_Renderer* renderer = window ? gfx::create_gpu_renderer(window) : nullptr;
    if (!renderer) {
        std::printf("[error] no GPU renderer on this machine (%s): the recipes need SDL's GPU backend\n", SDL_GetError());
        SDL_Quit();
        return 2;
    }
    // Which backend ran the check (SDL_GPU_DRIVER=vulkan|direct3d12|metal picks one)
    std::printf("[info] GPU driver: %s\n", SDL_GetGPUDeviceDriver(SDL_GetGPURendererDevice(renderer)));
    int failed = 0;
    for (const kit_shaders::Recipe& recipe : kit_shaders::kRecipes) {
        const std::string why = draw(renderer, recipe, argv[1]);
        if (why.empty()) {
            std::printf("SHADER_OK %s\n", recipe.name);
        } else {
            ++failed;
            std::printf("SHADER_FAIL %s %s\n", recipe.name, why.c_str());
        }
    }
    const int count = static_cast<int>(sizeof kit_shaders::kRecipes / sizeof kit_shaders::kRecipes[0]);
    std::printf("SHADER_CHECK_DONE %d %d\n", count, failed);
    std::fflush(stdout);
    gfx::release_kit_shaders(renderer);
    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return failed ? 1 : 0;
}
