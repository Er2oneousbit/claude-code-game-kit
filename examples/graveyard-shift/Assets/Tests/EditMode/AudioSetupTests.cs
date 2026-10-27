// ---------------------------------------------------------------------------
// AudioSetupTests.cs
// Purpose : EditMode tests that SceneBuilder wired every sound into the setup asset: the five effects
//           and the night ambience must be there (a missing clip is silent, not an error, at runtime),
//           the ambience is long enough to loop, and the loop volumes stay below the effects.
// Usage   : python tools/dev.py test
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using NUnit.Framework;
using UnityEditor;
using UnityEngine;

namespace graveyard_shift.Tests
{
    public class AudioSetupTests
    {
        private static graveyard_shift.Game.GraveyardSetup Setup()
        {
            var setup = AssetDatabase.LoadAssetAtPath<graveyard_shift.Game.GraveyardSetup>(TestTuning.SetupPath);
            Assert.IsNotNull(setup, $"{TestTuning.SetupPath} missing: run python tools/dev.py exec SceneBuilder.Build");
            return setup;
        }

        [Test]
        public void EveryEffectAndTheAmbienceAreAssigned()
        {
            var s = Setup();
            Assert.IsNotNull(s.soulCollected, "soulCollected");
            Assert.IsNotNull(s.gateOpens, "gateOpens");
            Assert.IsNotNull(s.ghostAlert, "ghostAlert");
            Assert.IsNotNull(s.caught, "caught");
            Assert.IsNotNull(s.lanternToggle, "lanternToggle");
            Assert.IsNotNull(s.ambience, "ambience");
        }

        [Test]
        public void WorldSoundsAreAssignedAndPositionalOnesAreMono()
        {
            var s = Setup();
            Assert.IsNotNull(s.soulWhisper, "soulWhisper");
            Assert.IsNotNull(s.ghostPresence, "ghostPresence");
            Assert.IsNotNull(s.lanternFlame, "lanternFlame");
            Assert.AreEqual(3, s.footsteps.Length, "three footstep takes");
            Assert.AreEqual(1, s.soulWhisper.channels, "a 3D sound must be mono to be placed in the world");
            Assert.AreEqual(1, s.ghostPresence.channels, "a 3D sound must be mono to be placed in the world");
            Assert.AreEqual(3, s.ghostNotice.Length, "three notice whispers");
            Assert.AreEqual(2, s.ghostCaught.Length, "two caught lines");
            foreach (var c in s.ghostNotice) Assert.AreEqual(1, c.channels, $"{c.name} plays from the ghost: mono");
            Assert.IsNotNull(s.dawnChorus, "dawnChorus");
        }

        [Test]
        public void EveryVoiceSetIsLoaded()
        {
            var s = Setup();
            Assert.AreEqual(2, s.ghostSearch.Length, "ghostSearch");
            Assert.AreEqual(2, s.ghostGiveUp.Length, "ghostGiveUp");
            Assert.AreEqual(3, s.keeperSoul.Length, "keeperSoul");
            Assert.AreEqual(2, s.keeperGate.Length, "keeperGate");
            Assert.AreEqual(2, s.keeperLowTime.Length, "keeperLowTime");
            Assert.AreEqual(2, s.keeperCaught.Length, "keeperCaught");
            Assert.AreEqual(2, s.narratorIntro.Length, "narratorIntro");
            Assert.AreEqual(2, s.narratorEscape.Length, "narratorEscape");
            Assert.AreEqual(2, s.narratorDawn.Length, "narratorDawn");
            foreach (var c in s.ghostSearch) Assert.AreEqual(1, c.channels, $"{c.name} plays from the ghost: mono");
        }

        [Test]
        public void GhostsGetLouderAsTheyCloseIn()
        {
            float patrol = graveyard_shift.Game.GraveyardAudio.GhostVolume(graveyard_shift.Core.GhostState.Patrol);
            float wary = graveyard_shift.Game.GraveyardAudio.GhostVolume(graveyard_shift.Core.GhostState.Suspicious);
            float hunt = graveyard_shift.Game.GraveyardAudio.GhostVolume(graveyard_shift.Core.GhostState.Hunt);
            Assert.Less(patrol, wary);
            Assert.Less(wary, hunt);
            Assert.AreEqual(wary, graveyard_shift.Game.GraveyardAudio.GhostVolume(graveyard_shift.Core.GhostState.Search));
        }

        [Test]
        public void BothMusicTracksAreAssignedAndStream()
        {
            var s = Setup();
            Assert.AreEqual(2, s.musicTracks.Length, "night_music_a and _b (the two Suno takes)");
            foreach (var t in s.musicTracks)
            {
                Assert.IsNotNull(t);
                Assert.Greater(t.length, 60f, "a loop over a minute long");
                var importer = (AudioImporter)AssetImporter.GetAtPath(AssetDatabase.GetAssetPath(t));
                Assert.AreEqual(AudioClipLoadType.Streaming, importer.defaultSampleSettings.loadType,
                    $"{t.name} must stream, not sit decompressed in memory");
            }
        }

        [Test]
        public void MusicTakesTurnsPerFinishedNight()
        {
            var a = UnityEngine.AudioClip.Create("a", 10, 1, 8000, false);
            var b = UnityEngine.AudioClip.Create("b", 10, 1, 8000, false);
            var tracks = new[] { a, b };
            Assert.AreSame(a, graveyard_shift.Game.GraveyardGame.PickMusic(tracks, 0));
            Assert.AreSame(b, graveyard_shift.Game.GraveyardGame.PickMusic(tracks, 1));
            Assert.AreSame(a, graveyard_shift.Game.GraveyardGame.PickMusic(tracks, 2));
            Assert.IsNull(graveyard_shift.Game.GraveyardGame.PickMusic(new UnityEngine.AudioClip[0], 3), "no tracks: no music");
            Object.DestroyImmediate(a);
            Object.DestroyImmediate(b);
        }

        [Test]
        public void AmbienceIsALoopNotAOneShot()
        {
            var s = Setup();
            Assert.Greater(s.ambience.length, 10f, "a short ambience loop repeats too audibly");
            Assert.Less(s.ambienceVolume, 1f);
            Assert.Less(s.musicVolume, 1f);
        }
    }
}
