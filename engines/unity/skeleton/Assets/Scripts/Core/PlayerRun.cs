// ---------------------------------------------------------------------------
// PlayerRun.cs
// Purpose : Two decisions a player build makes at run time, kept engine-free so EditMode tests hold them (#308):
//           when a scripted drive may run, and which full-screen kind a display mode gets.
// Usage   : if (PlayerRun.ArmDrive(FrontEnd.DriveArmed, !Application.isEditor, Shell.I.DriveOnCommandLine)) ...
//           string kind = PlayerRun.FullScreenKind("borderless", Screen.resolutions.Length);
//           // "windowed" | "exclusive" | "borderless" | "maximized"
// Notes   : A drive presses through the menus by itself and ignores the real keyboard and pad, so it never starts
//           from an environment variable alone in a player: only a PlayMode test (FrontEnd.DriveArmed) or a player
//           started with `--drive <scenario>` on its command line arms it (Shell.cs documents both). Full screen:
//           when Unity sees no display modes (Screen.resolutions is empty: seen in a disconnected remote session,
//           where Unity logged "Failed to find a valid fullscreen resolution" and fell back to a titled window for
//           both full-screen kinds), the window is maximized instead, so it still fills the screen.
//
// Pseudocode:
//   ArmDrive(test, player, cmdline) = test or (player and cmdline)
//   FullScreenKind(mode, modes)     = windowed -> windowed; no modes known -> maximized;
//                                     fullscreen -> exclusive; borderless (or anything else) -> borderless
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
namespace {{GAME_SLUG}}.Core
{
    public static class PlayerRun
    {
        /// <summary>True when Shell.Drive may run: a PlayMode test armed it, or a player got --drive on its command line.</summary>
        public static bool ArmDrive(bool armedByTest, bool isPlayer, bool driveOnCommandLine)
        {
            return armedByTest || (isPlayer && driveOnCommandLine);
        }

        /// <summary>The window kind for display.mode, given how many display modes Unity can see.</summary>
        public static string FullScreenKind(string mode, int knownDisplayModes)
        {
            if (mode == "windowed")
            {
                return "windowed";
            }
            if (knownDisplayModes <= 0)
            {
                return "maximized";
            }
            return mode == "fullscreen" ? "exclusive" : "borderless";
        }
    }
}
