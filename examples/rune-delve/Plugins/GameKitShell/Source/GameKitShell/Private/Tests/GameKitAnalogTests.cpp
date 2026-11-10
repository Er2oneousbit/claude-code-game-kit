// ---------------------------------------------------------------------------
// GameKitAnalogTests.cpp
// Purpose : Tests of the analog shaping in GameKitAnalog.h (#274): the stick's radial, rescaled deadzone and
//           invert_y, the triggers' own deadzone, and broken input (NaN) as 0. The same cases as the Bevy shell's
//           logic/analog.rs, so both engines shape a stick alike.
// Usage   : python tools/dev.py test --filter GameKit.Analog      (or `test` for everything)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "GameKitAnalog.h"
#include <limits>

namespace GameKitAnalogTests
{
	// ---- Constants ----
	constexpr EAutomationTestFlags AnalogTestFlags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::ProductFilter;
	constexpr double Eps = 1e-5;
	const double NaN = std::numeric_limits<double>::quiet_NaN();

	bool Close(const FVector2D& A, const FVector2D& B)
	{
		return FMath::Abs(A.X - B.X) < Eps && FMath::Abs(A.Y - B.Y) < Eps;
	}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitAnalogStickTest, "GameKit.Analog.StickDeadzoneIsRadialAndRescaled", AnalogTestFlags)
bool FGameKitAnalogStickTest::RunTest(const FString& Parameters)
{
	using GameKit::AnalogStick;
	TestTrue(TEXT("inside the deadzone is still"), AnalogStick(0.15, 0.1, 0.2, false) == FVector2D::ZeroVector);
	const double JustPast = AnalogStick(0.21, 0.0, 0.2, false).X;
	TestTrue(FString::Printf(TEXT("just past the deadzone is a small push, never a jump to 0.2 (%g)"), JustPast), JustPast > 0.0 && JustPast < 0.02);
	TestTrue(TEXT("0.6 with a 0.2 deadzone is 0.5"), Close(AnalogStick(0.6, 0.0, 0.2, false), FVector2D(0.5, 0.0)));
	TestTrue(TEXT("full deflection stays 1"), Close(AnalogStick(1.0, 0.0, 0.2, false), FVector2D(1.0, 0.0)));
	const FVector2D Diag = AnalogStick(1.0, 1.0, 0.2, false);
	TestTrue(TEXT("a diagonal past full deflection is clamped to length 1, direction kept"),
	         FMath::Abs(Diag.Size() - 1.0) < Eps && FMath::Abs(Diag.X - Diag.Y) < 1e-6);
	TestTrue(TEXT("no deadzone: the raw value"), Close(AnalogStick(-0.3, 0.4, 0.0, false), FVector2D(-0.3, 0.4)));
	TestTrue(TEXT("the radial rule: (0.15, 0.15) is past a 0.2 deadzone though each axis is inside"),
	         AnalogStick(0.15, 0.15, 0.2, false).X > 0.0);
	TestTrue(TEXT("a deadzone over the maximum is clamped, the rescale stays finite"),
	         FMath::IsFinite(AnalogStick(1.0, 0.0, 5.0, false).X) && Close(AnalogStick(1.0, 0.0, 5.0, false), FVector2D(1.0, 0.0)));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitAnalogInvertTest, "GameKit.Analog.InvertYFlipsOnlyTheVerticalAxis", AnalogTestFlags)
bool FGameKitAnalogInvertTest::RunTest(const FString& Parameters)
{
	using GameKit::AnalogStick;
	TestTrue(TEXT("up becomes down"), Close(AnalogStick(0.0, 1.0, 0.2, true), FVector2D(0.0, -1.0)));
	TestTrue(TEXT("right stays right"), Close(AnalogStick(1.0, 0.0, 0.2, true), FVector2D(1.0, 0.0)));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitAnalogTriggerTest, "GameKit.Analog.TriggersRescaleAndIgnoreBadValues", AnalogTestFlags)
bool FGameKitAnalogTriggerTest::RunTest(const FString& Parameters)
{
	using GameKit::AnalogTrigger;
	TestEqual(TEXT("a trigger resting at 0.04 is 0"), AnalogTrigger(0.04), 0.0);
	TestEqual(TEXT("fully in is 1"), AnalogTrigger(1.0), 1.0);
	TestEqual(TEXT("halfway past the deadzone is 0.5"), AnalogTrigger(0.525), 0.5, Eps);
	TestEqual(TEXT("a trigger never goes negative"), AnalogTrigger(-0.5, 0.0), 0.0);
	TestEqual(TEXT("past 1 is 1"), AnalogTrigger(1.7, 0.0), 1.0);
	TestEqual(TEXT("NaN is 0"), AnalogTrigger(NaN, 0.0), 0.0);
	TestTrue(TEXT("a NaN axis counts as 0, the other one stays"), Close(GameKit::AnalogStick(NaN, 1.0, 0.0, false), FVector2D(0.0, 1.0)));
	return true;
}

} // namespace GameKitAnalogTests

#endif // WITH_DEV_AUTOMATION_TESTS
