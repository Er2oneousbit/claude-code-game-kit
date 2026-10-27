// ---------------------------------------------------------------------------
// CharacterAnimator.cs
// Purpose : Plays the Kenney character clips by name on a legacy Animation component, with crossfades.
// Usage   : var a = new CharacterAnimator(modelInstance); a.Play("walk", speedFactor);
//           a.Hold("holding-right", CharacterAnimator.FindBone(model, "arm-right"));   // one arm keeps a pose
// Notes   : The character FBX files import as Legacy animation (Assets/Editor/GraveyardImport.cs), so
//           no Animator Controller asset is needed and everything stays in code. Clip names in Kenney
//           files may carry prefixes ("Root|walk"), so a clip matches when its name ends with the key.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using UnityEngine;

namespace graveyard_shift.Game
{
    public sealed class CharacterAnimator
    {
        private const float Fade = 0.15f;
        private const int HoldLayer = 1;   // above the walk and idle clips, so the held pose wins on its bones
        private readonly Animation _anim;
        private readonly Dictionary<string, string> _names = new Dictionary<string, string>();
        private string _current;

        public CharacterAnimator(GameObject model)
        {
            _anim = model.GetComponentInChildren<Animation>();
            if (_anim == null)
            {
                GameLog.Warn("anim", $"{model.name} has no Animation component (import it as Legacy: dev.py exec SceneBuilder.Build)");
                return;
            }
            foreach (AnimationState s in _anim) _names[Key(s.name)] = s.name;
            GameLog.Debug("anim", $"{model.name}: {string.Join(", ", _names.Keys)}");
        }

        private static string Key(string clip)
        {
            int bar = clip.LastIndexOf('|');
            return bar >= 0 ? clip.Substring(bar + 1) : clip;
        }

        // Keeps one clip's pose on one bone and its children (a held lantern) while Play changes the rest
        public void Hold(string key, Transform bone)
        {
            if (_anim == null || bone == null || !_names.TryGetValue(key, out string clip)) return;
            var state = _anim[clip];
            state.layer = HoldLayer;
            state.AddMixingTransform(bone, true);
            state.wrapMode = WrapMode.ClampForever;
            state.weight = 1f;
            state.enabled = true;
        }

        public static Transform FindBone(Transform root, string name)
        {
            if (root.name == name) return root;
            foreach (Transform child in root)
            {
                var found = FindBone(child, name);
                if (found != null) return found;
            }
            return null;
        }

        public void Play(string key, float speed, bool loop = true)
        {
            if (_anim == null || !_names.TryGetValue(key, out string clip)) return;
            var state = _anim[clip];
            state.speed = speed;
            state.wrapMode = loop ? WrapMode.Loop : WrapMode.ClampForever;
            if (_current == clip) return;
            _anim.CrossFade(clip, Fade);
            _current = clip;
        }
    }
}
