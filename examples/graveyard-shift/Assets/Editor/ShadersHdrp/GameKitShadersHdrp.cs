// ---------------------------------------------------------------------------
// GameKitShadersHdrp.cs
// Purpose : The HDRP part of the shader check (GameKitShaders.cs, #260): makes an HDRP camera draw a recipe's pixels
//           as the recipe returned them, so they can be compared with the golden image.
// Usage   : Called by GameKitShaders.DrawWithCamera through reflection (Game.ShadersHdrp.Editor is only compiled
//           when the HDRP package is installed, see Game.ShadersHdrp.Editor.asmdef), once per camera.
// Notes   : What HDRP does to a plain unlit pass, and what this undoes for the check (not for your game):
//             exposure    the colour buffer is pre-exposed: a global Volume with a Fixed exposure of EV100 -0.263
//                         makes the multiplier exactly 1 (exposure = 1 / (1.2 * 2^EV100))
//             post        the camera's custom frame settings turn Post Processing off (no tonemap, no dithering)
//             clear       the camera clears to a transparent colour
//             alpha       HDRP keeps the alpha channel only with an R16G16B16A16 colour buffer (the pipeline asset's
//                         setting, changed in memory for the check and put back; the file on disk is not touched)
//           The same recipes in a game under HDRP come out scaled by that game's exposure and tonemapped: the recipes
//           return display-referred colours, HDRP expects scene-referred ones. Set your own Volume's exposure,
//           or multiply the recipe's output by the exposure multiplier in your shader graph.
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// Updated : 2026-11-17 with Claude (Sonnet 5.5, claude-sonnet-5-5): new (#260)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

public static class GameKitShadersHdrp
{
    const float NeutralExposureEv100 = -0.263f;            // 1 / (1.2 * 2^-0.263) = 1.0

    static ColorBufferFormatHolder saved;                    // the asset's format before the check, put back by Restore

    class ColorBufferFormatHolder
    {
        public HDRenderPipelineAsset Asset;
        public RenderPipelineSettings.ColorBufferFormat Format;
    }

    /// Set the camera and the scene up for a faithful draw; `made` collects what the caller destroys afterwards.
    public static void Prepare(GameObject rig, List<Object> made)
    {
        if (!(GraphicsSettings.currentRenderPipeline is HDRenderPipelineAsset asset))
            return;
        var settings = asset.currentPlatformRenderPipelineSettings;
        if (settings.colorBufferFormat != RenderPipelineSettings.ColorBufferFormat.R16G16B16A16)
        {
            if (saved == null)
                saved = new ColorBufferFormatHolder { Asset = asset, Format = settings.colorBufferFormat };
            settings.colorBufferFormat = RenderPipelineSettings.ColorBufferFormat.R16G16B16A16;
            asset.currentPlatformRenderPipelineSettings = settings;
        }
        var data = rig.AddComponent<HDAdditionalCameraData>();
        data.clearColorMode = HDAdditionalCameraData.ClearColorMode.Color;
        data.backgroundColorHDR = new Color(0f, 0f, 0f, 0f);
        data.customRenderingSettings = true;
        data.renderingPathCustomFrameSettings.SetEnabled(FrameSettingsField.Postprocess, false);
        data.renderingPathCustomFrameSettingsOverrideMask.mask[(uint)FrameSettingsField.Postprocess] = true;
        var volumeObject = new GameObject("KitShaderExposure");
        made.Add(volumeObject);
        var volume = volumeObject.AddComponent<Volume>();
        volume.isGlobal = true;
        volume.priority = 1000f;
        var profile = ScriptableObject.CreateInstance<VolumeProfile>();
        made.Add(profile);
        var exposure = profile.Add<Exposure>(true);
        exposure.mode.Override(ExposureMode.Fixed);
        exposure.fixedExposure.Override(NeutralExposureEv100);
        volume.sharedProfile = profile;
    }

    /// Put the pipeline asset's colour buffer format back (called once, after the last recipe).
    public static void Restore()
    {
        if (saved == null)
            return;
        var settings = saved.Asset.currentPlatformRenderPipelineSettings;
        settings.colorBufferFormat = saved.Format;
        saved.Asset.currentPlatformRenderPipelineSettings = settings;
        saved = null;
    }
}
