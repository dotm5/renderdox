// Resolve the renamed game-local Aftermath DLL once, then forward every call
// without changing its arguments or return value.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <strsafe.h>
#include <wchar.h>

extern "C" intptr_t g_OrigAftermath[43];
extern "C" volatile LONG g_ResolutionReady;

namespace
{
constexpr int ExportCount = 43;
constexpr size_t PathCapacity = 32768;

const wchar_t *const OriginalNames[] = {
    L"GFSDK_Aftermath_Lib_orig.dll",
    L"GFSDK_Aftermath_Lib.x64.orig.dll",
    L"GFSDK_Aftermath_Lib_orig.x64.dll",
};

const char *const ExportNames[ExportCount] = {
    "GFSDK_Aftermath_DX11_CreateContextHandle",
    "GFSDK_Aftermath_DX11_Initialize",
    "GFSDK_Aftermath_DX12_CreateContextHandle",
    "GFSDK_Aftermath_DX12_Initialize",
    "GFSDK_Aftermath_DX12_RegisterResource",
    "GFSDK_Aftermath_DX12_UnregisterResource",
    "GFSDK_Aftermath_DisableGpuCrashDumps",
    "GFSDK_Aftermath_EnableGpuCrashDumps",
    "GFSDK_Aftermath_GetContextError",
    "GFSDK_Aftermath_GetCrashDumpStatus",
    "GFSDK_Aftermath_GetData",
    "GFSDK_Aftermath_GetDeviceStatus",
    "GFSDK_Aftermath_GetPageFaultInformation",
    "GFSDK_Aftermath_GetShaderDebugInfoIdentifier",
    "GFSDK_Aftermath_GetShaderDebugName",
    "GFSDK_Aftermath_GetShaderDebugNameSpirv",
    "GFSDK_Aftermath_GetShaderHash",
    "GFSDK_Aftermath_GetShaderHashForShaderInfo",
    "GFSDK_Aftermath_GetShaderHashSpirv",
    "GFSDK_Aftermath_GpuCrashDump_CreateDecoder",
    "GFSDK_Aftermath_GpuCrashDump_DestroyDecoder",
    "GFSDK_Aftermath_GpuCrashDump_GenerateJSON",
    "GFSDK_Aftermath_GpuCrashDump_GetActiveShadersInfo",
    "GFSDK_Aftermath_GpuCrashDump_GetActiveShadersInfoCount",
    "GFSDK_Aftermath_GpuCrashDump_GetBaseInfo",
    "GFSDK_Aftermath_GpuCrashDump_GetDescription",
    "GFSDK_Aftermath_GpuCrashDump_GetDescriptionSize",
    "GFSDK_Aftermath_GpuCrashDump_GetDeviceInfo",
    "GFSDK_Aftermath_GpuCrashDump_GetEventMarkersInfo",
    "GFSDK_Aftermath_GpuCrashDump_GetEventMarkersInfoCount",
    "GFSDK_Aftermath_GpuCrashDump_GetGpuInfo",
    "GFSDK_Aftermath_GpuCrashDump_GetGpuInfoCount",
    "GFSDK_Aftermath_GpuCrashDump_GetJSON",
    "GFSDK_Aftermath_GpuCrashDump_GetPageFaultInfo",
    "GFSDK_Aftermath_GpuCrashDump_GetSystemInfo",
    "GFSDK_Aftermath_ReleaseContextHandle",
    "GFSDK_Aftermath_SetEventMarker",
    "GFSDK_Aftermath_SetShaderDebugInfoPaths",
    "GetShaderDebugName",
    "GetShaderDebugNameSpirv",
    "GetShaderHashForShaderInfo",
    "GetShaderHashSpirv",
    "queryWrapper",
};

INIT_ONCE ResolveOnce = INIT_ONCE_STATIC_INIT;
HMODULE OriginalModule = NULL;    // Keep the original loaded for the proxy's lifetime.
volatile LONG ResolvingThread = 0;

bool GetOriginalDirectory(wchar_t (&directory)[PathCapacity])
{
  HMODULE self = NULL;
  if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                             GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                         reinterpret_cast<LPCWSTR>(&ResolveOnce), &self))
    return false;

  const DWORD length = GetModuleFileNameW(self, directory, (DWORD)PathCapacity);
  if(length == 0 || length >= PathCapacity)
    return false;

  wchar_t *separator = wcsrchr(directory, L'\\');
  if(separator == NULL)
    return false;
  separator[1] = 0;
  return true;
}

BOOL CALLBACK ResolveOriginals(PINIT_ONCE, PVOID, PVOID *)
{
  InterlockedExchange(&ResolvingThread, (LONG)GetCurrentThreadId());
  wchar_t directory[PathCapacity] = {};
  if(GetOriginalDirectory(directory))
  {
    for(const wchar_t *name : OriginalNames)
    {
      wchar_t originalPath[PathCapacity] = {};
      if(FAILED(StringCchCopyW(originalPath, PathCapacity, directory)) ||
         FAILED(StringCchCatW(originalPath, PathCapacity, name)))
        continue;

      // Resolve dependencies from the original's own directory without relying
      // on the process working directory or another directory on the DLL path.
      HMODULE original = LoadLibraryExW(originalPath, NULL,
                                        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR |
                                            LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
      if(original == NULL)
        continue;

      OriginalModule = original;
      for(int index = 0; index < ExportCount; ++index)
        g_OrigAftermath[index] = reinterpret_cast<intptr_t>(
            GetProcAddress(original, ExportNames[index]));
      break;
    }
  }
  InterlockedExchange(&g_ResolutionReady, 1);
  InterlockedExchange(&ResolvingThread, 0);
  return TRUE;
}

__declspec(noreturn) void ForwardingUnavailable()
{
  // A union export can be absent from a particular original. Returning zero
  // would falsely report success for some SDK functions, so fail explicitly.
  RaiseFailFastException(NULL, NULL, 0);
  __assume(0);
}
}    // namespace

extern "C" intptr_t g_OrigAftermath[43] = {};
extern "C" volatile LONG g_ResolutionReady = 0;

extern "C" intptr_t ResolveAftermathExport(int index)
{
  if(index < 0 || index >= ExportCount ||
     ResolvingThread == (LONG)GetCurrentThreadId() ||
     !InitOnceExecuteOnce(&ResolveOnce, ResolveOriginals, NULL, NULL))
    ForwardingUnavailable();

  const intptr_t target = g_OrigAftermath[index];
  if(target == 0)
    ForwardingUnavailable();
  return target;
}
