// ---------------------------------------------------------------------------
// UiComposite.cs
// Purpose : Lays a UI Toolkit panel's texture over the camera's picture on the CPU the way the GPU does when the
//           panel draws on the screen, so a capture (GameKitCapture, the F8 bug report's screenshot) matches what a
//           player sees (#277).
// Usage   : byte[] picture = cameraShot.GetRawTextureData();     // RGB24 (3 bytes a pixel) or RGBA32 (4)
//           byte[] layer = panelShot.GetRawTextureData();         // RGBA32, read from PanelSettings.targetTexture
//           UiComposite.Over(picture, w, h, 3, layer, lw, lh, panelTexture.sRGB);
//           cameraShot.LoadRawTextureData(picture); cameraShot.Apply();
// Notes   : No UnityEngine types (EditMode tests run it). UI Toolkit draws with premultiplied alpha (blend One
//           OneMinusSrcAlpha), and the panel's texture is cleared to transparent black, so a pixel holds
//           colour * alpha, not the colour: blending it again as straight alpha (colour * a + under * (1 - a))
//           darkens every soft edge, text most of all, and greys a translucent panel. When the texture is sRGB
//           (a Linear colour space project) the GPU blends in linear light and stores the result sRGB-encoded, so
//           the bytes are decoded, blended and encoded again; in a Gamma project they are blended as they are.
//           Checked against a windowed player's own screenshot (Direct3D 12, Unity 6000.6): every pixel within 1.
//           A layer of another size is stretched to the picture (nearest sampling). The picture stays opaque.
//           Opaque drops a screen capture's alpha (the F8 screenshot of a windowed player).
//
// Pseudocode:
//   for each picture pixel: the layer pixel under it (nearest) ; alpha 0 -> skip
//   gamma:  out = top + under * (1 - a)
//   linear: out = encode(decode(top) + decode(under) * (1 - a))      (sRGB transfer function both ways)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): Opaque (#283)
// ---------------------------------------------------------------------------
using System;

namespace graveyard_shift.Core
{
    public static class UiComposite
    {
        private static readonly double[] ToLinear = BuildDecodeTable();

        /// <summary>One channel: a premultiplied UI value (top, with the layer's alpha) over an opaque picture value.
        /// linearLight: the panel's texture is sRGB (blend in linear light, as the GPU does).</summary>
        public static byte Over(byte under, byte top, byte alpha, bool linearLight)
        {
            double rest = 1.0 - alpha / 255.0;
            if (!linearLight)
            {
                return ToByte((top + under * rest) / 255.0);
            }
            return ToByte(Encode(ToLinear[top] + ToLinear[under] * rest));
        }

        /// <summary>The whole layer over the picture, in place. picture: bottom-up rows of channels (3 or 4) bytes a
        /// pixel, as Texture2D raw data (RGB24, RGBA32); layer: RGBA32 of its own size, stretched to the picture.</summary>
        public static void Over(byte[] picture, int width, int height, int channels, byte[] layer, int layerWidth,
                                int layerHeight, bool linearLight)
        {
            if (picture == null || layer == null)
            {
                throw new ArgumentNullException(picture == null ? nameof(picture) : nameof(layer));
            }
            if (channels != 3 && channels != 4)
            {
                throw new ArgumentException($"channels is {channels}: 3 (RGB24) or 4 (RGBA32)", nameof(channels));
            }
            if (picture.Length < width * height * channels || layer.Length < layerWidth * layerHeight * 4)
            {
                throw new ArgumentException("an array is smaller than its width x height");
            }
            for (int y = 0; y < height; y++)
            {
                int sy = y * layerHeight / height;
                for (int x = 0; x < width; x++)
                {
                    int t = (sy * layerWidth + x * layerWidth / width) * 4;
                    byte a = layer[t + 3];
                    if (a == 0)
                    {
                        continue;
                    }
                    int i = (y * width + x) * channels;
                    for (int c = 0; c < 3; c++)
                    {
                        picture[i + c] = Over(picture[i + c], layer[t + c], a, linearLight);
                    }
                    if (channels == 4)
                    {
                        picture[i + 3] = 255;
                    }
                }
            }
        }

        /// <summary>Every pixel's alpha set to 255, in place (RGBA32 raw data). A screen capture holds the back
        /// buffer's alpha, which is whatever the camera cleared to and the game drew, not how the screen looks:
        /// saved as is, a PNG of a game that clears to alpha 0 is see-through (#283).</summary>
        public static void Opaque(byte[] rgba)
        {
            if (rgba == null)
            {
                throw new ArgumentNullException(nameof(rgba));
            }
            for (int i = 3; i < rgba.Length; i += 4)
            {
                rgba[i] = 255;
            }
        }

        /// <summary>sRGB-encoded 0..1 to linear light (the IEC 61966-2-1 curve).</summary>
        public static double Decode(double v)
        {
            return v <= 0.04045 ? v / 12.92 : Math.Pow((v + 0.055) / 1.055, 2.4);
        }

        /// <summary>Linear light 0..1 to sRGB-encoded 0..1.</summary>
        public static double Encode(double v)
        {
            if (v <= 0.0)
            {
                return 0.0;
            }
            if (v >= 1.0)
            {
                return 1.0;
            }
            return v <= 0.0031308 ? v * 12.92 : 1.055 * Math.Pow(v, 1.0 / 2.4) - 0.055;
        }

        private static byte ToByte(double v)
        {
            return (byte)Math.Round(Math.Max(0.0, Math.Min(1.0, v)) * 255.0, MidpointRounding.AwayFromZero);
        }

        private static double[] BuildDecodeTable()
        {
            var table = new double[256];
            for (int i = 0; i < 256; i++)
            {
                table[i] = Decode(i / 255.0);
            }
            return table;
        }
    }
}
