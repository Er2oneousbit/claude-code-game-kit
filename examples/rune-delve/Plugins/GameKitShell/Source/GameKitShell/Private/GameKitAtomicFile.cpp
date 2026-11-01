// ---------------------------------------------------------------------------
// GameKitAtomicFile.cpp
// Purpose : Implementation of the crash-safe writer and the file readers (see GameKitAtomicFile.h).
// Usage   : compiled into the GameKitShell module; call through GameKitAtomicFile.h.
// Notes   : Writes through IPlatformFile so the handle can be flushed to the disk (FlushFileBuffers on
//           Windows). On Linux and macOS the engine's MoveFile is rename(), which replaces the target in one
//           step; the folder entry is not fsynced after it, the file content is, which covers crashes and
//           most power cuts. Nothing here logs: callers get the reason in OutError.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "GameKitAtomicFile.h"

#include "GenericPlatform/GenericPlatformFile.h"
#include "HAL/PlatformFileManager.h"
#include "HAL/PlatformMisc.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Templates/UniquePtr.h"

#if PLATFORM_WINDOWS
#include "Windows/WindowsHWrapper.h"
#endif

namespace GameKit
{
	namespace
	{
		// ---- Tunables ----
		constexpr int32 ErrorTextLength = 512;   // characters of the OS error message kept

		void SetError(FString* OutError, const FString& Text)
		{
			if (OutError)
			{
				*OutError = Text;
			}
		}

		/** The last OS error as text ("Access is denied."), for messages a player or a bug report can use. */
		FString LastSystemError()
		{
			const uint32 Code = FPlatformMisc::GetLastError();
			TCHAR Buffer[ErrorTextLength] = {};
			FPlatformMisc::GetSystemErrorMessage(Buffer, ErrorTextLength, static_cast<int32>(Code));
			return FString::Printf(TEXT("%s (error %u)"), *FString(Buffer).TrimStartAndEnd(), Code);
		}

		IPlatformFile& PlatformFile()
		{
			return FPlatformFileManager::Get().GetPlatformFile();
		}

		TArray<uint8> Utf8Bytes(const FString& Text)
		{
			const FTCHARToUTF8 Utf8(*Text, Text.Len());
			return TArray<uint8>(reinterpret_cast<const uint8*>(Utf8.Get()), Utf8.Length());
		}
	}

	FString TempPathFor(const FString& Target)
	{
		return Target + TempSuffix;
	}

	FString BackupPathFor(const FString& Target)
	{
		return Target + BackupSuffix;
	}

	TOptional<TArray<uint8>> ReadFileBytes(const FString& Path, FString* OutError)
	{
		SetError(OutError, FString());
		IPlatformFile& PF = PlatformFile();
		if (PF.DirectoryExists(*Path))
		{
			SetError(OutError, FString::Printf(TEXT("%s is a folder, not a file"), *Path));
			return {};
		}
		if (!PF.FileExists(*Path))
		{
			return {};   // never written: not an error
		}
		TArray<uint8> Bytes;
		if (!FFileHelper::LoadFileToArray(Bytes, *Path, FILEREAD_Silent))
		{
			SetError(OutError, FString::Printf(TEXT("cannot read %s: %s"), *Path, *LastSystemError()));
			return {};
		}
		return Bytes;
	}

	TOptional<FString> ReadTextFile(const FString& Path, FString* OutError)
	{
		const TOptional<TArray<uint8>> Bytes = ReadFileBytes(Path, OutError);
		if (!Bytes.IsSet())
		{
			return {};
		}
		FString Text;
		if (!Bytes->IsEmpty())
		{
			FFileHelper::BufferToString(Text, Bytes->GetData(), Bytes->Num());   // UTF-8 (BOM or not) or UTF-16
		}
		return Text;
	}

	bool WriteTemp(const FString& Target, const TArray<uint8>& Bytes, FString* OutError)
	{
		IPlatformFile& PF = PlatformFile();
		const FString Tmp = TempPathFor(Target);
		const FString Folder = FPaths::GetPath(Target);
		if (!Folder.IsEmpty() && !PF.DirectoryExists(*Folder) && !PF.CreateDirectoryTree(*Folder))
		{
			SetError(OutError, FString::Printf(TEXT("cannot create the folder %s: %s"), *Folder, *LastSystemError()));
			return false;
		}
		TUniquePtr<IFileHandle> Handle(PF.OpenWrite(*Tmp, /*bAppend*/ false, /*bAllowRead*/ false));
		if (!Handle)
		{
			SetError(OutError, FString::Printf(TEXT("cannot create %s: %s"), *Tmp, *LastSystemError()));
			return false;
		}
		const bool bWritten = Bytes.IsEmpty() || Handle->Write(Bytes.GetData(), Bytes.Num());
		const bool bFlushed = bWritten && Handle->Flush(/*bFullFlush*/ true);
		Handle.Reset();   // closes the file
		if (!bFlushed)
		{
			PF.DeleteFile(*Tmp);
			SetError(OutError, FString::Printf(TEXT("write failed (disk full or removed?): %s"), *Tmp));
			return false;
		}
		return true;
	}

	bool WriteTemp(const FString& Target, const FString& Text, FString* OutError)
	{
		return WriteTemp(Target, Utf8Bytes(Text), OutError);
	}

	bool CommitTemp(const FString& Target, FString* OutError)
	{
		const FString Tmp = TempPathFor(Target);
#if PLATFORM_WINDOWS
		const FString From = FPaths::ConvertRelativePathToFull(Tmp);
		const FString To = FPaths::ConvertRelativePathToFull(Target);
		if (!::MoveFileExW(*From, *To, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
		{
			SetError(OutError, FString::Printf(TEXT("cannot replace %s: %s"), *Target, *LastSystemError()));
			return false;
		}
#else
		if (!PlatformFile().MoveFile(*Target, *Tmp))   // rename(): replaces Target in one step
		{
			SetError(OutError, FString::Printf(TEXT("cannot replace %s: %s"), *Target, *LastSystemError()));
			return false;
		}
#endif
		return true;
	}

	bool WriteFileAtomic(const FString& Target, const TArray<uint8>& Bytes, FString* OutError)
	{
		return WriteTemp(Target, Bytes, OutError) && CommitTemp(Target, OutError);
	}

	bool WriteFileAtomic(const FString& Target, const FString& Text, FString* OutError)
	{
		return WriteTemp(Target, Text, OutError) && CommitTemp(Target, OutError);
	}
}
