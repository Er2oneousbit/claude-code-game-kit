// ---------------------------------------------------------------------------
// DotworkSpritePhysics.cs
// Purpose : Gives the sprites of a Dotwork texture their custom physics shapes (the manifest's collision rects)
//           while Unity imports the PNG, so a TilemapCollider2D on a Dotwork tile uses exactly those rects.
// Usage   : automatic: DotworkImporter writes the rects into the PNG's TextureImporter.userData and reimports it
// Notes   : Sprite.OverridePhysicsShape called on the sprites an import makes is saved with the import, which
//           needs no package (the Sprite Editor data provider API lives in the 2D Sprite package, which an
//           adopt-first project has not). The rects are in each sprite's rect space (pixels, origin bottom-left),
//           converted by the importer. Textures without the importer's userData are left alone.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Dotwork
{
    public sealed class DotworkSpritePhysics : AssetPostprocessor
    {
        // ---- Tunables ------------------------------------------------------------
        private const uint VERSION = 1;               // bump to reimport every Dotwork texture after a change here

        public override uint GetVersion() => VERSION;

        private void OnPostprocessSprites(Texture2D texture, Sprite[] sprites)
        {
            var ti = assetImporter as TextureImporter;
            string data = ti != null ? ti.userData : null;
            if (string.IsNullOrEmpty(data) || !data.StartsWith(DotworkImporter.USERDATA_PREFIX, StringComparison.Ordinal))
            {
                return;
            }
            if (!Json.TryParse(data.Substring(DotworkImporter.USERDATA_PREFIX.Length), out object parsed)
                || !(Json.AsObject(parsed)?.TryGetValue("physics", out object p) == true) || !(p is Dictionary<string, object> physics))
            {
                Debug.LogWarning($"[WARN][dotwork] {assetPath}: unreadable importer data; no physics shapes set (run the import again)");
                return;
            }
            foreach (Sprite sprite in sprites)
            {
                if (!(physics.TryGetValue(sprite.name, out object rects) && rects is List<object> list) || list.Count == 0)
                {
                    continue;
                }
                var shapes = new List<Vector2[]>();
                foreach (object r in list)
                {
                    double[] v = DotworkManifest.Nums(r, 4);    // x0, y0, x1, y1
                    float x0 = (float)v[0], y0 = (float)v[1], x1 = (float)v[2], y1 = (float)v[3];
                    shapes.Add(new[] { new Vector2(x0, y0), new Vector2(x1, y0), new Vector2(x1, y1), new Vector2(x0, y1) });
                }
                sprite.OverridePhysicsShape(shapes);
            }
        }
    }
}
