// ---------------------------------------------------------------------------
// GameKitDotwork.cs
// Purpose : The Dotwork commands (#57): import every Dotwork pack of the game into Unity assets, check that every
//           manifest and its imported assets load (the stand-in for Dotwork's Godot `verify`), and show the art in
//           the starter scene (a character walking, a prop, the tile map, a label in the font).
// Usage   : python tools/dev.py exec GameKitDotwork.ImportAll            after every `dotwork.py pack` / `character`
//           python tools/dev.py exec GameKitDotwork.Verify               exit 1 on a missing file, broken or stale import
//           python tools/dev.py exec GameKitDotwork.ShowInStarterScene   (makes Assets/Scenes/Main.unity when missing)
//           (or the menu Tools > Game Kit > Dotwork)
// Notes   : Manifests are Assets/dotwork/<pack>.assets.json (Dotwork writes them; the spec is
//           tools/art/dotwork/ASSET_MANIFEST.md); each pack is imported into Assets/dotwork/<pack>/ with its index
//           Assets/dotwork/<pack>/<pack>.asset (DotworkPack). Commit the generated assets and their .meta files:
//           scenes reference them. Problems throw, so `dev.py exec` exits 1 and prints them; warnings (skipped extra
//           kinds) are logged as [WARN][dotwork]. `dev.py test` runs the verify check on every manifest too
//           (DotworkImportTests.EveryManifestInTheGameLoads). The importer itself is Assets/Editor/Dotwork/ (its own
//           assembly, so the EditMode tests can call it); this file stays in Assembly-CSharp-Editor beside
//           GameKitScenes, whose starter scene it adds to.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using graveyard_shift.Dotwork;

public static class GameKitDotwork
{
    // ---- Tunables ------------------------------------------------------------
    public const string SHOWCASE = "Dotwork";                 // the starter scene's root object for the showcase
    public const float SHOWCASE_MARGIN = 1.5f;                // units around the map in the camera's view
    public const string LABEL_TEXT = "DOTWORK";               // shown in the font (only the letters the font has)

    [MenuItem("Tools/Game Kit/Dotwork/Import All Packs")]
    public static void ImportAll()
    {
        AssetDatabase.Refresh();
        List<string> manifests = DotworkManifest.FindAll();
        if (manifests.Count == 0)
        {
            Debug.Log($"[INFO][dotwork] no manifests in {DotworkManifest.FOLDER}/ (*{DotworkManifest.SUFFIX}): nothing to import");
            return;
        }
        var failed = new List<string>();
        foreach (string path in manifests)
        {
            try
            {
                DotworkManifest m = DotworkManifest.Load(path);
                DotworkImporter.Import(path, DotworkVerify.OutDir(path, m.Pack));
            }
            catch (DotworkImportException e)
            {
                failed.Add(e.Message);
            }
        }
        if (failed.Count > 0)
        {
            LogErrors(failed);
            throw new DotworkImportException($"{failed.Count} of {manifests.Count} Dotwork pack(s) did not import, see the [ERROR][dotwork] lines");
        }
    }

    [MenuItem("Tools/Game Kit/Dotwork/Verify")]
    public static void Verify()
    {
        List<string> manifests = DotworkManifest.FindAll();
        List<string> problems = manifests.SelectMany(DotworkVerify.Problems).ToList();
        LogErrors(problems);
        if (problems.Count > 0)
        {
            throw new DotworkImportException($"{problems.Count} Dotwork problem(s) in {manifests.Count} manifest(s), see the [ERROR][dotwork] lines");
        }
        Debug.Log($"[INFO][dotwork] verify: {manifests.Count} manifest(s), every file and import loads");
    }

    // One [ERROR] line per problem line: dev.py exec prints the [ERROR] lines of a failed run
    private static void LogErrors(IEnumerable<string> problems)
    {
        foreach (string line in problems.SelectMany(p => p.Split('\n')).Where(l => l.Trim().Length > 0))
        {
            Debug.LogError("[ERROR][dotwork] " + line.Trim());
        }
    }

    [MenuItem("Tools/Game Kit/Dotwork/Show In Starter Scene")]
    public static void ShowInStarterScene()
    {
        if (!File.Exists(GameKitScenes.StarterScenePath))
        {
            GameKitScenes.CreateStarterScene();
        }
        Scene scene = EditorSceneManager.OpenScene(GameKitScenes.StarterScenePath, OpenSceneMode.Single);
        foreach (GameObject old in scene.GetRootGameObjects().Where(g => g.name == SHOWCASE))
        {
            Object.DestroyImmediate(old);
        }
        List<DotworkPack> packs = DotworkVerify.Packs();
        if (packs.Count == 0)
        {
            EditorSceneManager.SaveScene(scene);
            Debug.Log("[INFO][dotwork] no imported packs (run GameKitDotwork.ImportAll first): the starter scene has no showcase");
            return;
        }
        var root = new GameObject(SHOWCASE);
        float ppu = packs[0].pixelsPerUnit;
        var view = new Rect(0f, -4f, 8f, 4f);                  // the world rect to frame: the map's, else a small area

        DotworkMap map = packs.SelectMany(p => p.maps).FirstOrDefault(m => m.prefab != null);
        if (map != null)
        {
            var inst = (GameObject)PrefabUtility.InstantiatePrefab(map.prefab, scene);
            inst.transform.SetParent(root.transform, false);
            float w = map.size.x * map.tileSize.x / ppu, h = map.size.y * map.tileSize.y / ppu;
            view = new Rect(0f, -h, w, h);
        }
        Vector2 centre = view.center;

        // A character walking: the first animated sprite with a walk clip facing the camera (else its first clip)
        DotworkAnimated hero = packs.SelectMany(p => p.animated).Where(a => a.prefab != null)
                                    .OrderBy(a => a.Clip("walk", "s") != null ? 0 : 1).FirstOrDefault();
        if (hero != null)
        {
            var go = (GameObject)PrefabUtility.InstantiatePrefab(hero.prefab, scene);
            go.transform.SetParent(root.transform, false);
            go.transform.localPosition = new Vector3(centre.x, centre.y, 0f);
            go.AddComponent<DotworkPlayClip>().clip = hero.Clip("walk", "s") ?? hero.clips.FirstOrDefault()?.name ?? "";
            go.GetComponent<SpriteRenderer>().sortingOrder = 10;
        }
        // A prop beside it
        DotworkSprite prop = packs.SelectMany(p => p.sprites).FirstOrDefault(s => s.prefab != null);
        if (prop != null)
        {
            var go = (GameObject)PrefabUtility.InstantiatePrefab(prop.prefab, scene);
            go.transform.SetParent(root.transform, false);
            go.transform.localPosition = new Vector3(centre.x + 2f, centre.y, 0f);
            go.GetComponent<SpriteRenderer>().sortingOrder = 10;
        }
        // A label in the font that can write most of LABEL_TEXT, above the map
        DotworkFont font = packs.SelectMany(p => p.fonts).Where(f => f != null)
                                .OrderByDescending(f => LABEL_TEXT.Count(c => f.TryGlyph(c, out DotworkGlyph g) && g.sprite != null)).FirstOrDefault();
        if (font != null)
        {
            var go = new GameObject("Label");
            go.transform.SetParent(root.transform, false);
            go.transform.localPosition = new Vector3(view.xMin, view.yMax + font.lineHeight / font.pixelsPerUnit + 0.25f, 0f);
            var label = go.AddComponent<DotworkLabel>();
            label.font = font;
            label.Text = LabelText(font);
        }
        Camera cam = Object.FindAnyObjectByType<Camera>();
        if (cam != null)
        {
            cam.orthographic = true;
            cam.clearFlags = CameraClearFlags.SolidColor;     // a 2D backdrop, not the 3D template's sky
            cam.backgroundColor = new Color(0.10f, 0.11f, 0.16f);
            cam.transform.position = new Vector3(centre.x, centre.y + 0.5f, -10f);
            cam.transform.rotation = Quaternion.identity;
            float aspect = cam.aspect > 0f ? cam.aspect : 16f / 9f;
            cam.orthographicSize = Mathf.Max(view.height / 2f + 1f, view.width / 2f / aspect) + SHOWCASE_MARGIN;
        }
        if (!EditorSceneManager.SaveScene(scene))
        {
            throw new IOException($"could not save {GameKitScenes.StarterScenePath}");
        }
        Debug.Log($"[INFO][dotwork] showcase in {GameKitScenes.StarterScenePath}: map {map?.name ?? "-"}, character {hero?.name ?? "-"}, " +
                  $"prop {prop?.name ?? "-"}, font {(font != null ? font.fontName : "-")}");
    }

    /// <summary>LABEL_TEXT with only the letters the font has; else the font's first few printable glyphs.</summary>
    public static string LabelText(DotworkFont font)
    {
        string kept = new string(LABEL_TEXT.Where(c => font.TryGlyph(c, out DotworkGlyph g) && g.sprite != null).ToArray());
        if (kept.Length > 0)
        {
            return kept;
        }
        return new string(font.glyphs.Where(g => g.sprite != null && g.id < 0x10000).Take(8).Select(g => (char)g.id).ToArray());
    }
}
