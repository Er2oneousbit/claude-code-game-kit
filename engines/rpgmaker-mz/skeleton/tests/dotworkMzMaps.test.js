// ---------------------------------------------------------------------------
// dotworkMzMaps.test.js
// Purpose : Dotwork terrain and maps into RPG Maker MZ (tools/dotwork_mz_maps.mjs, #286): the autotile shapes
//           against RPG Maker's own floor table, the golden pack's blob terrain as A1 / A2 autotiles that rebuild
//           every Dotwork tile pixel for pixel, its maps as data/MapNNN.json that an MZ-style renderer draws exactly
//           as expected.json places them, the database entries (append only, re-runs write nothing, the user's
//           entries untouched), battle backs and parallaxes.
// Usage   : python tools/dev.py test
// Notes   : MZ itself is not here. The renderer below reads MZ's map data, tileset entry and sheets the way RPG
//           Maker MV's corescript (rpg_core/Tilemap.js, MIT) draws them: _drawNormalTile for B to E, _drawAutotile
//           with FLOOR_AUTOTILE_TABLE for A1 (frame 0) and A2. Whether MZ's editor shows the same is (verify).
//           Expected cells come from expected.json (assetspec.py, the reference), never from the converter.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
const { test, before, after } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const GOLDEN = path.resolve(__dirname, "..", "data", "golden", "dotwork");
const MANIFEST = path.join(GOLDEN, "assets", "dotwork", "golden.assets.json");
const K = 6;          // the golden pack's 8 px tiles at MZ's 48
const TILE = 48;

let mz, maps, png, expected, golden, tmp;
const temps = [];

before(async () => {
    mz = await import("../tools/dotwork_mz.mjs");
    maps = await import("../tools/dotwork_mz_maps.mjs");
    png = await import("../tools/pngio.mjs");
    expected = JSON.parse(fs.readFileSync(path.join(GOLDEN, "expected.json"), "utf8")).assets;
    golden = mz.loadManifest(MANIFEST);
    tmp = () => { const d = fs.mkdtempSync(path.join(os.tmpdir(), "dotwork-mz-maps-")); temps.push(d); return d; };
});
after(() => temps.forEach((d) => fs.rmSync(d, { recursive: true, force: true })));

const assetOf = (kind, name) => golden.doc.assets.find((a) => a.kind === kind && a.name === name);
const load = (rel) => png.readPng(golden.path(rel));

// A project with MZ's database as a new MZ project has it: one tileset, one map
function fakeProject(root) {
    const data = path.join(root, "game", "data");
    fs.mkdirSync(data, { recursive: true });
    fs.writeFileSync(path.join(data, "Tilesets.json"), '[\nnull,\n{"id":1,"flags":[],"mode":1,"name":"Field","note":"","tilesetNames":["","","","","","","","",""]}\n]');
    fs.writeFileSync(path.join(data, "MapInfos.json"), '[\nnull,\n{"id":1,"expanded":false,"name":"MAP001","order":1,"parentId":0,"scrollX":0,"scrollY":0}\n]');
    fs.writeFileSync(path.join(data, "Map001.json"), '{"width":17,"height":13,"data":[]}');
    return root;
}

function exportInto(root, opts = {}) {
    const paths = mz.projectPaths(root, path.join(root, "game"));
    const lines = [];
    const res = mz.exportAll(paths, [golden], opts, (tag, text) => lines.push(`${tag} ${text}`));
    return { paths, res, lines };
}

const readData = (root, rel) => JSON.parse(fs.readFileSync(path.join(root, "game", "data", rel), "utf8"));

// ---- MZ's way of drawing a map (RPG Maker MV corescript, rpg_core/Tilemap.js) -------------------------------
function drawMzMap(root, map) {
    const sets = readData(root, "Tilesets.json");
    const names = sets[map.tilesetId].tilesetNames;
    const sheet = (i) => (names[i] ? png.readPng(path.join(root, "game", "img", "tilesets", `${names[i]}.png`)) : null);
    const bitmaps = [0, 1, 2, 3, 4, 5, 6, 7, 8].map(sheet);   // A1 A2 A3 A4 A5 B C D E
    const out = png.blank(map.width * TILE, map.height * TILE);
    const h = TILE / 2;
    for (let z = 0; z < 4; z++) {
        for (let y = 0; y < map.height; y++) {
            for (let x = 0; x < map.width; x++) {
                const id = map.data[(z * map.height + y) * map.width + x];
                if (!id) continue;
                const cell = png.blank(TILE, TILE);
                if (id >= 2048) {   // _drawAutotile, animation frame 0
                    const kind = Math.floor((id - 2048) / 48), shape = (id - 2048) % 48;
                    const tx = kind % 8, ty = Math.floor(kind / 8);
                    let bx, by, src;
                    if (id < 2816) {
                        src = bitmaps[0];
                        if (kind === 0) [bx, by] = [0, 0];
                        else if (kind === 1) [bx, by] = [0, 3];
                        else [bx, by] = [Math.floor(tx / 4) * 8, ty * 6 + (Math.floor(tx / 2) % 2) * 3];
                    } else {
                        src = bitmaps[1];
                        [bx, by] = [tx * 2, (ty - 2) * 3];
                    }
                    maps.FLOOR_AUTOTILE_TABLE[shape].forEach(([qsx, qsy], i) => {
                        png.blit(cell, png.crop(src, (bx * 2 + qsx) * h, (by * 2 + qsy) * h, h, h), (i % 2) * h, Math.floor(i / 2) * h);
                    });
                } else if (id < 1024) {   // _drawNormalTile: B to E
                    const src = bitmaps[5 + Math.floor(id / 256)];
                    const sx = ((Math.floor(id / 128) % 2) * 8 + (id % 8)) * TILE, sy = (Math.floor((id % 256) / 8) % 16) * TILE;
                    png.blit(cell, png.crop(src, sx, sy, TILE, TILE), 0, 0);
                } else {
                    assert.fail(`tile id ${id} is on a sheet the converter does not write`);
                }
                png.blit(out, cell, x * TILE, y * TILE, true);
            }
        }
    }
    return out;
}

// The Dotwork map as expected.json places it (layer by layer, each cell's image at its left / top), at scale K
function drawDotworkMap(name) {
    const want = expected[`map/${name}`];
    const map = assetOf("map", name);
    const ts = assetOf("tileset", map.tileset);
    const out = png.blank(want.size[0] * want.tile_size[0] * K, want.size[1] * want.tile_size[1] * K);
    for (const L of map.layers) {
        for (const [, , a, c, r, left, top] of want.placed[L.name]) {
            const at = ts.atlases.find((x) => x.id === a);
            const [tw, th] = at.tile_size;
            png.blit(out, png.scale(png.crop(load(at.image), c * tw, r * th, tw, th), K), left * K, top * K, true);
        }
    }
    return out;
}

// ---- the shapes ---------------------------------------------------------------------------------------------
test("shapes: every one of Dotwork's 47 blob masks has its own row of RPG Maker's floor table", () => {
    assert.equal(maps.BLOB.length, 47);
    const shapes = maps.BLOB.map((m) => maps.shapeOf(m));
    assert.ok(shapes.every((s) => Number.isInteger(s) && s >= 0 && s <= 46), JSON.stringify(shapes));
    assert.equal(new Set(shapes).size, 47, "one shape per mask");
    assert.equal(maps.shapeOf(255), 0, "all eight neighbours: the inside");
    assert.equal(maps.shapeOf(0), 46, "a lone cell: four outer corners");
    assert.equal(maps.shapeOf(255 & ~128), 1, "all but the top-left corner: shape 1 (top-left inner corner)");
    assert.equal(maps.shapeOf(1 | 4 | 16 | 2 | 8), 16, "no west neighbour: the left edge (16)");
    // every quarter a table row reads sits where QUARTER_SOURCES says that quarter position reads from
    maps.FLOOR_AUTOTILE_TABLE.slice(0, 47).forEach((row, s) => row.forEach((q, i) => {
        assert.ok(Object.values(maps.QUARTER_SOURCES[i]).some((p) => p[0] === q[0] && p[1] === q[1]), `shape ${s} quarter ${i}`);
    }));
});

test("tile ids: RPG Maker's bases, 48 ids per kind, the blocks each kind is drawn from", () => {
    assert.deepEqual([maps.TILE_ID.A1, maps.TILE_ID.A2, maps.TILE_ID.A5, maps.KIND_IDS], [2048, 2816, 1536, 48]);
    assert.equal(maps.kindBase("A2", 1), 2864);
    assert.equal(maps.autotileId("A2", 0, 255), 2816);
    assert.deepEqual(maps.kindBlocks("A2", 9), [[2, 3]]);
    assert.deepEqual(maps.kindBlocks("A1", 0), [[0, 0], [2, 0], [4, 0]]);
    assert.deepEqual(maps.kindBlocks("A1", 1), [[0, 3], [2, 3], [4, 3]]);
    assert.deepEqual(maps.kindBlocks("A1", 4), [[8, 0], [10, 0], [12, 0]]);
    assert.equal(maps.kindBlocks("A1", 5), null, "a waterfall");
});

test("rules: the converter's terrain resolution is the spec's (hash and roll vectors)", () => {
    assert.deepEqual([maps.hash32(0), maps.hash32(1), maps.hash32(0xffffffff)], [1800329511, 3028713910, 4268016002]);
    assert.equal(Math.round(maps.cellRoll(3, 1, 1) * 1e6) / 1e6, 0.765973);
    assert.equal(Math.round(maps.cellRoll(-1, -1, 0) * 1e6) / 1e6, 0.992978);
});

// ---- autotiles ----------------------------------------------------------------------------------------------
test("autotiles: the yard's path is A2 kind 0, its animated water A1 kind 0, and every tile comes back exactly", () => {
    const ts = assetOf("tileset", "ground_yard");
    const auto = maps.autotilePlan(ts, load);
    assert.deepEqual(Object.keys(auto.terrains).sort(), ["0/1", "0/2"]);
    const path_ = auto.terrains["0/1"], water = auto.terrains["0/2"];
    assert.deepEqual([path_.sheet, path_.kind, path_.base, path_.impassable], ["A2", 0, 2816, false]);
    assert.deepEqual([water.sheet, water.kind, water.base, water.impassable, water.blocks.length], ["A1", 0, 2048, true, 3]);
    for (const [key, t] of Object.entries(auto.terrains)) {
        for (const m of maps.BLOB) {
            const ref = t.refs.get(m);
            const at = ts.atlases.find((a) => a.id === ref[0]);
            for (let f = 0; f < t.blocks.length; f++) {
                const frame = f % (ts.atlases.find((a) => a.id === ref[0]).tiles[0].anim?.frames ?? 1);
                const tile = png.crop(load(at.image), (ref[1] + frame) * 8, ref[2] * 8, 8, 8);
                assert.ok(png.samePixels(maps.drawShape(t.blocks[f], maps.shapeOf(m), 8), tile), `${key} mask ${m} frame ${f}`);
            }
        }
    }
    // the sheet MZ reads: the A2 block at 6x where kind 0 sits, A1 frames 0, 1, 2 side by side
    const a2 = maps.composeAutotileSheet(auto, "A2", K, TILE);
    assert.deepEqual([a2.width, a2.height], [768, 576]);
    assert.ok(png.samePixels(png.crop(a2, 0, 0, 96, 144), png.scale(path_.blocks[0], K)));
    const a1 = maps.composeAutotileSheet(auto, "A1", K, TILE);
    assert.ok(png.samePixels(png.crop(a1, 96, 0, 96, 144), png.scale(water.blocks[1], K)), "A1 frame 1");
    // sides4 and corners4 terrain are not MZ autotiles: their tiles go on B to E with a note
    assert.match(maps.autotilePlan(assetOf("tileset", "meadow"), load).notes.join(";"), /corners4 terrain is not blob-shaped/);
});

test("autotiles: art that does not split into quarters stays B to E tiles", () => {
    const ts = assetOf("tileset", "ground_yard");
    const broken = (rel) => {
        const img = load(rel);
        if (!rel.endsWith("overlay_path.png")) return img;
        const copy = png.crop(img, 0, 0, img.width, img.height);
        png.fill(copy, 8 + 3, 3, 2, 2, [255, 0, 255, 255]);   // a dot across the quarter lines of path tile (1, 0), mask 1
        return copy;
    };
    const auto = maps.autotilePlan(ts, broken);
    assert.deepEqual(Object.keys(auto.terrains), ["0/2"], "the path is no autotile any more");
    assert.match(auto.notes.join(";"), /path: the tile for mask \d+ does not split into MZ's quarter tiles/);
    const plan = mz.tilesetPlan(ts, K, TILE, maps.autotiledTiles(auto));
    assert.ok(plan.tiles["1,1,0"], "the path's tiles are B tiles now");
});

// ---- maps ---------------------------------------------------------------------------------------------------
test("maps: every square golden map loads to expected.json's cells", () => {
    const got = mz.expectedOf(golden.doc);
    const keys = Object.keys(expected).filter((k) => k.startsWith("map/") && expected[k].shape === "square");
    assert.deepEqual(keys.sort(), ["map/atlas_order_check", "map/meadow_patch", "map/yard"]);
    for (const k of keys) assert.deepEqual(got[k], expected[k], k);
    assert.equal(got["map/isle"], undefined, "an isometric map is not MZ's");
});

test("maps: MZ's map data, tileset and sheets draw every square golden map as Dotwork places it", () => {
    const root = fakeProject(tmp());
    const { res } = exportInto(root);
    assert.deepEqual(res.failures, []);
    for (const name of ["yard", "meadow_patch", "atlas_order_check"]) {
        const rec = res.record.packs.golden.maps[name];
        assert.ok(rec, `${name} converted`);
        const map = readData(root, path.basename(rec.file));
        const mine = drawMzMap(root, map), want = drawDotworkMap(name);
        assert.deepEqual([mine.width, mine.height], [want.width, want.height]);
        assert.ok(png.samePixels(mine, want), `${name}: MZ's drawing differs from Dotwork's`);
    }
    // the yard: path and water as autotiles, the crate an event with its object sheet, water blocked
    const yard = readData(root, path.basename(res.record.packs.golden.maps.yard.file));
    const ids = new Set(yard.data);
    assert.ok([...ids].some((id) => id >= 2816 && id < 2864), "path autotile ids");
    assert.ok([...ids].some((id) => id >= 2048 && id < 2096), "water autotile ids");
    assert.equal(yard.events[1].pages[0].image.characterName, "!$crate");
    assert.deepEqual([yard.events[1].x, yard.events[1].y], [1, 4], "the crate's feet at (12, 40): cell (1, 4)");
    const set = readData(root, "Tilesets.json")[yard.tilesetId];
    assert.equal(set.flags[2048 + 46], maps.IMPASSABLE, "water blocks");
    assert.equal(set.flags[2816], 0, "the path is walkable");
    assert.equal(set.flags[0], maps.STAR, "B's empty tile");
});

test("database: entries appended after MZ's own, a re-run writes nothing, the user's entries are kept", () => {
    const root = fakeProject(tmp());
    const first = exportInto(root);
    const infos = readData(root, "MapInfos.json"), sets = readData(root, "Tilesets.json");
    assert.equal(infos[1].name, "MAP001", "MZ's own map kept");
    assert.equal(sets[1].name, "Field", "MZ's own tileset kept");
    assert.deepEqual(Object.values(first.res.record.data.maps).sort(), [2, 3, 4]);
    assert.ok(Object.values(first.res.record.data.tilesets).every((id) => id >= 2));
    assert.deepEqual(infos.slice(2).map((e) => e.order), [2, 3, 4]);
    const again = exportInto(root);
    assert.deepEqual([again.res.written, again.res.held], [0, 0], again.lines.join("\n"));
    // the user renames the yard map's tileset in MZ and drops the <dotwork> note: the next export leaves it alone
    const yardSet = first.res.record.packs.golden.maps.yard.tileset_id;
    sets[yardSet].note = "mine now";
    fs.writeFileSync(path.join(root, "game", "data", "Tilesets.json"), maps.dataText(sets));
    const third = exportInto(root);
    const after = readData(root, "Tilesets.json");
    assert.equal(after[yardSet].note, "mine now");
    assert.notEqual(third.res.record.packs.golden.maps.yard.tileset_id, yardSet, "the yard gets a tileset of its own again");
    // a map edited in MZ is kept without --replace
    const yardFile = path.join(root, "game", third.res.record.packs.golden.maps.yard.file);
    fs.writeFileSync(yardFile, fs.readFileSync(yardFile, "utf8").replace('"note":"<dotwork>"', '"note":"edited"'));
    const fourth = exportInto(root);
    assert.match(fourth.res.notes.join("\n"), /map yard: .*changed in MZ since the export; kept/);
    assert.match(fs.readFileSync(yardFile, "utf8"), /"edited"/);
    // the held map keeps its id on record: the next run makes no second copy of it
    assert.equal(fourth.res.record.data.maps["golden/yard"], third.res.record.data.maps["golden/yard"]);
    const files = () => fs.readdirSync(path.join(root, "game", "data")).filter((n) => /^Map\d+\.json$/.test(n)).sort();
    const before = files(), rows = readData(root, "MapInfos.json").length;
    const fifth = exportInto(root);
    assert.deepEqual(files(), before, "no new map file");
    assert.equal(readData(root, "MapInfos.json").length, rows, "no new MapInfos row");
    assert.equal(fifth.res.record.data.maps["golden/yard"], third.res.record.data.maps["golden/yard"]);
    // --check reads the map files as MZ's maps
    assert.deepEqual(mz.checkExport(fourth.paths, [golden])[0], []);
});

test("database: --dry-run writes nothing; no MZ database leaves the maps out with a note", () => {
    const root = fakeProject(tmp());
    const before = fs.readFileSync(path.join(root, "game", "data", "Tilesets.json"), "utf8");
    const dry = exportInto(root, { dryRun: true });
    assert.equal(fs.readFileSync(path.join(root, "game", "data", "Tilesets.json"), "utf8"), before);
    assert.ok(!fs.existsSync(path.join(root, "game", "data", "Map002.json")));
    assert.ok(dry.lines.some((l) => /would write data\/Map00\d\.json/.test(l)));
    const bare = exportInto(tmp());
    assert.match(bare.res.notes.join("\n"), /maps: no MZ database .* 3 map\(s\) not written/);
});

// ---- backgrounds --------------------------------------------------------------------------------------------
test("backgrounds: a battle background becomes MZ's two battle backs at one whole factor covering the screen", () => {
    const root = fakeProject(tmp());
    const { res } = exportInto(root);
    const bb = res.record.packs.golden.battlebacks.hills;
    const want = expected["background/hills"].layers;   // [w, h, vx, vy, repeat]
    assert.equal(bb.factor, Math.max(Math.ceil(816 / want[0][0]), Math.ceil(624 / want[0][1])));
    const back1 = png.readPng(path.join(root, "game", "img", "battlebacks1", `${bb.battleback1}.png`));
    const back2 = png.readPng(path.join(root, "game", "img", "battlebacks2", `${bb.battleback2}.png`));
    assert.ok(back1.width >= 816 && back1.height >= 624);
    assert.ok(png.samePixels(back1, png.scale(load(assetOf("background", "hills").layers[0].image), bb.factor)));
    // the clouds layer over the floor's factor (it repeats along x; one copy already covers the screen here)
    const clouds = png.scale(load(assetOf("background", "hills").layers[1].image), bb.factor);
    assert.ok(png.samePixels(png.crop(back2, 0, 0, clouds.width, clouds.height), clouds));
    const wide = maps.coverLayer(load(assetOf("background", "hills").layers[1].image), { repeat: "x" }, 2, [816, 624]);
    assert.deepEqual([wide.width, wide.height], [816, 12], "a repeating layer narrower than the screen is tiled across it");
    assert.match(res.notes.join("\n"), /hills: MZ's battle backs stand still/);
    // a background of another role: one parallax per layer at its scale, with MZ's scroll numbers
    const p = maps.parallaxPlan({ name: "sky", layers: [{ image: "a.png", size: [32, 16], velocity: [-4, 0], repeat: "x", scale: 2 }] }, K);
    assert.deepEqual(p[0], { layer: "0", image: "a.png", factor: 12, loop_x: true, loop_y: false, sx: -3, sy: 0 });
});

// {{FOOTER}}
