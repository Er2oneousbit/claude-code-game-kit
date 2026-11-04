// ---------------------------------------------------------------------------
// SaveStore.cs
// Purpose : Save slots that survive crashes, corruption and game updates: a versioned envelope, a migration
//           chain from every old version, a fallback to the .bak copy, and a refusal to load (or overwrite)
//           a save made by a newer build. Checked against data/golden/shell.json ("save_load").
// Usage   : var saves = new SaveStore(Application.persistentDataPath);
//           SaveLoadResult r = saves.Load(1);       // r.Data (null = nothing usable), r.Source, r.Problems
//           saves.Save(1, new Dictionary<string, object> { { "level", 3.0 }, { "health", 9.0 } });
//           pure parts: SaveStore.LoadFromText(primaryText, backupText), SaveStore.Migrate(envelope)
// Notes   : No UnityEngine types (EditMode tests run it, also against the real filesystem). The file is
//           {"format": "save", "version": N, "data": {...}} as a JSON value tree (Json.cs, numbers are double).
//           MIGRATIONS is the TEMPLATE chain the kit's vectors test (v2 renamed hp to health, v3 added
//           difficulty): when your save data changes shape, bump SAVE_VERSION and add one step (SOP-19). Never
//           edit an old migration; old saves in the wild still need it. Save throws after a "newer" load, so an
//           old build never destroys progress from a newer one.
//
// Pseudocode (LoadFromText):
//   for primary, then backup: parse -> missing | unreadable | not a save | bad version | newer -> next
//   the first good one is migrated step by step up to SAVE_VERSION and returned with its source
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;

namespace graveyard_shift.Core
{
    public sealed class SaveLoadResult
    {
        public Dictionary<string, object> Envelope;    // null when neither file was usable
        public string Source;                          // "primary", "backup" or "none"
        public List<string> Problems;                  // "primary: unreadable", "backup: missing", ...

        public Dictionary<string, object> Data => Envelope != null ? Envelope["data"] as Dictionary<string, object> : null;
    }

    public sealed class SaveStore
    {
        // ---- Tunables ------------------------------------------------------------
        public const int SAVE_VERSION = 3;
        public const string SAVE_FORMAT = "save";
        public const string FILE_PATTERN = "save_{0}.json";
        public const string SOURCE_PRIMARY = "primary";
        public const string SOURCE_BACKUP = "backup";
        public const string SOURCE_NONE = "none";
        public const string PROBLEM_NEWER = "newer";

        /// <summary>MIGRATIONS[n] turns version-n data into version n+1 data (TEMPLATE chain, see Notes).</summary>
        public static readonly Dictionary<int, Func<Dictionary<string, object>, Dictionary<string, object>>> MIGRATIONS =
            new Dictionary<int, Func<Dictionary<string, object>, Dictionary<string, object>>>
            {
                { 1, data =>
                    {
                        if (data.TryGetValue("hp", out object hp))     // v2 renamed hp to health
                        {
                            data.Remove("hp");
                            data["health"] = hp;
                        }
                        return data;
                    }
                },
                { 2, data =>
                    {
                        if (!data.ContainsKey("difficulty"))           // v3 added the difficulty the game was started on
                        {
                            data["difficulty"] = "normal";
                        }
                        return data;
                    }
                },
            };

        // ---- Pure parts (no files) -------------------------------------------------------

        /// <summary>The envelope (version made a whole number), or null with problem set to missing, unreadable,
        /// not a save, bad version or newer.</summary>
        public static Dictionary<string, object> ParseSave(string text, out string problem)
        {
            problem = "";
            if (text == null)
            {
                problem = "missing";
                return null;
            }
            if (!Json.TryParse(text, out object parsed))
            {
                problem = "unreadable";
                return null;
            }
            if (!(parsed is Dictionary<string, object> env)
                || !(env.TryGetValue("format", out object format) && format is string f && f == SAVE_FORMAT)
                || !(env.TryGetValue("data", out object data) && data is Dictionary<string, object>))
            {
                problem = "not a save";
                return null;
            }
            env.TryGetValue("version", out object version);
            double v = Json.IsNumber(version) ? Json.ToNumber(version) : double.NaN;
            if (double.IsNaN(v) || double.IsInfinity(v) || v != Math.Floor(v) || v < 1)
            {
                problem = "bad version";
                return null;
            }
            if (v > SAVE_VERSION)
            {
                problem = PROBLEM_NEWER;
                return null;
            }
            env["version"] = v;
            return env;
        }

        /// <summary>A copy of the envelope, migrated step by step up to SAVE_VERSION.</summary>
        public static Dictionary<string, object> Migrate(Dictionary<string, object> envelope)
        {
            var env = (Dictionary<string, object>)Json.DeepCopy(envelope);
            int version = (int)Json.ToNumber(env["version"]);
            while (version < SAVE_VERSION)
            {
                if (!MIGRATIONS.TryGetValue(version, out var step))
                {
                    throw new InvalidOperationException($"no save migration from version {version}");
                }
                env["data"] = step((Dictionary<string, object>)env["data"]);
                version++;
                env["version"] = (double)version;
            }
            return env;
        }

        /// <summary>The newest usable save from the two files' text (null = that file is missing).</summary>
        public static SaveLoadResult LoadFromText(string primary, string backup)
        {
            var problems = new List<string>();
            string[] sources = { SOURCE_PRIMARY, SOURCE_BACKUP };
            string[] texts = { primary, backup };
            for (int i = 0; i < sources.Length; i++)
            {
                Dictionary<string, object> env = ParseSave(texts[i], out string problem);
                if (env != null)
                {
                    return new SaveLoadResult { Envelope = Migrate(env), Source = sources[i], Problems = problems };
                }
                problems.Add(sources[i] + ": " + problem);
            }
            return new SaveLoadResult { Envelope = null, Source = SOURCE_NONE, Problems = problems };
        }

        /// <summary>The file text for data at SAVE_VERSION (one-space indent).</summary>
        public static string EnvelopeText(Dictionary<string, object> data)
        {
            var env = new Dictionary<string, object>
            {
                { "format", SAVE_FORMAT }, { "version", (double)SAVE_VERSION }, { "data", data },
            };
            return Json.Stringify(env, 1) + "\n";
        }

        // ---- Slots on disk ---------------------------------------------------------------------

        private readonly string _folder;
        private readonly HashSet<string> _newer = new HashSet<string>();

        /// <summary>Slots as save_&lt;slot&gt;.json in folder (Application.persistentDataPath in a game).</summary>
        public SaveStore(string folder)
        {
            _folder = folder;
        }

        public string PathFor(string slot)
        {
            return Path.Combine(_folder, string.Format(CultureInfo.InvariantCulture, FILE_PATTERN, slot));
        }

        public SaveLoadResult Load(int slot)
        {
            return Load(slot.ToString(CultureInfo.InvariantCulture));
        }

        public SaveLoadResult Load(string slot)
        {
            string path = PathFor(slot);
            SaveLoadResult result = LoadFromText(AtomicFile.ReadOrNull(path), AtomicFile.ReadOrNull(path + AtomicFile.BAK_SUFFIX));
            if (result.Problems.Exists(p => p.EndsWith(": " + PROBLEM_NEWER, StringComparison.Ordinal)))
            {
                _newer.Add(path);
            }
            else
            {
                _newer.Remove(path);
            }
            return result;
        }

        public void Save(int slot, Dictionary<string, object> data)
        {
            Save(slot.ToString(CultureInfo.InvariantCulture), data);
        }

        /// <summary>Writes the slot atomically (keeps the previous good save as .bak). Throws
        /// InvalidOperationException while the slot or its .bak holds a save from a newer build of the game.</summary>
        public void Save(string slot, Dictionary<string, object> data)
        {
            string path = PathFor(slot);
            ParseSave(AtomicFile.ReadOrNull(path), out string problem);
            ParseSave(AtomicFile.ReadOrNull(path + AtomicFile.BAK_SUFFIX), out string backupProblem);
            if (_newer.Contains(path) || problem == PROBLEM_NEWER || backupProblem == PROBLEM_NEWER)
            {
                throw new InvalidOperationException($"{path} was written by a newer version of the game: not overwriting it");
            }
            AtomicFile.Write(path, EnvelopeText(data), true, old => ParseSave(old, out _) != null);
        }
    }
}
