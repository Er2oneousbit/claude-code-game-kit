// ---------------------------------------------------------------------------
// DotworkVerify.cs
// Purpose : Does every Dotwork manifest of the game load? Its files (missing, not a PNG, a rect outside its
//           image, an unknown tileset) and its import in Unity (missing, older than the manifest, an asset of the
//           manifest left out, a broken reference). The stand-in for Dotwork's Godot `verify`.
// Usage   : DotworkVerify.Problems("Assets/dotwork/town.assets.json")   -> [] when all is well
//           (GameKitDotwork.Verify runs it for every manifest; DotworkImportTests.EveryManifestInTheGameLoads too)
// Notes   : The file checks are the importer's plan pass (DotworkImporter.Check), so the verify and the import
//           can never disagree about what a manifest needs. Each problem names the fix where there is one.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace {{GAME_SLUG}}.Dotwork
{
    public static class DotworkVerify
    {
        // ---- Tunables ------------------------------------------------------------
        public const string FIX = "python tools/dev.py exec GameKitDotwork.ImportAll";

        /// <summary>The output folder of a manifest: Assets/dotwork/&lt;pack&gt; beside it.</summary>
        public static string OutDir(string manifestPath, string pack) => $"{DotworkManifest.DirOf(manifestPath)}/{pack}";

        public static string PackPath(string manifestPath, string pack) => $"{OutDir(manifestPath, pack)}/{pack}.asset";

        public static List<string> Problems(string manifestPath)
        {
            List<string> problems = DotworkImporter.Check(manifestPath).Select(p => $"{manifestPath}: {p}").ToList();
            DotworkManifest m;
            try
            {
                m = DotworkManifest.Load(manifestPath);
            }
            catch (DotworkImportException)
            {
                return problems;                                // Check reported it
            }
            string packPath = PackPath(manifestPath, m.Pack);
            var pack = AssetDatabase.LoadAssetAtPath<DotworkPack>(packPath);
            if (pack == null)
            {
                problems.Add($"{manifestPath}: not imported ({packPath} is missing): {FIX}");
                return problems;
            }
            if (pack.manifestHash != m.Hash)
            {
                problems.Add($"{manifestPath}: changed since it was imported: {FIX}");
            }
            foreach (Dictionary<string, object> a in m.Assets)
            {
                string kind = DotworkManifest.Str(a, "kind", ""), name = DotworkManifest.Str(a, "name", "");
                if (Array.IndexOf(DotworkManifest.CORE_KINDS, kind) >= 0 && !HasEntry(pack, kind, name))
                {
                    problems.Add($"{manifestPath}: {kind}/{name} is not in the import: {FIX}");
                }
            }
            problems.AddRange(BrokenReferences(pack).Select(p => $"{packPath}: {p}"));
            return problems;
        }

        public static bool HasEntry(DotworkPack pack, string kind, string name)
        {
            switch (kind)
            {
                case "animated_sprite": return pack.Animated(name) != null;
                case "sprite": return pack.Sprite(name) != null;
                case "icon": return pack.Icon(name) != null;
                case "portrait": return pack.Portrait(name) != null;
                case "tileset": return pack.Tileset(name) != null;
                case "map": return pack.Map(name) != null;
                case "font": return pack.Font(name) != null;
                case "ui_kit": return pack.UiKit(name) != null;
                default: return true;
            }
        }

        /// <summary>Entries of an imported pack whose Unity objects are gone (a deleted file, a sprite a reimport lost).</summary>
        public static List<string> BrokenReferences(DotworkPack pack)
        {
            var bad = new List<string>();
            void Need(Object o, string what)
            {
                if (o == null)
                {
                    bad.Add($"{what} is missing");
                }
            }
            foreach (DotworkAnimated a in pack.animated)
            {
                Need(a.controller, $"animated_sprite/{a.name} controller");
                Need(a.prefab, $"animated_sprite/{a.name} prefab");
                a.clips.ForEach(c => Need(c.clip, $"animated_sprite/{a.name} clip {c.name}"));
            }
            foreach (DotworkSprite s in pack.sprites)
            {
                Need(s.sprite, $"sprite/{s.name} sprite");
                Need(s.prefab, $"sprite/{s.name} prefab");
            }
            pack.icons.ForEach(i => i.sizes.ForEach(s => Need(s.sprite, $"icon/{i.name} size {s.size}")));
            pack.portraits.ForEach(p => p.expressions.ForEach(e => Need(e.sprite, $"portrait/{p.name} {e.name}")));
            foreach (DotworkTileset t in pack.tilesets)
            {
                foreach (DotworkTile tile in t.tiles)
                {
                    Need(tile, $"tileset/{t.name} tile");
                    if (tile != null)
                    {
                        Need(tile.sprite, $"tileset/{t.name} tile [{tile.atlas}, {tile.col}, {tile.row}] sprite");
                    }
                }
            }
            pack.maps.ForEach(m => Need(m.prefab, $"map/{m.name} prefab"));
            pack.fonts.ForEach(f => Need(f, "a font"));
            pack.uiKits.ForEach(k => k.parts.ForEach(p => Need(p.sprite, $"ui_kit/{k.name} {p.name}")));
            return bad;
        }

        /// <summary>Every imported pack of the game (one per manifest in Assets/dotwork that has been imported).</summary>
        public static List<DotworkPack> Packs()
        {
            var packs = new List<DotworkPack>();
            foreach (string path in DotworkManifest.FindAll())
            {
                try
                {
                    DotworkManifest m = DotworkManifest.Load(path);
                    var pack = AssetDatabase.LoadAssetAtPath<DotworkPack>(PackPath(path, m.Pack));
                    if (pack != null)
                    {
                        packs.Add(pack);
                    }
                }
                catch (DotworkImportException)
                {
                    // Problems() reports it; callers use what loads
                }
            }
            return packs;
        }
    }
}
