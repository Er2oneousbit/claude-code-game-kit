// ---------------------------------------------------------------------------
// DotworkImporter.cs
// Purpose : Turns one Dotwork asset manifest into Unity assets: sliced sprites (Point filter, no mipmaps, no
//           compression, pixels per unit = the tile size), an AnimationClip per clip with sprite keys at the
//           cumulative frame times plus an AnimatorController and a prefab per animated sprite, a prefab per prop
//           (BoxCollider2D per collision rect, contact shadow), icons, portraits, a DotworkFont per BMFont, UI kit
//           parts (9-slice margins as sprite borders), a DotworkTile per tileset cell (custom physics shapes for a
//           TilemapCollider2D, animation frames), a DotworkTerrainTile per terrain (the spec's cell_mask rule, for
//           the Tile Palette), a map prefab (Grid, a Tilemap per layer with every terrain layer resolved to the
//           spec's tiles, stamps expanded, the props), the extra kinds (a background's layers, a particle texture
//           with its emitter JSON, a transition mask, a normal map wired to its target, a loose image), all listed
//           in a DotworkPack index.
// Usage   : DotworkImporter.Import("Assets/dotwork/town.assets.json", "Assets/dotwork/town", warnings)
//           (GameKitDotwork.ImportAll runs it for every manifest: python tools/dev.py exec GameKitDotwork.ImportAll)
// Notes   : Why an explicit command and not a ScriptedImporter on .assets.json: the slicing, pivots, pixels per
//           unit and physics shapes belong to each PNG's own TextureImporter, which an importer of the JSON file
//           cannot set without fighting Unity's import order (and .json is Unity's own TextAsset type); a command
//           sets them, reimports the PNGs once, then builds everything else from the finished sprites, and the same
//           call runs headless (dev.py exec), from the menu and from the EditMode test.
//           Two passes over the manifest run the same builders: the first only records which sprite each texture
//           needs (and checks every file), the textures are configured and reimported together, the second builds.
//           Re-running keeps every asset's GUID (assets are updated in place; tiles, terrains and fonts are
//           sub-assets of the pack asset matched by name), so scenes that use them keep working; files of assets
//           that left the manifest are removed from the output folder.
//           Unity is y up: a rect's y becomes sheetH - y - h, a pivot (px / w, 1 - py / h), an object at pixel
//           (x, y) the position (x, -y) / ppu. Map cells (spec "Placing tiles", y down, cell (0, 0)'s top-left
//           corner at the origin): a square map's row y is the cell y = -1 - y; an isometric map uses Unity's
//           Isometric Grid with cell (u, v) = (-1 - y, -1 - x), which turns Unity's diamonds (x up-right, y
//           up-left) into Godot's diamond-down layout (x down-right, y down-left), plus half a cell of x on every
//           layer, because Unity centres diamond (0, 0) on x = 0 where the spec puts it at w / 2 (measured from the
//           Grid, not assumed). Each tile's sprite pivot is its origin, so its image lands at centre - origin.
//           A terrain layer is resolved here (cell_mask, the key match, the variant pick by cell_roll with the
//           layer's index) into plain DotworkTiles, so the Tilemap holds the spec's own tiles; a stamps layer
//           places every tile of each stamp; an unknown layer kind is skipped with one warning.
//
// Pseudocode:
//   manifest = load + check format and major version ; ppu = first tileset's tile width, else 16
//   plan pass:  for kind in sprite, animated_sprite, icon, portrait, font, ui_kit, tileset, map, background,
//               particles, transition, normal_map, image: run its builder, which only calls Want(texture, rect,
//               pivot, ...) for every sprite it needs ; record every PNG
//   textures:   per PNG: Sprite, Multiple, SpriteMetaData per wanted sprite, Point, no mips, uncompressed,
//               physics rects in importer.userData (DotworkSpritePhysics applies them), a normal map's target
//               gets it as its _NormalMap secondary texture ; reimport all at once
//   build pass: the same builders again; Want() now returns the imported Sprite, and each builder writes its assets
//   index:      DotworkPack with every entry, the manifest's hash, the unknown kinds skipped
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): asset manifest 1.1.0 (#285): corners4 terrain,
//           the variant pick, isometric placement on Unity's Isometric Grid, stamps layers, the extra kinds loaded
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;
using UnityEngine.Tilemaps;
using {{GAME_SLUG}}.Core;
using Object = UnityEngine.Object;
using M = {{GAME_SLUG}}.Dotwork.DotworkManifest;

namespace {{GAME_SLUG}}.Dotwork
{
    public sealed class DotworkImporter
    {
        // ---- Tunables ------------------------------------------------------------
        public const float DEFAULT_PPU = 16f;               // pixels per unit when the pack has no tileset
        public const string USERDATA_PREFIX = "dotwork:1:"; // TextureImporter.userData written by this importer
        public const int MAX_TEXTURE = 16384;
        public const double WHOLE_EPS = 1e-4;               // a duration times the clip's frame rate is "whole" within this
        public const string NORMAL_MAP_SLOT = "_NormalMap";  // the secondary texture name URP's 2D lights read
        public static readonly string[] BUILD_ORDER =
            { "sprite", "animated_sprite", "icon", "portrait", "font", "ui_kit", "tileset", "map",
              "background", "particles", "transition", "normal_map", "image" };
        private static readonly string[] OUTPUT_SUBFOLDERS = { "sprites", "animated", "maps", "particles" };
        private static readonly string[] PRUNED_EXTENSIONS = { ".anim", ".controller", ".prefab", ".mat", ".json" };
        private static readonly string[] ADDITIVE_SHADERS = { "Mobile/Particles/Additive", "Legacy Shaders/Particles/Additive" };

        public readonly List<string> Warnings = new List<string>();
        public M Manifest { get; private set; }

        private readonly string _manifestPath, _outDir;
        private readonly List<string> _errors = new List<string>();
        private readonly Dictionary<string, TexturePlan> _textures = new Dictionary<string, TexturePlan>();
        private readonly Dictionary<string, Dictionary<string, Sprite>> _loaded = new Dictionary<string, Dictionary<string, Sprite>>();
        private readonly Dictionary<string, Object> _oldSubs = new Dictionary<string, Object>();
        private readonly HashSet<Object> _keptSubs = new HashSet<Object>();
        private readonly HashSet<string> _written = new HashSet<string>();
        private readonly Dictionary<string, DotworkTileset> _tilesets = new Dictionary<string, DotworkTileset>();
        private bool _plan;
        private float _ppu;
        private DotworkPack _pack;
        private string _packPath;
        private Material _additive;

        private sealed class SpriteSpec
        {
            public string name;
            public RectInt rect;             // texture pixels, y down
            public Vector2 pivot;            // pixels in the rect, y down
            public Vector4 margins;          // left, top, right, bottom
            public List<Rect> physics;       // rect pixels, y down
        }

        private sealed class TexturePlan
        {
            public string path;
            public Vector2Int size;
            public bool repeatU, repeatV, normalMap;
            public string normalMapOf;       // the asset path of the normal map lighting this texture, or null
            public readonly List<SpriteSpec> sprites = new List<SpriteSpec>();
            public readonly Dictionary<string, SpriteSpec> byKey = new Dictionary<string, SpriteSpec>();
            public readonly HashSet<string> names = new HashSet<string>();
        }

        private DotworkImporter(string manifestPath, string outDir)
        {
            _manifestPath = M.Norm(manifestPath);
            _outDir = M.Norm(outDir);
        }

        /// <summary>Imports a manifest into outDir (an asset folder) and returns the pack index. Throws
        /// DotworkImportException listing every problem (a missing file, a rect outside its image, a bad version).</summary>
        public static DotworkPack Import(string manifestPath, string outDir, List<string> warnings = null)
        {
            var imp = new DotworkImporter(manifestPath, outDir);
            try
            {
                return imp.Run();
            }
            finally
            {
                warnings?.AddRange(imp.Warnings);
            }
        }

        /// <summary>The plan pass alone (writes nothing): every problem of a manifest and its files (a missing or
        /// non-PNG file, a rect outside its image, a map's unknown tileset, a bad version), or none.</summary>
        public static List<string> Check(string manifestPath, List<string> warnings = null)
        {
            var imp = new DotworkImporter(manifestPath, "Assets/unused");
            try
            {
                imp.Manifest = M.Load(imp._manifestPath);
                imp._ppu = imp.PickPpu();
                imp._plan = true;
                imp.BuildAll();
            }
            catch (DotworkImportException e)
            {
                imp._errors.Add(e.Message);
            }
            warnings?.AddRange(imp.Warnings);
            return imp._errors;
        }

        private DotworkPack Run()
        {
            Manifest = M.Load(_manifestPath);
            if (!_outDir.StartsWith("Assets/", StringComparison.Ordinal))
            {
                throw new DotworkImportException($"output folder {_outDir} must be under Assets/");
            }
            _ppu = PickPpu();

            _plan = true;
            BuildAll();
            if (_errors.Count > 0)
            {
                throw new DotworkImportException($"{_manifestPath}: {_errors.Count} problem(s):\n  " + string.Join("\n  ", _errors));
            }
            ApplyTextures();

            _plan = false;
            OpenPack();
            BuildAll();
            ClosePack();
            return _pack;
        }

        private float PickPpu()
        {
            foreach (Dictionary<string, object> a in Manifest.Assets)
            {
                if (M.Str(a, "kind") == "tileset")
                {
                    double w = M.Nums(a, "tile_size", 2)[0];
                    if (w > 0)
                    {
                        return (float)w;
                    }
                }
            }
            return DEFAULT_PPU;
        }

        private void BuildAll()
        {
            var built = new HashSet<Dictionary<string, object>>();
            foreach (string kind in BUILD_ORDER)
            {
                foreach (Dictionary<string, object> a in Manifest.Assets.Where(x => M.Str(x, "kind") == kind))
                {
                    built.Add(a);
                    string where = $"{kind}/{M.Str(a, "name", "?")}";
                    try
                    {
                        switch (kind)
                        {
                            case "sprite": BuildSprite(a); break;
                            case "animated_sprite": BuildAnimated(a); break;
                            case "icon": BuildIcon(a); break;
                            case "portrait": BuildPortrait(a); break;
                            case "font": BuildFont(a); break;
                            case "ui_kit": BuildUiKit(a); break;
                            case "tileset": BuildTileset(a); break;
                            case "map": BuildMap(a); break;
                            case "background": BuildBackground(a); break;
                            case "particles": BuildParticles(a); break;
                            case "transition": BuildTransition(a); break;
                            case "normal_map": BuildNormalMap(a); break;
                            case "image": BuildImage(a); break;
                        }
                    }
                    catch (DotworkImportException e)
                    {
                        if (!_plan)
                        {
                            throw;
                        }
                        _errors.Add($"{where}: {e.Message}");
                    }
                }
            }
            foreach (Dictionary<string, object> a in Manifest.Assets.Where(x => !built.Contains(x)))
            {
                string kind = M.Str(a, "kind", "?"), key = $"{kind}/{M.Str(a, "name", "?")}";
                if (_plan)
                {
                    Warn($"skipped {key}: unknown kind '{kind}' (a newer 1.x manifest?)");
                }
                else
                {
                    _pack.skipped.Add(key);
                }
            }
            if (_plan)
            {
                foreach (Dictionary<string, object> a in Manifest.Assets)
                {
                    CollectPngs(a);             // every PNG of every asset gets the pixel-art settings
                }
            }
        }

        // ---- Sprites and textures ------------------------------------------------------

        private void Warn(string msg)
        {
            Warnings.Add(msg);
            Debug.LogWarning($"[WARN][dotwork] {Manifest?.Pack}: {msg}");
        }

        /// <summary>The plan of a PNG named in the manifest (records it in the plan pass), or null when it is missing.</summary>
        private TexturePlan Texture(string rel)
        {
            string path = Manifest.Resolve(rel);
            if (_textures.TryGetValue(path, out TexturePlan tp))
            {
                return tp;
            }
            if (!_plan)
            {
                throw new DotworkImportException($"{rel} was not planned (importer bug)");
            }
            Vector2Int? size = M.PngSize(path);
            if (size == null)
            {
                _errors.Add(File.Exists(Path.GetFullPath(path)) ? $"{rel} is not a PNG" : $"{rel} is missing ({path})");
                _textures[path] = null;
                return null;
            }
            tp = new TexturePlan { path = path, size = size.Value };
            _textures[path] = tp;
            return tp;
        }

        private void CollectPngs(object v)
        {
            if (v is string s && s.EndsWith(".png", StringComparison.OrdinalIgnoreCase))
            {
                try
                {
                    Texture(s);
                }
                catch (DotworkImportException e)
                {
                    _errors.Add(e.Message);
                }
            }
            else if (v is Dictionary<string, object> d)
            {
                foreach (object x in d.Values)
                {
                    CollectPngs(x);
                }
            }
            else if (v is List<object> l)
            {
                foreach (object x in l)
                {
                    CollectPngs(x);
                }
            }
        }

        /// <summary>A sprite of a texture: rect and pivot in pixels, y down (the manifest's own numbers). The plan pass
        /// records it and returns null; the build pass returns the imported Sprite. Equal requests share one sprite.</summary>
        private Sprite Want(string rel, RectInt rect, Vector2 pivot, string name, Vector4 margins = default, List<Rect> physics = null)
        {
            TexturePlan tp = Texture(rel);
            if (tp == null)
            {
                return null;
            }
            if (rect.width <= 0 || rect.height <= 0 || rect.x < 0 || rect.y < 0
                || rect.x + rect.width > tp.size.x || rect.y + rect.height > tp.size.y)
            {
                throw new DotworkImportException($"rect [{rect.x}, {rect.y}, {rect.width}, {rect.height}] leaves {rel} ({tp.size.x}x{tp.size.y})");
            }
            string key = string.Format(CultureInfo.InvariantCulture, "{0},{1},{2},{3}|{4},{5}|{6}|{7}", rect.x, rect.y,
                rect.width, rect.height, pivot.x, pivot.y, margins,
                physics == null ? "" : string.Join(";", physics.Select(r => $"{r.x},{r.y},{r.width},{r.height}")));
            if (!tp.byKey.TryGetValue(key, out SpriteSpec spec))
            {
                if (!_plan)
                {
                    throw new DotworkImportException($"sprite {name} of {rel} was not planned (importer bug)");
                }
                string unique = name;
                for (int n = 2; tp.names.Contains(unique); n++)
                {
                    unique = $"{name}_{n}";
                }
                spec = new SpriteSpec { name = unique, rect = rect, pivot = pivot, margins = margins, physics = physics };
                tp.names.Add(unique);
                tp.sprites.Add(spec);
                tp.byKey[key] = spec;
            }
            return _plan ? null : LoadSprite(tp.path, spec.name);
        }

        /// <summary>The whole image as one sprite (pivot null = its centre).</summary>
        private Sprite WantWhole(string rel, string name, Vector2? pivot = null, Vector4 margins = default)
        {
            TexturePlan tp = Texture(rel);
            if (tp == null)
            {
                return null;
            }
            return Want(rel, new RectInt(0, 0, tp.size.x, tp.size.y), pivot ?? new Vector2(tp.size.x / 2f, tp.size.y / 2f), name, margins);
        }

        private Sprite LoadSprite(string path, string name)
        {
            if (!_loaded.TryGetValue(path, out Dictionary<string, Sprite> sprites))
            {
                sprites = new Dictionary<string, Sprite>();
                foreach (Sprite s in AssetDatabase.LoadAllAssetsAtPath(path).OfType<Sprite>())
                {
                    sprites[s.name] = s;
                }
                _loaded[path] = sprites;
            }
            if (!sprites.TryGetValue(name, out Sprite sprite))
            {
                throw new DotworkImportException($"{path} has no sprite {name} after the import (was it reimported?)");
            }
            return sprite;
        }

        /// <summary>Pixel-art settings and the sprite sheet on every planned PNG, reimported together.</summary>
        private void ApplyTextures()
        {
            var changed = new List<TextureImporter>();
            foreach (TexturePlan tp in _textures.Values.Where(t => t != null).OrderBy(t => t.path, StringComparer.Ordinal))
            {
                var ti = AssetImporter.GetAtPath(tp.path) as TextureImporter;
                if (ti == null)
                {
                    throw new DotworkImportException($"{tp.path} is not imported as a texture (run AssetDatabase.Refresh, or check the file)");
                }
                if (tp.sprites.Count == 0 && !tp.normalMap)
                {
                    string stem = Path.GetFileNameWithoutExtension(tp.path);
                    var whole = new SpriteSpec { name = stem, rect = new RectInt(0, 0, tp.size.x, tp.size.y), pivot = new Vector2(tp.size.x / 2f, tp.size.y / 2f) };
                    tp.sprites.Add(whole);
                }
                string userData = USERDATA_PREFIX + Json.Stringify(Describe(tp));
                if (ti.userData == userData)
                {
                    continue;                    // already set up by this importer for this plan
                }
                Configure(ti, tp);
                ti.userData = userData;
                changed.Add(ti);
            }
            if (changed.Count == 0)
            {
                return;
            }
            AssetDatabase.StartAssetEditing();
            try
            {
                foreach (TextureImporter ti in changed)
                {
                    ti.SaveAndReimport();
                }
            }
            finally
            {
                AssetDatabase.StopAssetEditing();
            }
            Debug.Log($"[INFO][dotwork] {Manifest.Pack}: {changed.Count} texture(s) set up and reimported");
        }

        // Everything the importer decides for a texture, as JSON: the importer's own record (userData), so a second
        // import with the same plan reimports nothing, and the physics rects DotworkSpritePhysics reads.
        private Dictionary<string, object> Describe(TexturePlan tp)
        {
            var physics = new Dictionary<string, object>();
            var sprites = new List<object>();
            foreach (SpriteSpec s in tp.sprites)
            {
                sprites.Add(new List<object> { s.name, s.rect.x, s.rect.y, s.rect.width, s.rect.height, (double)s.pivot.x,
                                                (double)s.pivot.y, (double)s.margins.x, (double)s.margins.y, (double)s.margins.z, (double)s.margins.w });
                if (s.physics != null && s.physics.Count > 0)
                {
                    // Sprite.OverridePhysicsShape takes points in the sprite's rect space: pixels, origin bottom-left
                    physics[s.name] = s.physics.Select(r => (object)new List<object> {
                        (double)r.x, (double)(s.rect.height - r.y - r.height), (double)(r.x + r.width), (double)(s.rect.height - r.y) }).ToList();
                }
            }
            return new Dictionary<string, object>
            {
                { "ppu", (double)_ppu }, { "repeat", (tp.repeatU ? "x" : "") + (tp.repeatV ? "y" : "") },
                { "normal_map", tp.normalMap }, { "normal_map_of", tp.normalMapOf ?? "" }, { "sprites", sprites }, { "physics", physics },
            };
        }

        private void Configure(TextureImporter ti, TexturePlan tp)
        {
            var s = new TextureImporterSettings();
            ti.ReadTextureSettings(s);
            s.textureType = tp.normalMap ? TextureImporterType.Default : TextureImporterType.Sprite;
            s.spriteMode = (int)SpriteImportMode.Multiple;
            s.spritePixelsPerUnit = _ppu;
            s.spriteMeshType = SpriteMeshType.FullRect;   // whole cells: no gaps between tiles, exact quads
            s.spriteExtrude = 0;
            s.spriteGenerateFallbackPhysicsShape = false; // only the manifest's collision rects, never an alpha outline
            s.filterMode = FilterMode.Point;
            s.mipmapEnabled = false;
            s.npotScale = TextureImporterNPOTScale.None;
            s.wrapModeU = tp.repeatU ? TextureWrapMode.Repeat : TextureWrapMode.Clamp;
            s.wrapModeV = tp.repeatV ? TextureWrapMode.Repeat : TextureWrapMode.Clamp;
            s.wrapModeW = TextureWrapMode.Clamp;
            s.alphaIsTransparency = !tp.normalMap;
            s.sRGBTexture = !tp.normalMap;                // a normal map holds directions, not colours
            ti.SetTextureSettings(s);
            ti.textureCompression = TextureImporterCompression.Uncompressed;
            int longest = Mathf.Max(tp.size.x, tp.size.y), max = 32;
            while (max < longest && max < MAX_TEXTURE)
            {
                max *= 2;
            }
            ti.maxTextureSize = max;                      // never downscaled (the default 2048 would shrink a big sheet)
            // The normal map lighting this texture rides along as its _NormalMap secondary texture: URP's 2D lights
            // read that slot on the sprite (the texture object keeps its GUID through the batch reimport)
            var secondary = new List<SecondarySpriteTexture>();
            if (!string.IsNullOrEmpty(tp.normalMapOf))
            {
                var normal = AssetDatabase.LoadAssetAtPath<Texture2D>(tp.normalMapOf);
                if (normal == null)
                {
                    throw new DotworkImportException($"{tp.normalMapOf} is not imported as a texture (run AssetDatabase.Refresh, or check the file)");
                }
                secondary.Add(new SecondarySpriteTexture { name = NORMAL_MAP_SLOT, texture = normal });
            }
            ti.secondarySpriteTextures = secondary.ToArray();
#pragma warning disable 0618 // spritesheet: the ISpriteEditorDataProvider replacement needs the 2D Sprite package
            ti.spritesheet = tp.sprites.Select(sp => new SpriteMetaData
            {
                name = sp.name,
                rect = new Rect(sp.rect.x, tp.size.y - sp.rect.y - sp.rect.height, sp.rect.width, sp.rect.height),
                alignment = (int)SpriteAlignment.Custom,
                pivot = new Vector2(sp.pivot.x / sp.rect.width, 1f - sp.pivot.y / sp.rect.height),
                border = new Vector4(sp.margins.x, sp.margins.w, sp.margins.z, sp.margins.y),   // left, bottom, right, top
            }).ToArray();
#pragma warning restore 0618
        }

        // ---- Output: the pack asset, sub-assets, files ---------------------------------------

        private void OpenPack()
        {
            EnsureFolder(_outDir);
            _packPath = $"{_outDir}/{Manifest.Pack}.asset";
            _pack = AssetDatabase.LoadAssetAtPath<DotworkPack>(_packPath);
            if (_pack == null)
            {
                _pack = ScriptableObject.CreateInstance<DotworkPack>();
                AssetDatabase.CreateAsset(_pack, _packPath);
            }
            foreach (Object o in AssetDatabase.LoadAllAssetsAtPath(_packPath))
            {
                if (o != null && o != _pack && !(o is DotworkPack))
                {
                    _oldSubs[o.GetType().Name + ":" + o.name] = o;
                }
            }
            _pack.pack = Manifest.Pack;
            _pack.version = Manifest.Version;
            _pack.manifestPath = _manifestPath;
            _pack.manifestHash = Manifest.Hash;
            _pack.pixelsPerUnit = _ppu;
            _pack.animated.Clear();
            _pack.sprites.Clear();
            _pack.icons.Clear();
            _pack.portraits.Clear();
            _pack.tilesets.Clear();
            _pack.maps.Clear();
            _pack.fonts.Clear();
            _pack.uiKits.Clear();
            _pack.backgrounds.Clear();
            _pack.particles.Clear();
            _pack.transitions.Clear();
            _pack.normalMaps.Clear();
            _pack.images.Clear();
            _pack.skipped.Clear();
            _written.Add(_packPath);
        }

        private void ClosePack()
        {
            foreach (Object old in _oldSubs.Values.Where(o => !_keptSubs.Contains(o)))
            {
                AssetDatabase.RemoveObjectFromAsset(old);
                Object.DestroyImmediate(old, true);
            }
            EditorUtility.SetDirty(_pack);
            AssetDatabase.SaveAssets();
            Prune();
            int extras = _pack.backgrounds.Count + _pack.particles.Count + _pack.transitions.Count + _pack.normalMaps.Count + _pack.images.Count;
            Debug.Log($"[INFO][dotwork] {Manifest.Pack}: imported {_pack.animated.Count} animated, {_pack.sprites.Count} sprite(s), " +
                      $"{_pack.icons.Count} icon(s), {_pack.portraits.Count} portrait(s), {_pack.fonts.Count} font(s), {_pack.uiKits.Count} UI kit(s), " +
                      $"{_pack.tilesets.Count} tileset(s), {_pack.maps.Count} map(s), {extras} background/particles/transition/normal_map/image " +
                      $"into {_outDir} at {_ppu} px per unit" + (_pack.skipped.Count > 0 ? $"; skipped {_pack.skipped.Count} unknown" : ""));
        }

        /// <summary>A ScriptableObject (tile, terrain, font) as a sub-asset of the pack, matched by type and name so a
        /// re-import updates it in place (same fileID: references to it keep working).</summary>
        private T Sub<T>(T fresh, string name) where T : ScriptableObject
        {
            fresh.name = name;
            if (_oldSubs.TryGetValue(typeof(T).Name + ":" + name, out Object old) && old is T existing)
            {
                EditorUtility.CopySerialized(fresh, existing);
                existing.name = name;
                Object.DestroyImmediate(fresh);
                EditorUtility.SetDirty(existing);
                _keptSubs.Add(existing);
                return existing;
            }
            AssetDatabase.AddObjectToAsset(fresh, _pack);
            _keptSubs.Add(fresh);
            return fresh;
        }

        /// <summary>A file asset (AnimationClip, Material) at path, updated in place when it exists (same GUID).</summary>
        private T SaveAsset<T>(T fresh, string path) where T : Object
        {
            EnsureFolder(M.DirOf(path));
            _written.Add(path);
            T old = AssetDatabase.LoadAssetAtPath<T>(path);
            if (old != null)
            {
                EditorUtility.CopySerialized(fresh, old);
                old.name = Path.GetFileNameWithoutExtension(path);
                Object.DestroyImmediate(fresh);
                EditorUtility.SetDirty(old);
                return old;
            }
            AssetDatabase.CreateAsset(fresh, path);
            return fresh;
        }

        private GameObject SavePrefab(GameObject go, string path)
        {
            EnsureFolder(M.DirOf(path));
            _written.Add(path);
            GameObject prefab = PrefabUtility.SaveAsPrefabAsset(go, path, out bool ok);
            Object.DestroyImmediate(go);
            if (!ok || prefab == null)
            {
                throw new DotworkImportException($"could not save {path}");
            }
            return prefab;
        }

        private static void EnsureFolder(string path)
        {
            if (AssetDatabase.IsValidFolder(path))
            {
                return;
            }
            string parent = M.DirOf(path);
            EnsureFolder(parent);
            AssetDatabase.CreateFolder(parent, path.Substring(parent.Length + 1));
        }

        // Files this importer wrote earlier for assets that are gone from the manifest (only its own kinds of file,
        // only in its own subfolders: anything else there is left alone).
        private void Prune()
        {
            foreach (string sub in OUTPUT_SUBFOLDERS)
            {
                string dir = $"{_outDir}/{sub}";
                if (!Directory.Exists(dir))
                {
                    continue;
                }
                foreach (string f in Directory.GetFiles(dir, "*", SearchOption.AllDirectories).Select(M.Norm))
                {
                    string ext = Path.GetExtension(f);
                    if (Array.IndexOf(PRUNED_EXTENSIONS, ext) >= 0 && !_written.Contains(f))
                    {
                        AssetDatabase.DeleteAsset(f);
                    }
                }
            }
        }

        // ---- Builders (each runs twice: plan, then build) ------------------------------------

        private static Vector2 Point(Dictionary<string, object> d, string key)
        {
            double[] p = M.Nums(d, key, 2);
            return new Vector2((float)p[0], (float)p[1]);
        }

        private static RectInt RectOf(object list)
        {
            double[] r = M.Nums(list, 4);
            return new RectInt((int)r[0], (int)r[1], (int)r[2], (int)r[3]);
        }

        private static Rect RectF(object list)
        {
            double[] r = M.Nums(list, 4);
            return new Rect((float)r[0], (float)r[1], (float)r[2], (float)r[3]);
        }

        private static Rect[] CollisionRects(Dictionary<string, object> d)
        {
            return M.Objs(d, "collision").Select(c => RectF(c.TryGetValue("rect", out object r) ? r : null)).ToArray();
        }

        private void BuildSprite(Dictionary<string, object> a)
        {
            string name = M.Str(a, "name");
            Vector2 pivot = Point(a, "pivot");
            Sprite sprite = WantWhole(M.Str(a, "image"), name, pivot);
            Dictionary<string, object> shadow = M.Obj(a, "shadow");
            Sprite shadowSprite = shadow != null ? WantWhole(M.Str(shadow, "image"), name + "_shadow") : null;
            if (_plan)
            {
                return;
            }
            Rect[] collision = CollisionRects(a);
            var go = new GameObject(name);
            go.AddComponent<SpriteRenderer>().sprite = sprite;
            foreach (Rect r in collision)
            {
                // A box in image pixels (y down) around the pivot, in units, y up
                var box = go.AddComponent<BoxCollider2D>();
                box.offset = new Vector2((r.x + r.width / 2f - pivot.x) / _ppu, -(r.y + r.height / 2f - pivot.y) / _ppu);
                box.size = new Vector2(r.width / _ppu, r.height / _ppu);
            }
            Vector2 offset = shadow != null ? Point(shadow, "offset") : Vector2.zero;
            if (shadowSprite != null)
            {
                var sh = new GameObject("Shadow");
                sh.transform.SetParent(go.transform, false);
                sh.transform.localPosition = new Vector3(offset.x / _ppu, -offset.y / _ppu, 0f);
                var sr = sh.AddComponent<SpriteRenderer>();
                sr.sprite = shadowSprite;
                sr.sortingOrder = -1;
            }
            GameObject prefab = SavePrefab(go, $"{_outDir}/sprites/{name}.prefab");
            double[] size = M.Nums(a, "size", 2);
            _pack.sprites.Add(new DotworkSprite
            {
                name = name, role = M.Str(a, "role", ""), sprite = sprite, prefab = prefab,
                size = new Vector2Int((int)size[0], (int)size[1]), pivot = pivot, collision = collision,
                shadow = shadowSprite, shadowOffset = offset,
            });
        }

        private void BuildAnimated(Dictionary<string, object> a)
        {
            string name = M.Str(a, "name");
            var clips = new List<(Dictionary<string, object> c, List<Sprite> sprites)>();
            foreach (Dictionary<string, object> c in M.Objs(a, "clips"))
            {
                string clip = M.Str(c, "name", "clip"), sheet = M.Str(c, "sheet");
                Vector2 pivot = Point(c, "pivot");
                var sprites = new List<Sprite>();
                int i = 0;
                foreach (Dictionary<string, object> f in M.Objs(c, "frames"))
                {
                    sprites.Add(Want(sheet ?? M.Str(f, "file"), RectOf(f.TryGetValue("rect", out object r) ? r : null), pivot, $"{name}_{clip}_{i}"));
                    i++;
                }
                if (i == 0)
                {
                    throw new DotworkImportException($"clip {clip} has no frames");
                }
                clips.Add((c, sprites));
            }
            if (_plan)
            {
                return;
            }
            var entry = new DotworkAnimated { name = name, role = M.Str(a, "role", ""), blend = M.Str(a, "blend", "normal") };
            string dir = $"{_outDir}/animated/{name}";
            foreach ((Dictionary<string, object> c, List<Sprite> sprites) in clips)
            {
                string clipName = M.Str(c, "name", "clip"), sheet = M.Str(c, "sheet");
                List<double> durations = M.Objs(c, "frames").Select(f => M.Num(f, "duration")).ToList();
                AnimationClip clip = SaveAsset(MakeClip(clipName, sprites, durations, M.Bool(c, "loop", true), M.Num(c, "fps", 0)),
                                               $"{dir}/{clipName}.anim");
                double[] fs = M.Nums(c, "frame_size", 2);
                entry.clips.Add(new DotworkClip
                {
                    name = clipName, clip = clip, frames = sprites.Count, loop = M.Bool(c, "loop", true), fps = (float)M.Num(c, "fps", 0),
                    pivot = Point(c, "pivot"), frameSize = new Vector2Int((int)fs[0], (int)fs[1]), sheet = sheet ?? "",
                });
            }
            Dictionary<string, object> dirs = M.Obj(a, "directions");
            if (dirs != null)
            {
                foreach (KeyValuePair<string, object> action in dirs)
                {
                    if (action.Value is Dictionary<string, object> byDir)
                    {
                        foreach (KeyValuePair<string, object> d in byDir)
                        {
                            entry.directions.Add(new DotworkDirection { action = action.Key, dir = d.Key, clip = d.Value as string ?? "" });
                        }
                    }
                }
            }
            entry.controller = MakeController($"{dir}/{name}.controller", entry.clips);
            var go = new GameObject(name);
            var sr = go.AddComponent<SpriteRenderer>();
            sr.sprite = clips[0].sprites[0];
            if (entry.blend == "add")
            {
                Material add = Additive();
                if (add != null)
                {
                    sr.sharedMaterial = add;
                }
            }
            go.AddComponent<Animator>().runtimeAnimatorController = entry.controller;
            entry.prefab = SavePrefab(go, $"{_outDir}/animated/{name}.prefab");
            _pack.animated.Add(entry);
        }

        /// <summary>Sprite keys at the cumulative frame times; loopTime from the manifest's loop. Unity counts the last
        /// sprite key as one frame long (clip length = last key + 1 / frameRate), so when the last frame is held
        /// longer, one more key with the same sprite goes one frame before the end: the clip then lasts exactly the
        /// sum of the durations.</summary>
        private static AnimationClip MakeClip(string clipName, List<Sprite> sprites, List<double> durations, bool loop, double fps)
        {
            double rate = FrameRate(durations, fps), step = 1.0 / rate;
            var clip = new AnimationClip { name = clipName, frameRate = (float)rate };
            var keys = new List<ObjectReferenceKeyframe>();
            double t = 0, last = 0;
            for (int i = 0; i < sprites.Count; i++)
            {
                keys.Add(new ObjectReferenceKeyframe { time = (float)t, value = sprites[i] });
                last = i < durations.Count ? durations[i] : step;
                t += last;
            }
            if (last > step + WHOLE_EPS / rate)
            {
                keys.Add(new ObjectReferenceKeyframe { time = (float)(t - step), value = sprites[sprites.Count - 1] });
            }
            AnimationUtility.SetObjectReferenceCurve(clip, EditorCurveBinding.PPtrCurve("", typeof(SpriteRenderer), "m_Sprite"), keys.ToArray());
            AnimationClipSettings settings = AnimationUtility.GetAnimationClipSettings(clip);
            settings.loopTime = loop;
            AnimationUtility.SetAnimationClipSettings(clip, settings);
            return clip;
        }

        /// <summary>A rate at which every duration is a whole number of frames (the clip's fps times 1 to 12, the spec's
        /// advice for holds of 1.5 and the like), so the Animation window shows the keys on frames; else 60.</summary>
        public static double FrameRate(IList<double> durations, double fps)
        {
            if (fps > 0)
            {
                for (int k = 1; k <= 12; k++)
                {
                    double rate = fps * k;
                    if (durations.All(d => Math.Abs(d * rate - Math.Round(d * rate)) < WHOLE_EPS))
                    {
                        return rate;
                    }
                }
            }
            return 60;
        }

        // One state per clip, named as the clip (Animator.Play("walk_s")), the first clip the default. An existing
        // controller is updated in place: states are matched by name, so the file changes only when the clips do.
        private RuntimeAnimatorController MakeController(string path, List<DotworkClip> clips)
        {
            _written.Add(path);
            AnimatorController ctrl = AssetDatabase.LoadAssetAtPath<AnimatorController>(path)
                                      ?? AnimatorController.CreateAnimatorControllerAtPath(path);
            AnimatorStateMachine sm = ctrl.layers[0].stateMachine;
            var want = new HashSet<string>(clips.Select(c => c.name));
            foreach (ChildAnimatorState cs in sm.states.Where(s => !want.Contains(s.state.name)).ToList())
            {
                sm.RemoveState(cs.state);
            }
            for (int i = 0; i < clips.Count; i++)
            {
                AnimatorState st = sm.states.Select(s => s.state).FirstOrDefault(s => s.name == clips[i].name)
                                   ?? sm.AddState(clips[i].name, new Vector3(300, 60 * i, 0));
                st.motion = clips[i].clip;
                st.writeDefaultValues = false;
                if (i == 0)
                {
                    sm.defaultState = st;
                }
            }
            EditorUtility.SetDirty(ctrl);
            return ctrl;
        }

        // The additive material for blend "add" (fire, sparks): a built-in particle shader drawn by the Built-in
        // pipeline (verify: URP needs a URP particle material, set blend there by hand). Null with a warning when
        // the shader is not in this editor.
        private Material Additive()
        {
            if (_additive != null)
            {
                return _additive;
            }
            Shader shader = ADDITIVE_SHADERS.Select(Shader.Find).FirstOrDefault(s => s != null);
            if (shader == null)
            {
                Warn("no additive sprite shader found: blend \"add\" sprites draw with the default material");
                return null;
            }
            _additive = SaveAsset(new Material(shader), $"{_outDir}/animated/additive.mat");
            return _additive;
        }

        private void BuildIcon(Dictionary<string, object> a)
        {
            string name = M.Str(a, "name");
            var sizes = new List<DotworkNamedSprite>();
            foreach (Dictionary<string, object> s in M.Objs(a, "sizes"))
            {
                int px = M.Int(s, "size");
                sizes.Add(new DotworkNamedSprite { name = px.ToString(CultureInfo.InvariantCulture), size = px, sprite = WantWhole(M.Str(s, "image"), $"{name}_{px}") });
            }
            if (!_plan)
            {
                _pack.icons.Add(new DotworkIcon { name = name, sizes = sizes.OrderBy(s => s.size).ToList() });
            }
        }

        private void BuildPortrait(Dictionary<string, object> a)
        {
            string name = M.Str(a, "name");
            var expressions = M.Objs(a, "expressions").Select(e => new DotworkNamedSprite
                { name = M.Str(e, "name", ""), sprite = WantWhole(M.Str(e, "image"), $"{name}_{M.Str(e, "name", "")}") }).ToList();
            if (_plan)
            {
                return;
            }
            double[] size = M.Nums(a, "size", 2);
            _pack.portraits.Add(new DotworkPortrait
            {
                name = name, size = new Vector2Int((int)size[0], (int)size[1]), expressions = expressions, animation = M.Str(a, "animation", ""),
            });
        }

        private void BuildFont(Dictionary<string, object> a)
        {
            string name = M.Str(a, "name");
            List<string> pages = M.List(a, "pages").OfType<string>().ToList();
            var glyphs = new List<DotworkGlyph>();
            foreach (object ch in M.List(a, "chars"))
            {
                double[] c = M.Nums(ch, 9);     // id, x, y, w, h, xoffset, yoffset, xadvance, page
                var g = new DotworkGlyph
                {
                    id = (int)c[0], x = (int)c[1], y = (int)c[2], w = (int)c[3], h = (int)c[4],
                    xoffset = (int)c[5], yoffset = (int)c[6], xadvance = (int)c[7], page = (int)c[8],
                };
                if (g.page < 0 || g.page >= pages.Count)
                {
                    throw new DotworkImportException($"char {g.id} is on page {g.page}, the font has {pages.Count}");
                }
                if (g.w > 0 && g.h > 0)
                {
                    g.sprite = Want(pages[g.page], new RectInt(g.x, g.y, g.w, g.h), Vector2.zero, $"{name}_{g.id}");   // top-left pivot
                }
                glyphs.Add(g);
            }
            foreach (string p in pages)
            {
                Texture(p);
            }
            if (_plan)
            {
                return;
            }
            var font = ScriptableObject.CreateInstance<DotworkFont>();
            font.fontName = name;
            font.lineHeight = M.Int(a, "line_height");
            font.baseline = M.Int(a, "base");
            font.scale = (float)M.Num(a, "scale", 1);
            font.tint = M.Bool(a, "tint", true);
            font.pixelsPerUnit = _ppu;
            font.pages = pages.Select(p => AssetDatabase.LoadAssetAtPath<Texture2D>(Manifest.Resolve(p))).ToArray();
            font.glyphs = glyphs.ToArray();
            font.kerning = M.List(a, "kerning").Select(k => M.Nums(k, 3))
                            .Select(k => new DotworkKerning { first = (int)k[0], second = (int)k[1], amount = (int)k[2] }).ToArray();
            _pack.fonts.Add(Sub(font, $"font.{name}"));
        }

        private void BuildUiKit(Dictionary<string, object> a)
        {
            string name = M.Str(a, "name");
            var kit = new DotworkUiKit { name = name, role = M.Str(a, "role", "") };
            foreach (Dictionary<string, object> p in M.Objs(a, "parts"))
            {
                bool hasMargins = M.Has(p, "margins"), hasHotspot = M.Has(p, "hotspot");
                double[] mg = M.Nums(p, "margins", 4), size = M.Nums(p, "size", 2), hs = M.Nums(p, "hotspot", 2);
                var margins = new Vector4((float)mg[0], (float)mg[1], (float)mg[2], (float)mg[3]);
                string part = M.Str(p, "name", "");
                kit.parts.Add(new DotworkUiPart
                {
                    name = part, role = M.Str(p, "role", ""), state = M.Str(p, "state", ""), control = M.Str(p, "control", ""),
                    glyph = M.Str(p, "glyph", ""), sprite = WantWhole(M.Str(p, "image"), part, null, hasMargins ? margins : default),
                    size = new Vector2Int((int)size[0], (int)size[1]), scale = (float)M.Num(p, "scale", 1),
                    hasMargins = hasMargins, margins = margins, hasHotspot = hasHotspot, hotspot = new Vector2((float)hs[0], (float)hs[1]),
                });
            }
            if (!_plan)
            {
                _pack.uiKits.Add(kit);
            }
        }

        private void BuildTileset(Dictionary<string, object> a)
        {
            string name = M.Str(a, "name");
            double[] ts = M.Nums(a, "tile_size", 2);
            var entry = new DotworkTileset { name = name, shape = M.Str(a, "shape", Autotile.SQUARE), tileSize = new Vector2Int((int)ts[0], (int)ts[1]) };
            var modes = new Dictionary<int, string>();                   // terrain set id -> mode (a tile's key depends on it)
            foreach (Dictionary<string, object> set in M.Objs(a, "terrain_sets"))
            {
                modes[M.Int(set, "id")] = M.Str(set, "mode", Autotile.BLOB47);
            }
            foreach (Dictionary<string, object> at in M.Objs(a, "atlases"))
            {
                string image = M.Str(at, "image"), atlasName = M.Str(at, "name", "atlas");
                int atlas = M.Int(at, "id");
                double[] size = M.Nums(at, "tile_size", 2);
                int tw = (int)size[0], th = (int)size[1];
                foreach (Dictionary<string, object> t in M.Objs(at, "tiles"))
                {
                    int col = M.Int(t, "col"), row = M.Int(t, "row");
                    Vector2 pivot = M.Has(t, "origin") ? Point(t, "origin") : new Vector2(tw / 2f, th / 2f);
                    Rect[] collision = CollisionRects(t);
                    List<Rect> physics = collision.Length > 0 ? collision.ToList() : null;
                    string sname = $"{name}_{atlasName}_{col}_{row}";
                    Sprite sprite = Want(image, new RectInt(col * tw, row * th, tw, th), pivot, sname, default, physics);
                    Dictionary<string, object> anim = M.Obj(t, "anim");
                    int frames = anim != null ? Math.Max(1, M.Int(anim, "frames", 1)) : 1;
                    var sprites = new List<Sprite> { sprite };
                    for (int k = 1; k < frames; k++)
                    {
                        sprites.Add(Want(image, new RectInt((col + k) * tw, row * th, tw, th), pivot, $"{sname}_f{k}", default, physics));
                    }
                    if (_plan)
                    {
                        continue;
                    }
                    var tile = ScriptableObject.CreateInstance<DotworkTile>();
                    tile.sprite = sprite;
                    tile.frames = frames > 1 ? sprites.ToArray() : new Sprite[0];
                    tile.fps = anim != null ? (float)M.Num(anim, "fps", 0) : 0f;
                    tile.solid = collision.Length > 0;
                    tile.collision = collision;
                    tile.origin = pivot;
                    tile.atlas = atlas;
                    tile.col = col;
                    tile.row = row;
                    bool terrain = M.Has(t, "terrain");
                    tile.terrainSet = terrain ? M.Int(t, "terrain_set", 0) : -1;
                    tile.terrain = terrain ? M.Int(t, "terrain") : -1;
                    tile.mask = terrain && M.Has(t, "mask") ? M.Int(t, "mask") : -1;
                    Dictionary<string, object> corners = M.Obj(t, "corners");
                    tile.corners = corners == null ? new int[0]
                        : corners.Keys.OrderBy(k => k, StringComparer.Ordinal).Select(k => M.Int(corners, k)).ToArray();
                    tile.key = TileKey(tile, corners, modes.TryGetValue(tile.terrainSet, out string mode) ? mode : Autotile.BLOB47, entry.shape);
                    tile.probability = M.Num(t, "probability", 1);
                    tile.surface = M.Str(t, "surface", "");
                    entry.tiles.Add(Sub(tile, $"tile.{name}.{atlas}_{col}_{row}"));
                }
            }
            foreach (Dictionary<string, object> st in M.Objs(a, "stamps"))
            {
                double[] size = M.Nums(st, "size", 2);
                var stamp = new DotworkStamp { name = M.Str(st, "name", ""), size = new Vector2Int((int)size[0], (int)size[1]), solid = M.Bool(st, "solid") };
                stamp.tiles = M.List(st, "tiles").Select(c => { double[] v = M.Nums(c, 3); return new Vector3Int((int)v[0], (int)v[1], (int)v[2]); }).ToArray();
                if (stamp.tiles.Length != stamp.size.x * stamp.size.y)
                {
                    throw new DotworkImportException($"stamp {stamp.name} is {stamp.size.x}x{stamp.size.y} cells but lists {stamp.tiles.Length} tile(s)");
                }
                entry.stamps.Add(stamp);
            }
            if (_plan)
            {
                return;
            }
            foreach (Dictionary<string, object> set in M.Objs(a, "terrain_sets"))
            {
                int sid = M.Int(set, "id");
                string mode = M.Str(set, "mode", Autotile.BLOB47);
                foreach (Dictionary<string, object> tr in M.Objs(set, "terrains"))
                {
                    int tid = M.Int(tr, "id");
                    var terrain = new DotworkTerrain { set = sid, id = tid, name = M.Str(tr, "name", ""), color = M.Str(tr, "color", ""), mode = mode };
                    // Every keyed tile of the terrain in atlas order (atlases by id, tiles in list order): the
                    // candidates the variant pick walks, several per key when the set has variants
                    List<DotworkTile> keyed = entry.tiles.Where(t => t.terrainSet == sid && t.terrain == tid && t.key >= 0)
                                                         .OrderBy(t => t.atlas).ToList();
                    if (keyed.Count > 0)
                    {
                        var tt = ScriptableObject.CreateInstance<DotworkTerrainTile>();
                        tt.mode = mode;
                        tt.shape = entry.shape;
                        tt.terrainSet = sid;
                        tt.terrain = tid;
                        tt.terrainName = terrain.name;
                        tt.keys = keyed.Select(t => t.key).ToArray();
                        tt.tiles = keyed.ToArray();
                        tt.weights = keyed.Select(t => t.probability).ToArray();
                        terrain.tile = Sub(tt, $"terrain.{name}.{sid}_{tid}");
                    }
                    entry.terrains.Add(terrain);
                }
            }
            _tilesets[name] = entry;
            _pack.tilesets.Add(entry);
        }

        /// <summary>The key a tile answers to: its mask (blob47, sides4) or the corner bits of its own terrain
        /// (corners4, the names mapped by the tileset's shape); -1 when it has neither.</summary>
        public static int TileKey(DotworkTile tile, Dictionary<string, object> corners, string mode, string shape)
        {
            if (tile.terrain < 0)
            {
                return -1;
            }
            if (mode != Autotile.CORNERS4)
            {
                return tile.mask;
            }
            if (corners == null)
            {
                return -1;
            }
            var byName = new Dictionary<string, int>();
            foreach (KeyValuePair<string, object> kv in corners)
            {
                byName[kv.Key] = M.Int(corners, kv.Key, -1);
            }
            return Autotile.CornerKey(byName, tile.terrain, shape);
        }

        private void BuildMap(Dictionary<string, object> a)
        {
            string name = M.Str(a, "name"), tsName = M.Str(a, "tileset", "");
            if (_plan)
            {
                if (!Manifest.Assets.Any(x => M.Str(x, "kind") == "tileset" && M.Str(x, "name") == tsName))
                {
                    throw new DotworkImportException($"tileset {tsName} is not in this manifest");
                }
                return;
            }
            DotworkTileset ts = _tilesets[tsName];
            double[] size = M.Nums(a, "size", 2), tsz = M.Nums(a, "tile_size", 2);
            string shape = ts.shape;
            bool iso = shape == Autotile.ISOMETRIC;
            var root = new GameObject(name);
            Grid grid = root.AddComponent<Grid>();
            grid.cellSize = new Vector3((float)tsz[0] / _ppu, (float)tsz[1] / _ppu, 0f);
            grid.cellLayout = iso ? GridLayout.CellLayout.Isometric : GridLayout.CellLayout.Rectangle;
            // Where the Grid puts the centre of map cell (0, 0) against where the spec puts it, (cx, -cy) / ppu: the
            // difference (half a diamond of x on an isometric map, nothing on a square one) moves every layer
            Vector3 want = ToUnity(CellCentre(shape, 0, 0, tsz[0], tsz[1]));
            Vector3 got = grid.CellToLocalInterpolated(Cell(shape, 0, 0) + new Vector3(0.5f, 0.5f, 0f));
            Vector3 shift = want - got;
            List<Dictionary<string, object>> layers = M.Objs(a, "layers").ToList();
            int order = -layers.Count;
            for (int i = 0; i < layers.Count; i++)
            {
                Dictionary<string, object> L = layers[i];
                var go = new GameObject(M.Str(L, "name", "Layer"));
                go.transform.SetParent(root.transform, false);
                go.transform.localPosition = shift;
                var tm = go.AddComponent<Tilemap>();
                tm.tileAnchor = new Vector3(0.5f, 0.5f, 0f);       // the sprite's pivot (the tile's origin) on the cell centre
                var tr = go.AddComponent<TilemapRenderer>();
                tr.sortingOrder = order++;
                if (iso)
                {
                    // Each diamond sorted on its own, the ones lower on the screen (smaller u + v) drawn last, so a
                    // taller tile overdraws the one above it as the spec says (verify: no renderer in the headless runs)
                    tr.mode = TilemapRenderer.Mode.Individual;
                    tr.sortOrder = TilemapRenderer.SortOrder.TopRight;
                }
                string kind = M.Str(L, "kind", "");
                bool solid;
                switch (kind)
                {
                    case "terrain": solid = PaintTerrain(tm, ts, L, name, i); break;
                    case "stamps": solid = PlaceStamps(tm, ts, L, name); break;
                    case "tiles": solid = PlaceTiles(tm, ts, L, name); break;
                    default:
                        Warn($"map {name} layer {M.Str(L, "name")}: unknown layer kind '{kind}' (a newer 1.x manifest?); skipped");
                        solid = false;
                        break;
                }
                if (M.Has(L, "opacity"))
                {
                    tm.color = new Color(1f, 1f, 1f, (float)M.Num(L, "opacity", 1));
                }
                tm.RefreshAllTiles();
                if (solid)
                {
                    go.AddComponent<TilemapCollider2D>();
                }
            }
            var objects = new GameObject("Objects");
            objects.transform.SetParent(root.transform, false);
            foreach (Dictionary<string, object> o in M.Objs(a, "objects"))
            {
                string asset = M.Str(o, "asset", "");
                GameObject prefab = _pack.Sprite(asset)?.prefab ?? _pack.Animated(asset)?.prefab;
                if (prefab == null)
                {
                    Warn($"map {name}: object {asset} is not a sprite or animated sprite of this pack; left out");
                    continue;
                }
                var inst = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
                inst.name = asset;
                inst.transform.SetParent(objects.transform, false);
                inst.transform.localPosition = new Vector3((float)M.Num(o, "x") / _ppu, -(float)M.Num(o, "y") / _ppu, 0f);
            }
            _pack.maps.Add(new DotworkMap
            {
                name = name, tileset = tsName, shape = shape, size = new Vector2Int((int)size[0], (int)size[1]),
                tileSize = new Vector2Int((int)tsz[0], (int)tsz[1]), prefab = SavePrefab(root, $"{_outDir}/maps/{name}.prefab"),
            });
        }

        /// <summary>A square map's row y is the cell y = -1 - y (the map's top-left corner at the origin).</summary>
        public static Vector3Int Cell(int x, int y) => new Vector3Int(x, -1 - y, 0);

        /// <summary>The Unity cell of map cell (x, y) for a shape: square (x, -1 - y); isometric (-1 - y, -1 - x), which
        /// turns Unity's diamonds (x up-right, y up-left) into the spec's diamond-down layout (x down-right, y
        /// down-left). The inverse is MapCell.</summary>
        public static Vector3Int Cell(string shape, int x, int y)
        {
            return shape == Autotile.ISOMETRIC ? new Vector3Int(-1 - y, -1 - x, 0) : Cell(x, y);
        }

        public static Vector2Int MapCell(string shape, Vector3Int cell)
        {
            return shape == Autotile.ISOMETRIC ? new Vector2Int(-1 - cell.y, -1 - cell.x) : new Vector2Int(cell.x, -1 - cell.y);
        }

        /// <summary>The spec's cell centre in map pixels (y down): square ((x + 0.5) w, (y + 0.5) h), isometric
        /// ((x - y + 1) w / 2, (x + y + 1) h / 2).</summary>
        public static Vector2 CellCentre(string shape, int x, int y, double w, double h)
        {
            if (shape == Autotile.ISOMETRIC)
            {
                return new Vector2((float)((x - y + 1) * w / 2), (float)((x + y + 1) * h / 2));
            }
            return new Vector2((float)((x + 0.5) * w), (float)((y + 0.5) * h));
        }

        /// <summary>Map pixels (y down) to the map prefab's local units (y up).</summary>
        private Vector3 ToUnity(Vector2 px) => new Vector3(px.x / _ppu, -px.y / _ppu, 0f);

        private bool PlaceTiles(Tilemap tm, DotworkTileset ts, Dictionary<string, object> L, string map)
        {
            bool solid = false;
            int missing = 0;
            foreach (object c in M.List(L, "cells"))
            {
                double[] v = M.Nums(c, 6);   // x, y, atlas, col, row, flags
                DotworkTile tile = ts.Tile((int)v[2], (int)v[3], (int)v[4]);
                if (tile == null)
                {
                    missing++;
                    continue;
                }
                Vector3Int cell = Cell(ts.shape, (int)v[0], (int)v[1]);
                tm.SetTile(cell, tile);
                int flags = (int)v[5];
                if (flags != 0)
                {
                    tm.SetTransformMatrix(cell, FlagMatrix(flags));
                }
                solid |= tile.solid;
            }
            if (missing > 0)
            {
                Warn($"map {map} layer {M.Str(L, "name")}: {missing} cell(s) name a tile the tileset does not have");
            }
            return solid;
        }

        /// <summary>The cell flags (1 flip h, 2 flip v, 4 transpose; transpose first) as a y-up transform.</summary>
        public static Matrix4x4 FlagMatrix(int flags)
        {
            Matrix4x4 m = Matrix4x4.identity;
            if ((flags & 4) != 0)
            {
                // (x, y) y down -> (y, x); in y up that is (x, y) -> (-y, -x)
                m.m00 = 0f;
                m.m01 = -1f;
                m.m10 = -1f;
                m.m11 = 0f;
            }
            Vector3 flip = new Vector3((flags & 1) != 0 ? -1f : 1f, (flags & 2) != 0 ? -1f : 1f, 1f);
            return Matrix4x4.Scale(flip) * m;
        }

        /// <summary>A terrain layer resolved to the spec's tiles: each painted cell's key from its painted neighbours
        /// (cell_mask in the layer's mode), the tile picked among the terrain's tiles with that key by the cell's
        /// roll (cell_roll with the layer's index). A cell with no tile stays empty, warned once per layer.</summary>
        private bool PaintTerrain(Tilemap tm, DotworkTileset ts, Dictionary<string, object> L, string map, int layerIndex)
        {
            DotworkTerrain terrain = ts.Terrain(M.Int(L, "terrain_set", 0), M.Int(L, "terrain"));
            if (terrain?.tile == null)
            {
                Warn($"map {map} layer {M.Str(L, "name")}: terrain {M.Int(L, "terrain")} of set {M.Int(L, "terrain_set", 0)} has no " +
                     $"keyed tiles in tileset {ts.name} ({terrain?.mode ?? "not in the tileset"}); the layer is left empty");
                return false;
            }
            var painted = new HashSet<Vector2Int>();
            foreach (object c in M.List(L, "cells"))
            {
                double[] v = M.Nums(c, 2);
                painted.Add(new Vector2Int((int)v[0], (int)v[1]));
            }
            bool solid = false;
            var missing = new List<string>();
            foreach (Vector2Int p in painted.OrderBy(p => p.y).ThenBy(p => p.x))
            {
                int key = Autotile.CellMask((x, y) => painted.Contains(new Vector2Int(x, y)), p.x, p.y, terrain.mode);
                DotworkTile tile = terrain.tile.TileFor(key, Autotile.CellRoll(p.x, p.y, layerIndex));
                if (tile == null)
                {
                    missing.Add($"({p.x}, {p.y}) key {key}");
                    continue;
                }
                tm.SetTile(Cell(ts.shape, p.x, p.y), tile);
                solid |= tile.solid;
            }
            if (missing.Count > 0)
            {
                Warn($"map {map} layer {M.Str(L, "name")}: {missing.Count} cell(s) have no tile for their key in terrain " +
                     $"{terrain.name} ({terrain.mode}) and stay empty: {string.Join(", ", missing.Take(6))}" +
                     (missing.Count > 6 ? ", ..." : "") + " (a corners4 terrain needs shapes at least 2 cells thick)");
            }
            return solid;
        }

        /// <summary>A stamps layer: every tile of each stamp, tile j at (x + j % w, y + j / w) from the cell.</summary>
        private bool PlaceStamps(Tilemap tm, DotworkTileset ts, Dictionary<string, object> L, string map)
        {
            bool solid = false;
            int badStamps = 0, missing = 0;
            foreach (object c in M.List(L, "cells"))
            {
                double[] v = M.Nums(c, 3);   // x, y, stamp
                int index = (int)v[2];
                if (index < 0 || index >= ts.stamps.Count)
                {
                    badStamps++;
                    continue;
                }
                DotworkStamp stamp = ts.stamps[index];
                int w = Math.Max(1, stamp.size.x);
                for (int j = 0; j < stamp.tiles.Length; j++)
                {
                    Vector3Int id = stamp.tiles[j];
                    DotworkTile tile = ts.Tile(id.x, id.y, id.z);
                    if (tile == null)
                    {
                        missing++;
                        continue;
                    }
                    tm.SetTile(Cell(ts.shape, (int)v[0] + j % w, (int)v[1] + j / w), tile);
                    solid |= tile.solid;
                }
            }
            if (badStamps > 0)
            {
                Warn($"map {map} layer {M.Str(L, "name")}: {badStamps} cell(s) name a stamp the tileset does not have ({ts.stamps.Count} stamps)");
            }
            if (missing > 0)
            {
                Warn($"map {map} layer {M.Str(L, "name")}: {missing} stamp tile(s) name a tile the tileset does not have");
            }
            return solid;
        }

        // ---- The extra kinds: loaded with the pixel-art settings and listed, the scene object is the game's ------

        private void BuildBackground(Dictionary<string, object> a)
        {
            string name = M.Str(a, "name");
            var entry = new DotworkBackground { name = name, role = M.Str(a, "role", "") };
            int i = 0;
            foreach (Dictionary<string, object> layer in M.Objs(a, "layers"))
            {
                string img = M.Str(layer, "image"), rep = M.Str(layer, "repeat", "none"), layerName = M.Str(layer, "name", "");
                TexturePlan tp = img != null ? Texture(img) : null;
                if (tp != null)
                {
                    tp.repeatU |= rep.Contains("x");            // the texture repeats on the layer's repeat axes
                    tp.repeatV |= rep.Contains("y");
                }
                Sprite sprite = img != null ? WantWhole(img, $"{name}_{(layerName != "" ? layerName : i.ToString(CultureInfo.InvariantCulture))}") : null;
                double[] size = M.Nums(layer, "size", 2), vel = M.Nums(layer, "velocity", 2);
                entry.layers.Add(new DotworkBackgroundLayer
                {
                    name = layerName, sprite = sprite, size = new Vector2Int((int)size[0], (int)size[1]),
                    velocity = new Vector2((float)vel[0], (float)vel[1]), repeat = rep,
                    wobblePx = (float)M.Num(layer, "wobble_px", 0), scale = (float)M.Num(layer, "scale", 1),
                });
                i++;
            }
            if (!_plan)
            {
                _pack.backgrounds.Add(entry);
            }
        }

        private void BuildParticles(Dictionary<string, object> a)
        {
            string name = M.Str(a, "name");
            Sprite texture = WantWhole(M.Str(a, "texture"), name);
            if (_plan)
            {
                return;
            }
            // The emitter JSON as Dotwork wrote it, as a file Unity imports as a TextAsset (game code parses it with Core/Json)
            string path = $"{_outDir}/particles/{name}.json";
            EnsureFolder(M.DirOf(path));
            string text = Json.Stringify(M.Obj(a, "emitter") ?? new Dictionary<string, object>());
            string full = Path.GetFullPath(path);
            if (!File.Exists(full) || File.ReadAllText(full, System.Text.Encoding.UTF8) != text)
            {
                File.WriteAllText(full, text, new System.Text.UTF8Encoding(false));
                AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
            }
            _written.Add(path);
            var emitter = AssetDatabase.LoadAssetAtPath<TextAsset>(path);
            if (emitter == null)
            {
                throw new DotworkImportException($"could not import {path} as a TextAsset");
            }
            _pack.particles.Add(new DotworkParticles { name = name, texture = texture, emitter = emitter });
        }

        private void BuildTransition(Dictionary<string, object> a)
        {
            string name = M.Str(a, "name");
            Sprite sprite = WantWhole(M.Str(a, "image"), name);
            if (!_plan)
            {
                double[] size = M.Nums(a, "size", 2);
                _pack.transitions.Add(new DotworkTransition
                {
                    name = name, transition = M.Str(a, "transition", ""), sprite = sprite, size = new Vector2Int((int)size[0], (int)size[1]),
                });
            }
        }

        private void BuildNormalMap(Dictionary<string, object> a)
        {
            string name = M.Str(a, "name"), image = M.Str(a, "image"), target = M.Str(a, "target");
            if (image == null || target == null)
            {
                throw new DotworkImportException($"normal_map {name} needs both an image and a target");
            }
            TexturePlan normal = Texture(image), lit = Texture(target);
            if (normal == null || lit == null)
            {
                return;                                           // the plan pass recorded the missing file
            }
            normal.normalMap = true;                              // linear, not a sprite
            if (!_plan)
            {
                string path = Manifest.Resolve(image);
                Sprite first = AssetDatabase.LoadAllAssetsAtPath(lit.path).OfType<Sprite>().OrderBy(s => s.name, StringComparer.Ordinal).FirstOrDefault();
                _pack.normalMaps.Add(new DotworkNormalMap
                {
                    name = name, convention = M.Str(a, "convention", "opengl"), texture = AssetDatabase.LoadAssetAtPath<Texture2D>(path),
                    target = target, targetSprite = first,
                });
                return;
            }
            if (!string.IsNullOrEmpty(lit.normalMapOf) && lit.normalMapOf != normal.path)
            {
                Warn($"normal_map {name}: {target} already has normal map {Manifest.Relative(lit.normalMapOf)}; {image} replaces it");
            }
            lit.normalMapOf = normal.path;
        }

        private void BuildImage(Dictionary<string, object> a)
        {
            string name = M.Str(a, "name");
            bool hasPivot = M.Has(a, "pivot");
            Vector2 pivot = Point(a, "pivot");
            Sprite sprite = WantWhole(M.Str(a, "image"), name, hasPivot ? pivot : (Vector2?)null);
            if (!_plan)
            {
                double[] size = M.Nums(a, "size", 2);
                _pack.images.Add(new DotworkImage
                {
                    name = name, role = M.Str(a, "role", ""), sprite = sprite, size = new Vector2Int((int)size[0], (int)size[1]),
                    hasPivot = hasPivot, pivot = pivot,
                });
            }
        }
    }
}
