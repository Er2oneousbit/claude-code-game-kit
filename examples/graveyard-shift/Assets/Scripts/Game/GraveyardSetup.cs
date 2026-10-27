// ---------------------------------------------------------------------------
// GraveyardSetup.cs
// Purpose : The one ScriptableObject the game reads: the tunables (GameTuning, editable in the
//           Inspector), every Kenney model by file name, and the sounds.
// Usage   : Assets/Config/SO_GraveyardSetup.asset, created and refreshed by SceneBuilder.Build
//           (python tools/dev.py exec SceneBuilder.Build); referenced by the Bootstrap object in the scene.
// Notes   : Models are looked up by their file name (the names in Core/Level.cs), so the level is data
//           and the art can change without touching code.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using graveyard_shift.Core;
using UnityEngine;

namespace graveyard_shift.Game
{
    [CreateAssetMenu(menuName = "Graveyard Shift/Setup", fileName = "SO_GraveyardSetup")]
    public class GraveyardSetup : ScriptableObject
    {
        [Serializable]
        public struct Model
        {
            public string name;
            public GameObject prefab;
        }

        public GameTuning tuning = new GameTuning();
        public List<Model> models = new List<Model>();

        [Header("Sounds")]
        public AudioClip soulCollected;
        public AudioClip gateOpens;
        public AudioClip ghostAlert;
        public AudioClip caught;
        public AudioClip lanternToggle;

        [Header("World sounds (GraveyardAudio; positional ones must be mono)")]
        public AudioClip soulWhisper;
        public AudioClip ghostPresence;
        public AudioClip[] footsteps = new AudioClip[0];
        public AudioClip lanternFlame;
        public AudioClip[] ghostNotice = new AudioClip[0];   // whispered lines, 3D from the ghost (Fish Audio)
        public AudioClip[] ghostCaught = new AudioClip[0];
        public AudioClip[] ghostSearch = new AudioClip[0];   // lost the keeper
        public AudioClip[] ghostGiveUp = new AudioClip[0];   // drifting home

        [Header("Voices (Fish Audio): the keeper and the narrator")]
        public AudioClip[] keeperSoul = new AudioClip[0];
        public AudioClip[] keeperGate = new AudioClip[0];
        public AudioClip[] keeperLowTime = new AudioClip[0];
        public AudioClip[] keeperCaught = new AudioClip[0];
        public AudioClip[] narratorIntro = new AudioClip[0];
        public AudioClip[] narratorEscape = new AudioClip[0];
        public AudioClip[] narratorDawn = new AudioClip[0];
        public AudioClip dawnChorus;

        [Header("End of the night (Suno; take turns like the night music)")]
        public AudioClip[] winTracks = new AudioClip[0];
        public AudioClip[] lossStings = new AudioClip[0];

        [Header("Loops (music tracks take turns, one per finished night)")]
        public AudioClip ambience;
        public AudioClip[] musicTracks = new AudioClip[0];
        [Range(0f, 1f)] public float ambienceVolume = 0.35f;
        [Range(0f, 1f)] public float musicVolume = 0.45f;

        public GameObject Find(string modelName)
        {
            foreach (var m in models)
            {
                if (m.name == modelName) return m.prefab;
            }
            return null;
        }
    }
}
