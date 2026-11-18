// ---------------------------------------------------------------------------
// steam_api.h (the kit's stand-in, NOT Valve's header)
// Purpose : Lets the unit-test build compile src/core/PlatformSteam.cpp's GAMEKIT_STEAM half without the Steamworks
//           SDK (which the kit never ships): the few declarations it uses, with the signatures the Steamworks API
//           reference gives (verify against your SDK). Nothing here is linked or run.
// Usage   : CMakeLists.txt's steam_standin_check object library (built with the tests).
// Notes   : Written for the kit from the public API reference; it is a compile check of the adapter's calls, not a
//           copy of the SDK. A real Steam build uses the SDK's own steam/steam_api.h (-DGAMEKIT_STEAM=ON).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <cstdint>

typedef std::int32_t int32;
typedef std::uint32_t uint32;
typedef std::uint8_t uint8;

class ISteamUserStats {
public:
    virtual bool SetAchievement(const char* pchName) = 0;
    virtual bool GetAchievement(const char* pchName, bool* pbAchieved) = 0;
    virtual bool SetStat(const char* pchName, int32 nData) = 0;
    virtual bool SetStat(const char* pchName, float fData) = 0;
    virtual bool GetStat(const char* pchName, int32* pData) = 0;
    virtual bool GetStat(const char* pchName, float* pData) = 0;
    virtual bool StoreStats() = 0;
    virtual bool IndicateAchievementProgress(const char* pchName, uint32 nCurProgress, uint32 nMaxProgress) = 0;
    virtual bool ResetAllStats(bool bAchievementsToo) = 0;
};

class ISteamFriends {
public:
    virtual bool SetRichPresence(const char* pchKey, const char* pchValue) = 0;
    virtual void ClearRichPresence() = 0;
};

class ISteamRemoteStorage {
public:
    virtual bool FileWrite(const char* pchFile, const void* pvData, int32 cubData) = 0;
};

typedef std::uint64_t uint64;

enum EResult { k_EResultOK = 1, k_EResultFail = 2 };

struct GameOverlayActivated_t {
    uint8 m_bActive;
};

struct UserStatsStored_t {
    uint64 m_nGameID;
    EResult m_eResult;
};

ISteamUserStats* SteamUserStats();
ISteamFriends* SteamFriends();
ISteamRemoteStorage* SteamRemoteStorage();
bool SteamAPI_Init();
void SteamAPI_RunCallbacks();
void SteamAPI_Shutdown();

// The SDK's macro declares a member callback object and its handler; this stand-in declares the handler only.
#define STEAM_CALLBACK(thisclass, func, param) void func(param* pParam)
