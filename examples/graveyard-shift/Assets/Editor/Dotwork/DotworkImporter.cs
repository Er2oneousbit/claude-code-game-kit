// ---------------------------------------------------------------------------
// DotworkImporter.cs
// Purpose : Turns one Dotwork asset manifest into Unity assets: sliced sprites (Point filter, no mipmaps, no
//           compression, pixels per unit = the tile size), an AnimationClip per clip with sprite keys at the
//           cumulative frame times plus an AnimatorController and a prefab per animated sprite, a prefab per prop
//           (BoxCollider2D per collision rect, contact shadow), icons, portraits, a DotworkFont per BMFont, UI kit
//           parts (9-slice margins as sprite borders), a DotworkTile per tileset cell (custom physics shapes for a
//           TilemapCollider2D, animation frames), a DotworkTerrainTile per terrain (the spec's cell_mask rule) and a
//           map prefab (Grid, a Tilemap per layer, the props), all listed in a DotworkPack index.
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
//           Unity is y up: a rect's y becomes sheetH - y - h, a pivot (px / w, 1 - py / h), a map row y the cell
//           y = -1 - y (top-left corner at the origin, like Godot), an object at pixel (x, y) the position
//           (x, -y) / ppu. Extra kinds (background, particles, transition, normal_map, image) are skipped with a
//           warning each; their PNGs still get the pixel-art settings (repeat on a background's repeat axes).
//
// Pseudocode:
//   manifest = load + check format and major version ; ppu = first tileset's tile width, else 16
//   plan pass:  for kind in sprite, animated_sprite, icon, portrait, font, ui_kit, tileset, map: run its builder,
//               which only calls Want(texture, rect, pivot, ...) for every sprite it needs ; record every PNG
//   textures:   per PNG: Sprite, Multiple, SpriteMetaData per wanted sprite, Point, no mips, uncompressed,
//               physics rects in importer.userData (DotworkSpritePhysics applies them) ; reimport all at once
//   build pass: the same builders again; Want() now returns the imported Sprite, and each builder writes its assets
//   index:      DotworkPack with every entry, the manifest's hash, the skipped kinds
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
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
using graveyard_shift.Core;
using Object = UnityEngine.Object;
using M = graveyard_shift.Dotwork.DotworkManifest;

namespace graveyard_shift.Dotwork
{
    public sealed class DotworkImporter
    {
        // ---- Tunables ------------------------------------------------------------
        public const float DEFAULT_PPU = 16f;               // pixels per unit when the pack has no tileset
        public const string USERDATA_PREFIX = "dotwork:1:"; // TextureImporter.userData written by this importer
        public const int MAX_TEXTURE = 16384;
        public const double WHOLE_EPS = 1e-4;               // a duration times the clip's frame rate is "whole" within this
        public static readonly string[] BUILD_ORDER =
            { "sprite", "animated_sprite", "icon", "portrait", "font", "ui_kit", "tileset", "map" };
        private static readonly string[] OUTPUT_SUBFOLDERS = { "sprites", "animated", "maps" };
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
                    bool extra = Array.IndexOf(M.EXTRA_KINDS, kind) >= 0;
                    Warn(extra ? $"skipped {key}: the Unity importer does not build the extra kind '{kind}' yet (its PNGs get the pixel-art settings)"
                               : $"skipped {key}: unknown kind '{kind}' (a newer 1.x manifest?)");
                    if (kind == "background")
                    {
                        PlanBackground(a);
                    }
                    if (kind == "normal_map" && M.Str(a, "image") != null)
                    {
                        TexturePlan tp = Texture(M.Str(a, "image"));
                        if (tp != null)
                        {
                            tp.normalMap = true;
                        }
                    }
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

        private void PlanBackground(Dictionary<string, object> a)
        {
            foreach (Dictionary<string, object> layer in M.Objs(a, "layers"))
            {
                string img = M.Str(layer, "image");
                TexturePlan tp = img != null ? Texture(img) : null;
                if (tp != null)
                {
                    string rep = M.Str(layer, "repeat", "none");
                    tp.repeatU |= rep.Contains("x");
                    tp.repeatV |= rep.Contains("y");
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
                { "normal_map", tp.normalMap }, { "sprites", sprites }, { "physics", physics },
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
            Debug.Log($"[INFO][dotwork] {Manifest.Pack}: imported {_pack.animated.Count} animated, {_pack.sprites.Count} sprite(s), " +
                      $"{_pack.icons.Count} icon(s), {_pack.portraits.Count} portrait(s), {_pack.fonts.Count} font(s), {_pack.uiKits.Count} UI kit(s), " +
                      $"{_pack.tilesets.Count} tileset(s), {_pack.maps.Count} map(s) into {_outDir} at {_ppu} px per unit" +
                      (_pack.skipped.Count > 0 ? $"; skipped {_pack.skipped.Count}" : ""));
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
                    if ((ext == ".anim" || ext == ".controller" || ext == ".prefab" || ext == ".mat") && !_written.Contains(f))
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
            var entry = new DotworkTileset { name = name, shape = M.Str(a, "shape", "square"), tileSize = new Vector2Int((int)ts[0], (int)ts[1]) };
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
                    tile.probability = (float)M.Num(t, "probability", 1);
                    tile.surface = M.Str(t, "surface", "");
                    entry.tiles.Add(Sub(tile, $"tile.{name}.{atlas}_{col}_{row}"));
                }
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
                    // The first tile per mask, atlas order: the variant the spec's loaded result names
                    List<DotworkTile> masked = entry.tiles.Where(t => t.terrainSet == sid && t.terrain == tid && t.mask >= 0).ToList();
                    var masks = new List<int>();
                    var tiles = new List<DotworkTile>();
                    foreach (DotworkTile t in masked.Where(t => !masks.Contains(t.mask)))
                    {
                        masks.Add(t.mask);
                        tiles.Add(t);
                    }
                    if (mode != Autotile.CORNERS4 && tiles.Count > 0)
                    {
                        var tt = ScriptableObject.CreateInstance<DotworkTerrainTile>();
                        tt.mode = mode;
                        tt.terrainSet = sid;
                        tt.terrain = tid;
                        tt.terrainName = terrain.name;
                        tt.masks = masks.ToArray();
                        tt.tiles = tiles.ToArray();
                        terrain.tile = Sub(tt, $"terrain.{name}.{sid}_{tid}");
                    }
                    entry.terrains.Add(terrain);
                }
            }
            _tilesets[name] = entry;
            _pack.tilesets.Add(entry);
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
            var root = new GameObject(name);
            Grid grid = root.AddComponent<Grid>();
            grid.cellSize = new Vector3((float)tsz[0] / _ppu, (float)tsz[1] / _ppu, 0f);
            if (ts.shape == "isometric")
            {
                grid.cellLayout = GridLayout.CellLayout.Isometric;   // verify: Godot's diamond-down layout, not checked here
            }
            List<Dictionary<string, object>> layers = M.Objs(a, "layers").ToList();
            int order = -layers.Count;
            foreach (Dictionary<string, object> L in layers)
            {
                var go = new GameObject(M.Str(L, "name", "Layer"));
                go.transform.SetParent(root.transform, false);
                var tm = go.AddComponent<Tilemap>();
                go.AddComponent<TilemapRenderer>().sortingOrder = order++;
                bool solid = M.Str(L, "kind") == "terrain" ? PaintTerrain(tm, ts, L, name) : PlaceTiles(tm, ts, L, name);
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
                name = name, tileset = tsName, size = new Vector2Int((int)size[0], (int)size[1]),
                tileSize = new Vector2Int((int)tsz[0], (int)tsz[1]), prefab = SavePrefab(root, $"{_outDir}/maps/{name}.prefab"),
            });
        }

        /// <summary>A map row y is the cell y = -1 - y (the map's top-left corner at the origin).</summary>
        public static Vector3Int Cell(int x, int y) => new Vector3Int(x, -1 - y, 0);

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
                Vector3Int cell = Cell((int)v[0], (int)v[1]);
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

        private bool PaintTerrain(Tilemap tm, DotworkTileset ts, Dictionary<string, object> L, string map)
        {
            DotworkTerrain terrain = ts.Terrain(M.Int(L, "terrain_set", 0), M.Int(L, "terrain"));
            if (terrain?.tile == null)
            {
                Warn($"map {map} layer {M.Str(L, "name")}: terrain {M.Int(L, "terrain")} has no blob47 or sides4 tiles " +
                     $"({terrain?.mode ?? "unknown"}); the layer is left empty");
                return false;
            }
            foreach (object c in M.List(L, "cells"))
            {
                double[] v = M.Nums(c, 2);
                tm.SetTile(Cell((int)v[0], (int)v[1]), terrain.tile);
            }
            return terrain.tile.tiles.Any(t => t.solid);
        }
    }
}
