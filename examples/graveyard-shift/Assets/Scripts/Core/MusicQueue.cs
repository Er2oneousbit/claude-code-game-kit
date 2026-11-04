// ---------------------------------------------------------------------------
// MusicQueue.cs
// Purpose : Which music track plays and which change still waits for its switch sample, with no UnityEngine types
//           (an EditMode test runs it). A change asked back before its switch is undone, as the Godot, LÖVE and
//           web players do: request("combat") and then request("explore") before the bar line leave explore
//           playing on, as if combat had never been asked. A track that has not entered yet (a stinger's gap) is
//           planned from where it enters.
// Usage   : var queue = new MusicQueue(director);
//           queue.Start("explore", atSample);
//           MusicQueue.Step s = queue.Request("combat", nowSample);
//           if (s.Undone) { drop the sources of the change that was pending; the old track plays on as before }
//           if (s.Plan != null) { schedule it: queue.Current is now the new track }
// Notes   : MusicPlayer.cs (Assets/Scripts/Game) keeps the AudioSources; this keeps the decisions. Too late to
//           undo means the switch sample is already before `now` (the request's own planning time).
//
// Pseudocode:
//   Request(to, now): pending change whose SwitchAt >= now -> undo it (Current = the track before it)
//                     -> to == Current: nothing to plan
//                     -> plan = director.Plan(Current, since, entry, to, max(now, Current.Since))
//                     -> remember Current as the track before it, Current = to from ToStartAt at ToOffset
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;

namespace graveyard_shift.Core
{
    public sealed class MusicQueue
    {
        /// <summary>A track on the music clock: started on sample Since, from Entry samples into the track.</summary>
        public sealed class Track
        {
            public string Name;
            public long Since;
            public long Entry;
        }

        /// <summary>What a request decided: Undone = the pending change was taken back (its sources must go);
        /// Started = nothing played, so `to` simply starts; Plan = the change to schedule, null for none.</summary>
        public sealed class Step
        {
            public bool Undone;
            public bool Started;
            public MusicPlan Plan;
        }

        private readonly MusicDirector _director;
        private Track _before;                               // what played before the pending change

        public MusicQueue(MusicDirector director)
        {
            _director = director ?? throw new ArgumentNullException(nameof(director));
        }

        public Track Current { get; private set; }

        /// <summary>The last planned change while it can still be undone (null once a newer request found its
        /// switch in the past, or after Start and Clear).</summary>
        public MusicPlan Pending { get; private set; }

        /// <summary>Plays `name` from its beginning on sample `at`, forgetting any pending change.</summary>
        public void Start(string name, long at)
        {
            _director.Track(name);                           // throws on an unknown track, as Plan would
            Current = new Track { Name = name, Since = at, Entry = 0 };
            Pending = null;
            _before = null;
        }

        /// <summary>Nothing plays.</summary>
        public void Clear()
        {
            Current = null;
            Pending = null;
            _before = null;
        }

        /// <summary>A change to `to`, asked on music-clock sample `now`.</summary>
        public Step Request(string to, long now)
        {
            var step = new Step();
            if (Current == null)
            {
                Start(to, now);
                step.Started = true;
                return step;
            }
            if (Pending != null && Pending.SwitchAt >= now)
            {
                Current = _before;
                step.Undone = true;
            }
            Pending = null;
            _before = null;
            if (Current.Name == to)
            {
                return step;
            }
            // a track that has not entered yet (a stinger's delayed entry) is planned from where it enters
            MusicPlan p = _director.Plan(Current.Name, Current.Since, Current.Entry, to, Math.Max(now, Current.Since));
            _before = Current;
            Pending = p;
            Current = new Track { Name = to, Since = p.ToStartAt, Entry = p.ToOffset };
            step.Plan = p;
            return step;
        }
    }
}
