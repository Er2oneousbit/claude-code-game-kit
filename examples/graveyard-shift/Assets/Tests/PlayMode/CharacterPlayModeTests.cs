// ---------------------------------------------------------------------------
// CharacterPlayModeTests.cs
// Purpose : The golden rigged character (#290) walking in real frames: KitCharacter.Load the fixture in Play mode
//           (glTFast's frame-budget loader), Play("walk") and let the frames run past one clip length: the moving
//           bone swings by a meaningful part of expected.json's swing and the clip is still playing (it loops).
// Usage   : python tools/dev.py test --mode PlayMode --filter Character
// Notes   : The EditMode CharacterImportTests sample the clips at exact times (both import routes); this one checks
//           that time really drives them. Ignored without glTFast, with the command that adds it.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using graveyard_shift.Characters;
using graveyard_shift.Core;

namespace graveyard_shift.Tests
{
    public class CharacterPlayModeTests
    {
        // ---- Tunables ------------------------------------------------------------
        private const string GOLDEN = "data/golden/character";       // relative to the project root
        private const double SWING_MIN = 0.5;                        // of expected.json's moving_bone_swing_deg
        private const float LOAD_TIMEOUT_S = 30f;
        private const float PLAY_LENGTHS = 1.5f;                     // play this many walk lengths
        private const int SAMPLES_PER_CLIP = 48;                     // poses kept per walk length (frames can be many)

        [UnityTest]
        public IEnumerator Character_WalkPlaysInRealFrames()
        {
            if (!KitCharacter.CanLoadGltf)
            {
                Assert.Ignore(KitCharacter.NO_GLTFAST);
            }
            var expected = Json.AsObject(Json.Parse(File.ReadAllText(Path.Combine(GOLDEN, "expected.json"), Encoding.UTF8)));
            string boneName = (string)expected["moving_bone"];
            double want = Json.ToNumber(expected["moving_bone_swing_deg"]);
            float seconds = (float)Json.ToNumber(Json.AsObject(Json.AsObject(expected["clips"])["walk"])["seconds"]);

            Task<KitCharacter> load = KitCharacter.Load(Path.Combine(GOLDEN, (string)expected["file"]));
            float waited = 0f;
            while (!load.IsCompleted && waited < LOAD_TIMEOUT_S)
            {
                waited += Time.unscaledDeltaTime;
                yield return null;
            }
            Assert.IsTrue(load.IsCompleted, $"the load did not finish in {LOAD_TIMEOUT_S} s");
            if (load.IsFaulted)
            {
                throw load.Exception.GetBaseException();
            }
            KitCharacter c = load.Result;
            try
            {
                Transform bone = c.Bone(boneName);
                Assert.IsNotNull(bone, boneName);
                c.Play("walk");
                var poses = new List<Quaternion>();
                float played = 0f, next = 0f;
                int frames = 0;
                while (played < seconds * PLAY_LENGTHS)
                {
                    yield return null;
                    played += Time.deltaTime;
                    frames++;
                    if (played >= next)                               // at most SAMPLES_PER_CLIP poses per length
                    {
                        poses.Add(bone.localRotation);
                        next = played + seconds / SAMPLES_PER_CLIP;
                    }
                }
                float swing = 0f;
                for (int i = 0; i < poses.Count; i++)
                {
                    for (int j = i + 1; j < poses.Count; j++)
                    {
                        swing = Mathf.Max(swing, Quaternion.Angle(poses[i], poses[j]));
                    }
                }
                Debug.Log($"[INFO][characters] walk: {frames} frames over {played:F2} s, {boneName} swung {swing:F1} deg (expected {want})");
                Assert.GreaterOrEqual(swing, want * SWING_MIN, $"{boneName} swung {swing:F1} deg in {frames} frames");
                Animation legacy = c.GetComponentInChildren<Animation>();
                Assert.IsTrue(legacy.IsPlaying("walk"), "walk still plays past its length (it loops)");
                Assert.AreEqual("walk", c.Playing);
            }
            finally
            {
                Object.Destroy(c.gameObject);
            }
        }
    }
}
