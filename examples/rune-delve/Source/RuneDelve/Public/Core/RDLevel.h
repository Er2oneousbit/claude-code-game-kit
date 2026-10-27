// ---------------------------------------------------------------------------
// RDLevel.h
// Purpose : The dungeon as data: three rooms in a row on a tile grid, walls, gates, columns, props, the
//           mage's start and the seeded orc spawns. The game builds it at runtime; tests check it.
// Usage   : TArray<FRDPiece> P; FRDLevel::Pieces(P); TArray<FRDSpawn> S; FRDLevel::Orcs(Seed, S);
// Notes   : Tile coordinates: x 0..30 along the dungeon, y -4..4 across. Walls stand at x = 0, 10, 20, 30
//           and y = -4, 4; room r's floor is x 10r+1..10r+9, y -3..3; gate g (0 or 1) fills x = 10(g+1),
//           y -1..1 and opens when room g is cleared. Kenney Mini Dungeon tiles measure 100 cm (measured by
//           tools/unreal/build_content.py), drawn at WorldScale 2, so one tile is 200 cm.
//           The seed only moves orcs (start tile and facing): the rooms are the same every delve.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 GateOf; no two orcs share a spawn tile (the warden used to land on a grunt's)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"

enum class ERDPiece : uint8
{
	Floor,
	Wall,
	Gate,
	Column,
	Barrel,
	Rocks
};

struct FRDPiece
{
	ERDPiece Kind = ERDPiece::Floor;
	int32 X = 0;
	int32 Y = 0;
	float Yaw = 0.f;
	int32 Gate = -1;   // which gate this piece belongs to (Gate pieces only)
};

struct FRDSpawn
{
	FVector2D Pos = FVector2D::ZeroVector;   // cm
	float Yaw = 0.f;
	int32 Room = 0;
	bool bWarden = false;
};

struct RUNEDELVE_API FRDLevel
{
	static constexpr float WorldScale = 2.f;
	static constexpr float Tile = 100.f * WorldScale;   // cm
	static constexpr int32 RoomCount = 3;
	static constexpr int32 Pitch = 10;    // tiles from one room's left wall to the next
	static constexpr int32 HalfH = 4;     // walls at y = -4 and 4
	static constexpr int32 GateHalf = 1;  // gate tiles y = -1..1
	static const int32 GruntsPerRoom[RoomCount];

	static FVector2D TileToWorld(int32 X, int32 Y) { return FVector2D(X * Tile, Y * Tile); }
	/** The room whose floor contains P, or -1 in a wall or gate. */
	static int32 RoomOf(const FVector2D& P);
	/** The gate opening (0 or 1) that contains P, or -1. Gate G joins room G and room G + 1. */
	static int32 GateOf(const FVector2D& P);
	/** Floor area of room R in cm (tile edges, not centres). */
	static FBox2D RoomInterior(int32 R);
	/** Centre of gate G (between room G and G + 1). */
	static FVector2D GateCenter(int32 G) { return TileToWorld(Pitch * (G + 1), 0); }
	static FVector2D MageStart() { return TileToWorld(2, 0); }
	static void Pieces(TArray<FRDPiece>& Out);
	static void Orcs(int32 Seed, TArray<FRDSpawn>& Out);
	/** Everything the NavMesh must cover (cm, with a margin). */
	static FBox NavBounds();
	/** True if the tile is solid for walking: walls, columns, props, and gates (closed). */
	static bool IsBlocking(ERDPiece Kind) { return Kind != ERDPiece::Floor; }
};
