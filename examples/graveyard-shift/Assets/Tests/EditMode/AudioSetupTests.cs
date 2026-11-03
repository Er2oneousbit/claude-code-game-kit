// ---------------------------------------------------------------------------
// AudioSetupTests.cs
// Purpose : EditMode tests that SceneBuilder wired every sound into the setup asset: the five effects
//           and the night ambience must be there (a missing clip is silent, not an error, at runtime),
//           the ambience is long enough to loop, and the loop volumes stay below the effects. Every WAV's
//           header gives its real sizes, and the narrator lines are normalized to one peak.
// Usage   : python tools/dev.py test
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-03 (Claude Opus 5.5): WAV header sizes and the narrator peak (issue #139: two narrator takes
//           and the ghost voices shipped as streamed, with placeholder RIFF and data sizes of about 4 GB).
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;

namespace graveyard_shift.Tests
{
    public class AudioSetupTests
    {
        private const string AudioFolder = "Assets/Audio";
        private const float NarratorPeakDb = -3f;     // dBFS: what wavfile.py normalize gave every narrator line
        private const float PeakToleranceDb = 0.1f;

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
            UnityEngine.Object.DestroyImmediate(a);
            UnityEngine.Object.DestroyImmediate(b);
        }

        [Test]
        public void AmbienceIsALoopNotAOneShot()
        {
            var s = Setup();
            Assert.Greater(s.ambience.length, 10f, "a short ambience loop repeats too audibly");
            Assert.Less(s.ambienceVolume, 1f);
            Assert.Less(s.musicVolume, 1f);
        }

        // A service that streams a WAV writes placeholder sizes (0xFFFFFF24 / 0xFFFFFF00) and never comes back to
        // fix them; a reader that trusts the header sees hours of audio. RIFF must be the file length minus 8 and
        // the data chunk must end inside the file.
        [Test]
        public void EveryWavHeaderGivesItsRealSizes()
        {
            var bad = new List<string>();
            foreach (string path in Directory.GetFiles(AudioFolder, "*.wav", SearchOption.AllDirectories))
            {
                byte[] b = File.ReadAllBytes(path);
                uint riff = BitConverter.ToUInt32(b, 4);
                long dataEnd = DataChunk(b, out int dataStart, out uint dataSize) ? dataStart + (long)dataSize : -1;
                if (riff != b.Length - 8 || dataEnd < 0 || dataEnd > b.Length)
                {
                    var clip = AssetDatabase.LoadAssetAtPath<AudioClip>(path.Replace('\\', '/'));
                    bad.Add($"{Path.GetFileName(path)} (RIFF 0x{riff:X8}, data ends at {dataEnd}, file {b.Length} bytes; " +
                            $"Unity's clip {(clip != null ? clip.length.ToString("0.000") + " s" : "not loaded")})");
                }
            }
            Assert.IsEmpty(bad, "WAV headers with sizes that are not the file's: " + string.Join("; ", bad));
        }

        // The narrator was mixed with every line at one peak; a line left at its generated level plays louder
        [Test]
        public void NarratorLinesShareOnePeak()
        {
            var off = new List<string>();
            foreach (string path in Directory.GetFiles(AudioFolder, "narrator_*.wav"))
            {
                byte[] b = File.ReadAllBytes(path);
                Assert.IsTrue(DataChunk(b, out int start, out uint size), $"{path}: no data chunk");
                long end = Math.Min(b.Length, start + (long)size);
                int peak = 1;
                for (long i = start; i + 1 < end; i += 2) peak = Math.Max(peak, Math.Abs((int)BitConverter.ToInt16(b, (int)i)));
                float db = 20f * Mathf.Log10(peak / 32768f);
                if (Mathf.Abs(db - NarratorPeakDb) > PeakToleranceDb) off.Add($"{Path.GetFileName(path)} {db:0.0} dBFS");
            }
            Assert.IsEmpty(off, $"narrator lines not at {NarratorPeakDb} dBFS peak: " + string.Join("; ", off));
        }

        // The data chunk's start and size, walking the chunks after "WAVE" (16-bit PCM, as every voice here is)
        private static bool DataChunk(byte[] b, out int start, out uint size)
        {
            start = 0;
            size = 0;
            if (b.Length < 12 || Encoding.ASCII.GetString(b, 0, 4) != "RIFF" || Encoding.ASCII.GetString(b, 8, 4) != "WAVE") return false;
            long i = 12;
            while (i + 8 <= b.Length)
            {
                uint chunk = BitConverter.ToUInt32(b, (int)i + 4);
                if (Encoding.ASCII.GetString(b, (int)i, 4) == "data")
                {
                    start = (int)i + 8;
                    size = chunk;
                    return true;
                }
                i += 8 + (long)chunk + (chunk & 1);
            }
            return false;
        }
    }
}
