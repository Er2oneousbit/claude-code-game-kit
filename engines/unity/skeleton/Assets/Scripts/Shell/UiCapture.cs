// ---------------------------------------------------------------------------
// UiCapture.cs
// Purpose : Lays a UI Toolkit panel's texture over a picture of the camera, so a screenshot taken without a screen
//           (batchmode, a capture, the F8 report with the panel in a texture) shows what a player sees (#277).
// Usage   : UiCapture.LayOver(picture, panelSettings.targetTexture);   // picture: RGB24 or RGBA32 Texture2D
// Notes   : The blend is Core/UiComposite (premultiplied alpha, in linear light when the panel's texture is sRGB),
//           checked against the GPU's own blend by GameKitCaptureTests. A panel texture of another size is
//           stretched to the picture. Does nothing for a missing or released texture.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using UnityEngine;
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Shell
{
    public static class UiCapture
    {
        /// <summary>The panel's texture over the picture, in place (the picture stays opaque).</summary>
        public static void LayOver(Texture2D picture, RenderTexture ui)
        {
            if (picture == null || ui == null || !ui.IsCreated())
            {
                return;
            }
            int channels = picture.format == TextureFormat.RGB24 ? 3 : picture.format == TextureFormat.RGBA32 ? 4 : 0;
            if (channels == 0)
            {
                throw new ArgumentException($"the picture is {picture.format}: RGB24 or RGBA32", nameof(picture));
            }
            var active = RenderTexture.active;
            RenderTexture.active = ui;
            var layer = new Texture2D(ui.width, ui.height, TextureFormat.RGBA32, false);
            layer.ReadPixels(new Rect(0, 0, ui.width, ui.height), 0, 0);
            RenderTexture.active = active;
            byte[] pixels = picture.GetRawTextureData();
            UiComposite.Over(pixels, picture.width, picture.height, channels, layer.GetRawTextureData(), ui.width, ui.height,
                             ui.sRGB);
            picture.LoadRawTextureData(pixels);
            picture.Apply();
            UnityEngine.Object.Destroy(layer);
        }
    }
}

// {{FOOTER}}
