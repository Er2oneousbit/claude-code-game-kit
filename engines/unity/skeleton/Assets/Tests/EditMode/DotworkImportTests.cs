// ---------------------------------------------------------------------------
// DotworkImportTests.cs
// Purpose : The Dotwork importer (#57, spec 1.1.0 #285) against the golden fixture: copy data/golden/dotwork/assets
//           into a temporary folder under Assets/, import its manifest, read the numbers back from the Unity objects
//           it made (sprite rects and pivots, AnimationClip keys, BoxCollider2Ds, tiles, the maps' Tilemaps with
//           their Grid's cell centres, the font, the extra kinds) and compare them with data/golden/dotwork/
//           expected.json (assetspec.expected(), the loaded result every engine's importer must reproduce) to
//           1e-6. Then the explicit cases of the spec (hash and roll vectors, the corners4 rule, isometric centres,
//           a stamps layer, the variant pick, a map's bounds), the rendered-character golden, and every real
//           manifest of the game.
// Usage   : python tools/dev.py test --filter Dotwork
// Notes   : Read-back, not re-computed: a rect comes from Sprite.rect flipped back to y down, a frame's seconds from
//           the clip's key times, a terrain cell's key from the Tilemap's own neighbours and its tile from the
//           DotworkTile the Tilemap holds, a placed cell's top-left from where the Tilemap puts the sprite's pivot
//           (CellToLocalInterpolated(cell + tileAnchor), Unity's own grid math, isometric included) less the pivot.
//           The order of `placed` follows the manifest's cell lists (the spec's order), which a Tilemap does not
//           keep, so the manifest drives the walk and the Tilemap answers. The temporary folders are deleted
//           afterwards (and before, if a killed run left them).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): asset manifest 1.1.0 (#285): placed cells and
//           centres on both shapes, corners4 keys, the variant pick, stamps, the extra kinds loaded, the
//           rendered-character golden
//           2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): DotworkMap.Bounds on both shapes (#297)
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
        private const string CHARACTER = "data/golden/character/sprites";   // the rendered character sheet pack
        private const string TEMP = "Assets/__DotworkGolden";       // gitignored; deleted after the run
        private const string TEMP_CHARACTER = "Assets/__DotworkCharacter";
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
            DeleteTemp(TEMP);
            CopyDir(Path.Combine(GOLDEN, "assets"), TEMP);
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            Warnings.Clear();
            _pack = DotworkImporter.Import(MANIFEST, OUT, Warnings);
            _expected = ExpectedAssets(GOLDEN);
            _actual = Loaded(_pack, MANIFEST);
        }

        [OneTimeTearDown]
        public void DeleteTheFixture()
        {
            DeleteTemp(TEMP);
            DeleteTemp(TEMP_CHARACTER);
        }

        // ---- The loaded result ---------------------------------------------------------

        private static IEnumerable<TestCaseData> AllAssets()
        {
            var cases = new List<TestCaseData>();
            try
            {
                foreach (string key in ExpectedAssets(GOLDEN).Keys)
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

        [TestCaseSource(nameof(AllAssets))]
        public void LoadedResultMatchesExpected(string key)
        {
            Assert.IsTrue(_expected.ContainsKey(key), $"{GOLDEN}/expected.json: {key} not found");
            Assert.IsTrue(_actual.ContainsKey(key), $"{key} was not imported");
            GoldenVectors.AssertClose(_actual[key], _expected[key], TOL, key);
        }

        [Test]
        public void Dotwork_EveryAssetIsImported()
        {
            CollectionAssert.AreEquivalent(_expected.Keys.ToList(), _actual.Keys.ToList());
            CollectionAssert.IsEmpty(_pack.skipped, "every kind of the fixture is known");
            Assert.IsFalse(Warnings.Any(w => w.Contains("skipped")), string.Join("\n", Warnings));
        }

        // ---- The extra kinds are loaded, not skipped -----------------------------------------

        [Test]
        public void Dotwork_ExtraKindsAreLoaded()
        {
            DotworkManifest m = DotworkManifest.Load(MANIFEST);
            foreach (Dictionary<string, object> a in m.Assets)
            {
                string kind = DotworkManifest.Str(a, "kind"), name = DotworkManifest.Str(a, "name");
                if (Array.IndexOf(DotworkManifest.EXTRA_KINDS, kind) >= 0)
                {
                    Assert.IsTrue(DotworkVerify.HasEntry(_pack, kind, name), $"{kind}/{name} is not in the pack");
                }
            }
            DotworkBackground bg = _pack.backgrounds[0];
            Assert.IsTrue(bg.layers.All(l => l.sprite != null), "every background layer has its sprite");
            Assert.IsTrue(bg.layers.Any(l => l.repeat == "x" && ((TextureImporter)AssetImporter.GetAtPath(AssetDatabase.GetAssetPath(l.sprite.texture))).wrapModeU == TextureWrapMode.Repeat),
                          "a layer that repeats on x has a texture that wraps on u");
            DotworkTransition tr = _pack.transitions[0];
            Assert.IsNotNull(tr.sprite);
            Assert.IsNotEmpty(tr.transition);
            Assert.AreEqual(new Vector2Int((int)tr.sprite.rect.width, (int)tr.sprite.rect.height), tr.size);
            DotworkImage img = _pack.images[0];
            Assert.IsNotNull(img.sprite);
            Assert.AreEqual(new Vector2Int((int)img.sprite.rect.width, (int)img.sprite.rect.height), img.size);
        }

        [Test]
        public void Dotwork_ParticlesCarryTheEmitterJson()
        {
            DotworkManifest m = DotworkManifest.Load(MANIFEST);
            foreach (Dictionary<string, object> a in m.Assets.Where(a => DotworkManifest.Str(a, "kind") == "particles"))
            {
                DotworkParticles p = _pack.Particles(DotworkManifest.Str(a, "name"));
                Assert.IsNotNull(p.texture, $"{p.name} texture");
                Assert.IsNotNull(p.emitter, $"{p.name} emitter");
                GoldenVectors.AssertClose(Json.Parse(p.emitter.text), DotworkManifest.Obj(a, "emitter"), TOL, $"particles/{p.name} emitter");
                Assert.AreEqual(m.Resolve(DotworkManifest.Str(a, "texture")), AssetDatabase.GetAssetPath(p.texture.texture));
            }
        }

        [Test]
        public void Dotwork_NormalMapIsTheTargetsSecondaryTexture()
        {
            DotworkManifest m = DotworkManifest.Load(MANIFEST);
            foreach (Dictionary<string, object> a in m.Assets.Where(a => DotworkManifest.Str(a, "kind") == "normal_map"))
            {
                DotworkNormalMap n = _pack.NormalMap(DotworkManifest.Str(a, "name"));
                string normalPath = m.Resolve(DotworkManifest.Str(a, "image")), targetPath = m.Resolve(DotworkManifest.Str(a, "target"));
                Assert.AreEqual(normalPath, AssetDatabase.GetAssetPath(n.texture), $"{n.name} texture");
                var ni = (TextureImporter)AssetImporter.GetAtPath(normalPath);
                Assert.IsFalse(ni.sRGBTexture, "a normal map is linear");
                Assert.AreEqual(FilterMode.Point, ni.filterMode);
                var ti = (TextureImporter)AssetImporter.GetAtPath(targetPath);
                SecondarySpriteTexture[] secondary = ti.secondarySpriteTextures;
                Assert.AreEqual(1, secondary.Length, $"{n.target} has one secondary texture");
                Assert.AreEqual(DotworkImporter.NORMAL_MAP_SLOT, secondary[0].name);
                Assert.AreEqual(n.texture, secondary[0].texture, "the slot holds the normal map");
                Assert.IsNotNull(n.targetSprite, "the target's sprite");
                Assert.AreEqual(targetPath, AssetDatabase.GetAssetPath(n.targetSprite.texture));
                Assert.AreEqual(1, n.targetSprite.GetSecondaryTextureCount(), "the sprite sees the slot");
                var onSprite = new SecondarySpriteTexture[1];
                n.targetSprite.GetSecondaryTextures(onSprite);
                Assert.AreEqual(DotworkImporter.NORMAL_MAP_SLOT, onSprite[0].name);
                Assert.AreEqual(n.texture, onSprite[0].texture);
                Assert.AreEqual(n.targetSprite.texture, _pack.Sprite("crate").sprite.texture, "the target is the crate's own image");
            }
        }

        // ---- The spec's explicit cases -------------------------------------------------------

        [Test]
        public void Dotwork_HashAndRollVectors()
        {
            // The spec's test vectors (ASSET_MANIFEST.md "Variants: the probability pick")
            Assert.AreEqual(1800329511u, Autotile.Hash32(0));
            Assert.AreEqual(3028713910u, Autotile.Hash32(1));
            Assert.AreEqual(4268016002u, Autotile.Hash32(0xFFFFFFFFu));
            Assert.AreEqual(0.169182, Autotile.CellRoll(0, 0, 0), TOL);
            Assert.AreEqual(0.765973, Autotile.CellRoll(3, 1, 1), TOL);
            Assert.AreEqual(0.531301, Autotile.CellRoll(3, 2, 1), TOL);
            Assert.AreEqual(0.992978, Autotile.CellRoll(-1, -1, 0), TOL);
            // The pick walks the weights in order; weight 0 is never picked; all zero gives the first
            Assert.AreEqual(0, Autotile.Pick(new double[] { 1, 0.6 }, 0.531301));
            Assert.AreEqual(1, Autotile.Pick(new double[] { 1, 0.6 }, 0.765973));
            Assert.AreEqual(1, Autotile.Pick(new double[] { 0, 1 }, 0.0));
            Assert.AreEqual(0, Autotile.Pick(new double[] { 0, 0 }, 0.9));
            Assert.AreEqual(1, Autotile.Pick(new double[] { 1, 1 }, 0.999999999));
        }

        [Test]
        public void Dotwork_Corners4MaskOnA3x3Block()
        {
            var block = new HashSet<(int, int)>();
            for (int y = 0; y < 3; y++)
            {
                for (int x = 0; x < 3; x++)
                {
                    block.Add((x, y));
                }
            }
            bool Painted(int x, int y) => block.Contains((x, y));
            Assert.AreEqual(170, Autotile.CellMask(Painted, 1, 1, Autotile.CORNERS4), "centre: all four corners");
            Assert.AreEqual(8, Autotile.CellMask(Painted, 0, 0, Autotile.CORNERS4), "top-left: SE only");
            Assert.AreEqual(40, Autotile.CellMask(Painted, 1, 0, Autotile.CORNERS4), "top-middle: SE and SW");
            Assert.AreEqual(255, Autotile.CellMask(Painted, 1, 1, Autotile.BLOB47));
            Assert.AreEqual(Autotile.E | Autotile.S, Autotile.CellMask(Painted, 0, 0, Autotile.SIDES4));
            // Corner names map to bits by shape
            var square = new Dictionary<string, int> { { "top_left", 1 }, { "top_right", 0 }, { "bottom_right", 1 }, { "bottom_left", 0 } };
            Assert.AreEqual(Autotile.NW | Autotile.SE, Autotile.CornerKey(square, 1, "square"));
            var iso = new Dictionary<string, int> { { "top", 1 }, { "right", 1 }, { "bottom", 0 }, { "left", 0 } };
            Assert.AreEqual(Autotile.NW | Autotile.NE, Autotile.CornerKey(iso, 1, "isometric"));
            Assert.AreEqual(-1, Autotile.CornerKey(square, 1, "isometric"), "the wrong shape's names give no key");
        }

        [Test]
        public void Dotwork_IsometricCentresComeFromTheGrid()
        {
            // The Grid itself places the isle's diamonds where the spec's formula says (expected.json centres)
            DotworkMap isle = _pack.Map("isle");
            Assert.AreEqual("isometric", isle.shape);
            var centres = (List<object>)((Dictionary<string, object>)_expected["map/isle"])["centres"];
            var inst = (GameObject)Object.Instantiate(isle.prefab);
            try
            {
                Assert.AreEqual(GridLayout.CellLayout.Isometric, inst.GetComponent<Grid>().cellLayout);
                Tilemap tm = inst.GetComponentInChildren<Tilemap>();
                int seen = 0;
                foreach (object row in centres)
                {
                    double[] c = DotworkManifest.Nums(row, 4);          // x, y, cx, cy
                    if (!((c[0] == 0 && c[1] == 0) || (c[0] == 1 && c[1] == 0) || (c[0] == 0 && c[1] == 1) || (c[0] == 3 && c[1] == 2)))
                    {
                        continue;
                    }
                    Vector2 got = CentrePx(tm, _pack.pixelsPerUnit, DotworkImporter.Cell(isle.shape, (int)c[0], (int)c[1]));
                    Assert.AreEqual(c[2], got.x, TOL, $"cell ({c[0]}, {c[1]}) centre x");
                    Assert.AreEqual(c[3], got.y, TOL, $"cell ({c[0]}, {c[1]}) centre y");
                    seen++;
                }
                Assert.AreEqual(4, seen, "the four spot cells of the spec");
            }
            finally
            {
                Object.DestroyImmediate(inst);
            }
            // The cell mapping and its inverse agree on both shapes
            foreach (string shape in new[] { "square", "isometric" })
            {
                Assert.AreEqual(new Vector2Int(3, 2), DotworkImporter.MapCell(shape, DotworkImporter.Cell(shape, 3, 2)), shape);
            }
        }

        [Test]
        public void Dotwork_MapBoundsAreTheRealExtentOnBothShapes()
        {
            // #297: the showcase framed every map by the square box (0..w, -h..0), so an isometric map sat off-centre.
            // Bounds is the box around every cell's tile from the spec's centres, and holds every centre the Grid placed.
            const float tol = 1e-4f;
            float ppu = _pack.pixelsPerUnit;
            foreach (string name in new[] { "isle", "yard" })
            {
                DotworkMap map = _pack.Map(name);
                Rect b = map.Bounds(ppu);
                float tw = map.tileSize.x, th = map.tileSize.y;
                float l = float.MaxValue, t = float.MaxValue, r = float.MinValue, d = float.MinValue;
                for (int x = 0; x < map.size.x; x++)
                {
                    for (int y = 0; y < map.size.y; y++)
                    {
                        Vector2 c = DotworkImporter.CellCentre(map.shape, x, y, tw, th);
                        l = Mathf.Min(l, c.x - tw / 2f);
                        r = Mathf.Max(r, c.x + tw / 2f);
                        t = Mathf.Min(t, c.y - th / 2f);
                        d = Mathf.Max(d, c.y + th / 2f);
                    }
                }
                Assert.AreEqual(l / ppu, b.xMin, tol, $"{name} ({map.shape}) left");
                Assert.AreEqual(r / ppu, b.xMax, tol, $"{name} right");
                Assert.AreEqual(-t / ppu, b.yMax, tol, $"{name} top (y up)");
                Assert.AreEqual(-d / ppu, b.yMin, tol, $"{name} bottom");
                var inst = (GameObject)Object.Instantiate(map.prefab);
                try
                {
                    int seen = 0;
                    foreach (Tilemap tm in inst.GetComponentsInChildren<Tilemap>())
                    {
                        foreach (Vector3Int p in tm.cellBounds.allPositionsWithin)
                        {
                            if (tm.GetTile(p) == null)
                            {
                                continue;
                            }
                            Vector2 px = CentrePx(tm, ppu, p);
                            Assert.IsTrue(b.Contains(new Vector2(px.x / ppu, -px.y / ppu)), $"{name}: cell {p} centre {px} inside {b}");
                            seen++;
                        }
                    }
                    Assert.Greater(seen, 0, $"{name} has painted cells");
                }
                finally
                {
                    Object.DestroyImmediate(inst);
                }
            }
            DotworkMap isle = _pack.Map("isle");
            Assert.AreEqual("isometric", isle.shape);
            var square = new Rect(0f, -isle.size.y * isle.tileSize.y / ppu, isle.size.x * isle.tileSize.x / ppu, isle.size.y * isle.tileSize.y / ppu);
            Assert.Greater(Mathf.Abs(isle.Bounds(ppu).center.x - square.center.x), isle.tileSize.x / ppu / 4f,
                           "the isometric map's centre is not the square box's");
        }

        [Test]
        public void Dotwork_StampsLayerPlacesEveryTileOfTheStamp()
        {
            DotworkManifest m = DotworkManifest.Load(MANIFEST);
            Dictionary<string, object> yard = m.Assets.First(a => DotworkManifest.Str(a, "kind") == "map" && DotworkManifest.Str(a, "name") == "yard");
            Dictionary<string, object> layer = DotworkManifest.Objs(yard, "layers").First(L => DotworkManifest.Str(L, "kind") == "stamps");
            DotworkTileset ts = _pack.Tileset("ground_yard");
            Assert.IsNotEmpty(ts.stamps, "the tileset has stamps");
            var inst = (GameObject)Object.Instantiate(_pack.Map("yard").prefab);
            try
            {
                var tm = inst.transform.Find(DotworkManifest.Str(layer, "name")).GetComponent<Tilemap>();
                int placed = 0;
                foreach (object c in DotworkManifest.List(layer, "cells"))
                {
                    double[] v = DotworkManifest.Nums(c, 3);
                    DotworkStamp stamp = ts.stamps[(int)v[2]];
                    for (int j = 0; j < stamp.tiles.Length; j++)
                    {
                        int x = (int)v[0] + j % stamp.size.x, y = (int)v[1] + j / stamp.size.x;
                        var tile = tm.GetTile<DotworkTile>(DotworkImporter.Cell(ts.shape, x, y));
                        Assert.IsNotNull(tile, $"stamp {stamp.name} tile {j} at ({x}, {y})");
                        Assert.AreEqual(stamp.tiles[j], new Vector3Int(tile.atlas, tile.col, tile.row), $"stamp {stamp.name} tile {j}");
                        placed++;
                    }
                }
                Assert.AreEqual(placed, Count(tm), "the layer holds the stamps' tiles and nothing else");
                Assert.IsNotNull(inst.transform.Find(DotworkManifest.Str(layer, "name")).GetComponent<TilemapCollider2D>(), "the door's tiles collide");
            }
            finally
            {
                Object.DestroyImmediate(inst);
            }
        }

        [Test]
        public void Dotwork_VariantPickFollowsTheRoll()
        {
            // The rule tile (what the Tile Palette paints with) picks the same variants the map got: both path cells
            // with every neighbour painted (key 255) in expected.json, one of which rolls the variant tile
            var path = (List<object>)((Dictionary<string, object>)((Dictionary<string, object>)_expected["map/yard"])["terrain"])["Path"];
            DotworkManifest m = DotworkManifest.Load(MANIFEST);
            Dictionary<string, object> yard = m.Assets.First(a => DotworkManifest.Str(a, "kind") == "map" && DotworkManifest.Str(a, "name") == "yard");
            List<Dictionary<string, object>> layers = DotworkManifest.Objs(yard, "layers").ToList();
            int layerIndex = layers.FindIndex(L => DotworkManifest.Str(L, "name") == "Path");
            Dictionary<string, object> L = layers[layerIndex];
            DotworkTerrain terrain = _pack.Tileset("ground_yard").Terrain(DotworkManifest.Int(L, "terrain_set", 0), DotworkManifest.Int(L, "terrain"));
            Assert.IsNotNull(terrain.tile, "the path terrain has a rule tile");
            var picks = new HashSet<string>();
            foreach (object row in path)
            {
                var r = (List<object>)row;
                int x = (int)Json.ToNumber(r[0]), y = (int)Json.ToNumber(r[1]), key = (int)Json.ToNumber(r[2]);
                double[] want = DotworkManifest.Nums(r[3], 3);
                DotworkTile got = terrain.tile.TileFor(key, Autotile.CellRoll(x, y, layerIndex));
                Assert.IsNotNull(got, $"({x}, {y}) key {key}");
                Assert.AreEqual(new Vector3Int((int)want[0], (int)want[1], (int)want[2]), new Vector3Int(got.atlas, got.col, got.row), $"({x}, {y}) key {key}");
                if (key == 255)
                {
                    picks.Add($"{got.col},{got.row}");
                }
            }
            Assert.AreEqual(2, picks.Count, "the two full path cells roll different variants");
        }

        [Test]
        public void Dotwork_RenderedCharacterSheetLoads()
        {
            // The rendered-character golden (tools/blender/render_sprites.py --manifest): a 1.0.0 pack of one
            // animated_sprite, loaded by this importer the same way
            DeleteTemp(TEMP_CHARACTER);
            CopyDir(Path.Combine(CHARACTER, "art"), TEMP_CHARACTER + "/art");
            CopyDir(Path.Combine(CHARACTER, "dotwork"), TEMP_CHARACTER + "/dotwork");
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            string manifest = Directory.GetFiles(TEMP_CHARACTER + "/dotwork", "*" + DotworkManifest.SUFFIX).Select(DotworkManifest.Norm).First();
            var warnings = new List<string>();
            DotworkPack pack = DotworkImporter.Import(manifest, TEMP_CHARACTER + "/dotwork/out", warnings);
            Dictionary<string, object> expected = ExpectedAssets(CHARACTER);
            Dictionary<string, object> actual = Loaded(pack, manifest);
            CollectionAssert.AreEquivalent(expected.Keys.ToList(), actual.Keys.ToList());
            foreach (string key in expected.Keys)
            {
                GoldenVectors.AssertClose(actual[key], PivotsThroughFloat32(expected[key]), TOL, key);
            }
            Assert.IsEmpty(warnings, string.Join("\n", warnings));
        }

        /// <summary>A sprite's pivot is a float32 in Unity: this pack's rendered pivots (24, 37.6) are not
        /// representable, the importer sets the nearest float (37.599998, 1.5e-6 off, over the 1e-6 tolerance),
        /// so the expected clip pivots are compared through float32 too. Everything else is compared as is.</summary>
        private static object PivotsThroughFloat32(object expectedAsset)
        {
            if (!(expectedAsset is Dictionary<string, object> asset) || !(asset.TryGetValue("clips", out object cv) && cv is Dictionary<string, object> clips))
            {
                return expectedAsset;
            }
            var copy = new Dictionary<string, object>(asset);
            var clipsCopy = new Dictionary<string, object>();
            foreach (KeyValuePair<string, object> kv in clips)
            {
                var clip = new Dictionary<string, object>((Dictionary<string, object>)kv.Value);
                if (clip.TryGetValue("pivot", out object pv) && pv is List<object> pivot)
                {
                    clip["pivot"] = pivot.Select(v => (object)(double)(float)Json.ToNumber(v)).ToList();
                }
                clipsCopy[kv.Key] = clip;
            }
            copy["clips"] = clipsCopy;
            return copy;
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
                        // The sprite's pivot is the tile's origin (its own, else the atlas cell's centre)
                        Vector2 origin = DotworkManifest.Has(t, "origin") ? Pt(DotworkManifest.Nums(t, "origin", 2)) : new Vector2((float)size[0] / 2f, (float)size[1] / 2f);
                        Assert.AreEqual(origin, tile.origin, $"{s.name} origin");
                        Assert.IsTrue((PivotDown(s) - origin).magnitude < 1e-3, $"{s.name}: pivot {PivotDown(s)} is not the origin {origin}");
                    }
                }
            }
        }

        [Test]
        public void Dotwork_MapLayersAreTilemapsWithColliders()
        {
            GameObject map = _pack.Map("yard").prefab;
            Assert.IsNotNull(map.GetComponent<Grid>());
            Assert.AreEqual(GridLayout.CellLayout.Rectangle, map.GetComponent<Grid>().cellLayout);
            Assert.IsNotNull(map.transform.Find("Water").GetComponent<TilemapCollider2D>(), "water tiles collide");
            Assert.IsNotNull(map.transform.Find("Fixtures").GetComponent<TilemapCollider2D>(), "fixtures collide");
            Assert.IsNull(map.transform.Find("Path").GetComponent<TilemapCollider2D>(), "a path does not collide");
            // A terrain layer holds the resolved tiles themselves: the water cell is a plain animated DotworkTile
            var water = map.transform.Find("Water").GetComponent<Tilemap>();
            var t = water.GetTile<DotworkTile>(DotworkImporter.Cell(2, 2));
            Assert.IsNotNull(t, "water (2, 2) is a DotworkTile");
            Assert.IsTrue(t.Animated, "water animates");
            var anim = new TileAnimationData();
            Assert.IsTrue(t.GetTileAnimationData(Vector3Int.zero, null, ref anim));
            Assert.AreEqual(2, anim.animatedSprites.Length);
            Assert.AreEqual(4f, anim.animationSpeed, 1e-6);
            Assert.AreEqual(t.sprite, water.GetSprite(DotworkImporter.Cell(2, 2)), "the Tilemap shows the tile's sprite");
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
            TextAsset emitter = _pack.particles[0].emitter;
            string packGuid = AssetDatabase.AssetPathToGUID(AssetDatabase.GetAssetPath(_pack));
            DotworkPack again = DotworkImporter.Import(MANIFEST, OUT);
            Assert.AreSame(_pack, again, "the same pack asset");
            Assert.AreEqual(packGuid, AssetDatabase.AssetPathToGUID(AssetDatabase.GetAssetPath(again)));
            Assert.AreSame(tile, again.Tileset("ground_yard").tiles[0], "tiles are updated in place");
            Assert.AreSame(clip, again.Animated("hero").clips[0].clip, "clips are updated in place");
            Assert.AreSame(prefab, again.Map("yard").prefab, "prefabs keep their asset");
            Assert.AreSame(emitter, again.particles[0].emitter, "the emitter JSON keeps its asset");
            GoldenVectors.AssertClose(Loaded(again, MANIFEST), Loaded(_pack, MANIFEST), TOL, "the second import");
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
        public void Dotwork_UnknownLayerKindIsSkippedWithOneWarning()
        {
            // A 1.x map with a layer kind this importer does not know: the layer is empty, the map still imports
            string text = File.ReadAllText(MANIFEST, Encoding.UTF8);
            var doc = (Dictionary<string, object>)Json.Parse(text);
            doc["pack"] = "future_map";
            var assets = (List<object>)doc["assets"];
            assets.RemoveAll(a => !(a is Dictionary<string, object> d) || !(DotworkManifest.Str(d, "kind") == "tileset" && DotworkManifest.Str(d, "name") == "ground_yard"
                                                                           || DotworkManifest.Str(d, "kind") == "map" && DotworkManifest.Str(d, "name") == "yard"));
            var map = (Dictionary<string, object>)assets.First(a => DotworkManifest.Str((Dictionary<string, object>)a, "kind") == "map");
            map["objects"] = new List<object>();
            ((List<object>)map["layers"]).Add(new Dictionary<string, object> { { "name", "Holo" }, { "kind", "hologram" }, { "cells", new List<object> { new List<object> { 0.0, 0.0 } } } });
            string path = TEMP + "/dotwork/future_map.assets.json";
            File.WriteAllText(path, Json.Stringify(doc), new UTF8Encoding(false));
            var warnings = new List<string>();
            DotworkPack pack = DotworkImporter.Import(path, TEMP + "/dotwork/future_map", warnings);
            Assert.AreEqual(1, warnings.Count(w => w.Contains("hologram")), string.Join("\n", warnings));
            var inst = (GameObject)Object.Instantiate(pack.Map("yard").prefab);
            try
            {
                Assert.AreEqual(0, Count(inst.transform.Find("Holo").GetComponent<Tilemap>()), "the unknown layer stays empty");
                Assert.Greater(Count(inst.transform.Find("Base").GetComponent<Tilemap>()), 0, "the known layers are placed");
            }
            finally
            {
                Object.DestroyImmediate(inst);
            }
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

        private static Dictionary<string, object> Loaded(DotworkPack pack, string manifestPath)
        {
            DotworkManifest m = DotworkManifest.Load(manifestPath);
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
                Dictionary<string, object> asset = m.Assets.First(a => DotworkManifest.Str(a, "kind") == "map" && DotworkManifest.Str(a, "name") == map.name);
                o["map/" + map.name] = MapResult(pack, map, asset);
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
            foreach (DotworkBackground b in pack.backgrounds)
            {
                o["background/" + b.name] = Obj("layers", b.layers.Select(l => (object)new List<object>
                    { (double)l.sprite.rect.width, (double)l.sprite.rect.height, (double)l.velocity.x, (double)l.velocity.y, l.repeat }).ToList());
            }
            pack.particles.ForEach(p => o["particles/" + p.name] = Obj("kind", "particles"));
            pack.transitions.ForEach(t => o["transition/" + t.name] = Obj("kind", "transition"));
            pack.normalMaps.ForEach(n => o["normal_map/" + n.name] = Obj("kind", "normal_map"));
            pack.images.ForEach(i => o["image/" + i.name] = Obj("kind", "image"));
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

        /// <summary>The map as the spec's loaded result, read from the prefab's Tilemaps: cells per layer, every
        /// terrain cell with its key (from the Tilemap's own neighbours) and its tile, every placed cell with the
        /// image's top-left (where the Tilemap puts the sprite's pivot, less the pivot), every cell's centre, the
        /// objects. The manifest's layer list gives the walk order the spec wants.</summary>
        private static Dictionary<string, object> MapResult(DotworkPack pack, DotworkMap map, Dictionary<string, object> asset)
        {
            DotworkTileset ts = pack.Tileset(map.tileset);
            float ppu = pack.pixelsPerUnit;
            var inst = (GameObject)Object.Instantiate(map.prefab);
            try
            {
                var layers = new Dictionary<string, object>();
                var terrain = new Dictionary<string, object>();
                var placed = new Dictionary<string, object>();
                Tilemap any = null;
                foreach (Dictionary<string, object> L in DotworkManifest.Objs(asset, "layers"))
                {
                    string lname = DotworkManifest.Str(L, "name"), kind = DotworkManifest.Str(L, "kind", "");
                    var tm = inst.transform.Find(lname).GetComponent<Tilemap>();
                    any = any ?? tm;
                    layers[lname] = (double)Count(tm);
                    // The cells to read, in the spec's order: the layer's list (stamps expanded) or, for terrain, by y then x
                    var walk = new List<Vector2Int>();
                    if (kind == "terrain")
                    {
                        foreach (Vector3Int p in tm.cellBounds.allPositionsWithin)
                        {
                            if (tm.GetTile(p) != null)
                            {
                                walk.Add(DotworkImporter.MapCell(map.shape, p));
                            }
                        }
                        walk = walk.OrderBy(p => p.y).ThenBy(p => p.x).ToList();
                    }
                    else if (kind == "stamps")
                    {
                        foreach (object c in DotworkManifest.List(L, "cells"))
                        {
                            double[] v = DotworkManifest.Nums(c, 3);
                            DotworkStamp stamp = ts.stamps[(int)v[2]];
                            for (int j = 0; j < stamp.tiles.Length; j++)
                            {
                                walk.Add(new Vector2Int((int)v[0] + j % stamp.size.x, (int)v[1] + j / stamp.size.x));
                            }
                        }
                    }
                    else
                    {
                        foreach (object c in DotworkManifest.List(L, "cells"))
                        {
                            double[] v = DotworkManifest.Nums(c, 2);
                            walk.Add(new Vector2Int((int)v[0], (int)v[1]));
                        }
                    }
                    var rows = new List<object>();
                    var trows = new List<object>();
                    string mode = kind == "terrain" ? ts.Terrain(DotworkManifest.Int(L, "terrain_set", 0), DotworkManifest.Int(L, "terrain"))?.mode : null;
                    foreach (Vector2Int p in walk)
                    {
                        Vector3Int cell = DotworkImporter.Cell(map.shape, p.x, p.y);
                        var tile = tm.GetTile<DotworkTile>(cell);
                        Assert.IsNotNull(tile, $"map {map.name} layer {lname}: no tile at ({p.x}, {p.y})");
                        Sprite shown = tm.GetSprite(cell);
                        Assert.AreEqual(tile.sprite, shown, $"map {map.name} layer {lname} ({p.x}, {p.y}): the Tilemap shows the tile's sprite");
                        // Where Unity draws it: the sprite's pivot at the tile anchor, in map pixels, y down
                        Vector3 at = tm.LocalToWorld(tm.CellToLocalInterpolated(cell + tm.tileAnchor));
                        Vector2 pivot = PivotDown(shown);
                        rows.Add(Nums(p.x, p.y, tile.atlas, tile.col, tile.row, at.x * ppu - pivot.x, -at.y * ppu - pivot.y));
                        if (mode != null)
                        {
                            int key = Autotile.CellMask((nx, ny) => tm.GetTile(DotworkImporter.Cell(map.shape, nx, ny)) != null, p.x, p.y, mode);
                            trows.Add(new List<object> { (double)p.x, (double)p.y, (double)key, Nums(tile.atlas, tile.col, tile.row) });
                        }
                    }
                    placed[lname] = rows;
                    if (kind == "terrain")
                    {
                        terrain[lname] = trows;
                    }
                }
                var centres = new List<object>();
                for (int y = 0; y < map.size.y; y++)
                {
                    for (int x = 0; x < map.size.x; x++)
                    {
                        Vector2 c = CentrePx(any, ppu, DotworkImporter.Cell(map.shape, x, y));
                        centres.Add(Nums(x, y, c.x, c.y));
                    }
                }
                var objects = new List<object>();
                foreach (Transform t in inst.transform.Find("Objects"))
                {
                    objects.Add(new List<object> { t.name, (double)(t.localPosition.x * ppu), (double)(-t.localPosition.y * ppu) });
                }
                return Obj("size", Nums(map.size.x, map.size.y), "shape", map.shape, "tile_size", Nums(map.tileSize.x, map.tileSize.y),
                    "layers", layers, "terrain", terrain, "placed", placed, "centres", centres, "objects", objects);
            }
            finally
            {
                Object.DestroyImmediate(inst);
            }
        }

        // ---- Helpers ---------------------------------------------------------------------

        /// <summary>A cell's centre as the Grid places it, in map pixels (y down), through the layer's transform.</summary>
        private static Vector2 CentrePx(Tilemap tm, float ppu, Vector3Int cell)
        {
            Vector3 w = tm.LocalToWorld(tm.CellToLocalInterpolated(cell + new Vector3(0.5f, 0.5f, 0f)));
            return new Vector2(w.x * ppu, -w.y * ppu);
        }

        private static int Count(Tilemap tm)
        {
            int n = 0;
            foreach (Vector3Int p in tm.cellBounds.allPositionsWithin)
            {
                if (tm.GetTile(p) != null)
                {
                    n++;
                }
            }
            return n;
        }

        private static Dictionary<string, object> ExpectedAssets(string folder)
        {
            string text = File.ReadAllText(Path.Combine(folder, "expected.json"), Encoding.UTF8);
            return (Dictionary<string, object>)((Dictionary<string, object>)Json.Parse(text))["assets"];
        }

        private static ObjectReferenceKeyframe[] Keys(AnimationClip clip)
        {
            EditorCurveBinding binding = AnimationUtility.GetObjectReferenceCurveBindings(clip).First(b => b.propertyName == "m_Sprite");
            return AnimationUtility.GetObjectReferenceCurve(clip, binding);
        }

        /// <summary>A sprite's pivot in its own pixels, y down (the manifest's space).</summary>
        private static Vector2 PivotDown(Sprite s) => new Vector2(s.pivot.x, s.rect.height - s.pivot.y);

        private static Vector2 Pt(double[] v) => new Vector2((float)v[0], (float)v[1]);

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

        private static void DeleteTemp(string folder)
        {
            if (AssetDatabase.IsValidFolder(folder))
            {
                AssetDatabase.DeleteAsset(folder);
            }
            if (Directory.Exists(folder))
            {
                Directory.Delete(folder, true);
                File.Delete(folder + ".meta");
                AssetDatabase.Refresh();
            }
        }
    }
}

// {{FOOTER}}
