// ---------------------------------------------------------------------------
// LevelBuilder.cs
// Purpose : Builds the graveyard at runtime from Core/Level.cs: ground and the grass outside, props (each with a
//           box collider from its mesh, marked as Cover; crypts get their roof and door), lights and fog for the
//           difficulty, souls, the iron gate, trees and bushes outside the wall, then bakes the NavMesh.
// Usage   : var built = LevelBuilder.Build(level, setup, DifficultySettings.For(d));
//           built.Gate.Open();   // when the last soul is collected
// Notes   : Runtime building keeps the scene file tiny (one Bootstrap object), so every change is C# and the
//           level is data. AI Navigation 2.0 bakes from physics colliders at runtime, so what blocks the keeper,
//           blocks the ghosts' paths and blocks their sight is the same box. Only children of the Level root are
//           baked: the grass and the trees outside the wall hang off a separate root. The grass has a collider (a
//           floor under anything that ever gets past the wall); the trees outside have none.
//           The ambient light is Trilight, set here from the difficulty. The scene's own default is Skybox, which
//           lights the yard from Unity's default sky and ignores the ambient colors, so every difficulty looked the
//           same (playtest); reflections of that sky are scaled down with it.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using graveyard_shift.Core;
using Unity.AI.Navigation;
using UnityEngine;
using UnityEngine.AI;
using UnityEngine.Rendering;

namespace graveyard_shift.Game
{
    public sealed class BuiltLevel
    {
        public Transform Root;
        public readonly List<GameObject> Souls = new List<GameObject>();
        public readonly List<V2> SoulPositions = new List<V2>();
        public Light GateLight;
        public Light Moon;   // EndSequence turns it into the dawn sun
        public GateSwing Gate;
    }

    public static class LevelBuilder
    {
        // Easy's ambient light from above, the sides and below (matched by eye to the night before difficulties)
        private static readonly Color AmbientSky = new Color(0.48f, 0.53f, 0.71f);
        private static readonly Color AmbientEquator = new Color(0.30f, 0.32f, 0.41f);
        private static readonly Color AmbientGround = new Color(0.14f, 0.14f, 0.16f);
        private static readonly Color FogColor = new Color(0.04f, 0.05f, 0.09f);
        private static readonly Color SoulColor = new Color(0.45f, 0.95f, 1.0f);
        private static readonly Color GateClosed = new Color(1.0f, 0.35f, 0.25f);
        private static readonly Color GrassColor = new Color(0.16f, 0.22f, 0.13f);
        private const float MoonIntensity = 0.35f;
        private const float SoulLightRange = 4f, SoulLightIntensity = 1.6f;
        private const float GateLightRange = 7f;

        // Outside the wall: one big grass plane, and trees and bushes out to OutsideReach meters
        private const float GrassSize = 500f;
        private const float OutsideReach = 30f;
        private const float OutsideClear = 3f;                 // nothing outside within this of the wall
        private const int OutsideCount = 160;
        private const float OutsideScaleMin = 1.6f, OutsideScaleMax = 2.8f;
        private static readonly string[] OutsideModels =
        {
            "plant_bush", "plant_bushLarge", "plant_bushSmall", "plant_bushDetailed", "plant_bush", "plant_bushLarge",
            "tree_oak_dark", "tree_default_dark", "tree_fat_darkh", "tree_pineTallA", "tree_pineRoundC", "tree_pineSmallB",
            "pine", "pine-crooked", "grass_large", "grass",
        };

        // The gate: two iron fence panels hinged at the opening's edges, swinging out when the gate opens
        private const string GateLeafModel = "iron-fence";
        private const float GateLeafZOffset = 0.65f;           // the iron-fence model sits this far behind its pivot

        public static BuiltLevel Build(Level level, GraveyardSetup setup, DifficultySettings d)
        {
            var built = new BuiltLevel { Root = new GameObject("Level").transform };

            // Night: the difficulty sets how much light there is (Easy is the original night)
            RenderSettings.ambientMode = AmbientMode.Trilight;
            RenderSettings.ambientSkyColor = AmbientSky * d.AmbientScale;
            RenderSettings.ambientEquatorColor = AmbientEquator * d.AmbientScale;
            RenderSettings.ambientGroundColor = AmbientGround * d.AmbientScale;
            RenderSettings.reflectionIntensity = d.AmbientScale;
            RenderSettings.fog = true;
            RenderSettings.fogMode = FogMode.ExponentialSquared;
            RenderSettings.fogDensity = d.FogDensity;
            RenderSettings.fogColor = FogColor * d.AmbientScale;
            var moon = new GameObject("Moon").AddComponent<Light>();
            moon.type = LightType.Directional;
            moon.color = new Color(0.55f, 0.62f, 0.9f);
            moon.intensity = MoonIntensity * d.MoonScale;
            moon.shadows = LightShadows.Soft;
            moon.transform.SetParent(built.Root);
            moon.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
            built.Moon = moon;

            // Ground: a box under the yard (it needs a collider for the NavMesh bake), grass all around it
            var b = level.Bounds;
            var ground = GameObject.CreatePrimitive(PrimitiveType.Cube);
            ground.name = "Ground";
            ground.transform.SetParent(built.Root);
            ground.transform.localScale = new Vector3(b.MaxX - b.MinX + 4f, 0.2f, b.MaxZ - b.MinZ + 4f);
            ground.transform.position = new Vector3((b.MinX + b.MaxX) * 0.5f, -0.1f, (b.MinZ + b.MaxZ) * 0.5f);
            ground.GetComponent<Renderer>().sharedMaterial = Flat(GrassColor);
            BuildOutside(level, setup);

            foreach (var prop in level.Props)
            {
                var go = SpawnProp(setup, prop, built.Root);
                if (go == null) continue;
                AddBlocker(go, true);
                if (prop.Model == "lightpost-single" && d.GateLamps) AddLight(go.transform, new Vector3(0f, 2.4f, 0f), new Color(1f, 0.8f, 0.5f), 6f, 1.2f);
            }

            // Souls: orbs, bobbing (SoulBob); glowing with their own light unless the night is pitch black
            for (int i = 0; i < level.Souls.Count; i++)
            {
                var soul = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                soul.name = $"Soul{i}";
                Object.Destroy(soul.GetComponent<Collider>());  // collected by distance, not physics
                soul.transform.SetParent(built.Root);
                soul.transform.position = ToWorld(level.Souls[i]) + Vector3.up * 1.1f;
                soul.transform.localScale = Vector3.one * 0.45f;
                soul.GetComponent<Renderer>().sharedMaterial = d.SoulGlows ? Glow(SoulColor) : Flat(SoulColor);
                if (d.SoulLightScale > 0f) AddLight(soul.transform, Vector3.zero, SoulColor, SoulLightRange * d.SoulLightScale, SoulLightIntensity);
                soul.AddComponent<SoulBob>();
                built.Souls.Add(soul);
                built.SoulPositions.Add(level.Souls[i]);
            }

            // The gate: iron leaves across the opening (shut until every soul is found), a red light above it, off
            // when the difficulty has no gate lamps (Insane: black outside the lantern; recolouring keeps it off)
            built.Gate = BuildGate(level, setup, built.Root);
            built.GateLight = AddLight(built.Root, ToWorld(level.Gate) + Vector3.up * 2f, GateClosed, GateLightRange, 2f);
            built.GateLight.enabled = d.GateLamps;

            // NavMesh from the colliders (ground walkable, every prop and the shut gate an obstacle)
            var surface = built.Root.gameObject.AddComponent<NavMeshSurface>();
            surface.collectObjects = CollectObjects.Children;
            surface.useGeometry = NavMeshCollectGeometry.PhysicsColliders;
            surface.BuildNavMesh();
            return built;
        }

        public static Vector3 ToWorld(V2 p) => new Vector3(p.X, 0f, p.Z);
        public static V2 ToGround(Vector3 p) => new V2(p.x, p.z);

        // One prop as the player sees it: the model at WorldScale, plus its roof and door (Footprint.Parts).
        // The footprint test spawns props through here too, so the measured box is the built one.
        public static GameObject SpawnProp(GraveyardSetup setup, Prop prop, Transform parent)
        {
            var prefab = setup.Find(prop.Model);
            if (prefab == null)
            {
                GameLog.Error("level", $"model '{prop.Model}' is not in SO_GraveyardSetup (run dev.py exec SceneBuilder.Build)");
                return null;
            }
            var go = Object.Instantiate(prefab, ToWorld(prop.Position), Quaternion.Euler(0f, prop.Yaw, 0f), parent);
            go.transform.localScale = Vector3.one * Level.WorldScale;
            foreach (var part in Footprint.Parts(prop.Model))
            {
                var piece = setup.Find(part.Model);
                if (piece == null)
                {
                    GameLog.Error("level", $"model '{part.Model}' is not in SO_GraveyardSetup (run dev.py exec SceneBuilder.Build)");
                    continue;
                }
                var child = Object.Instantiate(piece, go.transform);
                child.transform.localPosition = new Vector3(0f, part.Y, part.Z) / Level.WorldScale;
                child.transform.localRotation = Quaternion.identity;
                child.transform.localScale = Vector3.one;
            }
            return go;
        }

        // Two leaves hinged at the opening's edges, on the wall line; GateSwing turns them outward
        private static GateSwing BuildGate(Level level, GraveyardSetup setup, Transform root)
        {
            var gate = new GameObject("Gate");
            gate.transform.SetParent(root, false);
            var swing = gate.AddComponent<GateSwing>();
            float lineZ = level.Areas[0].MinZ;
            var leaf = setup.Find(GateLeafModel);
            for (int side = -1; side <= 1; side += 2)
            {
                var hinge = new GameObject(side < 0 ? "HingeWest" : "HingeEast").transform;
                hinge.SetParent(gate.transform, false);
                hinge.position = new Vector3(side * Level.GateWidth * 0.5f, 0f, lineZ);
                if (leaf != null)
                {
                    var panel = Object.Instantiate(leaf, hinge);
                    panel.transform.localScale = Vector3.one * Level.WorldScale;
                    panel.transform.localRotation = Quaternion.identity;
                    // The panel is one wall tile wide: centered half a tile from its hinge, toward the middle
                    panel.transform.localPosition = new Vector3(-side * Level.GateWidth * 0.25f, 0f, GateLeafZOffset);
                    AddBlocker(panel, false);   // bars: you can see through, so not Cover
                }
                swing.AddHinge(hinge, side);
            }
            return swing;
        }

        // Grass to the horizon and trees and bushes outside the wall: looks only, no colliders, not baked
        private static void BuildOutside(Level level, GraveyardSetup setup)
        {
            var outside = new GameObject("Outside").transform;
            var grass = GameObject.CreatePrimitive(PrimitiveType.Plane);
            grass.name = "Grass";
            grass.transform.SetParent(outside);
            grass.transform.position = new Vector3(0f, -0.02f, 0f);
            grass.transform.localScale = Vector3.one * (GrassSize / 10f);   // a Unity plane is 10 m
            grass.GetComponent<Renderer>().sharedMaterial = Flat(GrassColor);

            var rng = new SeededRandom(SeededRandom.Combine(level.Seed, 0x0D7));
            var b = level.Bounds;
            int placed = 0;
            for (int i = 0; i < OutsideCount * 4 && placed < OutsideCount; i++)
            {
                var p = new V2(rng.Step(b.MinX - OutsideReach, b.MaxX + OutsideReach, 4), rng.Step(b.MinZ - OutsideReach, b.MaxZ + OutsideReach, 4));
                if (NearYard(level, p)) continue;
                var prefab = setup.Find(rng.Pick(OutsideModels));
                if (prefab == null) continue;
                var go = Object.Instantiate(prefab, ToWorld(p), Quaternion.Euler(0f, rng.Range(0, 24) * 15f, 0f), outside);
                go.transform.localScale = Vector3.one * rng.Step(OutsideScaleMin, OutsideScaleMax, 4);
                placed++;
            }
        }

        // Inside the outline, or within OutsideClear of it
        private static bool NearYard(Level level, V2 p)
        {
            for (float dx = -OutsideClear; dx <= OutsideClear; dx += OutsideClear)
            for (float dz = -OutsideClear; dz <= OutsideClear; dz += OutsideClear)
                if (level.Inside(new V2(p.X + dx, p.Z + dz))) return true;
            return false;
        }

        // A world-aligned box around everything the prop draws; cover blocks the ghosts' sight
        private static void AddBlocker(GameObject go, bool cover)
        {
            var renderers = go.GetComponentsInChildren<Renderer>();
            if (renderers.Length == 0) return;
            Bounds b = renderers[0].bounds;
            foreach (var r in renderers) b.Encapsulate(r.bounds);
            var blocker = new GameObject("Blocker");
            blocker.transform.SetParent(go.transform, true);
            blocker.transform.position = b.center;
            blocker.transform.rotation = Quaternion.identity;
            blocker.transform.localScale = Vector3.one;
            var box = blocker.AddComponent<BoxCollider>();
            box.size = new Vector3(b.size.x / go.transform.lossyScale.x, b.size.y / go.transform.lossyScale.y, b.size.z / go.transform.lossyScale.z);
            if (cover) blocker.AddComponent<Cover>();
        }

        public static Light AddLight(Transform parent, Vector3 localPos, Color color, float range, float intensity)
        {
            var l = new GameObject("Light").AddComponent<Light>();
            l.transform.SetParent(parent, false);
            l.transform.localPosition = localPos;
            l.type = LightType.Point;
            l.color = color;
            l.range = range;
            l.intensity = intensity;
            return l;
        }

        public static Material Flat(Color c)
        {
            var m = new Material(Shader.Find("Standard")) { color = c };
            m.SetFloat("_Glossiness", 0.05f);
            return m;
        }

        public static Material Glow(Color c)
        {
            var m = Flat(c);
            m.EnableKeyword("_EMISSION");
            m.SetColor("_EmissionColor", c * 1.6f);
            return m;
        }
    }
}
