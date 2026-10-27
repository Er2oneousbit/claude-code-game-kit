// ---------------------------------------------------------------------------
// level.ts
// Purpose : The slice's map: three rooms as ASCII (the level is data, not a scene).
// Usage   : Grid.parse(LEVEL)
// Notes   : # wall  . floor  P player start  G ghost  o oil  K key  X exit door.
//           tests/level.test.ts checks the shape and that the key and the exit can
//           be reached; edit freely and let the test tell you if you broke it.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

export const LEVEL: readonly string[] = [
  "########################################",
  "#..........#.............#.............#",
  "#..........#......o......#.......G.....#",
  "#...P......#.............#.............#",
  "#..........###.....G..####.....##......#",
  "#.....o..........................#..K..#",
  "#..........###........####.....##......#",
  "#..........#.............#.............#",
  "#..........#......G......#.......o.....#",
  "#.......X..#.............#.............#",
  "########################################",
];
