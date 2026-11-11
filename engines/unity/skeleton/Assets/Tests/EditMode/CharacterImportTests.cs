// ---------------------------------------------------------------------------
// CharacterImportTests.cs
// Purpose : The golden rigged character (#290, data/golden/character/character.glb) in Unity through glTFast, both
//           routes: the editor import (copied into a temporary folder under Assets/, the way a game drops a model
//           into Assets/Models/) played with KitCharacter.Attach, and the run-time load (KitCharacter.Load). Checks
//           the bones and clips, metres and facing, that walk swings the moving bone, loops and has no root motion.
// Usage   : python tools/dev.py test --filter Character
// Notes   : Every number comes from data/golden/character/expected.json. The swing is peak to peak: the largest
//           angle between any two of SAMPLES poses of the bone over one walk; it must reach SWING_MIN of the
//           expected swing and stay under SWING_MAX of it. Without glTFast every test is ignored with the command
//           that adds it. The temporary folder is deleted afterwards (and before, if a killed run left it).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;
using UnityEngine.TestTools;
using {{GAME_SLUG}}.Characters;
using {{GAME_SLUG}}.Core;
using Object = UnityEngine.Object;

namespace {{GAME_SLUG}}.Tests
{
    public class CharacterImportTests
    {
        // ---- Tunables ------------------------------------------------------------
        private const string GOLDEN = "data/golden/character";       // relative to the project root
        private const string TEMP = "Assets/__CharacterGolden";     // gitignored; deleted after the run
        private const int SAMPLES = 48;                              // poses per walk for the swing
        private const double SWING_MIN = 0.5, SWING_MAX = 1.25;      // of expected.json's moving_bone_swing_deg
        private const float HEIGHT_TOL_M = 0.02f;
        private const float IN_PLACE_M = 0.05f;                      // the hips' largest sideways travel in a walk
        private const float POSE_TOL_DEG = 0.5f;
        private const double LOAD_TIMEOUT_S = 30;                    // a run-time load of a 62 KB file takes well under 1 s

        private static Dictionary<string, object> _expected;
        private string _model;                                       // the .glb's path under TEMP

        [OneTimeSetUp]
        public void ImportTheFixture()
        {
            if (!KitCharacter.CanLoadGltf)
            {
                Assert.Ignore(KitCharacter.NO_GLTFAST);
            }
            _expected = Json.AsObject(Json.Parse(File.ReadAllText(Path.Combine(GOLDEN, "expected.json"), Encoding.UTF8)));
            DeleteTemp();
            Directory.CreateDirectory(TEMP);
            _model = TEMP + "/" + Str("file");
            File.Copy(Path.Combine(GOLDEN, Str("file")), _model);
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
        }

        [OneTimeTearDown]
        public void DeleteTheFixture()
        {
            DeleteTemp();
        }

        // ---- The editor import (a .glb under Assets/) ------------------------------------------

        [Test]
        public void Character_ImportHasTheBonesAndClips()
        {
            GameObject go = Instance();
            try
            {
                foreach (string bone in Strs("bones"))
                {
                    Assert.IsNotNull(Find(go, bone), $"bone {bone} (Unity keeps glTF's names, ':' included)");
                }
                var skin = go.GetComponentInChildren<SkinnedMeshRenderer>();
                Assert.IsNotNull(skin, "one skinned mesh");
                Assert.AreEqual(Str("root_bone"), skin.rootBone.name);
                Assert.AreEqual(Strs("bones").Count, skin.bones.Length, "every joint skins the mesh");
                Assert.AreEqual((int)Num("triangles"), skin.sharedMesh.triangles.Length / 3, "triangles");
                Assert.IsNotNull(go.GetComponent<Animator>(), "glTFast adds an Animator (no controller, no avatar)");

                Dictionary<string, AnimationClip> clips = Clips();
                foreach (KeyValuePair<string, object> kv in Json.AsObject(_expected["clips"]))
                {
                    Assert.IsTrue(clips.ContainsKey(kv.Key), $"clip {kv.Key} (have: {string.Join(", ", clips.Keys)})");
                    AnimationClip clip = clips[kv.Key];
                    Dictionary<string, object> want = Json.AsObject(kv.Value);
                    Assert.AreEqual(Json.ToNumber(want["seconds"]), clip.length, 1.0 / Num("fps"), $"{kv.Key} length");
                    Assert.AreEqual((bool)want["loop"], clip.isLooping, $"{kv.Key} loopTime");
                    Assert.IsFalse(clip.legacy, $"{kv.Key}: the editor import makes Mecanim clips");
                    Assert.IsFalse(clip.humanMotion, $"{kv.Key}: glTF clips are Generic (transform curves)");
                }
            }
            finally
            {
                Object.DestroyImmediate(go);
            }
        }

        [Test]
        public void Character_IsInMetresStandingOnTheOriginFacingPlusZ()
        {
            GameObject go = Instance();
            try
            {
                Bounds b = go.GetComponentInChildren<SkinnedMeshRenderer>().bounds;
                Assert.AreEqual(Num("height_m"), b.size.y, HEIGHT_TOL_M, "height: 1 Unity unit = 1 metre, no import scale");
                Assert.AreEqual(0f, b.min.y, HEIGHT_TOL_M, "feet on the ground at the origin");
                AssertFacing(go);
            }
            finally
            {
                Object.DestroyImmediate(go);
            }
        }

        [Test]
        public void Character_WalkSwingsTheMovingBone()
        {
            GameObject go = Instance();
            try
            {
                KitCharacter c = KitCharacter.Attach(go, Clips().Values);
                AssertWalks(c, "imported, Attach");
                Assert.IsFalse(go.GetComponent<Animator>().applyRootMotion, "Attach turns root motion off");
            }
            finally
            {
                Object.DestroyImmediate(go);
            }
        }

        [Test]
        public void Character_IdleIsQuieterThanWalk()
        {
            GameObject go = Instance();
            try
            {
                KitCharacter c = KitCharacter.Attach(go, Clips().Values);
                c.Play("idle");
                float idle = Swing(c, Str("moving_bone"), (float)Json.ToNumber(Json.AsObject(Json.AsObject(_expected["clips"])["idle"])["seconds"]));
                c.Play("walk");
                float walk = Swing(c, Str("moving_bone"), WalkSeconds());
                Assert.Less(idle, walk, "the clips are told apart by name (idle is not walk)");
            }
            finally
            {
                Object.DestroyImmediate(go);
            }
        }

        // ---- The run-time load (KitCharacter.Load) -----------------------------------------------

        [UnityTest]
        public IEnumerator Character_RuntimeLoadPlaysWalk()
        {
            Task<KitCharacter> load = KitCharacter.Load(Path.Combine(GOLDEN, Str("file")));
            var clock = System.Diagnostics.Stopwatch.StartNew();
            int ticks = 0;
            while (!load.IsCompleted && clock.Elapsed.TotalSeconds < LOAD_TIMEOUT_S)
            {
                ticks++;
                yield return null;
            }
            Debug.Log($"[INFO][characters] run-time load: {(load.IsCompleted ? "done" : "NOT done")} after {ticks} editor ticks, {clock.Elapsed.TotalSeconds:F1} s");
            Assert.IsTrue(load.IsCompleted, $"the load did not finish in {LOAD_TIMEOUT_S} s ({ticks} editor ticks)");
            if (load.IsFaulted)
            {
                throw load.Exception.GetBaseException();
            }
            KitCharacter c = load.Result;
            try
            {
                CollectionAssert.IsSupersetOf(c.ClipNames.ToList(), Json.AsObject(_expected["clips"]).Keys.ToList(), "clips by name");
                Animation legacy = c.GetComponentInChildren<Animation>();
                Assert.IsNotNull(legacy, "a run-time load plays legacy clips on an Animation component");
                AssertFacing(c.gameObject);
                AssertWalks(c, "run-time, Load");
            }
            finally
            {
                Object.DestroyImmediate(c.gameObject);
            }
        }

        [Test]
        public void Character_UnknownClipNamesTheClips()
        {
            GameObject go = Instance();
            try
            {
                KitCharacter c = KitCharacter.Attach(go, Clips().Values);
                var e = Assert.Throws<System.ArgumentException>(() => c.Play("run"));
                StringAssert.Contains("walk", e.Message);
            }
            finally
            {
                Object.DestroyImmediate(go);
            }
        }

        // ---- Shared checks ------------------------------------------------------------------

        /// <summary>walk: the moving bone swings, the clip loops without a seam and the character stays in place.</summary>
        private static void AssertWalks(KitCharacter c, string route)
        {
            float seconds = WalkSeconds();
            double want = Num("moving_bone_swing_deg");
            c.Play("walk");
            float swing = Swing(c, Str("moving_bone"), seconds);
            Assert.GreaterOrEqual(swing, want * SWING_MIN, $"{route}: {Str("moving_bone")} swings {swing:F1} deg, expected about {want}");
            Assert.LessOrEqual(swing, want * SWING_MAX, $"{route}: {Str("moving_bone")} swings {swing:F1} deg, expected about {want}");

            Transform bone = c.Bone(Str("moving_bone"));
            c.Seek(seconds * 0.25f);
            Quaternion quarter = bone.localRotation;
            c.Seek(seconds * 1.25f);
            Assert.Less(Quaternion.Angle(quarter, bone.localRotation), POSE_TOL_DEG, $"{route}: walk loops (1.25 lengths = 0.25)");
            c.Seek(0f);
            Quaternion first = bone.localRotation;
            c.Seek(seconds * 0.999f);
            Assert.Less(Quaternion.Angle(first, bone.localRotation), 2f, $"{route}: walk ends where it starts (no seam)");

            Transform hips = c.Bone(Str("root_bone"));
            Vector3 root = c.transform.position;
            float minX = float.MaxValue, maxX = float.MinValue, minZ = float.MaxValue, maxZ = float.MinValue;
            for (int i = 0; i <= SAMPLES; i++)
            {
                c.Seek(seconds * i / SAMPLES);
                Vector3 p = hips.position;
                minX = Mathf.Min(minX, p.x);
                maxX = Mathf.Max(maxX, p.x);
                minZ = Mathf.Min(minZ, p.z);
                maxZ = Mathf.Max(maxZ, p.z);
            }
            Assert.Less(Mathf.Max(maxX - minX, maxZ - minZ), IN_PLACE_M, $"{route}: walk is in place (the hips do not travel)");
            Assert.AreEqual(root, c.transform.position, $"{route}: no root motion moves the character");
        }

        /// <summary>glTF front +Z stays Unity's +Z (transform.forward); glTF's +X left becomes -X (the handedness flip).</summary>
        private static void AssertFacing(GameObject go)
        {
            Assert.AreEqual("+Z", Str("front"), "this check assumes the fixture faces +Z");
            Transform foot = Find(go, "mixamorig:LeftFoot"), toe = Find(go, "mixamorig:LeftToeBase");
            Assert.Greater(toe.position.z, foot.position.z, "the toes point to +Z: the character faces +Z");
            Assert.Less(Find(go, "mixamorig:LeftUpLeg").position.x, 0f, "the left leg is on -X: not mirrored");
        }

        /// <summary>Peak to peak: the largest angle between any two of SAMPLES poses of a bone over one clip.</summary>
        private static float Swing(KitCharacter c, string boneName, float seconds)
        {
            Transform bone = c.Bone(boneName);
            Assert.IsNotNull(bone, boneName);
            var poses = new List<Quaternion>();
            for (int i = 0; i < SAMPLES; i++)
            {
                c.Seek(seconds * i / SAMPLES);
                poses.Add(bone.localRotation);
            }
            float best = 0f;
            for (int i = 0; i < poses.Count; i++)
            {
                for (int j = i + 1; j < poses.Count; j++)
                {
                    best = Mathf.Max(best, Quaternion.Angle(poses[i], poses[j]));
                }
            }
            return best;
        }

        // ---- Helpers ---------------------------------------------------------------------

        private GameObject Instance()
        {
            var main = AssetDatabase.LoadMainAssetAtPath(_model) as GameObject;
            Assert.IsNotNull(main, $"{_model} did not import as a model (is glTFast's importer active for .glb?)");
            return (GameObject)Object.Instantiate(main);
        }

        private Dictionary<string, AnimationClip> Clips() =>
            AssetDatabase.LoadAllAssetsAtPath(_model).OfType<AnimationClip>().ToDictionary(c => c.name);

        private static Transform Find(GameObject go, string name) =>
            go.GetComponentsInChildren<Transform>(true).FirstOrDefault(t => t.name == name);

        private static float WalkSeconds() => (float)Json.ToNumber(Json.AsObject(Json.AsObject(_expected["clips"])["walk"])["seconds"]);

        private static string Str(string key) => (string)_expected[key];

        private static double Num(string key) => Json.ToNumber(_expected[key]);

        private static List<string> Strs(string key) => Json.AsList(_expected[key]).Cast<string>().ToList();

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
