// ---------------------------------------------------------------------------
// RDLevel.cpp
// Purpose : See RDLevel.h.
//
// Pseudocode:
//   Pieces: floor under every room and gate tile; walls round the outside and between rooms, except the
//           gate openings; gate pieces in the openings; two columns and two props per room
//   Orcs:   per room, a seeded shuffle of candidate tiles in the far two thirds of the room; grunts take
//           the first N that are not the warden's tile, the warden (last room) takes a tile near the far
//           wall; facing is seeded too
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fix: the warden could spawn on a grunt's tile (24 of seeds 0..199, first 35); the
//           grunts now skip its tile. The random draws keep their order, so every other seed is unchanged.
//           GateOf for the bots' room filter.
// ---------------------------------------------------------------------------
#include "Core/RDLevel.h"

#include "Math/RandomStream.h"

const int32 FRDLevel::GruntsPerRoom[FRDLevel::RoomCount] = {2, 3, 2};

int32 FRDLevel::RoomOf(const FVector2D& P)
{
	for (int32 R = 0; R < RoomCount; ++R)
	{
		if (RoomInterior(R).IsInside(P))
		{
			return R;
		}
	}
	return -1;
}

int32 FRDLevel::GateOf(const FVector2D& P)
{
	for (int32 G = 0; G < RoomCount - 1; ++G)
	{
		const FVector2D Half(Tile * 0.5f, Tile * (GateHalf + 0.5f));
		if (FBox2D(GateCenter(G) - Half, GateCenter(G) + Half).IsInside(P))
		{
			return G;
		}
	}
	return -1;
}

FBox2D FRDLevel::RoomInterior(int32 R)
{
	// Tiles 10R+1 .. 10R+9 and -3 .. 3, measured to their outer edges
	const float Half = Tile * 0.5f;
	const FVector2D Min = TileToWorld(Pitch * R + 1, -(HalfH - 1)) - FVector2D(Half, Half);
	const FVector2D Max = TileToWorld(Pitch * R + Pitch - 1, HalfH - 1) + FVector2D(Half, Half);
	return FBox2D(Min, Max);
}

void FRDLevel::Pieces(TArray<FRDPiece>& Out)
{
	Out.Reset();
	const int32 MaxX = Pitch * RoomCount;
	for (int32 X = 0; X <= MaxX; ++X)
	{
		for (int32 Y = -HalfH; Y <= HalfH; ++Y)
		{
			const bool bEdgeRow = FMath::Abs(Y) == HalfH;
			const bool bWallColumn = X % Pitch == 0;
			const bool bGateGap = bWallColumn && X > 0 && X < MaxX && FMath::Abs(Y) <= GateHalf;
			if (bGateGap)
			{
				FRDPiece Gate;
				Gate.Kind = ERDPiece::Gate;
				Gate.X = X;
				Gate.Y = Y;
				Gate.Yaw = 90.f;
				Gate.Gate = X / Pitch - 1;
				Out.Add(FRDPiece{ERDPiece::Floor, X, Y});
				Out.Add(Gate);
			}
			else if (bEdgeRow || bWallColumn)
			{
				Out.Add(FRDPiece{ERDPiece::Wall, X, Y});
			}
			else
			{
				Out.Add(FRDPiece{ERDPiece::Floor, X, Y});
			}
		}
	}
	// Cover and clutter, the same in every room: two columns break sight lines, two props sit in corners
	for (int32 R = 0; R < RoomCount; ++R)
	{
		const int32 X0 = Pitch * R;
		Out.Add(FRDPiece{ERDPiece::Column, X0 + 4, -1});
		Out.Add(FRDPiece{ERDPiece::Column, X0 + 6, 2});
		Out.Add(FRDPiece{ERDPiece::Barrel, X0 + 1, -3});
		Out.Add(FRDPiece{ERDPiece::Rocks, X0 + 9, 3, 90.f});
	}
}

void FRDLevel::Orcs(int32 Seed, TArray<FRDSpawn>& Out)
{
	Out.Reset();
	for (int32 R = 0; R < RoomCount; ++R)
	{
		FRandomStream Rng(Seed * 7919 + R * 104729 + 17);
		TArray<FIntPoint> Spots;
		for (int32 X = 4; X <= 8; ++X)
		{
			for (int32 Y = -2; Y <= 2; ++Y)
			{
				const bool bColumn = (X == 4 && Y == -1) || (X == 6 && Y == 2);
				if (!bColumn)
				{
					Spots.Add(FIntPoint(Pitch * R + X, Y));
				}
			}
		}
		for (int32 I = Spots.Num() - 1; I > 0; --I)   // seeded Fisher-Yates
		{
			Spots.Swap(I, Rng.RandRange(0, I));
		}
		// Draw in the original order (grunt facings, then the warden's row) so seeds without a clash keep their layout
		TArray<float> Yaws;
		for (int32 I = 0; I < GruntsPerRoom[R]; ++I)
		{
			Yaws.Add(Rng.FRandRange(0.f, 360.f));
		}
		const bool bWardenRoom = R == RoomCount - 1;
		const FIntPoint WardenTile(Pitch * R + 8, bWardenRoom ? Rng.RandRange(-1, 1) : 0);
		int32 Next = 0;
		for (int32 I = 0; I < GruntsPerRoom[R]; ++I)
		{
			while (bWardenRoom && Spots[Next] == WardenTile)
			{
				++Next;
			}
			FRDSpawn S;
			S.Pos = TileToWorld(Spots[Next].X, Spots[Next].Y);
			S.Yaw = Yaws[I];
			S.Room = R;
			Out.Add(S);
			++Next;
		}
		if (bWardenRoom)
		{
			FRDSpawn W;
			W.Pos = TileToWorld(WardenTile.X, WardenTile.Y);
			W.Yaw = 180.f;
			W.Room = R;
			W.bWarden = true;
			Out.Add(W);
		}
	}
}

FBox FRDLevel::NavBounds()
{
	const FVector2D Min = TileToWorld(0, -HalfH) - FVector2D(Tile, Tile);
	const FVector2D Max = TileToWorld(Pitch * RoomCount, HalfH) + FVector2D(Tile, Tile);
	return FBox(FVector(Min, -200.f), FVector(Max, 400.f));
}
