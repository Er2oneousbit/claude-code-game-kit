// ---------------------------------------------------------------------------
// GameKitDotworkTests.cpp
// Purpose : Tests of the animated-tile player (GameKitDotworkTiles.h, #286): the tile user data the importer writes,
//           the frame clock, and a tile map imported from Dotwork's golden pack playing its water.
// Usage   : python tools/dev.py test --filter GameKit.Dotwork      (or `test` for everything)
// Notes   : The map test needs the golden pack imported (copy data/golden/dotwork/assets/ over assets/, then
//           python tools/dev.py exec Content/Python/kit_dotwork/import_dotwork.py): without it, it says so and passes.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "GameKitDotworkTiles.h"
#include "PaperTileMap.h"
#include "PaperTileMapComponent.h"
#include "PaperTileSet.h"

namespace GameKitDotworkTests
{
	// ---- Constants ----
	constexpr EAutomationTestFlags DotworkTestFlags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::ProductFilter;
	const TCHAR* GoldenYard = TEXT("/Game/Dotwork/golden/Maps/TM_yard.TM_yard");   // import_dotwork.py's golden map

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitDotworkUserDataTest, "GameKit.Dotwork.TileUserDataNamesTheAnimation", DotworkTestFlags)
bool FGameKitDotworkUserDataTest::RunTest(const FString& Parameters)
{
	using namespace GameKitDotwork;
	FTileAnim A;
	TestTrue(TEXT("anim=2@4 animates"), ParseTileUserData(TEXT("anim=2@4"), A));
	TestEqual(TEXT("two frames"), A.Frames, 2);
	TestEqual(TEXT("at 4 fps"), A.Fps, 4.0f);
	TestTrue(TEXT("after the surface"), ParseTileUserData(TEXT("water;anim=3@7.5"), A) && A.Frames == 3 && A.Fps == 7.5f);
	TestFalse(TEXT("a surface alone does not animate"), ParseTileUserData(TEXT("dirt"), A));
	TestFalse(TEXT("one frame does not animate"), ParseTileUserData(TEXT("anim=1@4"), A));
	TestFalse(TEXT("nothing"), ParseTileUserData(TEXT(""), A));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitDotworkClockTest, "GameKit.Dotwork.TileFrameClock", DotworkTestFlags)
bool FGameKitDotworkClockTest::RunTest(const FString& Parameters)
{
	using namespace GameKitDotwork;
	FTileAnim A;
	A.Frames = 2;
	A.Fps = 4.0f;
	TestEqual(TEXT("0 s: frame 0"), FrameAt(A, 0.0), 0);
	TestEqual(TEXT("0.24 s: still frame 0"), FrameAt(A, 0.24), 0);
	TestEqual(TEXT("0.25 s: frame 1"), FrameAt(A, 0.25), 1);
	TestEqual(TEXT("0.5 s: frame 0 again (it loops)"), FrameAt(A, 0.5), 0);
	FTileAnim Still;
	TestEqual(TEXT("a still tile: always 0"), FrameAt(Still, 10.0), 0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitDotworkMapTest, "GameKit.Dotwork.ImportedMapPlaysItsWater", DotworkTestFlags)
bool FGameKitDotworkMapTest::RunTest(const FString& Parameters)
{
	UPaperTileMap* Asset = LoadObject<UPaperTileMap>(nullptr, GoldenYard);
	if (!Asset)
	{
		AddInfo(FString::Printf(TEXT("DOTWORK_TILES_SKIPPED %s is not imported (see this file's Notes)"), GoldenYard));
		return true;
	}
	UPaperTileMapComponent* Component = NewObject<UPaperTileMapComponent>();
	Component->SetTileMap(Asset);
	FDotworkTilePlayer Player;
	if (!TestTrue(TEXT("the yard has animated cells (its water)"), Player.Bind(Component)))
	{
		return false;
	}
	const FDotworkTilePlayer::FCell Cell = Player.Cells()[0];
	TestEqual(TEXT("five water cells (the golden yard's Water layer)"), Player.Cells().Num(), 5);
	TestTrue(TEXT("the component plays a copy, never the asset"), Component->OwnsTileMap() && Component->TileMap != Asset);
	TestEqual(TEXT("0.1 s in: nothing changes"), Player.Advance(0.1), 0);
	TestEqual(TEXT("0.3 s in: every water cell shows frame 1"), Player.Advance(0.2), 5);
	const FPaperTileInfo Now = Component->GetTile(Cell.X, Cell.Y, Cell.Layer);
	TestEqual(TEXT("frame 1 is the next cell to the right in the tile set"), Now.GetTileIndex(), Cell.First.GetTileIndex() + 1);
	TestEqual(TEXT("the asset still shows frame 0"), Asset->TileLayers[Cell.Layer]->GetCell(Cell.X, Cell.Y).GetTileIndex(), Cell.First.GetTileIndex());
	Player.Advance(0.25);
	TestEqual(TEXT("0.55 s in: back to frame 0"), Component->GetTile(Cell.X, Cell.Y, Cell.Layer).GetTileIndex(), Cell.First.GetTileIndex());
	return true;
}

}   // namespace GameKitDotworkTests

#endif   // WITH_DEV_AUTOMATION_TESTS

// {{FOOTER}}
