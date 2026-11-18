// ---------------------------------------------------------------------------
// GameKitDotworkTiles.cpp
// Purpose : The animated-tile player (GameKitDotworkTiles.h, #286): user data parsing, the frame clock, and
//           setting each animated cell's frame on a tile map component that owns its map.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "GameKitDotworkTiles.h"

#include "PaperTileMap.h"
#include "PaperTileMapComponent.h"
#include "PaperTileSet.h"

namespace GameKitDotwork
{
	// ---- Constants ----
	static const TCHAR* AnimPrefix = TEXT("anim=");   // dotwork_spec.TILE_ANIM_PREFIX

	bool ParseTileUserData(const FString& Text, FTileAnim& Out)
	{
		Out = FTileAnim();
		TArray<FString> Parts;
		Text.ParseIntoArray(Parts, TEXT(";"));
		for (const FString& Part : Parts)
		{
			if (!Part.StartsWith(AnimPrefix))
			{
				continue;
			}
			FString Frames, Fps;
			if (Part.RightChop(FCString::Strlen(AnimPrefix)).Split(TEXT("@"), &Frames, &Fps))
			{
				Out.Frames = FMath::Max(1, FCString::Atoi(*Frames));
				Out.Fps = FMath::Max(0.0f, FCString::Atof(*Fps));
			}
		}
		return Out.Animates();
	}

	int32 FrameAt(const FTileAnim& Anim, double Seconds)
	{
		if (!Anim.Animates() || Seconds <= 0.0)
		{
			return 0;
		}
		return static_cast<int32>(FMath::FloorToDouble(Seconds * Anim.Fps)) % Anim.Frames;
	}
}

bool FDotworkTilePlayer::Bind(UPaperTileMapComponent* Component)
{
	AnimatedCells.Reset();
	Target.Reset();
	Clock = 0.0;
	if (!Component || !Component->TileMap)
	{
		return false;
	}
	int32 Width = 0, Height = 0, Layers = 0;
	Component->GetMapSize(Width, Height, Layers);
	for (int32 Layer = 0; Layer < Layers; ++Layer)
	{
		for (int32 Y = 0; Y < Height; ++Y)
		{
			for (int32 X = 0; X < Width; ++X)
			{
				const FPaperTileInfo Info = Component->GetTile(X, Y, Layer);
				if (!Info.IsValid())
				{
					continue;
				}
				GameKitDotwork::FTileAnim Anim;
				if (GameKitDotwork::ParseTileUserData(Info.TileSet->GetTileUserData(Info.GetTileIndex()).ToString(), Anim))
				{
					FCell Cell;
					Cell.X = X;
					Cell.Y = Y;
					Cell.Layer = Layer;
					Cell.First = Info;
					Cell.Anim = Anim;
					AnimatedCells.Add(Cell);
				}
			}
		}
	}
	if (AnimatedCells.Num() == 0)
	{
		return false;
	}
	if (!Component->OwnsTileMap())
	{
		Component->MakeTileMapEditable();   // a copy of the asset's map: SetTile edits only a map the component owns
	}
	Target = Component;
	return true;
}

int32 FDotworkTilePlayer::Advance(double DeltaSeconds)
{
	UPaperTileMapComponent* Component = Target.Get();
	if (!Component)
	{
		return 0;
	}
	Clock += FMath::Max(0.0, DeltaSeconds);
	int32 Changed = 0;
	for (FCell& Cell : AnimatedCells)
	{
		const int32 Frame = GameKitDotwork::FrameAt(Cell.Anim, Clock);
		if (Frame == Cell.Shown)
		{
			continue;
		}
		FPaperTileInfo Info = Cell.First;
		// the frames sit in the next cells to the right of the first one, in the same row of the tile set
		Info.PackedTileIndex = Cell.First.PackedTileIndex + Frame;
		Component->SetTile(Cell.X, Cell.Y, Cell.Layer, Info);
		Cell.Shown = Frame;
		++Changed;
	}
	return Changed;
}
