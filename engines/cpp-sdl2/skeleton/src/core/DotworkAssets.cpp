// ---------------------------------------------------------------------------
// DotworkAssets.cpp
// Purpose : Implementation of core::dotwork (see DotworkAssets.hpp): the Dotwork asset manifest loader, the
//           terrain rule, clip timing, glyph layout and the file check.
// Usage   : core::dotwork::load_manifest(path); see the header.
// Notes   : nlohmann-json throws on a missing field or a wrong type; each asset is read inside its own try, so a
//           broken asset becomes one error naming kind/name and the rest of the pack still loads.
//           Maps are read after every tileset (a map needs its tileset), whatever the order in the file.
//
// Pseudocode (parse_manifest):
//   format and major version -> base_dir -> for each asset: known kind -> read it (paths checked)
//     | unknown kind -> one warning per kind
//   -> for each map: its tileset -> tiles layers as is, stamps layers expanded, terrain layers through
//      resolve_terrain (cell_mask -> key -> the candidates with that key -> pick_variant with cell_roll)
//   -> portraits' animations and maps' objects must name assets of the pack
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): corners4 keys, the variant
//           pick, stamps layers, cell centres and placement, the extra kinds read and checked
// ---------------------------------------------------------------------------
#include "core/DotworkAssets.hpp"

#include <algorithm>
#include <cstdint>
#include <exception>
#include <fstream>
#include <stdexcept>
#include <system_error>

#include "core/AtomicFile.hpp"

namespace core::dotwork {

using nlohmann::json;
namespace fs = std::filesystem;

namespace {

// ---- Tunables ----
constexpr unsigned char kPngMagic[8] = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'};
// A corners4 tile's corner names and the mask bit of the neighbour across each (the spec's table): on a diamond
// the top corner touches the cell up the screen, which is NW in map coordinates.
using CornerBits = std::array<std::pair<const char*, int>, 4>;
constexpr CornerBits kSquareCorners{{{"top_left", 128}, {"top_right", 2}, {"bottom_right", 8}, {"bottom_left", 32}}};
constexpr CornerBits kIsoCorners{{{"top", 128}, {"right", 2}, {"bottom", 8}, {"left", 32}}};
constexpr double kTwo32 = 4294967296.0;   // 2^32: hash32's range, the roll divides by it

// ---- reading helpers (each throws json::exception on a missing field or a wrong type) ----
template <typename T>
T opt(const json& j, const char* key, T fallback) {
    const auto it = j.find(key);
    return it == j.end() || it->is_null() ? fallback : it->get<T>();
}

Rect rect_of(const json& j) {
    return {j.at(0).get<int>(), j.at(1).get<int>(), j.at(2).get<int>(), j.at(3).get<int>()};
}
RectF rectf_of(const json& j) {
    return {j.at(0).get<double>(), j.at(1).get<double>(), j.at(2).get<double>(), j.at(3).get<double>()};
}
Point point_of(const json& j) {
    return {j.at(0).get<double>(), j.at(1).get<double>()};
}
std::vector<RectF> collision_of(const json& j) {
    std::vector<RectF> out;
    const auto it = j.find("collision");
    if (it != j.end() && it->is_array()) {
        for (const auto& s : *it) {
            out.push_back(rectf_of(s.at("rect")));
        }
    }
    return out;
}

// A manifest path: relative, forward slashes, no "..", no drive (the spec's rule). Throws when it breaks it.
std::string safe_path(const std::string& p, const std::string& what) {
    const bool bad = p.empty() || p.front() == '/' || p.find('\\') != std::string::npos ||
                     p.find(':') != std::string::npos || p == ".." || p.rfind("../", 0) == 0 ||
                     p.find("/../") != std::string::npos ||
                     (p.size() >= 3 && p.compare(p.size() - 3, 3, "/..") == 0);
    if (bad) {
        throw std::runtime_error(what + " \"" + p + "\" is not a relative path inside the pack");
    }
    return p;
}
std::string path_of(const json& j, const char* key) {
    return safe_path(j.at(key).get<std::string>(), key);
}

int major_of(const std::string& version) {
    try {
        std::size_t used = 0;
        const int major = std::stoi(version, &used);
        return used > 0 && used < version.size() && version[used] == '.' ? major : -1;
    } catch (const std::exception&) {
        return -1;
    }
}

// ---- one reader per core kind ----
AnimatedSprite read_animated_sprite(const json& a) {
    AnimatedSprite s;
    s.name = a.at("name").get<std::string>();
    s.role = opt<std::string>(a, "role", "");
    s.blend = opt<std::string>(a, "blend", "normal") == "add" ? Blend::Add : Blend::Normal;
    for (const auto& c : a.at("clips")) {
        Clip clip;
        clip.name = c.at("name").get<std::string>();
        clip.fps = c.at("fps").get<double>();
        clip.loop = c.at("loop").get<bool>();
        const json& fs_ = c.at("frame_size");
        clip.frame_w = fs_.at(0).get<int>();
        clip.frame_h = fs_.at(1).get<int>();
        clip.pivot = point_of(c.at("pivot"));
        if (c.contains("sheet") && !c.at("sheet").is_null()) {
            clip.sheet = path_of(c, "sheet");
        }
        for (const auto& f : c.at("frames")) {
            Frame frame{path_of(f, "file"), rect_of(f.at("rect")), f.at("duration").get<double>()};
            clip.length += frame.seconds;
            clip.frames.push_back(std::move(frame));
        }
        if (clip.frames.empty()) {
            throw std::runtime_error("clip " + clip.name + " has no frames");
        }
        s.clips.push_back(std::move(clip));
    }
    const auto dirs = a.find("directions");
    if (dirs != a.end() && dirs->is_object()) {
        for (const auto& [action, table] : dirs->items()) {
            for (const auto& [dir, clip_name] : table.items()) {
                s.directions[action][dir] = clip_name.get<std::string>();
            }
        }
    }
    return s;
}

Sprite read_sprite(const json& a) {
    Sprite s;
    s.name = a.at("name").get<std::string>();
    s.role = opt<std::string>(a, "role", "");
    s.image = path_of(a, "image");
    s.w = a.at("size").at(0).get<int>();
    s.h = a.at("size").at(1).get<int>();
    s.pivot = point_of(a.at("pivot"));
    if (a.contains("content_rect")) {
        s.content_rect = rect_of(a.at("content_rect"));
    }
    s.collision = collision_of(a);
    const auto sh = a.find("shadow");
    if (sh != a.end() && sh->is_object()) {
        s.shadow_image = path_of(*sh, "image");
        s.shadow_offset = point_of(sh->at("offset"));
    }
    return s;
}

Icon read_icon(const json& a) {
    Icon icon;
    icon.name = a.at("name").get<std::string>();
    for (const auto& s : a.at("sizes")) {
        icon.sizes.push_back({s.at("size").get<int>(), path_of(s, "image")});
    }
    std::sort(icon.sizes.begin(), icon.sizes.end(), [](const IconSize& l, const IconSize& r) { return l.size < r.size; });
    return icon;
}

Portrait read_portrait(const json& a) {
    Portrait p;
    p.name = a.at("name").get<std::string>();
    p.w = a.at("size").at(0).get<int>();
    p.h = a.at("size").at(1).get<int>();
    for (const auto& e : a.at("expressions")) {
        p.expressions.push_back({e.at("name").get<std::string>(), path_of(e, "image")});
    }
    p.animation = opt<std::string>(a, "animation", "");
    return p;
}

Tileset read_tileset(const json& a) {
    Tileset ts;
    ts.name = a.at("name").get<std::string>();
    ts.tile_w = a.at("tile_size").at(0).get<int>();
    ts.tile_h = a.at("tile_size").at(1).get<int>();
    ts.shape = opt<std::string>(a, "shape", "square");
    ts.custom_data = opt<std::string>(a, "custom_data", "");
    for (const auto& s : a.at("terrain_sets")) {
        TerrainSet set{s.at("id").get<int>(), s.at("mode").get<std::string>(), {}};
        for (const auto& t : s.at("terrains")) {
            set.terrains.push_back({t.at("id").get<int>(), t.at("name").get<std::string>(), opt<std::string>(t, "color", "")});
        }
        ts.terrain_sets.push_back(std::move(set));
    }
    for (const auto& at : a.at("atlases")) {
        Atlas atlas;
        atlas.id = at.at("id").get<int>();
        atlas.name = opt<std::string>(at, "name", "");
        atlas.role = opt<std::string>(at, "role", "");
        atlas.image = path_of(at, "image");
        atlas.tile_w = at.at("tile_size").at(0).get<int>();
        atlas.tile_h = at.at("tile_size").at(1).get<int>();
        atlas.columns = at.at("columns").get<int>();
        atlas.rows = at.at("rows").get<int>();
        for (const auto& t : at.at("tiles")) {
            Tile tile;
            tile.col = t.at("col").get<int>();
            tile.row = t.at("row").get<int>();
            if (t.contains("terrain")) {
                tile.terrain = t.at("terrain").get<int>();
                tile.terrain_set = opt<int>(t, "terrain_set", 0);
            }
            if (t.contains("mask") && !t.at("mask").is_null()) {
                tile.mask = t.at("mask").get<int>();
            }
            const auto corners = t.find("corners");
            if (corners != t.end() && corners->is_object()) {
                for (const auto& [corner, id] : corners->items()) {
                    tile.corners[corner] = id.get<int>();
                }
            }
            tile.probability = opt<double>(t, "probability", 1.0);
            tile.surface = opt<std::string>(t, "surface", "");
            tile.collision = collision_of(t);
            const auto anim = t.find("anim");
            if (anim != t.end() && anim->is_object()) {
                tile.animated = true;
                tile.anim_frames = anim->at("frames").get<int>();
                tile.anim_fps = anim->at("fps").get<double>();
            }
            if (t.contains("origin") && !t.at("origin").is_null()) {
                tile.origin = point_of(t.at("origin"));
            }
            atlas.tiles.push_back(std::move(tile));
        }
        ts.atlases.push_back(std::move(atlas));
    }
    const auto stamps = a.find("stamps");
    if (stamps != a.end() && stamps->is_array()) {
        for (const auto& s : *stamps) {
            Stamp st;
            st.name = s.at("name").get<std::string>();
            st.w = s.at("size").at(0).get<int>();
            st.h = s.at("size").at(1).get<int>();
            st.solid = opt<bool>(s, "solid", false);
            for (const auto& r : s.at("tiles")) {
                st.tiles.push_back({r.at(0).get<int>(), r.at(1).get<int>(), r.at(2).get<int>()});
            }
            ts.stamps.push_back(std::move(st));
        }
    }
    return ts;
}

std::string tile_text(const TileRef& t) {
    return "[" + std::to_string(t.atlas) + ", " + std::to_string(t.col) + ", " + std::to_string(t.row) + "]";
}

// A map, its layers placed: tiles layers as listed, stamps layers expanded, terrain layers resolved against the
// tileset. A terrain layer's roll uses the layer's index in the manifest's list (skipped layers count too, as the
// reference loader enumerates them).
Map read_map(const json& a, const Pack& pack, std::vector<std::string>& warnings) {
    Map m;
    m.name = a.at("name").get<std::string>();
    m.tileset = a.at("tileset").get<std::string>();
    m.w = a.at("size").at(0).get<int>();
    m.h = a.at("size").at(1).get<int>();
    m.tile_w = a.at("tile_size").at(0).get<int>();
    m.tile_h = a.at("tile_size").at(1).get<int>();
    const Tileset* ts = pack.tileset(m.tileset);
    if (!ts) {
        throw std::runtime_error("tileset \"" + m.tileset + "\" is not in this manifest");
    }
    m.shape = ts->shape;
    const auto need_tile = [&](const std::string& layer_name, const TileRef& ref) {
        if (!ts->tile(ref)) {
            throw std::runtime_error("layer " + layer_name + " names tile " + tile_text(ref) + ", which tileset " +
                                     ts->name + " does not have");
        }
    };
    int layer_index = -1;
    for (const auto& L : a.at("layers")) {
        ++layer_index;
        MapLayer layer;
        layer.name = L.at("name").get<std::string>();
        layer.kind = L.at("kind").get<std::string>();
        layer.opacity = opt<double>(L, "opacity", 1.0);
        if (layer.kind == "tiles") {
            for (const auto& c : L.at("cells")) {
                MapCell cell{c.at(0).get<int>(), c.at(1).get<int>(), {c.at(2).get<int>(), c.at(3).get<int>(), c.at(4).get<int>()},
                             c.size() > 5 ? c.at(5).get<int>() : 0, -1};
                need_tile(layer.name, cell.tile);
                layer.cells.push_back(cell);
            }
        } else if (layer.kind == "stamps") {
            for (const auto& c : L.at("cells")) {
                const int x = c.at(0).get<int>(), y = c.at(1).get<int>(), index = c.at(2).get<int>();
                if (index < 0 || index >= static_cast<int>(ts->stamps.size())) {
                    throw std::runtime_error("layer " + layer.name + " places stamp " + std::to_string(index) +
                                             ", but tileset " + ts->name + " has " + std::to_string(ts->stamps.size()));
                }
                const Stamp& st = ts->stamps[static_cast<std::size_t>(index)];
                const int sw = std::max(1, st.w);
                for (std::size_t j = 0; j < st.tiles.size(); ++j) {
                    const int jj = static_cast<int>(j);
                    MapCell cell{x + jj % sw, y + jj / sw, st.tiles[j], 0, -1};
                    need_tile(layer.name, cell.tile);
                    layer.cells.push_back(cell);
                }
            }
        } else if (layer.kind == "terrain") {
            layer.terrain_set = opt<int>(L, "terrain_set", 0);
            layer.terrain = L.at("terrain").get<int>();
            if (!ts->terrain_set(layer.terrain_set)) {
                throw std::runtime_error("layer " + layer.name + ": tileset " + ts->name + " has no terrain set " +
                                         std::to_string(layer.terrain_set));
            }
            std::vector<std::pair<int, int>> painted;
            for (const auto& c : L.at("cells")) {
                painted.emplace_back(c.at(0).get<int>(), c.at(1).get<int>());
            }
            layer.cells = resolve_terrain(*ts, layer.terrain_set, layer.terrain, painted, layer_index);
            const auto unresolved = std::count_if(layer.cells.begin(), layer.cells.end(),
                                                  [](const MapCell& c) { return c.tile.atlas < 0; });
            if (unresolved > 0) {
                warnings.push_back("map/" + m.name + " layer " + layer.name + ": " + std::to_string(unresolved) +
                                   " terrain cells have no tile with their key (drawn as nothing)");
            }
        } else {
            warnings.push_back("map/" + m.name + " layer " + layer.name + ": unknown layer kind \"" + layer.kind +
                               "\", skipped");
            continue;
        }
        m.layers.push_back(std::move(layer));
    }
    const auto objects = a.find("objects");
    if (objects != a.end() && objects->is_array()) {
        for (const auto& o : *objects) {
            m.objects.push_back({o.at("asset").get<std::string>(), o.at("x").get<double>(), o.at("y").get<double>()});
        }
    }
    return m;
}

Font read_font(const json& a) {
    Font f;
    f.name = a.at("name").get<std::string>();
    f.file = path_of(a, "file");
    for (std::size_t i = 0; i < a.at("pages").size(); ++i) {
        f.pages.push_back(safe_path(a.at("pages").at(i).get<std::string>(), "page"));
    }
    f.line_height = a.at("line_height").get<int>();
    f.base = a.at("base").get<int>();
    f.scale = opt<double>(a, "scale", 1.0);
    f.tint = opt<bool>(a, "tint", true);
    if (a.contains("license") && !a.at("license").is_null()) {
        f.license = path_of(a, "license");
    }
    for (const auto& c : a.at("chars")) {
        Glyph g{c.at(0).get<int>(), c.at(1).get<int>(), c.at(2).get<int>(), c.at(3).get<int>(), c.at(4).get<int>(),
                c.at(5).get<int>(), c.at(6).get<int>(), c.at(7).get<int>(), c.at(8).get<int>()};
        if (g.page < 0 || g.page >= static_cast<int>(f.pages.size())) {
            throw std::runtime_error("char " + std::to_string(g.id) + " is on page " + std::to_string(g.page) +
                                     "; the font has " + std::to_string(f.pages.size()));
        }
        f.chars.push_back(g);
    }
    std::sort(f.chars.begin(), f.chars.end(), [](const Glyph& l, const Glyph& r) { return l.id < r.id; });
    const auto kern = a.find("kerning");
    if (kern != a.end() && kern->is_array()) {
        for (const auto& k : *kern) {
            f.kerning[{k.at(0).get<int>(), k.at(1).get<int>()}] = k.at(2).get<int>();
        }
    }
    return f;
}

UiKit read_ui_kit(const json& a) {
    UiKit kit;
    kit.name = a.at("name").get<std::string>();
    kit.role = opt<std::string>(a, "role", "");
    for (const auto& p : a.at("parts")) {
        UiPart part;
        part.name = p.at("name").get<std::string>();
        part.role = opt<std::string>(p, "role", "");
        part.image = path_of(p, "image");
        part.w = p.at("size").at(0).get<int>();
        part.h = p.at("size").at(1).get<int>();
        part.scale = opt<double>(p, "scale", 1.0);
        part.state = opt<std::string>(p, "state", "");
        part.control = opt<std::string>(p, "control", "");
        part.glyph = opt<std::string>(p, "glyph", "");
        if (p.contains("margins") && !p.at("margins").is_null()) {
            const json& m = p.at("margins");
            part.margins = std::array<int, 4>{m.at(0).get<int>(), m.at(1).get<int>(), m.at(2).get<int>(), m.at(3).get<int>()};
        }
        if (p.contains("stretch_margin") && !p.at("stretch_margin").is_null()) {
            const json& m = p.at("stretch_margin");
            part.stretch_margin = std::array<int, 2>{m.at(0).get<int>(), m.at(1).get<int>()};
        }
        if (p.contains("hotspot") && !p.at("hotspot").is_null()) {
            part.hotspot = point_of(p.at("hotspot"));
        }
        kit.parts.push_back(std::move(part));
    }
    return kit;
}

// ---- the extra kinds ----
Background read_background(const json& a) {
    Background b;
    b.name = a.at("name").get<std::string>();
    b.role = opt<std::string>(a, "role", "");
    for (const auto& L : a.at("layers")) {
        BackgroundLayer layer;
        layer.name = opt<std::string>(L, "name", "");
        layer.image = path_of(L, "image");
        layer.w = L.at("size").at(0).get<int>();
        layer.h = L.at("size").at(1).get<int>();
        layer.vx = L.at("velocity").at(0).get<double>();
        layer.vy = L.at("velocity").at(1).get<double>();
        layer.repeat = opt<std::string>(L, "repeat", "none");
        layer.wobble_px = opt<double>(L, "wobble_px", 0.0);
        layer.scale = opt<double>(L, "scale", 1.0);
        b.layers.push_back(std::move(layer));
    }
    return b;
}

Particles read_particles(const json& a) {
    Particles p;
    p.name = a.at("name").get<std::string>();
    p.texture = path_of(a, "texture");
    p.emitter = a.contains("emitter") ? a.at("emitter") : json::object();
    return p;
}

Transition read_transition(const json& a) {
    Transition t;
    t.name = a.at("name").get<std::string>();
    t.image = path_of(a, "image");
    t.w = a.at("size").at(0).get<int>();
    t.h = a.at("size").at(1).get<int>();
    t.transition = opt<std::string>(a, "transition", "");
    return t;
}

NormalMap read_normal_map(const json& a) {
    NormalMap n;
    n.name = a.at("name").get<std::string>();
    n.image = path_of(a, "image");
    if (a.contains("size") && a.at("size").is_array()) {   // the spec's normal_map row names no size
        n.w = a.at("size").at(0).get<int>();
        n.h = a.at("size").at(1).get<int>();
    }
    n.target = path_of(a, "target");
    n.convention = opt<std::string>(a, "convention", "opengl");
    return n;
}

Image read_image(const json& a) {
    Image i;
    i.name = a.at("name").get<std::string>();
    i.role = opt<std::string>(a, "role", "");
    i.image = path_of(a, "image");
    i.w = a.at("size").at(0).get<int>();
    i.h = a.at("size").at(1).get<int>();
    if (a.contains("pivot") && !a.at("pivot").is_null()) {
        i.pivot = point_of(a.at("pivot"));
    }
    return i;
}

template <typename T>
const T* by_name(const std::vector<T>& items, const std::string& name) {
    for (const auto& item : items) {
        if (item.name == name) {
            return &item;
        }
    }
    return nullptr;
}

// One UTF-8 code point from s at i (i moves past it); U+FFFD for a broken sequence.
std::uint32_t next_code_point(const std::string& s, std::size_t& i) {
    const auto byte = [&](std::size_t k) { return static_cast<unsigned char>(s[k]); };
    const unsigned char c = byte(i++);
    int extra = c < 0x80 ? 0 : (c >> 5) == 0x6 ? 1 : (c >> 4) == 0xE ? 2 : (c >> 3) == 0x1E ? 3 : -1;
    if (extra < 0) {
        return 0xFFFD;
    }
    std::uint32_t cp = extra == 0 ? c : extra == 1 ? (c & 0x1Fu) : extra == 2 ? (c & 0x0Fu) : (c & 0x07u);
    for (; extra > 0; --extra) {
        if (i >= s.size() || (byte(i) & 0xC0) != 0x80) {
            return 0xFFFD;
        }
        cp = (cp << 6) | (byte(i++) & 0x3Fu);
    }
    return cp;
}

}  // namespace

// ---- lookups ----
const Clip* AnimatedSprite::clip(const std::string& clip_name) const { return by_name(clips, clip_name); }

const Clip* AnimatedSprite::directed(const std::string& action, const std::string& dir) const {
    const auto a = directions.find(action);
    if (a == directions.end()) {
        return nullptr;
    }
    const auto d = a->second.find(dir);
    return d == a->second.end() ? nullptr : clip(d->second);
}

const Atlas* Tileset::atlas(int id) const {
    for (const auto& a : atlases) {
        if (a.id == id) {
            return &a;
        }
    }
    return nullptr;
}

const Tile* Tileset::tile(const TileRef& ref) const {
    const Atlas* a = atlas(ref.atlas);
    if (!a) {
        return nullptr;
    }
    for (const auto& t : a->tiles) {
        if (t.col == ref.col && t.row == ref.row) {
            return &t;
        }
    }
    return nullptr;
}

const TerrainSet* Tileset::terrain_set(int id) const {
    for (const auto& s : terrain_sets) {
        if (s.id == id) {
            return &s;
        }
    }
    return nullptr;
}

const Glyph* Font::glyph(int id) const {
    const auto it = std::lower_bound(chars.begin(), chars.end(), id, [](const Glyph& g, int v) { return g.id < v; });
    return it != chars.end() && it->id == id ? &*it : nullptr;
}

int Font::kern(int first, int second) const {
    const auto it = kerning.find({first, second});
    return it == kerning.end() ? 0 : it->second;
}

const UiPart* UiKit::part(const std::string& part_name) const { return by_name(parts, part_name); }

fs::path Pack::resolve(const std::string& rel) const { return base_dir / path_from_utf8(rel); }
const AnimatedSprite* Pack::animated_sprite(const std::string& name) const { return by_name(animated_sprites, name); }
const Sprite* Pack::sprite(const std::string& name) const { return by_name(sprites, name); }
const Tileset* Pack::tileset(const std::string& name) const { return by_name(tilesets, name); }
const Map* Pack::map(const std::string& name) const { return by_name(maps, name); }
const Font* Pack::font(const std::string& name) const { return by_name(fonts, name); }
const UiKit* Pack::ui_kit(const std::string& name) const { return by_name(ui_kits, name); }
const Background* Pack::background(const std::string& name) const { return by_name(backgrounds, name); }
const Particles* Pack::particle_set(const std::string& name) const { return by_name(particles, name); }
const Transition* Pack::transition(const std::string& name) const { return by_name(transitions, name); }
const NormalMap* Pack::normal_map(const std::string& name) const { return by_name(normal_maps, name); }
const Image* Pack::image(const std::string& name) const { return by_name(images, name); }

// ---- loading ----
Pack parse_manifest(const json& doc, const fs::path& manifest_path) {
    Pack pack;
    pack.manifest = manifest_path;
    const std::string where = path_to_utf8(manifest_path);
    try {
        if (!doc.is_object() || opt<std::string>(doc, "format", "") != kFormat) {
            pack.errors.push_back(where + ": not a Dotwork asset manifest (format is not \"" + kFormat + "\")");
            return pack;
        }
        pack.version = doc.at("version").get<std::string>();
        pack.pack = opt<std::string>(doc, "pack", "");
        pack.generator = opt<std::string>(doc, "generator", "");
        const int major = major_of(pack.version);
        if (major != kSpecMajor) {
            pack.errors.push_back(where + ": manifest version " + pack.version + " is not readable by this importer (spec " +
                                  std::to_string(kSpecMajor) + ".x); update the importer or rebuild the pack");
            return pack;
        }
        pack.base_dir = (manifest_path.parent_path() / path_from_utf8(opt<std::string>(doc, "base", "."))).lexically_normal();
        if (!doc.contains("assets") || !doc.at("assets").is_array()) {
            pack.errors.push_back(where + ": no \"assets\" list");
            return pack;
        }
    } catch (const json::exception& e) {
        pack.errors.push_back(where + ": " + e.what());
        return pack;
    }

    // Every asset but maps; maps second, once every tileset is in.
    std::set<std::string> skipped;
    std::vector<const json*> maps;
    for (const auto& a : doc.at("assets")) {   // a reference into doc: maps keeps pointers to its items
        const std::string kind = opt<std::string>(a, "kind", "");
        const std::string name = opt<std::string>(a, "name", "?");
        try {
            if (kind == "animated_sprite") {
                pack.animated_sprites.push_back(read_animated_sprite(a));
            } else if (kind == "sprite") {
                pack.sprites.push_back(read_sprite(a));
            } else if (kind == "icon") {
                pack.icons.push_back(read_icon(a));
            } else if (kind == "portrait") {
                pack.portraits.push_back(read_portrait(a));
            } else if (kind == "tileset") {
                pack.tilesets.push_back(read_tileset(a));
            } else if (kind == "map") {
                maps.push_back(&a);
            } else if (kind == "font") {
                pack.fonts.push_back(read_font(a));
            } else if (kind == "ui_kit") {
                pack.ui_kits.push_back(read_ui_kit(a));
            } else if (kind == "background") {
                pack.backgrounds.push_back(read_background(a));
            } else if (kind == "particles") {
                pack.particles.push_back(read_particles(a));
            } else if (kind == "transition") {
                pack.transitions.push_back(read_transition(a));
            } else if (kind == "normal_map") {
                pack.normal_maps.push_back(read_normal_map(a));
            } else if (kind == "image") {
                pack.images.push_back(read_image(a));
            } else if (skipped.insert(kind).second) {
                pack.warnings.push_back(where + ": unknown kind \"" + kind + "\" skipped (this importer does not know it)");
            }
        } catch (const std::exception& e) {
            pack.errors.push_back(where + ": " + kind + "/" + name + ": " + e.what());
        }
    }
    for (const json* a : maps) {
        try {
            pack.maps.push_back(read_map(*a, pack, pack.warnings));
        } catch (const std::exception& e) {
            pack.errors.push_back(where + ": map/" + opt<std::string>(*a, "name", "?") + ": " + e.what());
        }
    }

    // Cross-references: a portrait's animation, a map's objects
    for (const auto& p : pack.portraits) {
        if (!p.animation.empty() && !pack.animated_sprite(p.animation)) {
            pack.errors.push_back(where + ": portrait/" + p.name + ": animation \"" + p.animation + "\" is not in this manifest");
        }
    }
    for (const auto& m : pack.maps) {
        for (const auto& o : m.objects) {
            if (!pack.sprite(o.asset) && !pack.animated_sprite(o.asset)) {
                pack.errors.push_back(where + ": map/" + m.name + ": object \"" + o.asset + "\" is not an asset in this manifest");
            }
        }
    }
    return pack;
}

Pack load_manifest(const fs::path& path) {
    std::string error;
    const auto text = read_file(path, &error);
    if (!text) {
        Pack pack;
        pack.manifest = path;
        pack.errors.push_back(path_to_utf8(path) + ": " + (error.empty() ? std::string("not found") : error));
        return pack;
    }
    json doc;
    try {
        doc = json::parse(*text);
    } catch (const json::exception& e) {
        Pack pack;
        pack.manifest = path;
        pack.errors.push_back(path_to_utf8(path) + ": not valid JSON: " + e.what());
        return pack;
    }
    return parse_manifest(doc, path);
}

std::vector<fs::path> find_manifests(const fs::path& assets_dir) {
    std::vector<fs::path> out;
    std::error_code ec;
    const fs::path dir = assets_dir / kManifestDir;
    if (!fs::is_directory(dir, ec)) {
        return out;
    }
    const std::string suffix = kManifestSuffix;
    for (const auto& entry : fs::directory_iterator(dir, ec)) {
        const std::string name = path_to_utf8(entry.path().filename());
        if (entry.is_regular_file(ec) && name.size() > suffix.size() &&
            name.compare(name.size() - suffix.size(), suffix.size(), suffix) == 0) {
            out.push_back(entry.path());
        }
    }
    std::sort(out.begin(), out.end());
    return out;
}

std::optional<std::pair<int, int>> png_size(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    unsigned char head[24] = {};
    if (!in.read(reinterpret_cast<char*>(head), sizeof head)) {
        return std::nullopt;
    }
    if (!std::equal(std::begin(kPngMagic), std::end(kPngMagic), head) || head[12] != 'I' || head[13] != 'H' ||
        head[14] != 'D' || head[15] != 'R') {
        return std::nullopt;
    }
    const auto be32 = [&](int at) {
        return static_cast<int>((static_cast<std::uint32_t>(head[at]) << 24) | (static_cast<std::uint32_t>(head[at + 1]) << 16) |
                                (static_cast<std::uint32_t>(head[at + 2]) << 8) | static_cast<std::uint32_t>(head[at + 3]));
    };
    return std::make_pair(be32(16), be32(20));
}

std::vector<std::string> check_files(const Pack& pack) {
    std::vector<std::string> out;
    std::error_code ec;
    // A PNG that must exist, be a PNG and (when given) have this size; returns its size.
    const auto png = [&](const std::string& rel, const std::string& who, int w = 0, int h = 0) {
        const fs::path p = pack.resolve(rel);
        if (!fs::is_regular_file(p, ec)) {
            out.push_back(who + ": " + rel + " is missing");
            return std::optional<std::pair<int, int>>();
        }
        const auto size = png_size(p);
        if (!size) {
            out.push_back(who + ": " + rel + " is not a PNG");
        } else if (w > 0 && (size->first != w || size->second != h)) {
            out.push_back(who + ": " + rel + " is " + std::to_string(size->first) + "x" + std::to_string(size->second) +
                          ", the manifest says " + std::to_string(w) + "x" + std::to_string(h));
        }
        return size;
    };
    const auto inside = [](const Rect& r, const std::pair<int, int>& size) {
        return r.x >= 0 && r.y >= 0 && r.w > 0 && r.h > 0 && r.x + r.w <= size.first && r.y + r.h <= size.second;
    };
    for (const auto& a : pack.animated_sprites) {
        for (const auto& c : a.clips) {
            const std::string who = "animated_sprite/" + a.name + " clip " + c.name;
            const auto sheet = c.sheet.empty() ? std::nullopt : png(c.sheet, who);
            for (std::size_t i = 0; i < c.frames.size(); ++i) {
                const auto own = png(c.frames[i].file, who);
                const auto& size = c.sheet.empty() ? own : sheet;
                if (size && !inside(c.frames[i].rect, *size)) {
                    out.push_back(who + ": frame " + std::to_string(i) + "'s rect is outside " + c.texture_of(i));
                }
            }
        }
    }
    for (const auto& s : pack.sprites) {
        png(s.image, "sprite/" + s.name, s.w, s.h);
        if (!s.shadow_image.empty()) {
            png(s.shadow_image, "sprite/" + s.name + " shadow");
        }
    }
    for (const auto& i : pack.icons) {
        for (const auto& s : i.sizes) {
            png(s.image, "icon/" + i.name, s.size, s.size);
        }
    }
    for (const auto& p : pack.portraits) {
        for (const auto& e : p.expressions) {
            png(e.image, "portrait/" + p.name + " " + e.name, p.w, p.h);
        }
    }
    for (const auto& t : pack.tilesets) {
        for (const auto& at : t.atlases) {
            const std::string who = "tileset/" + t.name + " atlas " + at.name;
            const auto size = png(at.image, who);
            if (size && (at.columns * at.tile_w > size->first || at.rows * at.tile_h > size->second)) {
                out.push_back(who + ": " + std::to_string(at.columns) + "x" + std::to_string(at.rows) + " tiles of " +
                              std::to_string(at.tile_w) + "x" + std::to_string(at.tile_h) + " do not fit " + at.image);
            }
        }
    }
    for (const auto& f : pack.fonts) {
        if (!fs::is_regular_file(pack.resolve(f.file), ec)) {
            out.push_back("font/" + f.name + ": " + f.file + " is missing");
        }
        for (const auto& p : f.pages) {
            png(p, "font/" + f.name);
        }
        if (!f.license.empty() && !fs::is_regular_file(pack.resolve(f.license), ec)) {
            out.push_back("font/" + f.name + ": licence " + f.license + " is missing");
        }
    }
    for (const auto& k : pack.ui_kits) {
        for (const auto& p : k.parts) {
            png(p.image, "ui_kit/" + k.name + " " + p.name, p.w, p.h);
        }
    }
    for (const auto& b : pack.backgrounds) {
        for (const auto& L : b.layers) {
            png(L.image, "background/" + b.name + (L.name.empty() ? "" : " " + L.name), L.w, L.h);
        }
    }
    for (const auto& p : pack.particles) {
        png(p.texture, "particles/" + p.name);
    }
    for (const auto& t : pack.transitions) {
        png(t.image, "transition/" + t.name, t.w, t.h);
    }
    for (const auto& n : pack.normal_maps) {
        png(n.image, "normal_map/" + n.name, n.w, n.h);
        png(n.target, "normal_map/" + n.name + " target");
    }
    for (const auto& i : pack.images) {
        png(i.image, "image/" + i.name, i.w, i.h);
    }
    return out;
}

// ---- autotiling ----
int canon(int mask) {
    for (int c : {1, 3, 5, 7}) {   // NE, SE, SW, NW
        if (!(((mask >> ((c + 7) % 8)) & 1) && ((mask >> ((c + 1) % 8)) & 1))) {
            mask &= ~(1 << c);
        }
    }
    return mask;
}

int cell_mask(const std::set<std::pair<int, int>>& painted, int x, int y, const std::string& mode) {
    int m = 0;
    for (std::size_t b = 0; b < kNb8.size(); ++b) {
        if (painted.count({x + kNb8[b][0], y + kNb8[b][1]})) {
            m |= 1 << b;
        }
    }
    if (mode == "sides4") {
        return m & kSidesOnly;
    }
    if (mode == "corners4") {
        return canon(m) & kCornersOnly;
    }
    return canon(m);
}

std::optional<int> tile_key(const Tile& tile, const std::string& mode, const std::string& shape) {
    if (mode == "blob47" || mode == "sides4") {
        return tile.mask;
    }
    if (mode != "corners4" || tile.corners.empty()) {
        return std::nullopt;
    }
    const CornerBits& names = shape == "isometric" ? kIsoCorners : kSquareCorners;
    if (tile.corners.size() != names.size()) {   // not the shape's four corners: no key
        return std::nullopt;
    }
    int key = 0;
    for (const auto& [name, bit] : names) {
        const auto it = tile.corners.find(name);
        if (it == tile.corners.end()) {
            return std::nullopt;
        }
        if (it->second == tile.terrain) {
            key |= bit;
        }
    }
    return key;
}

std::uint32_t hash32(std::uint32_t k) {
    // Bob Jenkins' 6-shift integer hash, as the spec writes it; uint32_t arithmetic wraps at 32 bits by itself
    k = k + 0x7ED55D16u + (k << 12);
    k = k ^ 0xC761C23Cu ^ (k >> 19);
    k = k + 0x165667B1u + (k << 5);
    k = (k + 0xD3A2646Cu) ^ (k << 9);
    k = k + 0xFD7046C5u + (k << 3);
    k = k ^ 0xB55A4F09u ^ (k >> 16);
    return k;
}

double cell_roll(int x, int y, int layer_index) {
    // Coordinates wrap at 16 bits (unsigned first: a negative int shifted is undefined in C++)
    const std::uint32_t ux = static_cast<std::uint32_t>(x) & 0xFFFFu;
    const std::uint32_t uy = static_cast<std::uint32_t>(y) & 0xFFFFu;
    const std::uint32_t cell = hash32((ux << 16) | uy);
    return hash32(cell + static_cast<std::uint32_t>(layer_index)) / kTwo32;
}

TileRef pick_variant(const std::vector<std::pair<double, TileRef>>& candidates, double roll) {
    if (candidates.empty()) {
        return {};
    }
    double total = 0.0;
    for (const auto& [w, _] : candidates) {
        total += w;
    }
    if (total <= 0.0) {
        return candidates.front().second;
    }
    double u = roll * total;
    for (const auto& [w, tile] : candidates) {
        u -= w;
        if (u < 0.0) {
            return tile;
        }
    }
    return candidates.back().second;
}

std::vector<MapCell> resolve_terrain(const Tileset& tileset, int terrain_set, int terrain,
                                     const std::vector<std::pair<int, int>>& cells, int layer_index) {
    const TerrainSet* set = tileset.terrain_set(terrain_set);
    const std::string mode = set ? set->mode : "blob47";
    // The candidates per key in atlas order: atlases by id, tiles in list order
    std::vector<const Atlas*> atlases;
    for (const auto& at : tileset.atlases) {
        atlases.push_back(&at);
    }
    std::stable_sort(atlases.begin(), atlases.end(), [](const Atlas* l, const Atlas* r) { return l->id < r->id; });
    std::map<int, std::vector<std::pair<double, TileRef>>> by_key;
    for (const Atlas* at : atlases) {
        for (const auto& t : at->tiles) {
            if (t.terrain != terrain || t.terrain_set != terrain_set) {
                continue;
            }
            if (const auto key = tile_key(t, mode, tileset.shape)) {
                by_key[*key].emplace_back(t.probability, TileRef{at->id, t.col, t.row});
            }
        }
    }
    const std::set<std::pair<int, int>> painted(cells.begin(), cells.end());
    std::vector<std::pair<int, int>> order(painted.begin(), painted.end());
    std::sort(order.begin(), order.end(), [](const auto& l, const auto& r) {
        return l.second != r.second ? l.second < r.second : l.first < r.first;
    });
    std::vector<MapCell> out;
    for (const auto& [x, y] : order) {
        MapCell cell;
        cell.x = x;
        cell.y = y;
        cell.key = cell_mask(painted, x, y, mode);
        const auto it = by_key.find(cell.key);
        if (it != by_key.end()) {
            cell.tile = pick_variant(it->second, cell_roll(x, y, layer_index));
        }
        out.push_back(cell);
    }
    return out;
}

// ---- placing tiles ----
Point cell_centre(const std::string& shape, int x, int y, int tile_w, int tile_h) {
    const double w = tile_w, h = tile_h;
    if (shape == "isometric") {
        return {(x - y + 1) * w / 2, (x + y + 1) * h / 2};
    }
    return {(x + 0.5) * w, (y + 0.5) * h};
}

Point tile_origin(const Tile& tile, const Atlas& atlas) {
    if (tile.origin) {
        return *tile.origin;
    }
    return {atlas.tile_w / 2.0, atlas.tile_h / 2.0};
}

std::optional<Point> placed_corner(const Tileset& tileset, const Map& map, const MapCell& cell) {
    const Atlas* atlas = tileset.atlas(cell.tile.atlas);
    const Tile* tile = tileset.tile(cell.tile);
    if (!atlas || !tile) {
        return std::nullopt;
    }
    const Point c = cell_centre(map.shape, cell.x, cell.y, map.tile_w, map.tile_h);
    const Point o = tile_origin(*tile, *atlas);
    return Point{c.x - o.x, c.y - o.y};
}

MapBounds map_bounds(const Map& map) {
    const double w = map.tile_w, h = map.tile_h;
    if (map.shape == "isometric") {
        return {(1 - map.h) * w / 2, 0.0, (map.w + map.h) * w / 2, (map.w + map.h) * h / 2};
    }
    return {0.0, 0.0, map.w * w, map.h * h};
}

// ---- timing ----
void ClipPlayer::play(const Clip* clip) {
    clip_ = clip;
    index_ = 0;
    t_ = 0.0;
    done_ = false;
}

void ClipPlayer::update(double dt) {
    if (!clip_ || clip_->frames.empty() || clip_->length <= 0.0 || done_) {
        return;
    }
    t_ += dt;
    while (t_ >= clip_->frames[index_].seconds) {
        if (index_ + 1 < clip_->frames.size()) {
            t_ -= clip_->frames[index_].seconds;
            ++index_;
        } else if (clip_->loop) {
            t_ -= clip_->frames[index_].seconds;
            index_ = 0;
        } else {
            t_ = clip_->frames[index_].seconds;   // hold the last frame
            done_ = true;
            break;
        }
    }
}

// ---- text ----
std::vector<GlyphQuad> layout_text(const Font& font, const std::string& utf8, int* missing) {
    std::vector<GlyphQuad> out;
    double pen_x = 0.0, pen_y = 0.0;
    int prev = -1;
    for (std::size_t i = 0; i < utf8.size();) {
        const int cp = static_cast<int>(next_code_point(utf8, i));
        if (cp == '\n') {
            pen_x = 0.0;
            pen_y += font.line_height;
            prev = -1;
            continue;
        }
        const Glyph* g = font.glyph(cp);
        if (!g) {
            if (missing) {
                ++*missing;
            }
            prev = -1;
            continue;
        }
        if (prev >= 0) {
            pen_x += font.kern(prev, cp);
        }
        if (g->w > 0 && g->h > 0) {
            out.push_back({g, pen_x + g->xoffset, pen_y + g->yoffset});
        }
        pen_x += g->xadvance;
        prev = cp;
    }
    return out;
}

double text_width(const Font& font, const std::string& utf8) {
    double widest = 0.0, pen_x = 0.0;
    int prev = -1;
    for (std::size_t i = 0; i < utf8.size();) {
        const int cp = static_cast<int>(next_code_point(utf8, i));
        const Glyph* g = cp == '\n' ? nullptr : font.glyph(cp);
        if (cp == '\n' || !g) {
            widest = std::max(widest, pen_x);
            pen_x = cp == '\n' ? 0.0 : pen_x;
            prev = -1;
            continue;
        }
        pen_x += (prev >= 0 ? font.kern(prev, cp) : 0) + g->xadvance;
        prev = cp;
    }
    return std::max(widest, pen_x);
}

// ---- tile flags ----
TileTransform tile_transform(int flags) {
    // 2x2 integer matrices on (x, y), y down: {a, b, c, d} maps (x, y) to (a x + b y, c x + d y)
    using M = std::array<int, 4>;
    const auto mul = [](const M& l, const M& r) {
        return M{l[0] * r[0] + l[1] * r[2], l[0] * r[1] + l[1] * r[3], l[2] * r[0] + l[3] * r[2], l[2] * r[1] + l[3] * r[3]};
    };
    const M identity{1, 0, 0, 1}, flip_h{-1, 0, 0, 1}, flip_v{1, 0, 0, -1}, transpose{0, 1, 1, 0};
    const M quarter{0, -1, 1, 0};   // 90 degrees clockwise on screen
    M want = identity;
    if (flags & 4) {
        want = mul(transpose, want);
    }
    if (flags & 1) {
        want = mul(flip_h, want);
    }
    if (flags & 2) {
        want = mul(flip_v, want);
    }
    // SDL draws flip first, then the turn: find turn * flip == want (the 8 cases all have one)
    M turn = identity;
    for (int k = 0; k < 4; ++k) {
        for (int f = 0; f < 3; ++f) {
            const M& flip = f == 0 ? identity : f == 1 ? flip_h : flip_v;
            if (mul(turn, flip) == want) {
                return {k * 90, f == 1, f == 2};
            }
        }
        turn = mul(quarter, turn);
    }
    return {};
}

}  // namespace core::dotwork

// {{FOOTER}}
