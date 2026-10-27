// ---------------------------------------------------------------------------
// SaveData.cs
// Purpose : The save file's shapes and its migration (SOP-06: saves carry a version from day one and
//           migrate forward; a migration has a test).
// Usage   : SaveV3 data = SaveMigration.Upgrade(versionOnDisk, v1, v2, v3);  (the Game layer reads the JSON)
// Notes   : v1 (0.1.0, the toy) stored one best time. v2 (0.2.0) stores best times per bot-free run, the
//           number of nights played and the settings. v3 (0.3.0) adds the difficulty to the settings.
//           Never change a released shape: add a SaveV4 and a step.
//           Plain [Serializable] classes, so JsonUtility in the Game layer reads and writes them.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;

namespace graveyard_shift.Core
{
    // Read first: only the version, to pick the right shape.
    [Serializable]
    public class SaveHeader
    {
        public int version;
    }

    [Serializable]
    public class SaveV1
    {
        public int version = 1;
        public float bestSeconds;          // fastest escape, 0 = none
    }

    [Serializable]
    public class SaveSettings
    {
        public float volume = 0.8f;        // 0..1
        public bool showHints = true;      // the controls line at the start of a night
    }

    [Serializable]
    public class SaveV2
    {
        public const int Version = 2;
        public int version = Version;
        public float bestEscapeSeconds;    // fastest escape, 0 = none
        public int nightsPlayed;
        public int escapes;
        public SaveSettings settings = new SaveSettings();

        // Keep the faster time.
        public void RecordEscape(float seconds)
        {
            escapes++;
            if (bestEscapeSeconds <= 0f || seconds < bestEscapeSeconds) bestEscapeSeconds = seconds;
        }
    }

    [Serializable]
    public class SaveSettingsV3
    {
        public float volume = 0.8f;        // 0..1
        public bool showHints = true;      // the controls line at the start of a night
        public string difficulty = "Normal";   // Easy, Normal, Hard or Insane (DifficultySettings.Parse)
    }

    [Serializable]
    public class SaveV3
    {
        public const int Version = 3;
        public int version = Version;
        public float bestEscapeSeconds;    // fastest escape, 0 = none
        public int nightsPlayed;
        public int escapes;
        public SaveSettingsV3 settings = new SaveSettingsV3();

        // Keep the faster time.
        public void RecordEscape(float seconds)
        {
            escapes++;
            if (bestEscapeSeconds <= 0f || seconds < bestEscapeSeconds) bestEscapeSeconds = seconds;
        }
    }

    public static class SaveMigration
    {
        public const int Current = SaveV3.Version;

        // v2 had no difficulty: Normal, the default
        public static SaveV3 FromV2(SaveV2 old)
        {
            return new SaveV3
            {
                bestEscapeSeconds = old.bestEscapeSeconds,
                nightsPlayed = old.nightsPlayed,
                escapes = old.escapes,
                settings = new SaveSettingsV3 { volume = old.settings.volume, showHints = old.settings.showHints },
            };
        }

        public static SaveV2 FromV1(SaveV1 old)
        {
            return new SaveV2
            {
                bestEscapeSeconds = old.bestSeconds,
                // v1 only knew escapes that set a best time: count one if there was a time
                escapes = old.bestSeconds > 0f ? 1 : 0,
                nightsPlayed = old.bestSeconds > 0f ? 1 : 0,
            };
        }

        // Any known version to the current one. Unknown (newer) versions throw: never guess at a future format.
        public static SaveV3 Upgrade(int version, SaveV1 v1, SaveV2 v2, SaveV3 v3)
        {
            switch (version)
            {
                case 1: return FromV2(FromV1(v1 ?? new SaveV1()));
                case 2: return FromV2(v2 ?? new SaveV2());
                case 3: return v3 ?? new SaveV3();
                default: throw new NotSupportedException($"save version {version} is newer than this game ({Current})");
            }
        }
    }
}
