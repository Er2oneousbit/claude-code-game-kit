// ---------------------------------------------------------------------------
// dotworkMz.test.js
// Purpose : The Dotwork-to-MZ converter (tools/dotwork_mz.mjs, tools/pngio.mjs) against the kit's golden asset
//           pack (data/golden/dotwork/): the kinds MZ uses load to expected.json's numbers, the clip and portrait
//           numbers MZ's layouts are cut from come from there, and the images it writes hold those frames where MZ
//           reads them (character, object, face, side-view battler, Window.png, IconSet.png, B tileset).
// Usage   : python tools/dev.py test
// Notes   : Expected numbers come from expected.json (written by Dotwork's assetspec.py, the reference for every
//           engine); MZ's layout numbers (144 px faces, 3 x 4 frames ...) are the converter's constants. Each export
//           runs into a temporary folder, never into game/. MZ itself is not here: these prove the files have MZ's
//           shapes and the right pixels, not that MZ draws them as intended (verify in the editor).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
const { test, before, after } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { expectClose } = require("./support/golden.js");

const GOLDEN = path.resolve(__dirname, "..", "data", "golden", "dotwork");
const MANIFEST = path.join(GOLDEN, "assets", "dotwork", "golden.assets.json");
const TOL = 1e-6;               // ASSET_MANIFEST.md: numbers rounded to 6 decimals, compared within 1e-6
const MZ_KINDS = ["animated_sprite", "sprite", "icon", "portrait", "tileset", "ui_kit"];
const SKIPPED = ["map/yard", "font/tiny", "background/hills", "particles/vfx_embers_particles",
    "transition/transition_wipe", "normal_map/spr_crate_n", "image/logo_golden"];

let mz, png, expected, golden, tmp;
const temps = [];

before(async () => {
    mz = await import("../tools/dotwork_mz.mjs");
    png = await import("../tools/pngio.mjs");
    expected = JSON.parse(fs.readFileSync(path.join(GOLDEN, "expected.json"), "utf8")).assets;
    golden = mz.loadManifest(MANIFEST);
    tmp = () => { const d = fs.mkdtempSync(path.join(os.tmpdir(), "dotwork-mz-")); temps.push(d); return d; };
});
after(() => temps.forEach((d) => fs.rmSync(d, { recursive: true, force: true })));

const assetOf = (kind, name) => golden.doc.assets.find((a) => a.kind === kind && a.name === name);
const img = (rel) => png.readPng(golden.path(rel));

// One export of the golden pack into a temporary project; returns paths, the result and the log lines
function exportInto(root, opts = {}, manifests = [golden]) {
    const paths = mz.projectPaths(root, path.join(root, "game"));
    const lines = [];
    const res = mz.exportAll(paths, manifests, opts, (tag, text) => lines.push(`${tag} ${text}`));
    return { paths, res, lines, out: (rel) => png.readPng(path.join(root, "game", ...rel.split("/"))) };
}

// The pixels of a w x h region of a at (x, y) equal b
function sameRegion(a, x, y, b, where) {
    const region = png.crop(a, x, y, b.width, b.height);
    assert.ok(png.samePixels(region, b), `${where}: pixels differ at ${x},${y} (${b.width}x${b.height})`);
}

// ---- the manifest, as every engine's importer reads it ------------------------------------------------------
test("golden: every kind MZ uses loads to expected.json's numbers", () => {
    const got = mz.expectedOf(golden.doc);
    const keys = Object.keys(expected).filter((k) => MZ_KINDS.includes(k.split("/")[0]));
    assert.ok(keys.length >= 10, "the golden pack should hold every MZ kind");
    for (const k of keys) expectClose(got[k], expected[k], TOL, k);
    assert.deepEqual(Object.keys(got).sort(), keys.sort(), "no other kinds are loaded");
});

test("golden: another major version and unsafe paths are refused", () => {
    const doc = JSON.parse(fs.readFileSync(MANIFEST, "utf8"));
    assert.throws(() => mz.loadManifest(MANIFEST, { ...doc, version: "2.0.0" }), /version 2\.0\.0.*1\.x/);
    assert.throws(() => mz.loadManifest(MANIFEST, { ...doc, format: "other" }), /not a Dotwork asset manifest/);
    const m = mz.loadManifest(MANIFEST, doc);
    for (const bad of ["../x.png", "/x.png", "C:/x.png", "art/../../x.png"]) assert.throws(() => m.path(bad), /unsafe path/);
});

// ---- the numbers MZ's layouts are cut from ------------------------------------------------------------------
test("walk picks: the standing frame in MZ's middle column, Dotwork's strides either side", () => {
    // MZ walks columns 1, 2, 1, 0: column 2 is the stride after Dotwork's frame 0, column 0 the other one
    assert.deepEqual([1, 2, 3, 4, 6, 8].map(mz.walkPicks), [[0, 0, 0], [1, 0, 1], [2, 0, 1], [3, 0, 1], [5, 0, 2], [6, 0, 2]]);
    assert.deepEqual(mz.spreadPicks(3, false), [0, 1, 2]);
    assert.deepEqual(mz.spreadPicks(6, false), [0, 2, 5]);
    assert.deepEqual(mz.spreadPicks(6, true), [0, 2, 4]);
});

test("character plan: hero's MZ frames are expected.json's walk rects and pivots", () => {
    const hero = assetOf("animated_sprite", "hero");
    const plan = mz.characterPlan(hero, 6, 48);
    const want = expected["animated_sprite/hero"];
    assert.equal(plan.action, "walk");
    mz.MZ.charRows.forEach((d) => {
        const clip = want.clips[want.directions.walk[d]];
        assert.deepEqual(plan.picks[d], mz.walkPicks(clip.frames), d);
        plan.rows[d].forEach((f, col) => {
            expectClose(f.rect, clip.rects[plan.picks[d][col]], TOL, `${d} column ${col} rect`);
            expectClose(f.pivot, clip.pivot, TOL, `${d} column ${col} pivot`);
        });
    });
    // 16 x 24 frames at scale 6, feet on the bottom centre: a 96 x 144 cell, so a 288 x 576 "$" sheet
    assert.deepEqual([plan.cell.w, plan.cell.h, ...plan.sheet], [96, 144, 288, 576]);
    assert.equal(plan.cell.cut, false);
    assert.equal(mz.characterPlan(assetOf("animated_sprite", "fx_spark"), 6, 48), null, "an effect is no character");
});

test("face plan: the portrait's expressions as face indexes, neutral first, scaled to 144 px", () => {
    const want = expected["portrait/sage"];
    const plan = mz.facePlan(assetOf("portrait", "sage"));
    const faces = plan.files.flatMap((f) => f.faces);
    assert.deepEqual(faces.map((f) => f.name).sort(), want.expressions);
    assert.equal(faces[0].name, "neutral");
    assert.deepEqual(faces.map((f) => f.index), [0, 1, 2]);
    assert.equal(plan.k, 144 / want.size[0]);
    assert.deepEqual([...plan.offset, ...plan.sheet], [0, 0, 576, 288]);
    assert.match(mz.facePlan({ name: "big", size: [200, 200], expressions: [] }).skip, /never shrunk/);
});

test("icon pick: the size that fits MZ's 32 px cell", () => {
    assert.deepEqual(expected["icon/potion"].sizes, [16, 32]);
    assert.equal(mz.iconPick(assetOf("icon", "potion")).k, 1);
    assert.deepEqual(mz.iconPick({ sizes: [{ size: 16, image: "a" }, { size: 64, image: "b" }] }), { size: 16, image: "a", k: 2 });
    assert.equal(mz.iconPick({ sizes: [{ size: 24, image: "a" }] }), null);
});

test("tileset plan: plain tiles on B (tile 0 left empty), stamps kept whole, terrain left for later", () => {
    const ts = assetOf("tileset", "ground_yard");
    const want = expected["tileset/ground_yard"];
    const plan = mz.tilesetPlan(ts, 6, 48);
    const terrain = ts.atlases.flatMap((a) => a.tiles).filter((t) => "terrain" in t).length;
    assert.equal(Object.keys(plan.tiles).length, want.tiles - terrain, "every tile without a terrain");
    assert.deepEqual(Object.keys(plan.sheets), ["B"]);
    assert.equal(plan.sheets.B[0], "empty");
    // the 1 x 2 door stamp: one above the other in the editor's 8-wide palette
    assert.equal(plan.tiles["4,1,0"].id - plan.tiles["4,0,0"].id, 8);
    assert.equal(plan.tiles["4,0,0"].passable, false);
    assert.equal(plan.tiles["0,0,0"].passable, true);
    assert.ok(plan.notes.some((n) => /terrain tile.*A1 to A4/.test(n)), plan.notes.join("; "));
    assert.deepEqual(mz.tileSlot(0), { col: 0, row: 0 });
    assert.deepEqual(mz.tileSlot(9), { col: 1, row: 1 });
    assert.deepEqual(mz.tileSlot(128), { col: 8, row: 0 });
    assert.deepEqual(mz.tileSlot(255), { col: 15, row: 15 });
    assert.match(mz.tilesetPlan(assetOf("tileset", "iso_isle"), 6, 48).skip, /isometric/);
    assert.match(mz.tilesetPlan(ts, 4, 48).skip, /MZ's tiles are 48 px/);
});

// ---- the images written ------------------------------------------------------------------------------------
test("export: the golden pack's images in MZ's layouts, the right frames in the right cells", () => {
    const { res, out, paths } = exportInto(tmp());
    assert.deepEqual(res.failures, []);
    assert.equal(res.record.scale, 6);
    // character: row 0 (down) column 1 = walk_s frame 0; row 1 (left) column 0 = walk_w frame 3
    const hero = out("img/characters/$hero.png");
    assert.deepEqual([hero.width, hero.height], [288, 576]);
    sameRegion(hero, 96, 0, png.scale(img("art/characters/hero/frames/spr_hero_walk_s_00.png"), 6), "down, standing");
    sameRegion(hero, 0, 144, png.scale(img("art/characters/hero/frames/spr_hero_walk_w_03.png"), 6), "left, column 0");
    sameRegion(hero, 192, 432, png.scale(img("art/characters/hero/frames/spr_hero_walk_n_01.png"), 6), "up, column 2");
    // prop: an object sheet, the same picture in every cell
    const crate = out("img/characters/!$crate.png");
    assert.deepEqual([crate.width, crate.height], [288, 384]);
    sameRegion(crate, 192, 288, png.scale(img("art/props/spr_crate.png"), 6), "crate, last cell");
    // faces: index 1 = happy
    const face = out("img/faces/sage.png");
    assert.deepEqual([face.width, face.height], [576, 288]);
    sameRegion(face, 144, 0, png.scale(img("art/portraits/spr_sage_portrait_happy.png"), 6), "face 1");
    // IconSet: no MZ project here, so row 0 stays empty and the potion is icon 16
    const icons = out("img/system/IconSet.png");
    assert.equal(res.record.packs.golden.icons.potion, 16);
    sameRegion(icons, 0, 32, img("art/ui/icons/ui_icon_potion_32.png"), "icon 16");
    // Window.png: the window part 1:1 (a ui_kit is already at its scale): its 3 px corners on the frame's corners
    const skin = out("img/system/Window.png");
    const part = img("art/ui/windows/ui_window_plain.png");
    assert.deepEqual([skin.width, skin.height], [192, 192]);
    sameRegion(skin, 96, 0, png.crop(part, 0, 0, 3, 3), "frame top-left corner");
    sameRegion(skin, 192 - 3, 96 - 3, png.crop(part, 9, 9, 3, 3), "frame bottom-right corner");
    assert.equal(png.pixel(skin, 150, 48 - 6)[3], 0, "the frame's middle stays free (no border drawn there)");
    sameRegion(skin, 96, 96, png.crop(img("art/ui/windows/ui_button_plain_hover.png"), 0, 0, 2, 2), "cursor corner");
    // B tileset: tile 2 = the first grass tile at 6x
    const B = out("img/tilesets/golden_ground_yard_B.png");
    assert.deepEqual([B.width, B.height], [768, 768]);
    const t = res.record.packs.golden.tilesets.ground_yard.tiles["0,0,0"];
    const slot = mz.tileSlot(t.id);
    sameRegion(B, slot.col * 48, slot.row * 48, png.scale(png.crop(img("art/tiles/yard/base_grass.png"), 0, 0, 8, 8), 6), "grass tile");
    assert.ok(png.pixel(B, 0, 0)[3] === 0, "B's tile 0 stays empty");
    // every file has MZ's shape, and the record names it
    for (const rel of Object.keys(res.record.files)) {
        const i = out(rel);
        assert.equal(mz.shapeProblem(rel, i.width, i.height), null, rel);
    }
    assert.ok(fs.existsSync(paths.record));
});

test("window skin: a ui_kit's scale is never applied again; corners wider than MZ's get a note", () => {
    const part = png.scale(img("art/ui/windows/ui_window_plain.png"), 9);   // as Dotwork ships a kit at scale 9
    const { skin, notes } = mz.composeWindow({ img: part, margins: [27, 27, 27, 27] }, null, null);
    sameRegion(skin, 96, 0, png.crop(part, 0, 0, 24, 24), "1:1, cut at MZ's 24 px corner");
    assert.ok(notes.some((n) => /wider than MZ's 24 px frame corner/.test(n)), notes.join("; "));
    assert.deepEqual(mz.composeWindow({ img: img("art/ui/windows/ui_window_plain.png"), margins: [3, 3, 3, 3] }, null, null).notes, []);
});

test("export: kinds MZ has no place for are skipped with a note each", () => {
    const { res } = exportInto(tmp(), { dryRun: true });
    for (const key of SKIPPED) {
        const [kind, name] = key.split("/");
        assert.ok(res.notes.some((n) => n.includes(`${kind} ${name}:`)), `no note for ${key}`);
    }
    assert.ok(res.notes.some((n) => /iso_isle: isometric/.test(n)));
    assert.ok(res.notes.some((n) => /fx_spark/.test(n)));
    assert.equal(res.written, 7);
});

test("export: a re-run writes nothing; files Dotwork did not write are kept unless --replace", () => {
    const root = tmp();
    const sys = path.join(root, "game", "img", "system");
    fs.mkdirSync(sys, { recursive: true });
    const theirs = png.blank(192, 192);
    png.fill(theirs, 96, 144, 12, 12, [255, 0, 0, 255]);              // text colour 0, as MZ's own skin has one
    png.writePng(path.join(sys, "Window.png"), theirs);
    const mine = png.blank(512, 64, [9, 9, 9, 255]);                  // two rows of icons of the game's own
    png.writePng(path.join(sys, "IconSet.png"), mine);
    const first = exportInto(root);
    assert.equal(first.res.held, 2, first.lines.join("\n"));
    assert.ok(png.samePixels(first.out("img/system/Window.png"), theirs), "kept without --replace");
    const second = exportInto(root, { replace: true });
    assert.equal(second.res.written, 2);
    assert.deepEqual(png.pixel(second.out("img/system/Window.png"), 100, 150), [255, 0, 0, 255], "text colours kept");
    assert.ok(fs.existsSync(path.join(root, "build", "dotwork_mz", "originals", "img", "system", "Window.png")));
    const icons = second.out("img/system/IconSet.png");
    assert.deepEqual([icons.width, icons.height], [512, 96]);
    assert.equal(second.res.record.packs.golden.icons.potion, 32, "after the game's two rows");
    sameRegion(icons, 0, 0, mine, "the game's icons");
    const third = exportInto(root);
    assert.deepEqual([third.res.written, third.res.held], [0, 0], third.lines.join("\n"));
    assert.equal(third.out("img/system/IconSet.png").height, 96, "a re-run replaces only its own rows");
});

test("export: --sheet packs characters into MZ's 4 x 2 normal sheet", () => {
    const { res, out } = exportInto(tmp(), { sheet: "Actors", only: ["characters"] });
    const sheet = out("img/characters/Actors.png");
    assert.deepEqual([sheet.width, sheet.height], [96 * 12, 144 * 8]);
    assert.deepEqual(res.record.packs.golden.characters.hero, { file: "Actors", index: 0, from: "walk",
        frames: { s: [3, 0, 1], w: [3, 0, 1], e: [3, 0, 1], n: [3, 0, 1] }, cell: [96, 144] });
    assert.equal(mz.shapeProblem("img/characters/Actors.png", sheet.width, sheet.height), null);
});

test("side view: battle poses become MZ's 9 x 6 battler sheet; front-view games skip it", () => {
    const doc = JSON.parse(fs.readFileSync(MANIFEST, "utf8"));
    const hero = doc.assets.find((a) => a.kind === "animated_sprite" && a.name === "hero");
    const still = (name, from) => ({ ...hero.clips.find((c) => c.name === from), name, loop: true });
    hero.clips.push(still("ready_w", "idle_w"), still("ko_w", "idle_w"));   // stand-ins for Dotwork's battle stills
    const m = mz.loadManifest(MANIFEST, doc);
    const front = exportInto(tmp(), { only: ["sv"] }, [m]);
    assert.ok(front.res.notes.some((n) => /front-view game/.test(n)));
    const { res, out } = exportInto(tmp(), { only: ["sv"], sideView: true }, [m]);
    const sv = out("img/sv_actors/hero.png");
    const plan = mz.svPlan(m.doc.assets.find((a) => a.name === "hero"), 6);
    assert.deepEqual([sv.width, sv.height], [plan.cell.w * 9, plan.cell.h * 6]);
    const motions = res.record.packs.golden.sv_actors.hero.motions;
    // hero has attack_e only and no cast: swing and chant fall back to wait; escape runs east
    assert.deepEqual([motions.walk, motions.wait, motions.swing, motions.escape, motions.dead, motions.chant],
        ["walk_w", "ready_w", "ready_w", "walk_e", "ko_w", "ready_w"]);
    assert.ok(res.record.packs.golden.sv_actors.hero.missing.includes("swing"));
    // wait is motion 1: column 0, row 1; its middle frame is idle_w frame 1 at 6x, feet on the cell's bottom
    const f = png.scale(img("art/characters/hero/frames/spr_hero_idle_w_01.png"), 6);
    sameRegion(sv, plan.cell.w + (plan.cell.w - f.width) / 2, plan.cell.h + plan.cell.h - f.height, f, "wait, frame 1");
    assert.equal(mz.shapeProblem("img/sv_actors/hero.png", sv.width, sv.height), null);
});

test("check: the record against the files and MZ's shapes", () => {
    const root = tmp();
    const { paths } = exportInto(root);
    assert.deepEqual(mz.checkExport(paths, [golden])[0], []);
    fs.rmSync(path.join(root, "game", "img", "faces", "sage.png"));
    png.writePng(path.join(root, "game", "img", "characters", "$hero.png"), png.blank(100, 100));
    const [problems, warnings] = mz.checkExport(paths, [golden]);
    assert.ok(problems.some((p) => /sage\.png is missing/.test(p)), problems.join("; "));
    assert.ok(problems.some((p) => /\$hero\.png: 100x100 does not split into 3 x 4/.test(p)), problems.join("; "));
    assert.ok(warnings.some((w) => /\$hero\.png changed/.test(w)));
    assert.match(mz.shapeProblem("img/system/IconSet.png", 500, 64), /16 columns/);
    assert.match(mz.shapeProblem("img/characters/Actors.png", 290, 384), /12 x 8/);
    assert.equal(mz.shapeProblem("img/characters/Actors.png", 576, 384), null);
});

test("command line: options are checked before anything runs", () => {
    assert.throws(() => mz.parseArgs(["--scale", "1.5"]), /whole number/);
    assert.throws(() => mz.parseArgs(["--only", "maps"]), /unknown maps/);
    assert.throws(() => mz.parseArgs(["--sheet", "../x"]), /plain file name/);
    assert.throws(() => mz.parseArgs(["--bogus"]), /unknown option/);
    assert.deepEqual(mz.parseArgs(["--only", "faces,icons", "--replace"]).only, ["faces", "icons"]);
});

// ---- the PNG codec --------------------------------------------------------------------------------------------
test("png: every golden image survives a write and a read; damaged files are refused", () => {
    for (const rel of ["art/characters/hero/hero_walk_s_sheet.png", "art/tiles/yard/overlay_water.png", "art/ui/fonts/font_tiny.png"]) {
        const a = img(rel);
        assert.ok(png.samePixels(png.decodePng(png.encodePng(a)), a), rel);
    }
    const bytes = png.encodePng(img("art/props/spr_crate.png"));
    assert.throws(() => png.decodePng(bytes.subarray(0, 40), "cut"), /cut short|does not inflate|shorter/);
    assert.throws(() => png.decodePng(Buffer.from("not a png at all"), "text"), /not a PNG/);
    assert.deepEqual(png.pixel(png.scale(png.blank(1, 1, [1, 2, 3, 4]), 3), 2, 2), [1, 2, 3, 4]);
});

// {{FOOTER}}
