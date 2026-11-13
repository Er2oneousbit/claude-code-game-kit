// ---------------------------------------------------------------------------
// KitCharacterPlayTests.cs
// Purpose : The kit's play rule (#296), the same in all five engines' character helpers: Play of the clip already
//           playing, with the same loop setting, changes nothing (a game may call it every frame); restart: true or
//           another loop setting starts it from 0; a held one-shot keeps holding.
// Usage   : python tools/dev.py test --filter KitCharacterPlay
// Notes   : Needs no glTFast (unlike CharacterImportTests): a GameObject with one child bone and two Mecanim clips
//           made here, played through KitCharacter.Attach. In edit mode only Seek moves the clock, so ClipTime is
//           exact.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using NUnit.Framework;
using UnityEngine;
using {{GAME_SLUG}}.Characters;
using Object = UnityEngine.Object;

namespace {{GAME_SLUG}}.Tests
{
    public class KitCharacterPlayTests
    {
        // ---- Tunables ------------------------------------------------------------
        private const float CLIP_S = 1f;             // both clips last a second
        private const float TOL_S = 1e-4f;

        private GameObject _go;
        private KitCharacter _c;

        [SetUp]
        public void MakeACharacter()
        {
            _go = new GameObject("PlayRuleCharacter");
            new GameObject("Bone").transform.SetParent(_go.transform, false);
            _c = KitCharacter.Attach(_go, new[] { Clip("walk", 1f), Clip("idle", 0.1f) });
        }

        [TearDown]
        public void Destroy()
        {
            Object.DestroyImmediate(_go);
        }

        [Test]
        public void Play_TheSameClipKeepsItsTime()
        {
            _c.Play("walk");
            _c.Seek(0.3f);
            for (int i = 0; i < 3; i++)
            {
                _c.Play("walk");                     // a game asking every frame
            }
            Assert.AreEqual(0.3f, _c.ClipTime, TOL_S, "asking for the clip that plays kept its time");
            Assert.AreEqual("walk", _c.Playing);
        }

        [Test]
        public void Play_RestartIsExplicit()
        {
            _c.Play("walk");
            _c.Seek(0.3f);
            _c.Play("walk", restart: true);
            Assert.AreEqual(0f, _c.ClipTime, TOL_S, "restart: true starts the clip from 0");
            _c.Seek(0.2f);
            _c.Play("walk", loop: false);
            Assert.AreEqual(0f, _c.ClipTime, TOL_S, "another loop setting starts it again");
            _c.Seek(CLIP_S + 0.5f);
            _c.Play("walk", loop: false);
            Assert.AreEqual(CLIP_S + 0.5f, _c.ClipTime, TOL_S, "a held one-shot keeps holding");
            _c.Play("idle");
            Assert.AreEqual(0f, _c.ClipTime, TOL_S, "another clip starts from 0");
            Assert.AreEqual("idle", _c.Playing);
        }

        /// <summary>A one-second Mecanim clip moving the child "Bone" along x up to <paramref name="reach"/>.</summary>
        private static AnimationClip Clip(string name, float reach)
        {
            var clip = new AnimationClip { name = name, legacy = false };
            clip.SetCurve("Bone", typeof(Transform), "localPosition.x", AnimationCurve.Linear(0f, 0f, CLIP_S, reach));
            return clip;
        }
    }
}

// {{FOOTER}}
