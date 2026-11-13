// ---------------------------------------------------------------------------
// DotworkPack.cs
// Purpose : The index of one imported Dotwork pack (one <pack>.assets.json): every asset the importer made, by
//           kind and name, so game code finds a character's clips, a prop's prefab, a map, a font, a UI part, a
//           background's layers, a particle texture with its emitter JSON, a transition mask, a normal map or a
//           loose image without hard-coded paths. The importer writes it to Assets/dotwork/<pack>/<pack>.asset.
// Usage   : DotworkPack pack = ...;  (a serialized field, or Resources/Addressables if you move it there)
//           Instantiate(pack.Animated("hero").prefab).GetComponent<Animator>().Play(pack.Animated("hero").Clip("walk", "s"));
//           Instantiate(pack.Map("yard").prefab);  pack.Map("yard").Bounds(pack.pixelsPerUnit);  pack.Font("tiny");  pack.UiPart("windows", "ui_window_plain").sprite
//           pack.Background("hills").layers[1].velocity;  pack.Particles("embers").emitter.text;  pack.Image("logo").sprite
// Notes   : Units: one Unity unit is `pixelsPerUnit` art pixels (the pack's first tileset's tile width, else 16).
//           Pixel data kept from the manifest (pivots, collision rects, margins, hotspots, velocities) stays in
//           the manifest's own space (pixels, y down) so it reads the same as the spec; the sprites and colliders
//           the importer made are already converted to Unity's y up. `manifestHash` lets the verify check spot a
//           stale import. The extra kinds (background, particles, transition, normal_map, image) are loaded, not
//           built into scene objects: the game object that uses them (a parallax, an emitter, a wipe shader, a 2D
//           light) is the game's or the shader recipes' job. `skipped` lists only kinds this importer does not know.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): stamps, the map's shape, the extra kinds (#285)
//           2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): DotworkMap.Bounds, a map's real extent on both
//           shapes (#297)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using UnityEngine;

namespace graveyard_shift.Dotwork
{
    public sealed class DotworkPack : ScriptableObject
    {
        public string pack = "";
        public string version = "";
        public string manifestPath = "";            // Assets/dotwork/<pack>.assets.json
        public string manifestHash = "";            // SHA-256 of the manifest text this import was made from
        public float pixelsPerUnit = 16f;
        public List<DotworkAnimated> animated = new List<DotworkAnimated>();
        public List<DotworkSprite> sprites = new List<DotworkSprite>();
        public List<DotworkIcon> icons = new List<DotworkIcon>();
        public List<DotworkPortrait> portraits = new List<DotworkPortrait>();
        public List<DotworkTileset> tilesets = new List<DotworkTileset>();
        public List<DotworkMap> maps = new List<DotworkMap>();
        public List<DotworkFont> fonts = new List<DotworkFont>();
        public List<DotworkUiKit> uiKits = new List<DotworkUiKit>();
        public List<DotworkBackground> backgrounds = new List<DotworkBackground>();
        public List<DotworkParticles> particles = new List<DotworkParticles>();
        public List<DotworkTransition> transitions = new List<DotworkTransition>();
        public List<DotworkNormalMap> normalMaps = new List<DotworkNormalMap>();
        public List<DotworkImage> images = new List<DotworkImage>();
        public List<string> skipped = new List<string>();   // "<kind>/<name>" the importer left out (unknown kinds)

        public DotworkAnimated Animated(string name) => animated.Find(a => a.name == name);
        public DotworkSprite Sprite(string name) => sprites.Find(a => a.name == name);
        public DotworkIcon Icon(string name) => icons.Find(a => a.name == name);
        public DotworkPortrait Portrait(string name) => portraits.Find(a => a.name == name);
        public DotworkTileset Tileset(string name) => tilesets.Find(a => a.name == name);
        public DotworkMap Map(string name) => maps.Find(a => a.name == name);
        public DotworkFont Font(string name) => fonts.Find(a => a != null && a.fontName == name);
        public DotworkUiKit UiKit(string name) => uiKits.Find(a => a.name == name);
        public DotworkBackground Background(string name) => backgrounds.Find(a => a.name == name);
        public DotworkParticles Particles(string name) => particles.Find(a => a.name == name);
        public DotworkTransition Transition(string name) => transitions.Find(a => a.name == name);
        public DotworkNormalMap NormalMap(string name) => normalMaps.Find(a => a.name == name);
        public DotworkImage Image(string name) => images.Find(a => a.name == name);

        public DotworkUiPart UiPart(string kit, string part)
        {
            DotworkUiKit k = UiKit(kit);
            return k?.parts.Find(p => p.name == part);
        }
    }

    [Serializable]
    public sealed class DotworkClip
    {
        public string name = "";
        public AnimationClip clip;                   // sprite keys at the frame times (a last frame held longer has
                                                     // one more key, a frame before the end: Unity's clip length rule)
        public int frames;
        public bool loop;
        public float fps;
        public Vector2 pivot;                       // pixels, y down
        public Vector2Int frameSize;
        public string sheet = "";                   // the sheet's path under the pack's base, "" for separate frames
    }

    [Serializable]
    public sealed class DotworkDirection
    {
        public string action = "", dir = "", clip = "";
    }

    [Serializable]
    public sealed class DotworkAnimated
    {
        public string name = "", role = "", blend = "normal";
        public RuntimeAnimatorController controller; // one state per clip, named as the clip
        public GameObject prefab;                    // SpriteRenderer + Animator, first clip's first frame
        public List<DotworkClip> clips = new List<DotworkClip>();
        public List<DotworkDirection> directions = new List<DotworkDirection>();

        public DotworkClip ClipNamed(string clip) => clips.Find(c => c.name == clip);

        /// <summary>The clip name for an action and a direction (walk, s -> walk_s), or null.</summary>
        public string Clip(string action, string dir) => directions.Find(d => d.action == action && d.dir == dir)?.clip;
    }

    [Serializable]
    public sealed class DotworkSprite
    {
        public string name = "", role = "";
        public UnityEngine.Sprite sprite;
        public GameObject prefab;                    // SpriteRenderer, BoxCollider2D per rect, Shadow child
        public Vector2Int size;
        public Vector2 pivot;                        // pixels, y down
        public Rect[] collision = new Rect[0];       // pixels, y down
        public UnityEngine.Sprite shadow;
        public Vector2 shadowOffset;                 // pixels from the pivot, y down
    }

    [Serializable]
    public sealed class DotworkNamedSprite
    {
        public string name = "";
        public int size;                             // icons: the pixel size
        public UnityEngine.Sprite sprite;
    }

    [Serializable]
    public sealed class DotworkIcon
    {
        public string name = "";
        public List<DotworkNamedSprite> sizes = new List<DotworkNamedSprite>();   // smallest first

        /// <summary>The largest size that fits in px, else the smallest.</summary>
        public UnityEngine.Sprite Best(int px)
        {
            DotworkNamedSprite best = sizes.Count > 0 ? sizes[0] : null;
            foreach (DotworkNamedSprite s in sizes)
            {
                if (s.size <= px)
                {
                    best = s;
                }
            }
            return best?.sprite;
        }
    }

    [Serializable]
    public sealed class DotworkPortrait
    {
        public string name = "";
        public Vector2Int size;
        public List<DotworkNamedSprite> expressions = new List<DotworkNamedSprite>();
        public string animation = "";                // the animated_sprite with idle, talk and blink, or ""

        public UnityEngine.Sprite Expression(string expression) => expressions.Find(e => e.name == expression)?.sprite;
    }

    [Serializable]
    public sealed class DotworkTerrain
    {
        public int set, id;
        public string name = "", color = "", mode = "";
        public DotworkTerrainTile tile;              // the paintable rule tile; null for a terrain with no keyed tiles
    }

    [Serializable]
    public sealed class DotworkStamp
    {
        public string name = "";
        public Vector2Int size;                      // cells
        public bool solid;
        public Vector3Int[] tiles = new Vector3Int[0];   // [atlas, col, row] per cell, reading order (tile j at (x + j % w, y + j / w))
    }

    [Serializable]
    public sealed class DotworkTileset
    {
        public string name = "", shape = "square";
        public Vector2Int tileSize;
        public List<DotworkTile> tiles = new List<DotworkTile>();
        public List<DotworkTerrain> terrains = new List<DotworkTerrain>();
        public List<DotworkStamp> stamps = new List<DotworkStamp>();

        public DotworkTile Tile(int atlas, int col, int row) => tiles.Find(t => t.atlas == atlas && t.col == col && t.row == row);
        public DotworkTerrain Terrain(int set, int id) => terrains.Find(t => t.set == set && t.id == id);
    }

    [Serializable]
    public sealed class DotworkMap
    {
        public string name = "", tileset = "", shape = "square";
        public Vector2Int size, tileSize;
        public GameObject prefab;                    // Grid > one Tilemap per layer, Objects > prop instances

        /// <summary>The map's extent in its prefab's local units (y up, the map's top-left corner at the origin):
        /// the box around every cell's tile, as the other engines' map_bounds. A square map is (0, -h, w, h); an
        /// isometric one is the diamond's box, from x = (1 - rows) * tileW / 2 to (cols + rows) * tileW / 2 and
        /// (cols + rows) * tileH / 2 deep (spec "Placing tiles": cell centres ((x - y + 1) w / 2, (x + y + 1) h / 2)).</summary>
        public Rect Bounds(float pixelsPerUnit)
        {
            float w = tileSize.x / pixelsPerUnit, h = tileSize.y / pixelsPerUnit;
            if (shape == "isometric")
            {
                float depth = (size.x + size.y) * h / 2f;
                return new Rect((1 - size.y) * w / 2f, -depth, (size.x + size.y) * w / 2f, depth);
            }
            return new Rect(0f, -size.y * h, size.x * w, size.y * h);
        }
    }

    [Serializable]
    public sealed class DotworkUiPart
    {
        public string name = "", role = "", state = "", control = "", glyph = "";
        public UnityEngine.Sprite sprite;            // 9-slice margins are its border
        public Vector2Int size;
        public float scale = 1f;                     // already applied to the image and margins: draw 1:1
        public bool hasMargins, hasHotspot;
        public Vector4 margins;                      // left, top, right, bottom (the manifest's order)
        public Vector2 hotspot;                      // pixels, y down
    }

    [Serializable]
    public sealed class DotworkUiKit
    {
        public string name = "", role = "";
        public List<DotworkUiPart> parts = new List<DotworkUiPart>();
    }

    [Serializable]
    public sealed class DotworkBackgroundLayer
    {
        public string name = "";
        public UnityEngine.Sprite sprite;            // its texture repeats on the `repeat` axes
        public Vector2Int size;
        public Vector2 velocity;                     // px/s of the art, y down
        public string repeat = "none";               // none, x, y, xy
        public float wobblePx;
        public float scale = 1f;                     // the whole-number scale the art is drawn at
    }

    [Serializable]
    public sealed class DotworkBackground
    {
        public string name = "", role = "";
        public List<DotworkBackgroundLayer> layers = new List<DotworkBackgroundLayer>();   // drawn first to last
    }

    [Serializable]
    public sealed class DotworkParticles
    {
        public string name = "";
        public UnityEngine.Sprite texture;           // a white mask, tinted by the emitter's colour steps
        public TextAsset emitter;                    // the emitter JSON as Dotwork wrote it (amount, lifetime, colors ...)
    }

    [Serializable]
    public sealed class DotworkTransition
    {
        public string name = "", transition = "";    // wipe, iris, spiral ...
        public UnityEngine.Sprite sprite;            // greyscale: a pixel is covered once progress passes its grey / 255
        public Vector2Int size;
    }

    [Serializable]
    public sealed class DotworkNormalMap
    {
        public string name = "", convention = "opengl";
        public Texture2D texture;                    // linear, not a sprite
        public string target = "";                   // the lit image's path under the pack's base
        public UnityEngine.Sprite targetSprite;      // the first sprite of the target image (its _NormalMap secondary texture is `texture`)
    }

    [Serializable]
    public sealed class DotworkImage
    {
        public string name = "", role = "";
        public UnityEngine.Sprite sprite;
        public Vector2Int size;
        public bool hasPivot;
        public Vector2 pivot;                        // pixels, y down
    }
}
