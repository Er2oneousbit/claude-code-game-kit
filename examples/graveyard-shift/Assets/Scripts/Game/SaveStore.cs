// ---------------------------------------------------------------------------
// SaveStore.cs
// Purpose : Reads and writes the save file (JSON) and runs the migration from Core/SaveData.cs.
// Usage   : var store = new SaveStore(path); SaveV3 data = store.Load(); ... store.Write(data);
// Notes   : Default path: Application.persistentDataPath/save.json. A broken or newer file is kept
//           aside as save.json.bad (never silently overwritten) and the game starts fresh.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fix (Claude Opus 5.5): a broken save.json.tmp with no save.json is the file kept as
//           .bad (the old code copied the missing save.json and threw: a black window on every launch), and the
//           .tmp is set aside so the next launch does not read it again.
// ---------------------------------------------------------------------------
using System;
using System.IO;
using graveyard_shift.Core;
using UnityEngine;

namespace graveyard_shift.Game
{
    public sealed class SaveStore
    {
        public readonly string Path;

        public SaveStore(string path = null)
        {
            Path = path ?? System.IO.Path.Combine(Application.persistentDataPath, "save.json");
        }

        public SaveV3 Load()
        {
            // No save but a finished .tmp: a crash came between writing the first save and moving it into place
            string from = File.Exists(Path) ? Path : File.Exists(Path + ".tmp") ? Path + ".tmp" : null;
            if (from == null) return new SaveV3();
            try
            {
                string json = File.ReadAllText(from);
                int version = JsonUtility.FromJson<SaveHeader>(json).version;
                var data = SaveMigration.Upgrade(version,
                    version == 1 ? JsonUtility.FromJson<SaveV1>(json) : null,
                    version == 2 ? JsonUtility.FromJson<SaveV2>(json) : null,
                    version == 3 ? JsonUtility.FromJson<SaveV3>(json) : null);
                if (version != SaveMigration.Current) GameLog.Info("save", $"migrated save v{version} to v{SaveMigration.Current}");
                return data;
            }
            catch (Exception e)
            {
                GameLog.Warn("save", $"could not read {from} ({e.Message}); kept it as {Path}.bad, starting fresh");
                SetAside(from);
                return new SaveV3();
            }
        }

        // Keep the unreadable file as save.json.bad. A broken save.json stays where it is (the next Write replaces it);
        // a broken .tmp goes, or every launch would read it again. Never throws: a fresh start beats no start.
        private void SetAside(string from)
        {
            try
            {
                File.Copy(from, Path + ".bad", true);
                if (from != Path) File.Delete(from);
            }
            catch (Exception e)
            {
                GameLog.Warn("save", $"could not set {from} aside ({e.Message})");
            }
        }

        public void Write(SaveV3 data)
        {
            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(Path));
            string tmp = Path + ".tmp";
            File.WriteAllText(tmp, JsonUtility.ToJson(data, true));
            // Write, then swap in one step: File.Replace never leaves a moment with no save (Kimi audit: deleting the
            // old file first and moving the new one after did)
            if (File.Exists(Path)) File.Replace(tmp, Path, null);
            else File.Move(tmp, Path);
        }
    }
}
