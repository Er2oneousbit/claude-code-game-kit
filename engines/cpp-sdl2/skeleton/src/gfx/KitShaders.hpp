// ---------------------------------------------------------------------------
// KitShaders.hpp
// Purpose : The kit's shader recipes on SDL3's GPU renderer: one KitShader per recipe wraps the compiled fragment
//           shader (shaders/kit/<name>.frag.<format>, next to the exe) in an SDL_GPURenderState.
// Usage   :   auto flash = gfx::KitShader::load(renderer, "flash");      // nullptr: no GPU renderer (logged)
//             kit_shaders::FlashParams p;  p.amount.x = 1.0f;  flash->set_params(&p, sizeof p);
//             flash->begin(renderer);  SDL_RenderTexture(renderer, sprite, nullptr, &dst);  flash->end(renderer);
//           A recipe with a second picture takes it at load: KitShader::load(renderer, "dissolve", noise_texture).
// Notes   : Needs the renderer SDL_GPU_RENDERER ("gpu"), which main.cpp asks for outside smoke runs; the software
//           renderer of a headless smoke run has no shaders (load returns nullptr, so code must cope with that).
//           The format follows the device: SPIR-V (Vulkan), DXIL (D3D12) or MSL (Metal), all three built by
//           CMakeLists.txt with shadercross. Coordinates run 0 to 1 over the drawn texture (image space).
//           Each recipe's GPU shader is compiled once per device and kept until release_kit_shaders(): SDL 3.4.12's
//           GPU renderer caches pipelines by shader address, and a shader released and another made at the same
//           address drew the old effect (seen in the kit's shader check). Render states come and go freely.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <SDL3/SDL.h>

#include <memory>
#include <string>

namespace gfx {

class KitShader {
public:
    // Loads recipe `name` for `renderer`; `aux` is the second picture of recipes that take one (dissolve's noise,
    // palette_swap's palette, triplanar's tile, sprite_light's normal map). nullptr on failure, with the reason logged.
    static std::unique_ptr<KitShader> load(SDL_Renderer* renderer, const std::string& name, SDL_Texture* aux = nullptr);

    // The recipe's kit_shaders::<Name>Params (shaders/kit/kit_shaders.hpp), copied for the following draws.
    bool set_params(const void* params, Uint32 size);

    // Draw calls between begin() and end() run through the recipe.
    void begin(SDL_Renderer* renderer) const;
    static void end(SDL_Renderer* renderer);

    ~KitShader();
    KitShader(const KitShader&) = delete;
    KitShader& operator=(const KitShader&) = delete;

private:
    KitShader() = default;
    SDL_GPUDevice* device_ = nullptr;
    SDL_GPUSampler* aux_sampler_ = nullptr;
    SDL_GPURenderState* state_ = nullptr;
};

// Creates the GPU renderer the recipes need (vsync on), or nullptr when this machine has no GPU backend
// (then SDL_CreateRenderer(window, nullptr) is the fallback, without shaders).
SDL_Renderer* create_gpu_renderer(SDL_Window* window);

// Releases the recipes' GPU shaders kept for `renderer`'s device. Call it before SDL_DestroyRenderer, after the last
// KitShader of that renderer is gone (main.cpp's renderer deleter does).
void release_kit_shaders(SDL_Renderer* renderer);

}  // namespace gfx

// {{FOOTER}}
