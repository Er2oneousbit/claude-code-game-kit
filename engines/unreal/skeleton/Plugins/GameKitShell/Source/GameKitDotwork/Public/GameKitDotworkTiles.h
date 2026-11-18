// ---------------------------------------------------------------------------
// GameKitDotworkTiles.h
// Purpose : Animated tiles for Dotwork tile maps in Paper2D (#286). Paper2D's tile maps have no tile animation, so
//           the importer (Content/Python/kit_dotwork) writes each animated tile's frames into the tile set's user
//           data ("anim=<frames>@<fps>", after the surface: "water;anim=2@4"; the frames sit in the next cells to
//           the right, ASSET_MANIFEST.md), and FDotworkTilePlayer plays them on a tile map component it owns.
// Usage   : Nothing to do in a game: UDotworkTileAnimatorSubsystem plays every tile map in the world at BeginPlay.
//           A map spawned later: GetWorld()->GetSubsystem<UDotworkTileAnimatorSubsystem>()->Register(Component).
//           By hand: FDotworkTilePlayer Player; Player.Bind(Component); every frame Player.Advance(DeltaSeconds).
// Notes   : Bind makes the component's tile map its own copy (MakeTileMapEditable: SetTile edits only a map the
//           component owns), so the asset is never changed. A cell shows frame floor(t * fps) mod frames of its
//           tile, every cell from the same clock (all water ripples together, as in Godot's TileSet animation).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "PaperTileLayer.h"

class UPaperTileMapComponent;

namespace GameKitDotwork
{
	/** A tile's animation from its user data: Frames 1 and Fps 0 when it does not animate. */
	struct FTileAnim
	{
		int32 Frames = 1;
		float Fps = 0.0f;
		bool Animates() const { return Frames > 1 && Fps > 0.0f; }
	};

	/** Reads "anim=<frames>@<fps>" from a tile's user data ("surface;anim=2@4"); false when there is none. */
	GAMEKITDOTWORK_API bool ParseTileUserData(const FString& Text, FTileAnim& Out);

	/** The frame (0 to Frames - 1) a tile shows Seconds after the clock started. */
	GAMEKITDOTWORK_API int32 FrameAt(const FTileAnim& Anim, double Seconds);
}

/** Plays the animated tiles of one tile map component. */
class GAMEKITDOTWORK_API FDotworkTilePlayer
{
public:
	/** One animated cell: where it is, its first frame's tile and its animation. */
	struct FCell
	{
		int32 X = 0, Y = 0, Layer = 0;
		FPaperTileInfo First;
		GameKitDotwork::FTileAnim Anim;
		int32 Shown = 0;
	};

	/** Finds the animated cells (none: false, the component is left as it was), then owns the map's copy. */
	bool Bind(UPaperTileMapComponent* Component);

	/** Moves the clock on and sets every cell whose frame changed. Returns how many cells changed. */
	int32 Advance(double DeltaSeconds);

	const TArray<FCell>& Cells() const { return AnimatedCells; }
	bool IsBound() const { return Target.IsValid(); }
	UPaperTileMapComponent* Component() const { return Target.Get(); }

private:
	TWeakObjectPtr<UPaperTileMapComponent> Target;
	TArray<FCell> AnimatedCells;
	double Clock = 0.0;
};

// {{FOOTER}}
