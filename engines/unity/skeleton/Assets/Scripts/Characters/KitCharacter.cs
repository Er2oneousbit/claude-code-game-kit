// ---------------------------------------------------------------------------
// KitCharacter.cs
// Purpose : Play a rigged glTF character's clips by name (#290): a .glb/.gltf loaded at run time through glTFast,
//           or a model glTFast already imported into Assets/ (the usual route). Loops by default, never applies
//           root motion, and needs no AnimatorController.
// Usage   : // a file at run time (mods, downloaded or generated characters):
//           KitCharacter hero = await KitCharacter.Load("data/golden/character/character.glb", parent);
//           hero.Play("walk");                       // loops; Play("idle", loop: false) holds the last frame
//           // a model imported into Assets/Models/ (instantiate it, hand over its clips):
//           var go = Instantiate(prefab);            // the .glb's main asset
//           KitCharacter.Attach(go, clips).Play("idle");
//           hero.ClipNames, hero.Playing, hero.Seek(0.5f) (jump to a time and pose now), hero.Bone("mixamorig:Hips")
// Notes   : Load needs the glTFast package (com.unity.cloud.gltfast, `python tools/dev.py exec
//           GameKitCharacters.AddGltfast`); without it CanLoadGltf is false and Load throws with that command.
//           Load asks glTFast for legacy clips (an Animation component): glTFast cannot make Mecanim clips in a
//           player build. Attach plays Mecanim clips (glTFast's editor import makes them, loopTime on) through a
//           PlayableGraph on the model's Animator, which works for a Humanoid avatar with humanoid clips too;
//           the graph is evaluated here in Update (manual mode) so loop, hold and Seek are exact.
//           glTF is +Y up, front +Z, metres; glTFast flips X for Unity's left-handed space, so the character
//           faces +Z (transform.forward) and its left side is -X. Docs: docs/ENGINE.md "Rigged characters".
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Animations;
using UnityEngine.Playables;
#if GAMEKIT_GLTFAST
using GLTFast;
#endif
using Object = UnityEngine.Object;

namespace {{GAME_SLUG}}.Characters
{
    [ExecuteAlways]                                   // so OnDestroy frees the graph and glTFast's objects in edit mode too
    public sealed class KitCharacter : MonoBehaviour
    {
        // ---- Tunables ------------------------------------------------------------
        public const string NO_GLTFAST = "glTFast (com.unity.cloud.gltfast) is not installed, so a .glb cannot be loaded: " +
                                         "python tools/dev.py exec GameKitCharacters.AddGltfast";
        private const double HOLD_S = 1e-4;          // a clip that does not loop holds this far before its end
                                                      // (at the end itself a loopTime clip shows frame 0 again)

#if GAMEKIT_GLTFAST
        public static bool CanLoadGltf => true;
        private GltfImport _gltf;                     // owns the meshes, materials and clips of a Load
#else
        public static bool CanLoadGltf => false;
#endif

        private readonly Dictionary<string, AnimationClip> _clips = new Dictionary<string, AnimationClip>();
        private readonly List<string> _names = new List<string>();
        private Animation _legacy;                    // Load: glTFast's legacy clips
        private Animator _animator;                   // Attach: Mecanim clips through a playable graph
        private PlayableGraph _graph;
        private AnimationPlayableOutput _output;
        private AnimationClipPlayable _playable;
        private double _time;                         // Attach: seconds since Play, before loop or hold
        private bool _loop = true;

        /// <summary>The clips by name, in the file's order.</summary>
        public IReadOnlyList<string> ClipNames => _names;

        /// <summary>The clip Play started last (null before the first Play).</summary>
        public string Playing { get; private set; }

        // ---- Making one ---------------------------------------------------------------

        /// <summary>Load a .glb or .gltf file (a path relative to the working directory, or absolute) under
        /// <paramref name="parent"/>. The new GameObject (named after the file) carries the KitCharacter.</summary>
        public static async Task<KitCharacter> Load(string path, Transform parent = null)
        {
#if GAMEKIT_GLTFAST
            string full = Path.GetFullPath(path);
            if (!File.Exists(full))
            {
                throw new FileNotFoundException($"no character file at {full}", full);
            }
            var go = new GameObject(Path.GetFileNameWithoutExtension(full));
            go.transform.SetParent(parent, false);
            var character = go.AddComponent<KitCharacter>();
            // In edit mode (tests, editor tools) nothing ticks glTFast's frame-budget agent: load in one go there
            character._gltf = new GltfImport(deferAgent: Application.isPlaying ? null : new UninterruptedDeferAgent());
            bool ok = await character._gltf.LoadFile(full, new Uri(full), new ImportSettings { AnimationMethod = AnimationMethod.Legacy });
            ok = ok && await character._gltf.InstantiateMainSceneAsync(go.transform);
            if (!ok)
            {
                Kill(go);
                throw new InvalidDataException($"glTFast could not load {full} (its errors are in the log above)");
            }
            character._legacy = go.GetComponentInChildren<Animation>();
            if (character._legacy != null)
            {
                foreach (AnimationClip clip in character._gltf.GetAnimationClips() ?? new AnimationClip[0])
                {
                    character.Add(clip);
                }
            }
            return character;
#else
            await Task.CompletedTask;
            throw new InvalidOperationException(NO_GLTFAST + $" (asked for {path})");
#endif
        }

        /// <summary>Play <paramref name="clips"/> on a model that is already in the scene (an instance of an
        /// imported .glb, or of an FBX). Adds an Animator if there is none and turns its root motion off.</summary>
        public static KitCharacter Attach(GameObject instance, IEnumerable<AnimationClip> clips)
        {
            var character = instance.GetComponent<KitCharacter>();
            if (character == null)
            {
                character = instance.AddComponent<KitCharacter>();
            }
            character._animator = instance.GetComponent<Animator>();
            if (character._animator == null)
            {
                character._animator = instance.AddComponent<Animator>();
            }
            character._animator.applyRootMotion = false;
            foreach (AnimationClip clip in clips)
            {
                if (clip.legacy)
                {
                    throw new ArgumentException($"{clip.name} is a legacy clip: it plays on an Animation component (KitCharacter.Load), not an Animator");
                }
                character.Add(clip);
            }
            return character;
        }

        // ---- Playing ------------------------------------------------------------------

        /// <summary>Play a clip from its start; <paramref name="loop"/> false holds its last frame.</summary>
        public void Play(string clip, bool loop = true)
        {
            if (!_clips.TryGetValue(clip, out AnimationClip c))
            {
                throw new ArgumentException($"{name}: no clip '{clip}' (clips: {string.Join(", ", _names)})", nameof(clip));
            }
            Playing = clip;
            _loop = loop;
            if (_legacy != null)
            {
                _legacy[clip].wrapMode = loop ? WrapMode.Loop : WrapMode.ClampForever;
                _legacy.Play(clip);
                _legacy[clip].time = 0f;
                return;
            }
            if (!_graph.IsValid())
            {
                _graph = PlayableGraph.Create(name + " KitCharacter");
                _graph.SetTimeUpdateMode(DirectorUpdateMode.Manual);
                _output = AnimationPlayableOutput.Create(_graph, "clip", _animator);
            }
            if (_playable.IsValid())
            {
                _playable.Destroy();
            }
            _playable = AnimationClipPlayable.Create(_graph, c);
            _output.SetSourcePlayable(_playable);
            _graph.Play();
            Seek(0f);
        }

        /// <summary>Jump the playing clip to <paramref name="seconds"/> (looped or held as Play said) and pose
        /// the character now, also in edit mode.</summary>
        public void Seek(float seconds)
        {
            if (Playing == null)
            {
                throw new InvalidOperationException($"{name}: Seek before Play");
            }
            if (_legacy != null)
            {
                AnimationState state = _legacy[Playing];
                state.enabled = true;                 // Play enables it in play mode; edit mode needs it said
                state.weight = 1f;
                state.time = seconds;                 // its wrap mode loops or clamps the time
                _legacy.Sample();
                return;
            }
            _time = seconds;
            Apply();
        }

        /// <summary>A bone (any transform under the character) by name, e.g. "mixamorig:LeftUpLeg"; null if none.</summary>
        public Transform Bone(string boneName) =>
            GetComponentsInChildren<Transform>(true).FirstOrDefault(t => t.name == boneName);

        // ---- Internals ------------------------------------------------------------------

        private void Add(AnimationClip clip)
        {
            if (clip == null || _clips.ContainsKey(clip.name))
            {
                return;
            }
            _clips[clip.name] = clip;
            _names.Add(clip.name);
        }

        private void Update()
        {
            if (Application.isPlaying && _playable.IsValid())      // edit mode: only Seek moves it
            {
                _time += Time.deltaTime;
                Apply();
            }
        }

        private void Apply()
        {
            double length = _playable.GetAnimationClip().length;
            double t = _time;
            if (length > 0)
            {
                t = _loop ? t - Math.Floor(t / length) * length : Math.Min(Math.Max(t, 0), Math.Max(length - HOLD_S, 0));
            }
            _playable.SetTime(t);
            _graph.Evaluate();
        }

        private void OnDestroy()
        {
            if (_graph.IsValid())
            {
                _graph.Destroy();
            }
#if GAMEKIT_GLTFAST
            _gltf?.Dispose();                         // the meshes, materials and clips it made
            _gltf = null;
#endif
        }

        private static void Kill(Object o)
        {
            if (Application.isPlaying)
            {
                Destroy(o);
            }
            else
            {
                DestroyImmediate(o);
            }
        }
    }
}

// {{FOOTER}}
