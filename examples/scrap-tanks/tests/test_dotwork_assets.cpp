// ---------------------------------------------------------------------------
// test_dotwork_assets.cpp
// Purpose : Holds the Dotwork asset importer (src/core/DotworkAssets) to the spec's golden fixture, and checks that
//           every real manifest of the game loads with all its files.
// Usage   : python tools/dev.py test   (ctest lists each "dotwork assets: ..." case; build/debug/bin/Debug/unit_tests.exe
//           -tc="dotwork*" runs only these)
// Notes   : The fixture is data/golden/dotwork/ (GOLDEN_DIR): its manifest is loaded through the importer, the
//           loaded structs are turned back into the shape of expected.json (the reference loader's result,
//           tools/art/dotwork/assetspec.py expected) and every core-kind entry is compared, numbers within 1e-6.
//           Expected values are read from the file at test time, never copied here. The extra kinds in it must
//           be skipped with a warning. The game's own manifests are <assets>/dotwork/*.assets.json (GAME_ASSETS_DIR):
//           none yet passes with a message; each one found must load without errors and name only files that
//           are there, are PNGs and fit (the stand-in for Dotwork's Godot verify). No window: SDL is not linked.
//
// Pseudocode:
//   load golden manifest -> loaded_result(pack) -> for each expected entry: core kind -> same(expected, got)
//     | extra kind -> a warning names it
//   then the rule tests (cell_mask, clip timing, glyph layout, tile flags) and the game's manifests
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include <algorithm>
#include <array>
#include <cmath>
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
const std::set<std::string> kCoreKinds{"animated_sprite", "sprite", "icon", "portrait",
                                       "tileset", "map", "font", "ui_kit"};

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

// The loaded structs in the shape of expected.json ("kind/name" -> numbers), core kinds only.
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
        json layers = json::object(), terrain = json::object(), objects = json::array();
        for (const auto& L : m.layers) {
            layers[L.name] = L.cells.size();
            if (L.kind != "terrain") {
                continue;
            }
            json cells = json::array();
            for (const auto& c : L.cells) {
                cells.push_back({c.x, c.y, c.mask,
                                 c.tile.atlas < 0 ? json(nullptr) : json::array({c.tile.atlas, c.tile.col, c.tile.row})});
            }
            terrain[L.name] = cells;
        }
        for (const auto& o : m.objects) {
            objects.push_back({o.asset, o.x, o.y});
        }
        out["map/" + m.name] = {{"size", {m.w, m.h}}, {"layers", layers}, {"terrain", terrain}, {"objects", objects}};
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
    std::size_t compared = 0;
    for (const auto& [key, want] : expected.at("assets").items()) {
        const std::string kind = key.substr(0, key.find('/'));
        if (!kCoreKinds.count(kind)) {
            continue;   // extra kinds: the next case checks they were skipped
        }
        ++compared;
        INFO("asset " << key);
        REQUIRE_MESSAGE(got.contains(key), key << " was not loaded");
        std::string why;
        CHECK_MESSAGE(same(want, got.at(key), key, why), why);
    }
    CHECK_MESSAGE(got.size() == compared, "the importer loaded core assets expected.json does not list");
    MESSAGE("compared " << compared << " core assets with expected.json");
}

TEST_CASE("dotwork assets: the extra kinds are skipped with one warning each") {
    const dw::Pack pack = golden_pack();
    const json expected = load_json(golden(kGoldenExpected));
    std::set<std::string> extra;
    for (const auto& [key, want] : expected.at("assets").items()) {
        const std::string kind = key.substr(0, key.find('/'));
        if (!kCoreKinds.count(kind)) {
            extra.insert(kind);
        }
    }
    REQUIRE_FALSE(extra.empty());
    CHECK(pack.warnings.size() == extra.size());
    for (const auto& kind : extra) {
        const bool warned = std::any_of(pack.warnings.begin(), pack.warnings.end(), [&](const std::string& w) {
            return w.find("\"" + kind + "\"") != std::string::npos;
        });
        CHECK_MESSAGE(warned, "no warning for the skipped kind " << kind);
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
