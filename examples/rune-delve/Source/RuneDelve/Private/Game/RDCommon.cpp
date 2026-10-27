// ---------------------------------------------------------------------------
// RDCommon.cpp
// Purpose : Launch options from the command line, and the test override.
// Notes   : Flags (after the map, or after `--` with dev.py): -autoplay=weaver|masher -seed=N -god -debugai
//           -fixedfps -quitatend -record=<dir> -recordevery=N -maxseconds=N
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "Game/RDCommon.h"

#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

DEFINE_LOG_CATEGORY(LogRuneDelve);

namespace
{
	TOptional<FRDLaunchOptions> GOverride;

	FRDLaunchOptions Parse()
	{
		FRDLaunchOptions O;
		const TCHAR* Cmd = FCommandLine::Get();
		FString Bot;
		if (FParse::Value(Cmd, TEXT("autoplay="), Bot))
		{
			O.Bot = RDBot::Parse(Bot);
		}
		FParse::Value(Cmd, TEXT("seed="), O.Seed);
		FParse::Value(Cmd, TEXT("record="), O.RecordDir);
		FParse::Value(Cmd, TEXT("recordevery="), O.RecordEvery);
		FParse::Value(Cmd, TEXT("maxseconds="), O.MaxSeconds);
		O.bGod = FParse::Param(Cmd, TEXT("god"));
		O.bDebugAI = FParse::Param(Cmd, TEXT("debugai"));
		O.bFixedFps = FParse::Param(Cmd, TEXT("fixedfps"));
		O.bQuitAtEnd = FParse::Param(Cmd, TEXT("quitatend"));
		O.RecordEvery = FMath::Max(1, O.RecordEvery);
		return O;
	}
}

const FRDLaunchOptions& FRDLaunchOptions::Get()
{
	static const FRDLaunchOptions FromCommandLine = Parse();
	return GOverride.IsSet() ? GOverride.GetValue() : FromCommandLine;
}

void FRDLaunchOptions::SetTestOverride(const FRDLaunchOptions& Options)
{
	GOverride = Options;
}

void FRDLaunchOptions::ClearTestOverride()
{
	GOverride.Reset();
}
