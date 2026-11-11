// ---------------------------------------------------------------------------
// DotworkPlayClip.cs
// Purpose : Starts one clip of an imported Dotwork character on its Animator when the scene starts (the starter
//           scene's showcase uses it to show a walk). Game code usually calls Animator.Play itself instead.
// Usage   : go.AddComponent<DotworkPlayClip>().clip = "walk_s";
// Notes   : The importer's AnimatorController has one state per clip, named as the clip, so Play(clip) works for
//           any clip of the manifest. A missing state logs a warning (not an error: smoke fails on errors).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using UnityEngine;

namespace graveyard_shift.Dotwork
{
    [RequireComponent(typeof(Animator))]
    public sealed class DotworkPlayClip : MonoBehaviour
    {
        public string clip = "";

        private void Start()
        {
            var animator = GetComponent<Animator>();
            if (string.IsNullOrEmpty(clip) || animator.runtimeAnimatorController == null)
            {
                return;
            }
            if (!animator.HasState(0, Animator.StringToHash(clip)))
            {
                Debug.LogWarning($"[WARN][dotwork] {name}: no clip '{clip}' in {animator.runtimeAnimatorController.name}");
                return;
            }
            animator.Play(clip);
        }
    }
}
