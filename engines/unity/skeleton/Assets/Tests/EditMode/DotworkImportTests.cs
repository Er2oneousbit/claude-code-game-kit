// ---------------------------------------------------------------------------
// DotworkImportTests.cs
// Purpose : The Dotwork importer (#57) against the golden fixture: copy data/golden/dotwork/assets into a temporary
//           folder under Assets/, import its manifest, read the numbers back from the Unity objects it made (sprite
//           rects and pivots, AnimationClip keys, BoxCollider2Ds, tiles, the map's Tilemaps, the font) and compare
//           them with data/golden/dotwork/expected.json (assetspec.expected(), the loaded result every engine's
//           importer must reproduce) to 1e-6. The same for the sheet render_sprites.py --manifest rendered from the
//           golden rigged character (data/golden/character/sprites/, #290). Then: every real manifest of the game
//           loads (DotworkVerify).
// Usage   : python tools/dev.py test --filter Dotwork
// Notes   : Read-back, not re-computed: a rect comes from Sprite.rect flipped back to y down, a frame's seconds from
//           the clip's key times, a terrain cell's mask from the Tilemap's own neighbours and its tile from the
//           sprite the Tilemap shows. Only the core kinds are compared; the extra kinds must be reported as
//           skipped. The temporary folder is deleted afterwards (and before, if a killed run left it).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using NUnit.Framework;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;
using UnityEngine.Tilemaps;
using {{GAME_SLUG}}.Core;
using {{GAME_SLUG}}.Dotwork;
using Object = UnityEngine.Object;

namespace {{GAME_SLUG}}.Tests
{
    public class DotworkImportTests
    {
        // ---- Tunables ------------------------------------------------------------
        private const string GOLDEN = "data/golden/dotwork";         // relative to the project root
        private const string RENDERED = "data/golden/character/sprites";   // render_sprites.py --manifest's sheets of the golden character
        private const string TEMP = "Assets/__DotworkGolden";       // gitignored; deleted after the run
        private const string MANIFEST = TEMP + "/dotwork/golden.assets.json";
        private const string OUT = TEMP + "/dotwork/golden";
        private const double TOL = 1e-6;                             // the spec's tolerance
        private const double PIXEL_TOL = 1e-4;                       // a Sprite stores its pivot as float32: a rendered sheet's
                                                                     // 37.6 reads back as 37.599998 (Dotwork's own pivots are whole pixels)

        private static DotworkPack _pack;
        private static readonly List<string> Warnings = new List<string>();
        private static Dictionary<string, object> _expected;         // expected.json "assets"
        private static Dictionary<string, object> _actual;           // the same shape, read back from Unity

        [OneTimeSetUp]
        public void ImportTheFixture()
        {
            DeleteTemp();
            CopyDir(Path.Combine(GOLDEN, "assets"), TEMP);
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            Warnings.Clear();
            _pack = DotworkImporter.Import(MANIFEST, OUT, Warnings);
            _expected = ExpectedAssets();
            _actual = Loaded(_pack);
        }

        [OneTimeTearDown]
        public void DeleteTheFixture()
        {
            DeleteTemp();
        }

        // ---- The loaded result ---------------------------------------------------------

        private static IEnumerable<TestCaseData> CoreAssets()
        {
            var cases = new List<TestCaseData>();
            try
            {
                foreach (string key in ExpectedAssets().Keys.Where(IsCore))
                {
                    cases.Add(new TestCaseData(key).SetName("Dotwork_" + key.Replace('/', '_')));
                }
            }
            catch (Exception)
            {
                cases.Add(new TestCaseData("expected.json unreadable").SetName("Dotwork_ExpectedUnreadable"));
            }
            return cases;
        }

        [TestCaseSource(nameof(CoreAssets))]
        public void LoadedResultMatchesExpected(string key)
        {
            Assert.IsTrue(_expected.ContainsKey(key), $"{GOLDEN}/expected.json: {key} not found");
            Assert.IsTrue(_actual.ContainsKey(key), $"{key} was not imported");
            GoldenVectors.AssertClose(_actual[key], _expected[key], TOL, key);
        }

        [Test]
        public void Dotwork_EveryCoreAssetIsImported()
        {
            CollectionAssert.AreEquivalent(_expected.Keys.Where(IsCore).ToList(), _actual.Keys.ToList());
        }

        [Test]
        public void Dotwork_ExtraKindsAreSkippedWithAWarning()
        {
            foreach (string key in _expected.Keys.Where(k => !IsCore(k)))
            {
                CollectionAssert.Contains(_pack.skipped, key, $"{key} is not in the pack's skipped list");
                Assert.IsTrue(Warnings.Any(w => w.Contains(key)), $"no warning names {key}");
            }
        }

        // ---- Details the loaded result does not show ----------------------------------------

        [Test]
        public void Dotwork_FramesComeFromTheSheetOrTheirOwnFiles()
        {
            DotworkManifest m = DotworkManifest.Load(MANIFEST);
            foreach (Dictionary<string, object> a in m.Assets.Where(a => DotworkManifest.Str(a, "kind") == "animated_sprite"))
            {
                DotworkAnimated entry = _pack.Animated(DotworkManifest.Str(a, "name"));
                foreach (Dictionary<string, object> c in DotworkManifest.Objs(a, "clips"))
                {
                    string sheet = DotworkManifest.Str(c, "sheet");
                    DotworkClip dc = entry.ClipNamed(DotworkManifest.Str(c, "name"));
                    List<Sprite> sprites = Keys(dc.clip).Take(dc.frames).Select(k => (Sprite)k.value).ToList();
                    List<Dictionary<string, object>> frames = DotworkManifest.Objs(c, "frames").ToList();
                    for (int i = 0; i < frames.Count; i++)
                    {
                        string want = m.Resolve(sheet ?? DotworkManifest.Str(frames[i], "file"));
                        Assert.AreEqual(want, AssetDatabase.GetAssetPath(sprites[i].texture), $"{entry.name} {DotworkManifest.Str(c, "name")} frame {i}");
                    }
                }
            }
        }

        [Test]
        public void Dotwork_ClipsLoopAsTheManifestSays()
        {
            DotworkAnimated hero = _pack.Animated("hero");
            Assert.IsTrue(hero.ClipNamed("walk_s").clip.isLooping, "walk_s loops");
            Assert.IsFalse(hero.ClipNamed("attack_e").clip.isLooping, "attack_e plays once");
            var ctrl = (AnimatorController)hero.controller;
            List<string> states = ctrl.layers[0].stateMachine.states.Select(s => s.state.name).ToList();
            CollectionAssert.AreEquivalent(hero.clips.Select(c => c.name).ToList(), states);
            Assert.AreEqual("idle_s", ctrl.layers[0].stateMachine.defaultState.name);
        }

        [Test]
        public void Dotwork_TileCollisionIsTheSpritePhysicsShape()
        {
            int checkedTiles = 0;
            foreach (DotworkTile tile in _pack.tilesets.SelectMany(t => t.tiles))
            {
                Sprite s = tile.sprite;
                if (!tile.solid)
                {
                    Assert.AreEqual(0, s.GetPhysicsShapeCount(), $"{s.name} has a physics shape but no collision");
                    continue;
                }
                var got = new List<Rect>();
                var points = new List<Vector2>();
                for (int i = 0; i < s.GetPhysicsShapeCount(); i++)
                {
                    s.GetPhysicsShape(i, points);
                    // Local units around the pivot, y up -> tile pixels, y down
                    float x0 = points.Min(p => p.x) * s.pixelsPerUnit + s.pivot.x, x1 = points.Max(p => p.x) * s.pixelsPerUnit + s.pivot.x;
                    float y0 = points.Min(p => p.y) * s.pixelsPerUnit + s.pivot.y, y1 = points.Max(p => p.y) * s.pixelsPerUnit + s.pivot.y;
                    got.Add(new Rect(x0, s.rect.height - y1, x1 - x0, y1 - y0));
                }
                Assert.AreEqual(tile.collision.Length, got.Count, $"{s.name}: physics shapes");
                foreach (Rect want in tile.collision)
                {
                    Assert.IsTrue(got.Any(g => Close(g, want)), $"{s.name}: no physics shape at {want} (got {string.Join(", ", got)})");
                }
                checkedTiles++;
            }
            Assert.Greater(checkedTiles, 0, "the fixture has tiles with collision");
        }

        [Test]
        public void Dotwork_TilesAreTheirAtlasCells()
        {
            DotworkManifest m = DotworkManifest.Load(MANIFEST);
            foreach (Dictionary<string, object> ts in m.Assets.Where(a => DotworkManifest.Str(a, "kind") == "tileset"))
            {
                DotworkTileset entry = _pack.Tileset(DotworkManifest.Str(ts, "name"));
                foreach (Dictionary<string, object> at in DotworkManifest.Objs(ts, "atlases"))
                {
                    double[] size = DotworkManifest.Nums(at, "tile_size", 2);
                    foreach (Dictionary<string, object> t in DotworkManifest.Objs(at, "tiles"))
                    {
                        DotworkTile tile = entry.Tile(DotworkManifest.Int(at, "id"), DotworkManifest.Int(t, "col"), DotworkManifest.Int(t, "row"));
                        Sprite s = tile.sprite;
                        Rect r = s.rect;
                        var got = new Rect(r.x, s.texture.height - r.y - r.height, r.width, r.height);
                        var want = new Rect((float)(tile.col * size[0]), (float)(tile.row * size[1]), (float)size[0], (float)size[1]);
                        Assert.IsTrue(Close(got, want), $"{s.name}: {got} is not the cell {want}");
                        Assert.AreEqual(m.Resolve(DotworkManifest.Str(at, "image")), AssetDatabase.GetAssetPath(s.texture));
                    }
                }
            }
        }

        [Test]
        public void Dotwork_MapLayersAreTilemapsWithColliders()
        {
            GameObject map = _pack.Map("yard").prefab;
            Assert.IsNotNull(map.GetComponent<Grid>());
            Assert.IsNotNull(map.transform.Find("Water").GetComponent<TilemapCollider2D>(), "water tiles collide");
            Assert.IsNotNull(map.transform.Find("Fixtures").GetComponent<TilemapCollider2D>(), "fixtures collide");
            Assert.IsNull(map.transform.Find("Path").GetComponent<TilemapCollider2D>(), "a path does not collide");
            var water = map.transform.Find("Water").GetComponent<Tilemap>();
            TileBase t = water.GetTile(DotworkImporter.Cell(2, 2));
            Assert.IsInstanceOf<DotworkTerrainTile>(t);
            var anim = new TileAnimationData();
            Assert.IsTrue(((DotworkTerrainTile)t).TileFor(28).GetTileAnimationData(Vector3Int.zero, null, ref anim), "water animates");
            Assert.AreEqual(2, anim.animatedSprites.Length);
            Assert.AreEqual(4f, anim.animationSpeed, 1e-6);
        }

        [Test]
        public void Dotwork_TexturesArePixelArt()
        {
            foreach (string path in AssetDatabase.FindAssets("t:Texture2D", new[] { TEMP }).Select(AssetDatabase.GUIDToAssetPath))
            {
                var ti = (TextureImporter)AssetImporter.GetAtPath(path);
                Assert.AreEqual(FilterMode.Point, ti.filterMode, path);
                Assert.IsFalse(ti.mipmapEnabled, path);
                Assert.AreEqual(TextureImporterCompression.Uncompressed, ti.textureCompression, path);
                Assert.AreEqual(TextureImporterNPOTScale.None, ti.npotScale, path);
                var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(path);
                Assert.AreEqual(DotworkManifest.PngSize(path).Value, new Vector2Int(tex.width, tex.height), $"{path} keeps its size");
            }
            var bg = (TextureImporter)AssetImporter.GetAtPath(TEMP + "/art/battle/bg/spr_bg_hills_clouds_near.png");
            Assert.AreEqual(TextureWrapMode.Repeat, bg.wrapModeU, "a background layer that repeats on x");
            Assert.AreEqual(TextureWrapMode.Clamp, bg.wrapModeV);
            Assert.AreEqual(8f, _pack.pixelsPerUnit, "pixels per unit = the first tileset's tile size");
        }

        [Test]
        public void Dotwork_LabelPlacesGlyphsWithKerning()
        {
            DotworkFont font = _pack.Font("tiny");
            var go = new GameObject("label test");
            try
            {
                var label = go.AddComponent<DotworkLabel>();
                label.font = font;
                label.Text = "AB";
                List<Transform> glyphs = go.GetComponentsInChildren<Transform>(true).Where(t => t != go.transform).ToList();
                Assert.AreEqual(2, glyphs.Count);
                // A at pen 0; B at A's advance (4) plus the pair's kerning (-1) = 3 pixels
                Assert.AreEqual(0f, glyphs[0].localPosition.x, 1e-6);
                Assert.AreEqual(3f / font.pixelsPerUnit, glyphs[1].localPosition.x, 1e-6);
                Assert.AreEqual(7, font.Measure("AB"));
                // Dotwork already drew the pages at the font's scale: a scale-2 font is laid out 1:1 all the same
                DotworkFont scaled = Object.Instantiate(font);
                try
                {
                    scaled.scale = 2f;
                    label.font = scaled;
                    label.Rebuild();
                    glyphs = go.GetComponentsInChildren<Transform>(true).Where(t => t != go.transform).ToList();
                    Assert.AreEqual(3f / font.pixelsPerUnit, glyphs[1].localPosition.x, 1e-6, "no second upscale of the pen");
                    Assert.AreEqual(Vector3.one, glyphs[1].localScale, "no second upscale of the glyph");
                }
                finally
                {
                    Object.DestroyImmediate(scaled);
                }
            }
            finally
            {
                Object.DestroyImmediate(go);
            }
        }

        [Test]
        public void Dotwork_SecondImportUpdatesInPlace()
        {
            DotworkTile tile = _pack.Tileset("ground_yard").tiles[0];
            AnimationClip clip = _pack.Animated("hero").clips[0].clip;
            GameObject prefab = _pack.Map("yard").prefab;
            string packGuid = AssetDatabase.AssetPathToGUID(AssetDatabase.GetAssetPath(_pack));
            DotworkPack again = DotworkImporter.Import(MANIFEST, OUT);
            Assert.AreSame(_pack, again, "the same pack asset");
            Assert.AreEqual(packGuid, AssetDatabase.AssetPathToGUID(AssetDatabase.GetAssetPath(again)));
            Assert.AreSame(tile, again.Tileset("ground_yard").tiles[0], "tiles are updated in place");
            Assert.AreSame(clip, again.Animated("hero").clips[0].clip, "clips are updated in place");
            Assert.AreSame(prefab, again.Map("yard").prefab, "prefabs keep their asset");
            GoldenVectors.AssertClose(Loaded(again), Loaded(_pack), TOL, "the second import");
        }

        [Test]
        public void Dotwork_AnotherMajorVersionIsRefused()
        {
            string path = TEMP + "/dotwork/v2.assets.json";
            File.WriteAllText(path, "{\"format\": \"dotwork-assets\", \"version\": \"2.0.0\", \"pack\": \"v2\", \"base\": \"..\", \"assets\": []}");
            var e = Assert.Throws<DotworkImportException>(() => DotworkImporter.Import(path, TEMP + "/dotwork/v2"));
            StringAssert.Contains("2.0.0", e.Message);
            StringAssert.Contains("major 1", e.Message);
        }

        [Test]
        public void Dotwork_UnknownKindIsSkippedNotFatal()
        {
            string path = TEMP + "/dotwork/future.assets.json";
            File.WriteAllText(path, "{\"format\": \"dotwork-assets\", \"version\": \"1.9.0\", \"pack\": \"future\", \"base\": \"..\", " +
                                    "\"new_field\": 1, \"assets\": [{\"kind\": \"hologram\", \"name\": \"orb\", \"glow\": 3}]}");
            var warnings = new List<string>();
            DotworkPack pack = DotworkImporter.Import(path, TEMP + "/dotwork/future", warnings);
            CollectionAssert.Contains(pack.skipped, "hologram/orb");
            Assert.IsTrue(warnings.Any(w => w.Contains("unknown kind")), string.Join("\n", warnings));
        }

        [Test]
        public void Dotwork_MissingFileIsReported()
        {
            string path = TEMP + "/dotwork/broken.assets.json";
            File.WriteAllText(path, "{\"format\": \"dotwork-assets\", \"version\": \"1.0.0\", \"pack\": \"broken\", \"base\": \"..\", \"assets\": [" +
                                    "{\"kind\": \"sprite\", \"name\": \"ghost\", \"image\": \"art/props/nope.png\", \"size\": [8, 8], \"pivot\": [4, 8]}]}");
            List<string> problems = DotworkImporter.Check(path);
            Assert.IsTrue(problems.Any(p => p.Contains("art/props/nope.png")), string.Join("\n", problems));
            Assert.Throws<DotworkImportException>(() => DotworkImporter.Import(path, TEMP + "/dotwork/broken"));
        }

        [Test]
        public void Dotwork_AutotileHas47BlobMasks()
        {
            Assert.AreEqual(47, Autotile.BlobMasks().Count);
            Assert.AreEqual(255, Autotile.Canon(255));
            Assert.AreEqual(Autotile.N | Autotile.NE | Autotile.E, Autotile.Canon(Autotile.N | Autotile.NE | Autotile.E));
            Assert.AreEqual(Autotile.N, Autotile.Canon(Autotile.N | Autotile.NE));     // a corner needs both sides
        }

        // ---- A sheet render_sprites.py rendered from the golden rigged character (#290) ---------------------
        // Rows are directions, columns frames: one animated_sprite with a clip per action and direction, cut from a
        // shared sheet. The importer takes it as it takes Dotwork's packs.

        [Test]
        public void Dotwork_RenderedCharacterSheetImportsToItsExpectedJson()
        {
            string folder = TEMP + "/rendered";
            CopyDir(RENDERED, folder);
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            var warnings = new List<string>();
            DotworkPack pack = DotworkImporter.Import(folder + "/dotwork/character.assets.json", folder + "/dotwork/character", warnings);
            Assert.IsEmpty(warnings, string.Join("\n", warnings));
            Dictionary<string, object> expected = Json.AsObject(Json.AsObject(Json.Parse(File.ReadAllText(Path.Combine(RENDERED, "expected.json"), Encoding.UTF8)))["assets"]);
            Dictionary<string, object> actual = Loaded(pack);
            Assert.IsNotEmpty(expected.Keys, RENDERED + "/expected.json names no asset");
            CollectionAssert.AreEquivalent(expected.Keys.ToList(), actual.Keys.ToList());
            foreach (string key in expected.Keys)
            {
                GoldenVectors.AssertClose(actual[key], expected[key], PIXEL_TOL, key);
            }
            Assert.IsTrue(pack.Animated("character").ClipNamed("walk_w").clip.isLooping, "a rendered walk loops");
        }

        // ---- Every real manifest of the game -------------------------------------------------

        [Test]
        public void Dotwork_EveryManifestInTheGameLoads()
        {
            List<string> manifests = DotworkManifest.FindAll();
            if (manifests.Count == 0)
            {
                Assert.Ignore($"no Dotwork manifests in {DotworkManifest.FOLDER}/ yet (Dotwork writes them; then python tools/dev.py exec GameKitDotwork.ImportAll)");
            }
            List<string> problems = manifests.SelectMany(DotworkVerify.Problems).ToList();
            Assert.IsEmpty(problems, string.Join("\n", problems));
        }

        // ---- Read back: Unity objects -> the loaded result's numbers ---------------------------------

        private static Dictionary<string, object> Loaded(DotworkPack pack)
        {
            var o = new Dictionary<string, object>();
            foreach (DotworkAnimated a in pack.animated)
            {
                var clips = new Dictionary<string, object>();
                foreach (DotworkClip c in a.clips)
                {
                    clips[c.name] = ClipResult(c);
                }
                var dirs = new Dictionary<string, object>();
                foreach (DotworkDirection d in a.directions)
                {
                    if (!dirs.ContainsKey(d.action))
                    {
                        dirs[d.action] = new Dictionary<string, object>();
                    }
                    ((Dictionary<string, object>)dirs[d.action])[d.dir] = d.clip;
                }
                o["animated_sprite/" + a.name] = Obj("blend", a.blend, "clips", clips, "directions", dirs);
            }
            foreach (DotworkSprite s in pack.sprites)
            {
                var sr = s.prefab.GetComponent<SpriteRenderer>();
                Vector2 pivot = PivotDown(sr.sprite);
                var boxes = s.prefab.GetComponents<BoxCollider2D>().Select(b => (object)Nums(
                    b.offset.x * pack.pixelsPerUnit + pivot.x - b.size.x * pack.pixelsPerUnit / 2,
                    pivot.y - b.offset.y * pack.pixelsPerUnit - b.size.y * pack.pixelsPerUnit / 2,
                    b.size.x * pack.pixelsPerUnit, b.size.y * pack.pixelsPerUnit)).ToList();
                o["sprite/" + s.name] = Obj("size", Nums(sr.sprite.rect.width, sr.sprite.rect.height), "pivot", Nums(pivot.x, pivot.y), "collision", boxes);
            }
            foreach (DotworkIcon i in pack.icons)
            {
                o["icon/" + i.name] = Obj("sizes", i.sizes.Select(s => (double)s.sprite.rect.width).OrderBy(x => x).Cast<object>().ToList());
            }
            foreach (DotworkPortrait p in pack.portraits)
            {
                Sprite first = p.expressions[0].sprite;
                o["portrait/" + p.name] = Obj("size", Nums(first.rect.width, first.rect.height),
                    "expressions", p.expressions.Select(e => e.name).OrderBy(n => n, StringComparer.Ordinal).Cast<object>().ToList(),
                    "animation", string.IsNullOrEmpty(p.animation) ? null : p.animation);
            }
            foreach (DotworkTileset t in pack.tilesets)
            {
                // Per terrain: the distinct masks (a number each) or corner lists, sorted as Python sorts them
                var masks = new Dictionary<string, List<int[]>>();
                var isMask = new Dictionary<string, bool>();
                foreach (DotworkTile tile in t.tiles.Where(x => x.terrain >= 0))
                {
                    string tk = $"{tile.terrainSet}/{tile.terrain}";
                    int[] v = tile.mask >= 0 ? new[] { tile.mask } : tile.corners;
                    if (!masks.ContainsKey(tk))
                    {
                        masks[tk] = new List<int[]>();
                        isMask[tk] = tile.mask >= 0;
                    }
                    if (!masks[tk].Any(x => x.SequenceEqual(v)))
                    {
                        masks[tk].Add(v);
                    }
                }
                var maskOut = new Dictionary<string, object>();
                foreach (KeyValuePair<string, List<int[]>> kv in masks)
                {
                    maskOut[kv.Key] = kv.Value.OrderBy(x => x, Comparer<int[]>.Create(Lexical))
                        .Select(x => isMask[kv.Key] ? (object)(double)x[0] : x.Select(n => (object)(double)n).ToList()).ToList();
                }
                o["tileset/" + t.name] = Obj("tile_size", Nums(t.tileSize.x, t.tileSize.y), "shape", t.shape, "tiles", (double)t.tiles.Count,
                    "collision_tiles", (double)t.tiles.Count(x => x.solid && x.sprite.GetPhysicsShapeCount() > 0),
                    "animated_tiles", (double)t.tiles.Count(x => x.Animated),
                    "terrains", t.terrains.ToDictionary(x => $"{x.set}/{x.id}", x => (object)x.name), "masks", maskOut);
            }
            foreach (DotworkMap map in pack.maps)
            {
                o["map/" + map.name] = MapResult(pack, map);
            }
            foreach (DotworkFont f in pack.fonts)
            {
                DotworkGlyph g = f.glyphs.FirstOrDefault(x => x.id == 65);
                if (g.id != 65)
                {
                    g = f.glyphs[0];
                }
                double x0 = g.x, y0 = g.y, w = g.w, h = g.h;
                if (g.sprite != null)
                {
                    Rect r = g.sprite.rect;
                    x0 = r.x;
                    y0 = g.sprite.texture.height - r.y - r.height;
                    w = r.width;
                    h = r.height;
                }
                o["font/" + f.fontName] = Obj("line_height", (double)f.lineHeight, "base", (double)f.baseline, "chars", (double)f.glyphs.Length,
                    "pages", (double)f.pages.Length, "sample", Nums(g.id, x0, y0, w, h, g.xoffset, g.yoffset, g.xadvance, g.page));
            }
            foreach (DotworkUiKit k in pack.uiKits)
            {
                var parts = new Dictionary<string, object>();
                foreach (DotworkUiPart p in k.parts)
                {
                    Vector4 b = p.sprite.border;                // left, bottom, right, top
                    parts[p.name] = Obj("size", Nums(p.sprite.rect.width, p.sprite.rect.height),
                        "margins", p.hasMargins ? Nums(b.x, b.w, b.z, b.y) : null, "hotspot", p.hasHotspot ? Nums(p.hotspot.x, p.hotspot.y) : null);
                }
                o["ui_kit/" + k.name] = Obj("parts", parts);
            }
            return o;
        }

        private static Dictionary<string, object> ClipResult(DotworkClip c)
        {
            AnimationClip clip = c.clip;
            ObjectReferenceKeyframe[] keys = Keys(clip);
            int n = c.frames;                              // a last frame held longer has one more key after it
            Assert.IsTrue(keys.Length == n || keys.Length == n + 1, $"{clip.name}: {keys.Length} keys for {n} frames");
            var rects = new List<object>();
            var seconds = new List<object>();
            for (int i = 0; i < n; i++)
            {
                var s = (Sprite)keys[i].value;
                Rect r = s.rect;
                rects.Add(Nums(r.x, s.texture.height - r.y - r.height, r.width, r.height));
                // The last frame lasts until the clip's end (Unity's length: the last key plus one frame)
                seconds.Add((double)((i + 1 < n ? keys[i + 1].time : clip.length) - keys[i].time));
            }
            Vector2 pivot = PivotDown((Sprite)keys[0].value);
            return Obj("frames", (double)n, "rects", rects, "seconds", seconds, "length", (double)clip.length,
                "loop", AnimationUtility.GetAnimationClipSettings(clip).loopTime, "pivot", Nums(pivot.x, pivot.y),
                "texture", string.IsNullOrEmpty(c.sheet) ? null : c.sheet);
        }

        private static Dictionary<string, object> MapResult(DotworkPack pack, DotworkMap map)
        {
            DotworkTileset ts = pack.Tileset(map.tileset);
            var inst = (GameObject)Object.Instantiate(map.prefab);
            try
            {
                var layers = new Dictionary<string, object>();
                var terrain = new Dictionary<string, object>();
                foreach (Tilemap tm in inst.GetComponentsInChildren<Tilemap>())
                {
                    var cells = new List<Vector3Int>();
                    foreach (Vector3Int p in tm.cellBounds.allPositionsWithin)
                    {
                        if (tm.GetTile(p) != null)
                        {
                            cells.Add(p);
                        }
                    }
                    layers[tm.name] = (double)cells.Count;
                    var rows = new List<object>();
                    foreach (Vector3Int p in cells.OrderBy(p => -1 - p.y).ThenBy(p => p.x))
                    {
                        if (!(tm.GetTile(p) is DotworkTerrainTile tt))
                        {
                            continue;
                        }
                        Sprite shown = tm.GetSprite(p);
                        DotworkTile tile = shown == null ? null : ts.tiles.FirstOrDefault(x => x.sprite == shown);
                        rows.Add(new List<object> { (double)p.x, (double)(-1 - p.y), (double)tt.MaskAt(tm.GetTile, p),
                            tile == null ? null : Nums(tile.atlas, tile.col, tile.row) });
                    }
                    if (rows.Count > 0)
                    {
                        terrain[tm.name] = rows;
                    }
                }
                var objects = new List<object>();
                foreach (Transform t in inst.transform.Find("Objects"))
                {
                    objects.Add(new List<object> { t.name, (double)(t.localPosition.x * pack.pixelsPerUnit), (double)(-t.localPosition.y * pack.pixelsPerUnit) });
                }
                return Obj("size", Nums(map.size.x, map.size.y), "layers", layers, "terrain", terrain, "objects", objects);
            }
            finally
            {
                Object.DestroyImmediate(inst);
            }
        }

        // ---- Helpers ---------------------------------------------------------------------

        private static bool IsCore(string key) => Array.IndexOf(DotworkManifest.CORE_KINDS, key.Split('/')[0]) >= 0;

        private static Dictionary<string, object> ExpectedAssets()
        {
            string text = File.ReadAllText(Path.Combine(GOLDEN, "expected.json"), Encoding.UTF8);
            return (Dictionary<string, object>)((Dictionary<string, object>)Json.Parse(text))["assets"];
        }

        private static ObjectReferenceKeyframe[] Keys(AnimationClip clip)
        {
            EditorCurveBinding binding = AnimationUtility.GetObjectReferenceCurveBindings(clip).First(b => b.propertyName == "m_Sprite");
            return AnimationUtility.GetObjectReferenceCurve(clip, binding);
        }

        /// <summary>A sprite's pivot in its own pixels, y down (the manifest's space).</summary>
        private static Vector2 PivotDown(Sprite s) => new Vector2(s.pivot.x, s.rect.height - s.pivot.y);

        private static List<object> Nums(params double[] v) => v.Select(x => (object)x).ToList();

        private static Dictionary<string, object> Obj(params object[] pairs)
        {
            var d = new Dictionary<string, object>();
            for (int i = 0; i + 1 < pairs.Length; i += 2)
            {
                d[(string)pairs[i]] = pairs[i + 1];
            }
            return d;
        }

        private static int Lexical(int[] a, int[] b)
        {
            for (int i = 0; i < Math.Min(a.Length, b.Length); i++)
            {
                if (a[i] != b[i])
                {
                    return a[i].CompareTo(b[i]);
                }
            }
            return a.Length.CompareTo(b.Length);
        }

        private static bool Close(Rect a, Rect b) =>
            Math.Abs(a.x - b.x) < 1e-3 && Math.Abs(a.y - b.y) < 1e-3 && Math.Abs(a.width - b.width) < 1e-3 && Math.Abs(a.height - b.height) < 1e-3;

        private static void CopyDir(string from, string to)
        {
            Directory.CreateDirectory(to);
            foreach (string f in Directory.GetFiles(from))
            {
                if (!Path.GetFileName(f).StartsWith("."))
                {
                    File.Copy(f, Path.Combine(to, Path.GetFileName(f)), true);
                }
            }
            foreach (string d in Directory.GetDirectories(from))
            {
                CopyDir(d, Path.Combine(to, Path.GetFileName(d)));
            }
        }

        private static void DeleteTemp()
        {
            if (AssetDatabase.IsValidFolder(TEMP))
            {
                AssetDatabase.DeleteAsset(TEMP);
            }
            if (Directory.Exists(TEMP))
            {
                Directory.Delete(TEMP, true);
                File.Delete(TEMP + ".meta");
                AssetDatabase.Refresh();
            }
        }
    }
}

// {{FOOTER}}
