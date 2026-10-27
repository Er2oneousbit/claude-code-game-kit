// ---------------------------------------------------------------------------
// CameraRig.cs
// Purpose : The third-person camera: high, behind, never rotating (so WASD always means the same
//           screen direction), easing after the keeper.
// Usage   : CameraRig.Create(keeperTransform)  (the AudioListener is GraveyardAudio's: at the keeper, not up here)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using UnityEngine;

namespace graveyard_shift.Game
{
    public sealed class CameraRig : MonoBehaviour
    {
        private static readonly Vector3 Offset = new Vector3(0f, 13f, -9.5f);
        private static readonly Vector3 LookAhead = new Vector3(0f, 0f, 2f);
        private const float Smooth = 0.18f;   // s

        private Transform _target;
        private Vector3 _velocity;

        public static Camera Create(Transform target)
        {
            var go = new GameObject("Main Camera") { tag = "MainCamera" };
            var cam = go.AddComponent<Camera>();
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0.03f, 0.04f, 0.08f);
            cam.fieldOfView = 50f;
            var rig = go.AddComponent<CameraRig>();
            rig._target = target;
            go.transform.position = target.position + Offset;
            go.transform.LookAt(target.position + LookAhead);
            return cam;
        }

        private void LateUpdate()
        {
            if (_target == null) return;
            transform.position = Vector3.SmoothDamp(transform.position, _target.position + Offset, ref _velocity, Smooth);
            transform.LookAt(transform.position - Offset + LookAhead);
        }
    }
}
