// ---------------------------------------------------------------------------
// mz_drives.js
// Purpose : The scripted runs of `python tools/dev.py smoke --drive <name>` (#280): functions that smoke.mjs runs
//           inside the page after MZ booted, walking MZ's real screens and printing markers to the console.
// Usage   : python tools/dev.py smoke --drive menus | access | crash
//             menus   MZ's own screens one after another (title, menu, item, skill, equip, status, options, save, load,
//                     game end) on a new game: each must open and survive ten frames. DRIVE_SCREEN <Scene_Name> each.
//             access  the Options screen: every row the kit added (Reduce Motion, Screen Shake, Gentle Flashes, Text
//                     Size, Line Spacing and your extraRows) is turned once with OK, the value must change and reach
//                     ConfigManager.makeData().kit. DRIVE_ROW <symbol> <before> <after> each.
//             crash   plants an error in a scene's update: the run must FAIL (a smoke that cannot fail proves nothing).
//           Each prints DRIVE_START <name> and, when it got to the end, DRIVE_DONE <name>.
// Notes   : Each drive is one self-contained async function (smoke.mjs sends its source into the page, so it may use
//           the page's globals SceneManager, Scene_*, ConfigManager, DataManager and nothing from this file). The
//           tests (tests/drives.test.js) run them against stand-ins for those; against a real MZ project they are
//           NOT yet tried (verify): MZ's scene classes, Window_Options methods and SceneManager.goto are used as
//           the kit knows them from MZ 1.x. A pseudo-locale run and a rebinding screen are not here: MZ has neither
//           screen (ENGINE_FLOW "The shell, juice and accessibility in MZ").
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// ---------------------------------------------------------------------------

async function menus() {
    const wait = (n) => new Promise((done) => {
        let left = n;
        const tick = () => (--left <= 0 ? done() : requestAnimationFrame(tick));
        requestAnimationFrame(tick);
    });
    console.log("DRIVE_START menus");
    DataManager.setupNewGame();
    const screens = [Scene_Title, Scene_Menu, Scene_Item, Scene_Skill, Scene_Equip, Scene_Status, Scene_Options,
        Scene_Save, Scene_Load, Scene_GameEnd];
    for (const screen of screens) {
        SceneManager.goto(screen);
        await wait(10);
        if (!(SceneManager._scene instanceof screen)) throw new Error(`DRIVE_FAIL ${screen.name} did not open`);
        console.log(`DRIVE_SCREEN ${screen.name}`);
    }
    console.log("DRIVE_DONE menus");
}

async function access() {
    const wait = (n) => new Promise((done) => {
        let left = n;
        const tick = () => (--left <= 0 ? done() : requestAnimationFrame(tick));
        requestAnimationFrame(tick);
    });
    console.log("DRIVE_START access");
    DataManager.setupNewGame();
    SceneManager.goto(Scene_Options);
    await wait(10);
    const win = SceneManager._scene._optionsWindow;
    if (!win) throw new Error("DRIVE_FAIL the Options scene has no _optionsWindow");
    let rows = 0;
    for (let i = 0; i < win.maxItems(); i++) {
        const symbol = win.commandSymbol(i);
        if (!symbol.startsWith("kit")) continue;
        const before = ConfigManager[symbol];
        win.select(i);
        win.processOk();
        await wait(2);
        const after = ConfigManager[symbol];
        if (after === before) throw new Error(`DRIVE_FAIL ${symbol} did not change with OK (${before})`);
        const saved = JSON.stringify(ConfigManager.makeData().kit);
        if (!saved) throw new Error(`DRIVE_FAIL ${symbol} is not in the saved config`);
        console.log(`DRIVE_ROW ${symbol} ${before} ${after}`);
        rows++;
    }
    if (rows < 5) throw new Error(`DRIVE_FAIL only ${rows} kit row(s) on the Options screen (GameAccess is not on?)`);
    console.log("DRIVE_DONE access");
}

async function crash() {
    const wait = (n) => new Promise((done) => {
        let left = n;
        const tick = () => (--left <= 0 ? done() : requestAnimationFrame(tick));
        requestAnimationFrame(tick);
    });
    console.log("DRIVE_START crash");
    DataManager.setupNewGame();
    SceneManager.goto(Scene_Options);
    await wait(5);
    SceneManager._scene.update = () => {
        throw new Error("DRIVE_CRASH planted by smoke --drive crash");
    };
    await wait(5);
    console.log("DRIVE_DONE crash");
}

const DRIVES = { menus, access, crash };
const FAILS_ON_PURPOSE = { crash: "DRIVE_CRASH" };     // drive -> the marker that proves the failure was the planted one

if (typeof module === "object" && module.exports) module.exports = { DRIVES, FAILS_ON_PURPOSE };
