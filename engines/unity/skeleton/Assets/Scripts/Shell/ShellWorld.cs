// ---------------------------------------------------------------------------
// ShellWorld.cs
// Purpose : What the front end shows under the screens once Play (or the juice demo) is entered: a world with a name
//           (the screen name drives and the narrator see), its subtitle bar, and a tick on game time.
// Usage   : class MyGame : ShellWorld { public override string Name => "play"; ... }
//           FrontEnd.StartWorld(() => new MyGame(front));   // through the loading screen
// Notes   : PlayWorld (the placeholder game) and JuiceWorld (the juice demo, #275) are the kit's two. Build adds the
//           world's elements to the world layer (drawn under the screens); Dispose removes them and unhooks events.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using UnityEngine.UIElements;

namespace {{GAME_SLUG}}.Shell
{
    public abstract class ShellWorld
    {
        /// <summary>The world's subtitle bar (dialogue lines, barks, sound captions).</summary>
        public readonly SubtitleBar Subtitles = new SubtitleBar();

        /// <summary>The screen name while this world shows with no screen over it: "play", "juice".</summary>
        public abstract string Name { get; }

        public abstract void Build(VisualElement layer);

        /// <summary>Once a frame with the game's delta (0 while paused).</summary>
        public abstract void Tick(float dt);

        public abstract void Dispose();
    }
}

// {{FOOTER}}
