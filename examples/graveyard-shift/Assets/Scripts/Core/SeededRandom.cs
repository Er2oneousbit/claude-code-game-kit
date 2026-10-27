// ---------------------------------------------------------------------------
// SeededRandom.cs
// Purpose : The game's own random numbers for anything that must replay from a seed (the generated
//           graveyard). Same seed, same numbers, on every runtime and version.
// Usage   : var rng = new SeededRandom(seed);  rng.Step(-5f, 5f, 16); rng.Range(0, 4); rng.Chance(0.25f)
// Notes   : Mulberry32, integer math only. System.Random is not used on purpose: Microsoft does not promise
//           its seeded sequence stays the same across .NET versions, and Unity's runtime (Mono, IL2CPP) is not
//           the one the docs describe (EVIDENCE E57, SOP-17). UnityEngine.Random is shared global state.
//           No float formulas here: see Step.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;

namespace graveyard_shift.Core
{
    public sealed class SeededRandom
    {
        private uint _state;

        public SeededRandom(int seed)
        {
            _state = Mix((uint)seed);
        }

        // Two numbers into one well-spread seed (the generator's seed and its attempt number)
        public static int Combine(int a, int b) => unchecked((int)Mix((uint)a * 0x9E3779B9u ^ Mix((uint)b + 0x632BE5ABu)));

        public uint NextUInt()
        {
            unchecked
            {
                uint z = _state += 0x6D2B79F5u;
                z = (z ^ (z >> 15)) * (z | 1u);
                z ^= z + (z ^ (z >> 7)) * (z | 61u);
                return z ^ (z >> 14);
            }
        }

        // [0, 1) with 24 bits, exact in a float
        public float Value() => (NextUInt() >> 8) * (1f / 16777216f);

        // A multiple of 1/perMeter between min and max (inclusive). With perMeter a power of two the result is
        // exact in a float, so sums of such numbers are exact too and every runtime gets the same yard. A float formula like
        // min + (max - min) * Value() is not: Unity's Mono and .NET 8 rounded it differently (HOW_IT_WAS_MADE).
        public float Step(float min, float max, int perMeter)
        {
            int lo = (int)Math.Ceiling(min * perMeter), hi = (int)Math.Floor(max * perMeter);
            return Range(lo, hi + 1) / (float)perMeter;
        }

        // [min, maxExclusive)
        public int Range(int min, int maxExclusive) => min + (int)(NextUInt() % (uint)(maxExclusive - min));

        public bool Chance(float p) => Value() < p;

        public T Pick<T>(T[] items) => items[Range(0, items.Length)];

        private static uint Mix(uint x)
        {
            unchecked
            {
                x ^= x >> 16;
                x *= 0x7FEB352Du;
                x ^= x >> 15;
                x *= 0x846CA68Bu;
                x ^= x >> 16;
                return x;
            }
        }
    }
}
