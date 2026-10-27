// ---------------------------------------------------------------------------
// KeeperController.cs
// Purpose : The caretaker: moves with a CharacterController, carries the lantern (a point light you
//           can switch off), faces where it walks and plays the Kenney walk/idle clips.
// Usage   : keeper.Init(tuning, setup, darkGlow); each frame keeper.Move(direction, dt); keeper.SetLantern(on)
// Notes   : Speed depends on the lantern (pillar 1: lit is fast and seen from afar, dark is slow and
//           nearly invisible). The model is the Kenney Graveyard Kit keeper at Level.WorldScale. Lantern out, he
//           walks the same cycle slower (the kit's "crouch" is a still pose: his legs froze). The lantern hangs from
//           the end of his right arm, which holds the kit's "holding-right" pose over every other clip.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using graveyard_shift.Core;
using UnityEngine;

namespace graveyard_shift.Game
{
    [RequireComponent(typeof(CharacterController))]
    public sealed class KeeperController : MonoBehaviour
    {
        private const float TurnSpeed = 720f;           // degrees per second
        private const float LanternRange = 9f;
        private const float LanternIntensity = 2.64f;   // 2.4 until the owner asked for 10% brighter (10-23)
        private const float DarkGlowRange = 1.6f;       // a faint glow, so the player still sees the keeper
        private const float DarkGlowIntensity = 0.5f;
        private static readonly Color LanternColor = new Color(1f, 0.78f, 0.45f);
        private const string HandBone = "arm-right";
        private const string HoldClip = "holding-right";
        private static readonly Vector3 InHand = new Vector3(0.29f, -0.22f, 0f);   // model units, from the arm's pivot
        private const float LanternScale = 0.6f;                                    // of the model's scale
        // the light sits at the top of the lantern, not its middle: lower, it grazed the ground and lit a smaller pool
        private static readonly Vector3 FlameInLantern = new Vector3(0f, 0.6f, 0f);

        private GameTuning _t;
        private CharacterController _cc;
        private Light _lantern;
        private CharacterAnimator _anim;

        public bool LanternLit { get; private set; } = true;
        public Transform Lantern { get; private set; }   // the lantern model, in his right hand
        public Light LanternLight => _lantern;
        public bool Moving { get; private set; }
        public V2 Ground => LevelBuilder.ToGround(transform.position);
        public Vector3 Chest => transform.position + Vector3.up * Footprint.ChestHeight;   // where ghosts look (and cover must reach)

        private float _darkGlow = 1f;   // the difficulty's scale on the lantern-out glow (0: black)

        public void Init(GameTuning tuning, GraveyardSetup setup, float darkGlow = 1f)
        {
            _darkGlow = darkGlow;
            _t = tuning;
            _cc = GetComponent<CharacterController>();
            _cc.height = 1.8f;
            _cc.radius = 0.4f;
            _cc.center = new Vector3(0f, 0.9f, 0f);

            var body = Instantiate(setup.Find("character-keeper"), transform);
            body.transform.localScale = Vector3.one * Level.WorldScale;
            _anim = new CharacterAnimator(body);
            var hand = CharacterAnimator.FindBone(body.transform, HandBone);
            _anim.Hold(HoldClip, hand);
            var lantern = setup.Find("lantern-candle");
            if (lantern != null && hand != null)
            {
                Lantern = Instantiate(lantern, hand).transform;
                Lantern.localPosition = InHand;
                Lantern.localRotation = Quaternion.identity;
                Lantern.localScale = Vector3.one * LanternScale;
                // the light sits inside the lantern: its glass must not shadow its own flame
                foreach (var r in Lantern.GetComponentsInChildren<Renderer>()) r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
                _lantern = LevelBuilder.AddLight(Lantern, FlameInLantern, LanternColor, LanternRange, LanternIntensity);
            }
            else
            {
                GameLog.Warn("keeper", "no lantern model or no hand bone: the light floats at his side");
                _lantern = LevelBuilder.AddLight(transform, new Vector3(0.45f, 1.2f, 0.35f), LanternColor, LanternRange, LanternIntensity);
            }
            _lantern.shadows = LightShadows.Soft;
            SetLantern(true);
        }

        public void SetLantern(bool on)
        {
            LanternLit = on;
            _lantern.range = on ? LanternRange : DarkGlowRange * _darkGlow;
            _lantern.intensity = on ? LanternIntensity : DarkGlowIntensity * _darkGlow;
        }

        // direction: world x/z, length up to 1
        public void Move(Vector2 direction, float dt)
        {
            if (direction.sqrMagnitude > 1f) direction.Normalize();
            Moving = direction.sqrMagnitude > 0.01f;
            float speed = LanternLit ? _t.LitSpeed : _t.DarkSpeed;
            var v = new Vector3(direction.x, 0f, direction.y) * speed;
            _cc.SimpleMove(v);
            if (Moving)
            {
                var want = Quaternion.LookRotation(new Vector3(direction.x, 0f, direction.y));
                transform.rotation = Quaternion.RotateTowards(transform.rotation, want, TurnSpeed * dt);
            }
            _anim.Play(Moving ? "walk" : "idle", Moving ? speed / _t.LitSpeed : 1f);
        }

        // Back to a spot (the gate after a catch). The CharacterController must be off to teleport.
        public void Respawn(Vector3 at)
        {
            _cc.enabled = false;
            transform.position = at;
            _cc.enabled = true;
        }

        public void PlayEnd(bool won) => _anim.Play(won ? "emote-yes" : "die", 1f, loop: false);
    }
}
