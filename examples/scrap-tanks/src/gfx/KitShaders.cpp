// ---------------------------------------------------------------------------
// KitShaders.cpp
// Purpose : Loads the kit's compiled shader recipes into SDL_GPURenderState objects (see KitShaders.hpp).
// Notes   : Pseudocode for load()
//             device = the renderer's GPU device (none: not the GPU renderer -> nullptr)
//             format = the first of SPIR-V, DXIL, MSL the device takes -> file shaders/kit/<name>.frag.<ext>
//             fragment shader: 1 sampler (the drawn texture) + 1 for an aux picture, 1 uniform buffer
//             render state: the shader plus the aux picture as an extra sampler binding (nearest, clamped)
//           The GPU shaders live in a per-device cache until release_kit_shaders() (KitShaders.hpp says why).
//           MSL's entry point is main0: SPIRV-Cross renames main while translating (verify on Metal).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "gfx/KitShaders.hpp"

#include "core/Log.hpp"

#include <map>
#include <tuple>

namespace gfx {

namespace {

constexpr const char* kShaderFolder = "shaders/kit/";   // next to the exe (CMakeLists.txt copies it there)

struct Format {
    SDL_GPUShaderFormat flag;
    const char* extension;
    const char* entrypoint;
};
constexpr Format kFormats[] = {
    {SDL_GPU_SHADERFORMAT_SPIRV, "spv", "main"},
    {SDL_GPU_SHADERFORMAT_DXIL, "dxil", "main"},
    {SDL_GPU_SHADERFORMAT_MSL, "msl", "main0"},
};

// (device, recipe, has aux) -> its GPU shader, kept for the device's life
std::map<std::tuple<SDL_GPUDevice*, std::string, bool>, SDL_GPUShader*>& shader_cache() {
    static std::map<std::tuple<SDL_GPUDevice*, std::string, bool>, SDL_GPUShader*> cache;
    return cache;
}

}  // namespace

std::unique_ptr<KitShader> KitShader::load(SDL_Renderer* renderer, const std::string& name, SDL_Texture* aux) {
    SDL_GPUDevice* device = renderer ? SDL_GetGPURendererDevice(renderer) : nullptr;
    if (!device) {
        LOG_WARN("gfx", "shader " << name << ": not the GPU renderer, so no shaders");
        return nullptr;
    }
    const SDL_GPUShaderFormat formats = SDL_GetGPUShaderFormats(device);
    const Format* format = nullptr;
    for (const Format& f : kFormats) {
        if (formats & f.flag) {
            format = &f;
            break;
        }
    }
    if (!format) {
        LOG_ERROR("gfx", "shader " << name << ": the GPU device takes none of SPIR-V, DXIL, MSL");
        return nullptr;
    }
    SDL_GPUShader*& shader = shader_cache()[std::make_tuple(device, name, aux != nullptr)];
    if (!shader) {
        const char* base = SDL_GetBasePath();   // owned by SDL; nullptr when the platform cannot say
        const std::string path = std::string(base ? base : "") + kShaderFolder + name + ".frag." + format->extension;
        size_t size = 0;
        void* code = SDL_LoadFile(path.c_str(), &size);
        if (!code) {
            LOG_ERROR("gfx", "shader " << name << ": cannot read " << path << ": " << SDL_GetError());
            return nullptr;
        }
        SDL_GPUShaderCreateInfo info{};
        info.code_size = size;
        info.code = static_cast<const Uint8*>(code);
        info.entrypoint = format->entrypoint;
        info.format = format->flag;
        info.stage = SDL_GPU_SHADERSTAGE_FRAGMENT;
        info.num_samplers = aux ? 2 : 1;
        info.num_uniform_buffers = 1;
        shader = SDL_CreateGPUShader(device, &info);
        SDL_free(code);
        if (!shader) {
            LOG_ERROR("gfx", "shader " << name << ": " << SDL_GetError());
            return nullptr;
        }
    }
    std::unique_ptr<KitShader> kit(new KitShader());
    kit->device_ = device;
    SDL_GPURenderStateCreateInfo state{};
    state.fragment_shader = shader;
    SDL_GPUTextureSamplerBinding binding{};
    if (aux) {
        auto* texture = static_cast<SDL_GPUTexture*>(
            SDL_GetPointerProperty(SDL_GetTextureProperties(aux), SDL_PROP_TEXTURE_GPU_TEXTURE_POINTER, nullptr));
        if (!texture) {
            LOG_ERROR("gfx", "shader " << name << ": the aux picture is not a GPU renderer texture");
            return nullptr;
        }
        SDL_GPUSamplerCreateInfo sampler{};
        sampler.min_filter = SDL_GPU_FILTER_NEAREST;
        sampler.mag_filter = SDL_GPU_FILTER_NEAREST;
        sampler.mipmap_mode = SDL_GPU_SAMPLERMIPMAPMODE_NEAREST;
        sampler.address_mode_u = SDL_GPU_SAMPLERADDRESSMODE_CLAMP_TO_EDGE;
        sampler.address_mode_v = SDL_GPU_SAMPLERADDRESSMODE_CLAMP_TO_EDGE;
        sampler.address_mode_w = SDL_GPU_SAMPLERADDRESSMODE_CLAMP_TO_EDGE;
        kit->aux_sampler_ = SDL_CreateGPUSampler(device, &sampler);
        if (!kit->aux_sampler_) {
            LOG_ERROR("gfx", "shader " << name << ": " << SDL_GetError());
            return nullptr;
        }
        binding.texture = texture;
        binding.sampler = kit->aux_sampler_;
        state.num_sampler_bindings = 1;
        state.sampler_bindings = &binding;
    }
    kit->state_ = SDL_CreateGPURenderState(renderer, &state);
    if (!kit->state_) {
        LOG_ERROR("gfx", "shader " << name << ": " << SDL_GetError());
        return nullptr;
    }
    return kit;
}

bool KitShader::set_params(const void* params, Uint32 size) {
    return SDL_SetGPURenderStateFragmentUniforms(state_, 0, params, size);
}

void KitShader::begin(SDL_Renderer* renderer) const {
    SDL_SetGPURenderState(renderer, state_);
}

void KitShader::end(SDL_Renderer* renderer) {
    SDL_SetGPURenderState(renderer, nullptr);
}

KitShader::~KitShader() {
    if (state_) SDL_DestroyGPURenderState(state_);
    if (aux_sampler_) SDL_ReleaseGPUSampler(device_, aux_sampler_);
}

void release_kit_shaders(SDL_Renderer* renderer) {
    SDL_GPUDevice* device = renderer ? SDL_GetGPURendererDevice(renderer) : nullptr;
    if (!device) {
        return;
    }
    auto& cache = shader_cache();
    for (auto it = cache.begin(); it != cache.end();) {
        if (std::get<0>(it->first) == device) {
            if (it->second) SDL_ReleaseGPUShader(device, it->second);
            it = cache.erase(it);
        } else {
            ++it;
        }
    }
}

SDL_Renderer* create_gpu_renderer(SDL_Window* window) {
    SDL_PropertiesID props = SDL_CreateProperties();
    SDL_SetStringProperty(props, SDL_PROP_RENDERER_CREATE_NAME_STRING, SDL_GPU_RENDERER);
    SDL_SetPointerProperty(props, SDL_PROP_RENDERER_CREATE_WINDOW_POINTER, window);
    SDL_SetBooleanProperty(props, SDL_PROP_RENDERER_CREATE_GPU_SHADERS_SPIRV_BOOLEAN, true);
    SDL_SetBooleanProperty(props, SDL_PROP_RENDERER_CREATE_GPU_SHADERS_DXIL_BOOLEAN, true);
    SDL_SetBooleanProperty(props, SDL_PROP_RENDERER_CREATE_GPU_SHADERS_MSL_BOOLEAN, true);
    SDL_SetNumberProperty(props, SDL_PROP_RENDERER_CREATE_PRESENT_VSYNC_NUMBER, 1);
    SDL_Renderer* renderer = SDL_CreateRendererWithProperties(props);
    SDL_DestroyProperties(props);
    return renderer;
}

}  // namespace gfx
