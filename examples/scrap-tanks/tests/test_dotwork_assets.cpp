// ---------------------------------------------------------------------------
// test_dotwork_assets.cpp
// Purpose : Holds the Dotwork asset importer (src/core/DotworkAssets) to the spec's golden fixture, and checks that
//           every real manifest of the game loads with all its files.
// Usage   : python tools/dev.py test   (ctest lists each "dotwork assets: ..." case; build/debug/bin/Debug/unit_tests.exe
//           -tc="dotwork*" runs only these)
// Notes   : The fixture is data/golden/dotwork/ (GOLDEN_DIR): its manifest is loaded through the importer, the
//           loaded structs are turned back into the shape of expected.json (the reference loader's result,
//           tools/art/dotwork/assetspec.py expected) and every entry is compared, numbers within 1e-6: the
//           maps' terrain keys and picks, placed corners and cell centres included. Expected values are read
//           from the file at test time, never copied here; the spec's own test vectors (hash32, cell_roll, the
//           corners4 keys of a 3x3 block, the isometric centres) are the only numbers written down. The extra
//           kinds must load by name without a warning. The game's own manifests are
//           <assets>/dotwork/*.assets.json (GAME_ASSETS_DIR): none yet passes with a message; each one found must
//           load without errors and name only files that are there, are PNGs and fit (the stand-in for Dotwork's
//           Godot verify). No window: SDL is not linked.
//
// Pseudocode:
//   load golden manifest -> loaded_result(pack) -> for each expected entry: same(expected, got)
//   then the rule tests (cell_mask on all three modes, hash32 and cell_roll vectors, the pick, cell centres and
//   placement, a stamps layer, clip timing, glyph layout, tile flags) and the game's manifests
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): the maps' full loaded result,
//           the extra kinds loaded, the hash, roll, corners4, centre and stamps cases
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <optional>
#include <set>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "core/AtomicFile.hpp"
#include "core/DotworkAssets.hpp"

#ifndef GOLDEN_DIR
#error "GOLDEN_DIR must name the folder with the golden files (CMakeLists.txt sets it)"
#endif
#ifndef GAME_ASSETS_DIR
#error "GAME_ASSETS_DIR must name the game's assets folder (CMakeLists.txt sets it)"
#endif

namespace {

using nlohmann::json;
namespace dw = core::dotwork;
namespace fs = std::filesystem;

// ---- Constants ----
constexpr double kTol = 1e-6;   // the spec's tolerance (expected.json rounds to 6 decimals)
constexpr const char* kGoldenManifest = "dotwork/assets/dotwork/golden.assets.json";
constexpr const char* kGoldenExpected = "dotwork/expected.json";
const std::set<std::string> kExtraKinds{"background", "particles", "transition", "normal_map", "image"};

fs::path golden(const char* rel) { return core::path_from_utf8(GOLDEN_DIR) / core::path_from_utf8(rel); }

json load_json(const fs::path& path) {
    const auto text = core::read_file(path);
    REQUIRE_MESSAGE(text.has_value(), "cannot read " << core::path_to_utf8(path));
    return json::parse(*text);
}

dw::Pack golden_pack() {
    dw::Pack pack = dw::load_manifest(golden(kGoldenManifest));
    REQUIRE_MESSAGE(pack.ok(), "the golden manifest has errors: " << (pack.errors.empty() ? "" : pack.errors.front()));
    return pack;
}

json rect_json(const dw::Rect& r) { return json::array({r.x, r.y, r.w, r.h}); }
json rect_json(const dw::RectF& r) { return json::array({r.x, r.y, r.w, r.h}); }
json point_json(const dw::Point& p) { return json::array({p.x, p.y}); }

json tile_json(const dw::TileRef& t) { return json::array({t.atlas, t.col, t.row}); }

// The loaded structs in the shape of expected.json ("kind/name" -> numbers), every kind.
json loaded_result(const dw::Pack& pack) {
    json out = json::object();
    for (const auto& a : pack.animated_sprites) {
        json clips = json::object();
        for (const auto& c : a.clips) {
            json rects = json::array(), secs = json::array();
            for (const auto& f : c.frames) {
                rects.push_back(rect_json(f.rect));
                secs.push_back(f.seconds);
            }
            clips[c.name] = {{"frames", c.frames.size()}, {"rects", rects}, {"seconds", secs}, {"length", c.length},
                             {"loop", c.loop}, {"pivot", point_json(c.pivot)},
                             {"texture", c.sheet.empty() ? json(nullptr) : json(c.sheet)}};
        }
        out["animated_sprite/" + a.name] = {{"blend", a.blend == dw::Blend::Add ? "add" : "normal"}, {"clips", clips},
                                            {"directions", a.directions.empty() ? json::object() : json(a.directions)}};
    }
    for (const auto& s : pack.sprites) {
        json coll = json::array();
        for (const auto& r : s.collision) {
            coll.push_back(rect_json(r));
        }
        out["sprite/" + s.name] = {{"size", {s.w, s.h}}, {"pivot", point_json(s.pivot)}, {"collision", coll}};
    }
    for (const auto& i : pack.icons) {
        json sizes = json::array();
        for (const auto& s : i.sizes) {
            sizes.push_back(s.size);
        }
        out["icon/" + i.name] = {{"sizes", sizes}};
    }
    for (const auto& p : pack.portraits) {
        std::vector<std::string> names;
        for (const auto& e : p.expressions) {
            names.push_back(e.name);
        }
        std::sort(names.begin(), names.end());
        out["portrait/" + p.name] = {{"size", {p.w, p.h}}, {"expressions", names},
                                     {"animation", p.animation.empty() ? json(nullptr) : json(p.animation)}};
    }
    for (const auto& t : pack.tilesets) {
        int tiles = 0, coll = 0, anim = 0;
        std::map<std::string, std::vector<json>> masks;
        for (const auto& at : t.atlases) {
            for (const auto& tile : at.tiles) {
                ++tiles;
                coll += tile.collision.empty() ? 0 : 1;
                anim += tile.animated ? 1 : 0;
                if (tile.terrain < 0) {
                    continue;
                }
                json v;
                if (tile.mask) {
                    v = *tile.mask;
                } else {
                    v = json::array();
                    for (const auto& [corner, id] : tile.corners) {   // std::map: corner names sorted, as the reference does
                        v.push_back(id);
                    }
                }
                auto& list = masks[std::to_string(tile.terrain_set) + "/" + std::to_string(tile.terrain)];
                if (std::find(list.begin(), list.end(), v) == list.end()) {
                    list.push_back(v);
                }
            }
        }
        json terrains = json::object(), mask_json = json::object();
        for (const auto& s : t.terrain_sets) {
            for (const auto& tr : s.terrains) {
                terrains[std::to_string(s.id) + "/" + std::to_string(tr.id)] = tr.name;
            }
        }
        for (auto& [key, list] : masks) {
            std::sort(list.begin(), list.end());
            mask_json[key] = list;
        }
        out["tileset/" + t.name] = {{"tile_size", {t.tile_w, t.tile_h}}, {"shape", t.shape}, {"tiles", tiles},
                                    {"collision_tiles", coll}, {"animated_tiles", anim}, {"terrains", terrains},
                                    {"masks", mask_json}};
    }
    for (const auto& m : pack.maps) {
        const dw::Tileset* ts = pack.tileset(m.tileset);
        json layers = json::object(), terrain = json::object(), placed = json::object(), objects = json::array();
        for (const auto& L : m.layers) {
            // The cells a layer draws (a terrain cell no tile fits is not drawn), each with its image's top-left
            json drawn = json::array();
            for (const auto& c : L.cells) {
                if (c.tile.atlas < 0) {
                    continue;
                }
                std::optional<dw::Point> corner;
                if (ts) {
                    corner = dw::placed_corner(*ts, m, c);
                }
                drawn.push_back({c.x, c.y, c.tile.atlas, c.tile.col, c.tile.row, corner ? json(corner->x) : json(nullptr),
                                 corner ? json(corner->y) : json(nullptr)});
            }
            layers[L.name] = drawn.size();
            placed[L.name] = drawn;
            if (L.kind != "terrain") {
                continue;
            }
            json cells = json::array();
            for (const auto& c : L.cells) {
                cells.push_back({c.x, c.y, c.key, c.tile.atlas < 0 ? json(nullptr) : tile_json(c.tile)});
            }
            terrain[L.name] = cells;
        }
        json centres = json::array();
        for (int y = 0; y < m.h; ++y) {
            for (int x = 0; x < m.w; ++x) {
                const dw::Point c = dw::cell_centre(m.shape, x, y, m.tile_w, m.tile_h);
                centres.push_back({x, y, c.x, c.y});
            }
        }
        for (const auto& o : m.objects) {
            objects.push_back({o.asset, o.x, o.y});
        }
        out["map/" + m.name] = {{"size", {m.w, m.h}},   {"shape", m.shape},     {"tile_size", {m.tile_w, m.tile_h}},
                                {"layers", layers},    {"terrain", terrain},   {"placed", placed},
                                {"centres", centres},  {"objects", objects}};
    }
    for (const auto& f : pack.fonts) {
        const dw::Glyph* g = f.glyph('A') ? f.glyph('A') : (f.chars.empty() ? nullptr : &f.chars.front());
        out["font/" + f.name] = {
            {"line_height", f.line_height}, {"base", f.base}, {"chars", f.chars.size()}, {"pages", f.pages.size()},
            {"sample", g ? json::array({g->id, g->x, g->y, g->w, g->h, g->xoffset, g->yoffset, g->xadvance, g->page})
                         : json(nullptr)}};
    }
    for (const auto& k : pack.ui_kits) {
        json parts = json::object();
        for (const auto& p : k.parts) {
            parts[p.name] = {{"size", {p.w, p.h}},
                             {"margins", p.margins ? json(*p.margins) : json(nullptr)},
                             {"hotspot", p.hotspot ? point_json(*p.hotspot) : json(nullptr)}};
        }
        out["ui_kit/" + k.name] = {{"parts", parts}};
    }
    // The extra kinds: a background's layers as [w, h, vx, vy, repeat], the others by kind alone (the reference
    // records no more; the next case checks their data)
    for (const auto& b : pack.backgrounds) {
        json layers = json::array();
        for (const auto& L : b.layers) {
            layers.push_back({L.w, L.h, L.vx, L.vy, L.repeat});
        }
        out["background/" + b.name] = {{"layers", layers}};
    }
    for (const auto& p : pack.particles) {
        out["particles/" + p.name] = {{"kind", "particles"}};
    }
    for (const auto& t : pack.transitions) {
        out["transition/" + t.name] = {{"kind", "transition"}};
    }
    for (const auto& n : pack.normal_maps) {
        out["normal_map/" + n.name] = {{"kind", "normal_map"}};
    }
    for (const auto& i : pack.images) {
        out["image/" + i.name] = {{"kind", "image"}};
    }
    return out;
}

// want == got: numbers within kTol (an int 0 equals a float 0.0), arrays in order, objects as key sets.
bool same(const json& want, const json& got, const std::string& at, std::string& why) {
    if (want.is_number() && got.is_number()) {
        if (std::fabs(want.get<double>() - got.get<double>()) <= kTol) {
            return true;
        }
        why = at + ": expected " + want.dump() + ", got " + got.dump();
        return false;
    }
    if (want.is_array() && got.is_array()) {
        if (want.size() != got.size()) {
            why = at + ": expected " + std::to_string(want.size()) + " items, got " + std::to_string(got.size());
            return false;
        }
        for (std::size_t i = 0; i < want.size(); ++i) {
            if (!same(want[i], got[i], at + "[" + std::to_string(i) + "]", why)) {
                return false;
            }
        }
        return true;
    }
    if (want.is_object() && got.is_object()) {
        for (const auto& [key, value] : want.items()) {
            if (!got.contains(key)) {
                why = at + "." + key + ": missing";
                return false;
            }
            if (!same(value, got.at(key), at + "." + key, why)) {
                return false;
            }
        }
        for (const auto& [key, value] : got.items()) {
            if (!want.contains(key)) {
                why = at + "." + key + ": not in expected.json";
                return false;
            }
        }
        return true;
    }
    if (want == got) {
        return true;
    }
    why = at + ": expected " + want.dump() + ", got " + got.dump();
    return false;
}

json manifest(const json& assets, const std::string& version = "1.0.0") {
    return {{"format", "dotwork-assets"}, {"version", version}, {"pack", "t"}, {"base", ".."}, {"assets", assets}};
}

}  // namespace

TEST_CASE("dotwork assets: the golden pack loads as expected.json") {
    const dw::Pack pack = golden_pack();
    const json expected = load_json(golden(kGoldenExpected));
    REQUIRE(expected.at("format") == "dotwork-assets-expected");
    CHECK(expected.at("version") == pack.version);
    CHECK(expected.at("pack") == pack.pack);
    const json got = loaded_result(pack);
    std::size_t compared = 0, maps = 0;
    for (const auto& [key, want] : expected.at("assets").items()) {
        ++compared;
        maps += key.rfind("map/", 0) == 0 ? 1 : 0;
        INFO("asset " << key);
        REQUIRE_MESSAGE(got.contains(key), key << " was not loaded");
        std::string why;
        CHECK_MESSAGE(same(want, got.at(key), key, why), why);
    }
    CHECK_MESSAGE(got.size() == compared, "the importer loaded assets expected.json does not list");
    CHECK(maps == 3);   // yard (blob47, a stamps layer), meadow_patch (corners4) and isle (isometric corners4)
    // (the message is built even when the check passes under -s, so never front() an empty vector in one)
    CHECK_MESSAGE(pack.warnings.empty(), "the golden pack warned: " << (pack.warnings.empty() ? "" : pack.warnings.front()));
    MESSAGE("compared " << compared << " assets with expected.json");
}

TEST_CASE("dotwork assets: the extra kinds load by name with their data") {
    const dw::Pack pack = golden_pack();
    const json expected = load_json(golden(kGoldenExpected));
    std::set<std::string> extra;
    for (const auto& [key, want] : expected.at("assets").items()) {
        const std::string kind = key.substr(0, key.find('/'));
        if (kExtraKinds.count(kind)) {
            extra.insert(key);
        }
    }
    REQUIRE(extra.size() == kExtraKinds.size());   // the fixture has one of each
    CHECK(pack.warnings.empty());                   // none is skipped any more
    for (const auto& key : extra) {
        const std::string kind = key.substr(0, key.find('/')), name = key.substr(key.find('/') + 1);
        INFO("asset " << key);
        if (kind == "background") {
            const dw::Background* b = pack.background(name);
            REQUIRE(b);
            REQUIRE_FALSE(b->layers.empty());
            for (const auto& L : b->layers) {
                CHECK_FALSE(L.image.empty());
                CHECK((L.repeat == "none" || L.repeat == "x" || L.repeat == "y" || L.repeat == "xy"));
            }
        } else if (kind == "particles") {
            const dw::Particles* p = pack.particle_set(name);
            REQUIRE(p);
            CHECK_FALSE(p->texture.empty());
            CHECK(p->emitter.is_object());
            CHECK_FALSE(p->emitter.empty());   // the emitter JSON travels with the texture
        } else if (kind == "transition") {
            const dw::Transition* t = pack.transition(name);
            REQUIRE(t);
            CHECK_FALSE(t->image.empty());
            CHECK_FALSE(t->transition.empty());
        } else if (kind == "normal_map") {
            const dw::NormalMap* n = pack.normal_map(name);
            REQUIRE(n);
            CHECK_FALSE(n->image.empty());
            CHECK_FALSE(n->target.empty());
            CHECK(n->convention == "opengl");
        } else {
            const dw::Image* i = pack.image(name);
            REQUIRE(i);
            CHECK_FALSE(i->image.empty());
            CHECK(i->w > 0);
        }
    }
}

TEST_CASE("dotwork assets: every file of the golden pack is there") {
    for (const auto& p : dw::check_files(golden_pack())) {
        FAIL_CHECK(p);
    }
}

TEST_CASE("dotwork assets: another major version and a broken asset are reported") {
    const fs::path where = core::path_from_utf8("assets/dotwork/t.assets.json");
    const dw::Pack v2 = dw::parse_manifest(manifest(json::array(), "2.0.0"), where);
    REQUIRE(v2.errors.size() == 1);
    CHECK(v2.errors[0].find("2.0.0") != std::string::npos);
    CHECK(v2.errors[0].find("1.x") != std::string::npos);

    CHECK_FALSE(dw::parse_manifest(json{{"format", "something-else"}}, where).ok());

    // A path out of the pack breaks that asset only; an unknown kind and an unknown field are not errors.
    const json assets = json::array({
        {{"kind", "sprite"}, {"name", "bad"}, {"image", "../outside.png"}, {"size", {8, 8}}, {"pivot", {4, 8}}},
        {{"kind", "sprite"}, {"name", "good"}, {"image", "art/x.png"}, {"size", {8, 8}}, {"pivot", {4, 8}},
         {"future_field", 1}},
        {{"kind", "hologram"}, {"name", "h"}},
        {{"kind", "hologram"}, {"name", "h2"}},
    });
    const dw::Pack pack = dw::parse_manifest(manifest(assets), where);
    REQUIRE(pack.errors.size() == 1);
    CHECK(pack.errors[0].find("sprite/bad") != std::string::npos);
    REQUIRE(pack.sprites.size() == 1);
    CHECK(pack.sprites[0].name == "good");
    CHECK(pack.warnings.size() == 1);   // one warning per kind, not per asset
    CHECK(pack.resolve("art/x.png") == core::path_from_utf8("assets/art/x.png"));
}

TEST_CASE("dotwork assets: cell_mask follows the blob rule") {
    std::set<int> blob;
    for (int m = 0; m < 256; ++m) {
        blob.insert(dw::canon(m));
    }
    CHECK(blob.size() == 47);
    CHECK(dw::canon(255) == 255);
    CHECK(dw::canon(2) == 0);            // NE alone: its sides N and E are not set
    CHECK(dw::canon(1 | 2 | 4) == 7);    // NE with N and E counts
    // A 2x2 block: the top-left cell sees E, SE, S
    const std::set<std::pair<int, int>> block{{0, 0}, {1, 0}, {0, 1}, {1, 1}};
    CHECK(dw::cell_mask(block, 0, 0) == (4 | 8 | 16));
    CHECK(dw::cell_mask(block, 0, 0, "sides4") == (4 | 16));
}

TEST_CASE("dotwork assets: corners4 keys are the corner bits of the blob mask") {
    // A 3x3 block (the spec's probe): the centre holds all four corners, the top-left cell only its SE corner, the
    // top-middle cell its SE and SW corners (a corner counts when all four cells meeting there are painted)
    std::set<std::pair<int, int>> block;
    for (int y = 0; y < 3; ++y) {
        for (int x = 0; x < 3; ++x) {
            block.insert({x, y});
        }
    }
    CHECK(dw::cell_mask(block, 1, 1, "corners4") == 170);
    CHECK(dw::cell_mask(block, 0, 0, "corners4") == 8);
    CHECK(dw::cell_mask(block, 1, 0, "corners4") == 40);
    CHECK(dw::cell_mask(block, 2, 2, "corners4") == 128);
    // A tile's key: the bits of the corners holding its own terrain, names by shape
    dw::Tile tile;
    tile.terrain = 1;
    tile.corners = {{"top_left", 1}, {"top_right", -1}, {"bottom_right", 1}, {"bottom_left", -1}};
    CHECK(dw::tile_key(tile, "corners4", "square") == 128 + 8);
    CHECK_FALSE(dw::tile_key(tile, "corners4", "isometric").has_value());   // not the diamond's corner names
    tile.corners = {{"top", 1}, {"right", 1}, {"bottom", -1}, {"left", -1}};
    CHECK(dw::tile_key(tile, "corners4", "isometric") == 128 + 2);
    tile.corners = {{"top", 0}, {"right", 0}, {"bottom", 0}, {"left", 0}};   // another terrain's corners
    CHECK(dw::tile_key(tile, "corners4", "isometric") == 0);
    tile.mask = 255;
    CHECK(dw::tile_key(tile, "blob47", "square") == 255);
}

TEST_CASE("dotwork assets: hash32 and cell_roll give the spec's vectors") {
    CHECK(dw::hash32(0) == 1800329511u);
    CHECK(dw::hash32(1) == 3028713910u);
    CHECK(dw::hash32(0xFFFFFFFFu) == 4268016002u);
    CHECK(dw::cell_roll(0, 0, 0) == doctest::Approx(0.169182).epsilon(kTol));
    CHECK(dw::cell_roll(3, 1, 1) == doctest::Approx(0.765973).epsilon(kTol));
    CHECK(dw::cell_roll(3, 2, 1) == doctest::Approx(0.531301).epsilon(kTol));
    CHECK(dw::cell_roll(-1, -1, 0) == doctest::Approx(0.992978).epsilon(kTol));   // coordinates wrap at 16 bits
    for (int x = -3; x < 3; ++x) {
        const double r = dw::cell_roll(x, 2 * x, 1);
        CHECK((r >= 0.0 && r < 1.0));
    }
    // The pick walks the weights in order; every weight 0 gives the first; a roll at the end gives the last
    const dw::TileRef a{0, 0, 0}, b{0, 1, 0}, c{1, 0, 0};
    const std::vector<std::pair<double, dw::TileRef>> cands{{1.0, a}, {0.6, b}, {0.6, c}};
    CHECK(dw::pick_variant(cands, 0.0).col == a.col);
    CHECK(dw::pick_variant(cands, 0.5).col == b.col);          // 1.1 of 2.2: past a's 1.0, inside b's
    CHECK(dw::pick_variant(cands, 0.999999).atlas == c.atlas);
    CHECK(dw::pick_variant({{0.0, a}, {0.0, b}}, 0.7).col == a.col);
    CHECK(dw::pick_variant({{0.0, a}, {2.0, b}}, 0.0).col == b.col);   // weight 0 is never picked
}

TEST_CASE("dotwork assets: cell centres and placement follow the spec on both shapes") {
    // Isometric 16x8 (Godot's diamond-down layout): the spec's four probed cells
    CHECK(dw::cell_centre("isometric", 0, 0, 16, 8).x == doctest::Approx(8));
    CHECK(dw::cell_centre("isometric", 0, 0, 16, 8).y == doctest::Approx(4));
    CHECK(dw::cell_centre("isometric", 1, 0, 16, 8).x == doctest::Approx(16));
    CHECK(dw::cell_centre("isometric", 1, 0, 16, 8).y == doctest::Approx(8));
    CHECK(dw::cell_centre("isometric", 0, 1, 16, 8).x == doctest::Approx(0));
    CHECK(dw::cell_centre("isometric", 0, 1, 16, 8).y == doctest::Approx(8));
    CHECK(dw::cell_centre("isometric", 3, 2, 16, 8).x == doctest::Approx(16));
    CHECK(dw::cell_centre("isometric", 3, 2, 16, 8).y == doctest::Approx(24));
    CHECK(dw::cell_centre("square", 2, 1, 8, 8).x == doctest::Approx(20));
    CHECK(dw::cell_centre("square", 2, 1, 8, 8).y == doctest::Approx(12));
    // A 16x12 block with origin [8, 8] on a 16x8 diamond at (3, 0): top-left (32 - 8, 16 - 8); without an origin
    // the atlas tile's centre sits on the cell's
    dw::Tileset ts;
    ts.shape = "isometric";
    dw::Atlas blocks;
    blocks.id = 1;
    blocks.tile_w = 16;
    blocks.tile_h = 12;
    dw::Tile raised;
    raised.origin = dw::Point{8, 8};
    blocks.tiles.push_back(raised);
    dw::Tile flat;
    flat.col = 1;
    blocks.tiles.push_back(flat);
    ts.atlases.push_back(blocks);
    dw::Map map;
    map.shape = "isometric";
    map.w = 4;
    map.h = 3;
    map.tile_w = 16;
    map.tile_h = 8;
    const auto top_left = dw::placed_corner(ts, map, dw::MapCell{3, 0, {1, 0, 0}, 0, -1});
    REQUIRE(top_left);
    CHECK(top_left->x == doctest::Approx(24));
    CHECK(top_left->y == doctest::Approx(8));
    const auto centred = dw::placed_corner(ts, map, dw::MapCell{0, 0, {1, 1, 0}, 0, -1});
    REQUIRE(centred);
    CHECK(centred->x == doctest::Approx(0));
    CHECK(centred->y == doctest::Approx(-2));
    CHECK_FALSE(dw::placed_corner(ts, map, dw::MapCell{0, 0, {7, 0, 0}, 0, -1}).has_value());
    // What the cells cover: the 4x3 diamond map reaches 16 px left of pixel 0 and is 7 half-tiles wide and tall
    const dw::MapBounds iso = dw::map_bounds(map);
    CHECK(iso.left == doctest::Approx(-16));
    CHECK(iso.w == doctest::Approx(56));
    CHECK(iso.h == doctest::Approx(28));
    map.shape = "square";
    CHECK(dw::map_bounds(map).left == doctest::Approx(0));
    CHECK(dw::map_bounds(map).w == doctest::Approx(64));
}

TEST_CASE("dotwork assets: a stamps layer places every tile of the stamp") {
    // A 1.1.0 manifest: a tileset with a 2x3 atlas, a 1x2 door stamp and a 2x1 bench stamp; a map that places the
    // door at (7, 0) and the bench at (0, 4), then a layer of a kind this importer does not know
    const json tiles = json::array({{{"col", 0}, {"row", 0}}, {{"col", 1}, {"row", 0}}, {{"col", 0}, {"row", 1}},
                                    {{"col", 1}, {"row", 1}}, {{"col", 0}, {"row", 2}}});
    const json assets = json::array({
        {{"kind", "tileset"}, {"name", "t"}, {"tile_size", {8, 8}}, {"shape", "square"}, {"terrain_sets", json::array()},
         {"atlases", json::array({{{"id", 4}, {"name", "fixtures"}, {"role", "fixtures"}, {"image", "art/fix.png"},
                                   {"tile_size", {8, 8}}, {"columns", 2}, {"rows", 3}, {"tiles", tiles}}})},
         {"stamps", json::array({{{"name", "door"}, {"size", {1, 2}}, {"solid", true}, {"tiles", {{4, 0, 0}, {4, 1, 0}}}},
                                 {{"name", "bench"}, {"size", {2, 1}}, {"tiles", {{4, 0, 1}, {4, 1, 1}}}}})}},
        {{"kind", "map"}, {"name", "m"}, {"tileset", "t"}, {"size", {8, 6}}, {"tile_size", {8, 8}},
         {"layers", json::array({{{"name", "Fixtures"}, {"kind", "stamps"}, {"cells", {{7, 0, 0}, {0, 4, 1}}}},
                                 {{"name", "Lights"}, {"kind", "lights"}, {"cells", json::array()}}})}},
    });
    const fs::path where = core::path_from_utf8("assets/dotwork/t.assets.json");
    const dw::Pack pack = dw::parse_manifest(manifest(assets, "1.1.0"), where);
    REQUIRE_MESSAGE(pack.ok(), "the stamps manifest has errors: " << (pack.errors.empty() ? "" : pack.errors.front()));
    REQUIRE(pack.maps.size() == 1);
    const dw::Map& m = pack.maps.front();
    REQUIRE(m.layers.size() == 1);   // the unknown kind is skipped with one warning
    REQUIRE(pack.warnings.size() == 1);
    CHECK(pack.warnings.front().find("\"lights\"") != std::string::npos);
    const dw::MapLayer& L = m.layers.front();
    CHECK(L.kind == "stamps");
    REQUIRE(L.cells.size() == 4);
    const auto cell = [&](std::size_t i) { return json::array({L.cells[i].x, L.cells[i].y, L.cells[i].tile.atlas,
                                                                L.cells[i].tile.col, L.cells[i].tile.row}); };
    CHECK(cell(0) == json::array({7, 0, 4, 0, 0}));   // tile j at (x + j % w, y + j / w), in reading order
    CHECK(cell(1) == json::array({7, 1, 4, 1, 0}));
    CHECK(cell(2) == json::array({0, 4, 4, 0, 1}));
    CHECK(cell(3) == json::array({1, 4, 4, 1, 1}));
    // The second placed tile's image: its top-left is the cell centre less the tile's centre, (56, 8) on 8x8 cells
    const auto corner = dw::placed_corner(pack.tilesets.front(), m, L.cells[1]);
    REQUIRE(corner);
    CHECK(corner->x == doctest::Approx(56));
    CHECK(corner->y == doctest::Approx(8));
    // A stamp the tileset lacks is that map's error
    json broken = assets;
    broken[1]["layers"][0]["cells"] = {{7, 0, 2}};
    const dw::Pack bad = dw::parse_manifest(manifest(broken, "1.1.0"), where);
    REQUIRE(bad.errors.size() == 1);
    CHECK(bad.errors.front().find("stamp 2") != std::string::npos);
    CHECK(bad.maps.empty());
}

TEST_CASE("dotwork assets: a clip plays by each frame's duration") {
    const dw::Pack pack = golden_pack();
    const dw::AnimatedSprite* hero = pack.animated_sprite("hero");
    REQUIRE(hero);
    for (const dw::Clip& clip : hero->clips) {
        INFO("clip " << clip.name);
        // Sample the middle of every frame over two passes: the player must show that frame (one loop clip
        // wraps around; a one-shot clip holds its last frame).
        double start = 0.0;
        for (int pass = 0; pass < 2; ++pass) {
            for (std::size_t i = 0; i < clip.frames.size(); ++i) {
                dw::ClipPlayer player(&clip);
                player.update(start + clip.frames[i].seconds / 2);
                const std::size_t want = clip.loop || pass == 0 ? i : clip.frames.size() - 1;
                CHECK(player.frame() == want);
                CHECK(player.finished() == (!clip.loop && pass == 1));
                start += clip.frames[i].seconds;
            }
        }
    }
    // Small steps add up the same way (a hold of 2 shows twice as long)
    const dw::Clip* walk = hero->clip("walk_s");
    REQUIRE(walk);
    dw::ClipPlayer player(walk);
    std::vector<std::size_t> seen;
    const int steps = static_cast<int>(std::round(walk->length / 0.0625));
    for (int k = 0; k < steps; ++k) {
        seen.push_back(player.frame());
        player.update(0.0625);
    }
    std::vector<std::size_t> want;
    for (std::size_t i = 0; i < walk->frames.size(); ++i) {
        for (int n = 0; n < static_cast<int>(std::round(walk->frames[i].seconds / 0.0625)); ++n) {
            want.push_back(i);
        }
    }
    CHECK(seen == want);
    CHECK(player.frame() == 0);   // looped back
}

TEST_CASE("dotwork assets: text becomes glyph quads from the font's chars") {
    const dw::Pack pack = golden_pack();
    REQUIRE_FALSE(pack.fonts.empty());
    const dw::Font& font = pack.fonts.front();
    const dw::Glyph* a = font.glyph('A');
    const dw::Glyph* b = font.glyph('B');
    REQUIRE(a);
    REQUIRE(b);
    int missing = 0;
    const auto quads = dw::layout_text(font, "AB\nA\xE2\x82\xAC", &missing);   // the euro sign is not in the font
    REQUIRE(quads.size() == 3);
    CHECK(missing == 1);
    CHECK(quads[0].glyph == a);
    CHECK(quads[0].x == doctest::Approx(a->xoffset));
    CHECK(quads[1].x == doctest::Approx(a->xadvance + font.kern('A', 'B') + b->xoffset));
    CHECK(quads[2].y == doctest::Approx(font.line_height + a->yoffset));
    CHECK(dw::text_width(font, "AB") == doctest::Approx(a->xadvance + font.kern('A', 'B') + b->xadvance));
}

TEST_CASE("dotwork assets: tile flags as SDL's flip-then-turn") {
    // The corners of a tile centred on the origin, moved by the flags directly (transpose first, then the flips)
    // and by the flip and quarter turns tile_transform gives (SDL flips the image, then turns it clockwise).
    const std::array<std::array<int, 2>, 2> points{{{1, 2}, {-3, 5}}};
    for (int flags = 0; flags < 8; ++flags) {
        INFO("flags " << flags);
        const dw::TileTransform t = dw::tile_transform(flags);
        CHECK_FALSE((t.flip_h && t.flip_v));
        for (auto p : points) {
            auto want = p;
            if (flags & 4) {
                std::swap(want[0], want[1]);
            }
            if (flags & 1) {
                want[0] = -want[0];
            }
            if (flags & 2) {
                want[1] = -want[1];
            }
            auto got = p;
            if (t.flip_h) {
                got[0] = -got[0];
            }
            if (t.flip_v) {
                got[1] = -got[1];
            }
            for (int k = 0; k < t.angle / 90; ++k) {
                got = {-got[1], got[0]};   // a quarter turn clockwise, y down
            }
            CHECK(got == want);
        }
    }
}

// A sheet render_sprites.py made from the golden rigged character (#290): rows are directions, columns frames, so a
// clip's rects sit on its own row of a shared sheet. The importer loads it as it loads Dotwork's packs.
TEST_CASE("dotwork assets: a sheet render_sprites rendered loads as its expected.json") {
    const dw::Pack pack = dw::load_manifest(golden("character/sprites/dotwork/character.assets.json"));
    REQUIRE_MESSAGE(pack.ok(), "the rendered manifest has errors: " << (pack.errors.empty() ? "" : pack.errors.front()));
    CHECK(pack.warnings.empty());
    const json expected = load_json(golden("character/sprites/expected.json"));
    const json got = loaded_result(pack);
    REQUIRE(expected.at("assets").size() == got.size());
    for (const auto& [key, want] : expected.at("assets").items()) {
        INFO("asset " << key);
        REQUIRE_MESSAGE(got.contains(key), key << " was not loaded");
        std::string why;
        CHECK_MESSAGE(same(want, got.at(key), key, why), why);
    }
    for (const auto& p : dw::check_files(pack)) {
        FAIL_CHECK(p);
    }
}

TEST_CASE("dotwork assets: every manifest in the game loads") {
    const auto manifests = dw::find_manifests(core::path_from_utf8(GAME_ASSETS_DIR));
    if (manifests.empty()) {
        MESSAGE("no Dotwork manifests in assets/dotwork yet (nothing to check)");
        return;
    }
    for (const auto& path : manifests) {
        const std::string name = core::path_to_utf8(path.filename());
        const dw::Pack pack = dw::load_manifest(path);
        for (const auto& e : pack.errors) {   // errors and warnings name the manifest already
            FAIL_CHECK(e);
        }
        for (const auto& p : dw::check_files(pack)) {
            FAIL_CHECK(name << ": " << p);
        }
        for (const auto& w : pack.warnings) {
            MESSAGE(w);
        }
    }
    MESSAGE("checked " << manifests.size() << " Dotwork manifests");
}
