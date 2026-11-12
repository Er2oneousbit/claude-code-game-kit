// ---------------------------------------------------------------------------
// DotworkAssets.hpp
// Purpose : The SDL-free half of the Dotwork asset importer (#60): reads Dotwork's engine-neutral asset manifests
//           (<assets>/dotwork/<pack>.assets.json, spec: tools/art/dotwork/ASSET_MANIFEST.md, version 1) into plain
//           structs, resolves terrain map layers with the spec's cell_mask rule, times clips by each frame's
//           duration, lays out bitmap-font text from the `chars` table and checks that every file a pack names is
//           there. src/gfx/DotworkRender draws what this loads.
// Usage   : auto pack = core::dotwork::load_manifest(path);   // pack.errors empty = usable; pack.warnings = skipped
//           for (auto& p : core::dotwork::find_manifests("assets")) ...
//           const auto* hero = pack.animated_sprite("hero"); core::dotwork::ClipPlayer player(hero->clip("walk_s"));
//           player.update(dt); player.frame();   core::dotwork::layout_text(*font, "Hello");
//           auto problems = core::dotwork::check_files(pack);   // missing or broken files, empty when all is well
// Notes   : Everything is in core::dotwork so a game's own Sprite, Map or Font types never clash with these.
//           Coordinates are the manifest's: pixels of the art, origin top-left, y down (SDL's axes, no flip).
//           All thirteen kinds load: the eight core kinds (animated_sprite, sprite, icon, portrait, tileset, map,
//           font, ui_kit) and the five extra ones (background, particles, transition, normal_map, image) as plain
//           data by name (the game object that uses one is the game's). Unknown kinds are skipped with one warning
//           per kind; unknown fields are ignored. Spec 1.x loads (1.0.0 and 1.1.0); another major version is
//           refused (an error naming both). Paths resolve as join(dirname(manifest), base, path); a path with
//           "..", a drive or a leading "/" is an error. Map layers become placed cells at load: a tiles layer as
//           listed, a stamps layer expanded tile by tile, a terrain layer through resolve_terrain (the spec's
//           cell_mask for blob47, sides4 and corners4, then the probability pick with cell_roll), which is what
//           the golden expected.json names. cell_centre and placed_corner give where a cell's image lands on both
//           shapes (square rows, isometric diamond-down), so the renderer and the test share one formula.
//           Tested against data/golden/dotwork/ in tests/test_dotwork_assets.cpp.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): corners4 keys, the variant
//           pick (hash32, cell_roll, pick_variant), stamps layers, cell centres and placement, the extra kinds loaded
// ---------------------------------------------------------------------------
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>

namespace core::dotwork {

// ---- Constants ----
constexpr const char* kFormat = "dotwork-assets";        // the manifest's "format"
constexpr int kSpecMajor = 1;                             // the major "version" this importer reads
constexpr const char* kManifestSuffix = ".assets.json";   // <assets>/dotwork/<pack>.assets.json
constexpr const char* kManifestDir = "dotwork";           // ... under the assets folder

struct Rect {
    int x = 0, y = 0, w = 0, h = 0;
};
struct RectF {   // collision boxes can sit on half pixels
    double x = 0, y = 0, w = 0, h = 0;
};
struct Point {
    double x = 0, y = 0;
};

// ---- animated_sprite ----
struct Frame {
    std::string file;      // the frame's own PNG (always shipped)
    Rect rect;             // in the clip's sheet when it has one, else [0, 0, w, h] of `file`
    double seconds = 0.0;  // how long the frame shows (hold / fps)
};
struct Clip {
    std::string name;
    double fps = 0.0;
    bool loop = true;      // false: play once and hold the last frame
    int frame_w = 0, frame_h = 0;
    Point pivot;           // the point drawn at the sprite's position (feet, centre)
    std::string sheet;     // "" = every frame is its own file
    std::vector<Frame> frames;
    double length = 0.0;   // seconds, the sum of the frames'
    // The image frame i is cut from: the sheet, or the frame's own file.
    const std::string& texture_of(std::size_t i) const { return sheet.empty() ? frames.at(i).file : sheet; }
};
enum class Blend { Normal, Add };
struct AnimatedSprite {
    std::string name, role;
    Blend blend = Blend::Normal;
    std::vector<Clip> clips;
    std::map<std::string, std::map<std::string, std::string>> directions;   // action -> dir -> clip name
    const Clip* clip(const std::string& clip_name) const;
    // The clip for an action facing dir ("walk", "e"), or nullptr.
    const Clip* directed(const std::string& action, const std::string& dir) const;
};

// ---- sprite, icon, portrait ----
struct Sprite {
    std::string name, role, image;
    int w = 0, h = 0;
    Point pivot;
    Rect content_rect;
    std::vector<RectF> collision;   // in the image's pixels
    std::string shadow_image;       // "" = no contact shadow
    Point shadow_offset;            // the shadow's centre, from the pivot
};
struct IconSize {
    int size = 0;
    std::string image;
};
struct Icon {
    std::string name;
    std::vector<IconSize> sizes;    // smallest first
};
struct Expression {
    std::string name, image;
};
struct Portrait {
    std::string name;
    int w = 0, h = 0;
    std::vector<Expression> expressions;   // neutral first
    std::string animation;                  // the talking animated_sprite ("" = none)
};

// ---- tileset ----
struct TileRef {   // [atlas, col, row]: how maps and stamps name a tile
    int atlas = -1, col = 0, row = 0;
};
struct Tile {
    int col = 0, row = 0;
    int terrain_set = 0;
    int terrain = -1;                     // -1: no terrain
    std::optional<int> mask;              // blob47, sides4
    std::map<std::string, int> corners;   // corners4: terrain id per corner name
    double probability = 1.0;
    std::string surface;                  // custom data ("stone", "water")
    std::vector<RectF> collision;         // in tile pixels
    bool animated = false;                // the manifest gave `anim`
    int anim_frames = 1;                  // the frames sit in this cell and the next ones to the right
    double anim_fps = 0.0;
    std::optional<Point> origin;          // the point drawn on the cell's centre (default: the image's centre)
};
struct Atlas {
    int id = 0;
    std::string name, role, image;
    int tile_w = 0, tile_h = 0, columns = 0, rows = 0;
    std::vector<Tile> tiles;
};
struct Terrain {
    int id = 0;
    std::string name, color;
};
struct TerrainSet {
    int id = 0;
    std::string mode;   // blob47, corners4, sides4
    std::vector<Terrain> terrains;
};
struct Stamp {
    std::string name;
    int w = 0, h = 0;
    bool solid = false;
    std::vector<TileRef> tiles;   // reading order
};
struct Tileset {
    std::string name;
    int tile_w = 0, tile_h = 0;
    std::string shape;   // square, isometric
    std::vector<TerrainSet> terrain_sets;
    std::vector<Atlas> atlases;
    std::vector<Stamp> stamps;
    std::string custom_data;
    const Atlas* atlas(int id) const;
    const Tile* tile(const TileRef& ref) const;
    const TerrainSet* terrain_set(int id) const;
};

// ---- map ----
struct MapCell {
    int x = 0, y = 0;   // cell coordinates
    TileRef tile;       // atlas -1: a terrain cell no tile fits (a warning at load, drawn as nothing)
    int flags = 0;      // 1 flip horizontally, 2 flip vertically, 4 transpose (first)
    int key = -1;       // terrain cells: the key cell_mask gave (the blob or sides mask, or the corner bits)
};
struct MapLayer {
    std::string name, kind;   // kind: tiles, terrain, stamps
    int terrain_set = 0, terrain = -1;
    double opacity = 1.0;
    // Placed tiles in draw order: a tiles layer as listed, a stamps layer expanded (tile j of a stamp at
    // (x + j % w, y + j / w), stamp by stamp), a terrain layer resolved and sorted by (y, x).
    std::vector<MapCell> cells;
};
struct MapObject {
    std::string asset;
    double x = 0, y = 0;   // pixels: where the asset's pivot sits
};
struct Map {
    std::string name, tileset;
    std::string shape;   // the tileset's: square, isometric
    int w = 0, h = 0, tile_w = 0, tile_h = 0;
    std::vector<MapLayer> layers;     // drawn first to last
    std::vector<MapObject> objects;   // draw sorted by y with the characters
};

// ---- font ----
struct Glyph {
    int id = 0, x = 0, y = 0, w = 0, h = 0, xoffset = 0, yoffset = 0, xadvance = 0, page = 0;
};
struct Font {
    std::string name, file, license;
    std::vector<std::string> pages;
    int line_height = 0, base = 0;
    double scale = 1.0;                // the pages, chars and metrics are ALREADY at this scale: draw them 1:1
    bool tint = true;                  // white ink that takes a colour
    std::vector<Glyph> chars;          // sorted by id
    std::map<std::pair<int, int>, int> kerning;
    const Glyph* glyph(int id) const;
    int kern(int first, int second) const;
};

// ---- ui_kit ----
struct UiPart {
    std::string name, role, image, state, control, glyph;
    int w = 0, h = 0;
    double scale = 1.0;                                 // the image and margins are ALREADY at it: draw 1:1
    std::optional<std::array<int, 4>> margins;          // 9-slice [left, top, right, bottom], image pixels
    std::optional<std::array<int, 2>> stretch_margin;   // a gauge's ends that never stretch
    std::optional<Point> hotspot;                       // a cursor's click point
};
struct UiKit {
    std::string name, role;
    std::vector<UiPart> parts;
    const UiPart* part(const std::string& part_name) const;
};

// ---- the extra kinds: loaded as data, the game object that uses one is the game's ----
struct BackgroundLayer {
    std::string name, image;
    int w = 0, h = 0;
    double vx = 0, vy = 0;      // px/s of the art
    std::string repeat = "none";   // none, x, y, xy: the image tiles seamlessly on those axes
    double wobble_px = 0;       // weather layers sway sideways by up to this
    double scale = 1.0;         // the whole-number scale the art is drawn at
};
struct Background {
    std::string name, role;
    std::vector<BackgroundLayer> layers;   // drawn first to last
};
struct Particles {
    std::string name, texture;   // a white mask, tinted by the emitter's colour steps
    nlohmann::json emitter;      // the emitter JSON as Dotwork writes it (amount, lifetime, one_shot, colors ...)
};
struct Transition {
    std::string name, image, transition;   // a greyscale rule image; transition: wipe, iris, spiral ...
    int w = 0, h = 0;
};
struct NormalMap {
    std::string name, image, target;   // target: the image it lights
    std::string convention = "opengl";   // green up
    int w = 0, h = 0;
};
struct Image {
    std::string name, role, image;
    int w = 0, h = 0;
    std::optional<Point> pivot;
};

// ---- one manifest ----
struct Pack {
    std::filesystem::path manifest;   // the .assets.json file
    std::filesystem::path base_dir;   // join(dirname(manifest), base): every path is relative to it
    std::string pack, version, generator;
    std::vector<AnimatedSprite> animated_sprites;
    std::vector<Sprite> sprites;
    std::vector<Icon> icons;
    std::vector<Portrait> portraits;
    std::vector<Tileset> tilesets;
    std::vector<Map> maps;
    std::vector<Font> fonts;
    std::vector<UiKit> ui_kits;
    std::vector<Background> backgrounds;
    std::vector<Particles> particles;
    std::vector<Transition> transitions;
    std::vector<NormalMap> normal_maps;
    std::vector<Image> images;
    std::vector<std::string> errors;     // the pack (or an asset) is broken; a broken asset is left out
    std::vector<std::string> warnings;   // unknown kinds and layer kinds, unresolved terrain cells

    bool ok() const { return errors.empty(); }
    std::filesystem::path resolve(const std::string& rel) const;   // base_dir / rel
    const AnimatedSprite* animated_sprite(const std::string& name) const;
    const Sprite* sprite(const std::string& name) const;
    const Tileset* tileset(const std::string& name) const;
    const Map* map(const std::string& name) const;
    const Font* font(const std::string& name) const;
    const UiKit* ui_kit(const std::string& name) const;
    const Background* background(const std::string& name) const;
    const Particles* particle_set(const std::string& name) const;
    const Transition* transition(const std::string& name) const;
    const NormalMap* normal_map(const std::string& name) const;
    const Image* image(const std::string& name) const;
};

// Reads a manifest file. Never throws: a file that is missing or not JSON gives a Pack with an error.
Pack load_manifest(const std::filesystem::path& path);
// The same from parsed JSON; manifest_path places `base` (the file need not exist).
Pack parse_manifest(const nlohmann::json& doc, const std::filesystem::path& manifest_path);
// Every <assets_dir>/dotwork/*.assets.json, sorted. Empty when the folder does not exist.
std::vector<std::filesystem::path> find_manifests(const std::filesystem::path& assets_dir);
// Problems with the files a loaded pack names: missing, not a PNG, a size other than the one declared, a frame
// rect or atlas grid outside its image. Empty when every file is there and fits (Dotwork's Godot verify, here).
std::vector<std::string> check_files(const Pack& pack);
// (width, height) from a PNG's header, without decoding it; nullopt when the file is missing or not a PNG.
std::optional<std::pair<int, int>> png_size(const std::filesystem::path& path);

// ---- autotiling (the spec's rules, ported: ASSET_MANIFEST.md "Autotiling and maps") ----
// Neighbour bits N, NE, E, SE, S, SW, W, NW = 1, 2, 4, ... 128 (y down).
constexpr std::array<std::array<int, 2>, 8> kNb8{{{0, -1}, {1, -1}, {1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0}, {-1, -1}}};
constexpr int kSidesOnly = 1 | 4 | 16 | 64;
constexpr int kCornersOnly = 2 | 8 | 32 | 128;
// A corner bit counts only when both sides next to it are set: 256 raw masks fold into the 47 blob masks.
int canon(int mask);
// The key a painted cell needs, from the painted cells of the same terrain: blob47 the canon mask, sides4 the four
// side bits, corners4 the four corner bits of the canon mask (a corner counts when all four cells meeting there
// are painted).
int cell_mask(const std::set<std::pair<int, int>>& painted, int x, int y, const std::string& mode = "blob47");
// The key a tileset tile answers to: its mask (blob47, sides4), or the sum of the corner bits whose corner holds
// the tile's own terrain (corners4; square top_left NW, top_right NE, bottom_right SE, bottom_left SW; isometric
// top NW, right NE, bottom SE, left SW). nullopt when it has neither (or its corners are not the shape's four).
std::optional<int> tile_key(const Tile& tile, const std::string& mode, const std::string& shape);
// The variant pick: Bob Jenkins' 6-shift 32-bit integer hash (shifts, adds, xors only; every step 32 bits), the
// cell's roll in [0, 1) from the cell and its layer's index in the map's layers list (coordinates wrap at 16 bits),
// and the pick: candidates [(weight, tile)] in atlas order, the one whose weight span holds roll * total.
std::uint32_t hash32(std::uint32_t k);
double cell_roll(int x, int y, int layer_index);
TileRef pick_variant(const std::vector<std::pair<double, TileRef>>& candidates, double roll);
// A terrain layer's cells -> placed tiles, sorted by (y, x): each cell's key is cell_mask's, its tile is picked
// among the layer's terrain's tiles with that key (atlas order) by probability with cell_roll(x, y, layer_index).
// A cell no tile fits keeps atlas -1.
std::vector<MapCell> resolve_terrain(const Tileset& tileset, int terrain_set, int terrain,
                                     const std::vector<std::pair<int, int>>& cells, int layer_index = 0);

// ---- placing tiles (the spec's "Placing tiles"; map pixels, y down, cell (0, 0) first) ----
// The centre of cell (x, y): square ((x + 0.5) w, (y + 0.5) h); isometric ((x - y + 1) w / 2, (x + y + 1) h / 2),
// Godot's diamond-down layout (x runs down-right, y down-left; cell (0, 0) of a 16x8 set sits at (8, 4)).
Point cell_centre(const std::string& shape, int x, int y, int tile_w, int tile_h);
// The point of a tile's image drawn on the cell's centre: its `origin`, else the atlas tile's centre.
Point tile_origin(const Tile& tile, const Atlas& atlas);
// Where a placed cell's image lands: its top-left in map pixels, the cell centre less the tile's origin. nullopt
// when the tileset has no such tile.
std::optional<Point> placed_corner(const Tileset& tileset, const Map& map, const MapCell& cell);

// ---- timing: one clip, played by each frame's duration ----
class ClipPlayer {
public:
    explicit ClipPlayer(const Clip* clip = nullptr) { play(clip); }
    void play(const Clip* clip);            // from the first frame
    void update(double dt);                 // seconds
    std::size_t frame() const { return index_; }
    bool finished() const { return done_; }   // a clip that does not loop, on its last frame
    const Clip* clip() const { return clip_; }

private:
    const Clip* clip_ = nullptr;
    std::size_t index_ = 0;
    double t_ = 0.0;   // seconds into the current frame
    bool done_ = false;
};

// ---- text: glyph quads from a font's chars ----
struct GlyphQuad {
    const Glyph* glyph = nullptr;
    double x = 0, y = 0;   // the glyph image's top-left, in font pixels from the text's top-left
};
// UTF-8 text -> glyph quads (xoffset, yoffset, xadvance, kerning; "\n" starts a line line_height lower).
// A code point the font lacks is skipped (*missing counts them when given).
std::vector<GlyphQuad> layout_text(const Font& font, const std::string& utf8, int* missing = nullptr);
double text_width(const Font& font, const std::string& utf8);   // the widest line's advance, font pixels

// ---- a tile's flags as SDL_RenderTextureRotated's flip and angle ----
struct TileTransform {
    int angle = 0;   // degrees clockwise: 0, 90, 180, 270
    bool flip_h = false;
    bool flip_v = false;
};
// flags: 1 flip horizontally, 2 flip vertically, 4 transpose (transpose first, then flip); SDL flips the
// image first, then turns it.
TileTransform tile_transform(int flags);

}  // namespace core::dotwork

// {{FOOTER}}
