/******************************************************************************
 * The MIT License (MIT)
 *
 * Copyright (c) 2026 DComp contributors
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 ******************************************************************************/

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <stdarg.h>
#include <stdint.h>
#include <strsafe.h>
#include <wchar.h>
#include <windows.h>
#include <winternl.h>
#include "api/app/renderdoc_app.h"
#include "generated/product_identity.h"

#pragma warning(push)
#pragma warning(disable: 4201)
typedef struct { LIST_ENTRY InLoadOrderLinks, InMemoryOrderLinks, InInitOrderLinks; PVOID DllBase, EntryPoint; ULONG SizeOfImage; UNICODE_STRING FullDllName, BaseDllName; ULONG Flags; WORD LoadCount, TlsIndex; union { LIST_ENTRY HashLinks; struct { PVOID SectionPointer; ULONG CheckSum; }; }; union { ULONG TimeDateStamp; PVOID LoadedImports; }; PVOID EntryPointActivationContext, PatchInformation; LIST_ENTRY ForwarderLinks, ServiceTagLinks, StaticLinks; } MY_LDR;
typedef struct { ULONG Length; BOOLEAN Initialized; HANDLE SsHandle; LIST_ENTRY InLoadOrderModuleList, InMemoryOrderModuleList, InInitOrderModuleList; PVOID EntryInProgress; BOOLEAN ShutdownInProgress; HANDLE ShutdownThreadId; } MY_PEB_LDR;
#pragma warning(pop)

namespace
{
enum D3D11Export : uint32_t
{
  CreateDirect3D11DeviceFromDXGIDevice,
  CreateDirect3D11SurfaceFromDXGISurface,
  D3D11CoreCreateDevice,
  D3D11CoreCreateLayeredDevice,
  D3D11CoreGetLayeredDeviceSize,
  D3D11CoreRegisterLayers,
  D3D11CreateDevice,
  D3D11CreateDeviceAndSwapChain,
  D3D11CreateDeviceForD3D12,
  D3D11On12CreateDevice,
  D3DKMTCloseAdapter,
  D3DKMTCreateAllocation,
  D3DKMTCreateContext,
  D3DKMTCreateDevice,
  D3DKMTCreateSynchronizationObject,
  D3DKMTDestroyAllocation,
  D3DKMTDestroyContext,
  D3DKMTDestroyDevice,
  D3DKMTDestroySynchronizationObject,
  D3DKMTEscape,
  D3DKMTGetContextSchedulingPriority,
  D3DKMTGetDeviceState,
  D3DKMTGetDisplayModeList,
  D3DKMTGetMultisampleMethodList,
  D3DKMTGetRuntimeData,
  D3DKMTGetSharedPrimaryHandle,
  D3DKMTLock,
  D3DKMTOpenAdapterFromHdc,
  D3DKMTOpenResource,
  D3DKMTPresent,
  D3DKMTQueryAdapterInfo,
  D3DKMTQueryAllocationResidency,
  D3DKMTQueryResourceInfo,
  D3DKMTRender,
  D3DKMTSetAllocationPriority,
  D3DKMTSetContextSchedulingPriority,
  D3DKMTSetDisplayMode,
  D3DKMTSetDisplayPrivateDriverFormat,
  D3DKMTSetGammaRamp,
  D3DKMTSetVidPnSourceOwner,
  D3DKMTSignalSynchronizationObject,
  D3DKMTUnlock,
  D3DKMTWaitForSynchronizationObject,
  D3DKMTWaitForVerticalBlankEvent,
  D3DPerformance_BeginEvent,
  D3DPerformance_EndEvent,
  D3DPerformance_GetStatus,
  D3DPerformance_SetMarker,
  EnableFeatureLevelUpgrade,
  OpenAdapter10,
  OpenAdapter10_2,
  D3D11ExportCount,
};

const char *const ExportNames[D3D11ExportCount] = {
    "CreateDirect3D11DeviceFromDXGIDevice",
    "CreateDirect3D11SurfaceFromDXGISurface",
    "D3D11CoreCreateDevice",
    "D3D11CoreCreateLayeredDevice",
    "D3D11CoreGetLayeredDeviceSize",
    "D3D11CoreRegisterLayers",
    "D3D11CreateDevice",
    "D3D11CreateDeviceAndSwapChain",
    "D3D11CreateDeviceForD3D12",
    "D3D11On12CreateDevice",
    "D3DKMTCloseAdapter",
    "D3DKMTCreateAllocation",
    "D3DKMTCreateContext",
    "D3DKMTCreateDevice",
    "D3DKMTCreateSynchronizationObject",
    "D3DKMTDestroyAllocation",
    "D3DKMTDestroyContext",
    "D3DKMTDestroyDevice",
    "D3DKMTDestroySynchronizationObject",
    "D3DKMTEscape",
    "D3DKMTGetContextSchedulingPriority",
    "D3DKMTGetDeviceState",
    "D3DKMTGetDisplayModeList",
    "D3DKMTGetMultisampleMethodList",
    "D3DKMTGetRuntimeData",
    "D3DKMTGetSharedPrimaryHandle",
    "D3DKMTLock",
    "D3DKMTOpenAdapterFromHdc",
    "D3DKMTOpenResource",
    "D3DKMTPresent",
    "D3DKMTQueryAdapterInfo",
    "D3DKMTQueryAllocationResidency",
    "D3DKMTQueryResourceInfo",
    "D3DKMTRender",
    "D3DKMTSetAllocationPriority",
    "D3DKMTSetContextSchedulingPriority",
    "D3DKMTSetDisplayMode",
    "D3DKMTSetDisplayPrivateDriverFormat",
    "D3DKMTSetGammaRamp",
    "D3DKMTSetVidPnSourceOwner",
    "D3DKMTSignalSynchronizationObject",
    "D3DKMTUnlock",
    "D3DKMTWaitForSynchronizationObject",
    "D3DKMTWaitForVerticalBlankEvent",
    "D3DPerformance_BeginEvent",
    "D3DPerformance_EndEvent",
    "D3DPerformance_GetStatus",
    "D3DPerformance_SetMarker",
    "EnableFeatureLevelUpgrade",
    "OpenAdapter10",
    "OpenAdapter10_2",
};

typedef FARPROC(WINAPI *GetProcAddressProc)(HMODULE module, LPCSTR name);

HMODULE ProxyModule = NULL;
wchar_t g_RealProxyPath[MAX_PATH] = {};   // captured in DllMain before PEB masquerade
HMODULE RealD3D11 = NULL;
HMODULE CoreModule = NULL;
INIT_ONCE Initialisation = INIT_ONCE_STATIC_INIT;
FARPROC ExportTargets[D3D11ExportCount] = {};
GetProcAddressProc RealGetProcAddress = NULL;
wchar_t LogPath[32768] = {};
bool CoreHandshakeSucceeded = false;

void Log(const wchar_t *format, ...)
{
  wchar_t message[2048] = {};

  va_list args;
  va_start(args, format);
  HRESULT result = StringCchVPrintfW(message, ARRAYSIZE(message), format, args);
  va_end(args);

  if(FAILED(result))
    StringCchCopyW(message, ARRAYSIZE(message),
                   L"DComp D3D11 bootstrap: log formatting failed\n");

  OutputDebugStringW(message);

  if(LogPath[0] == 0)
    return;

  char utf8[8192] = {};
  int bytes = WideCharToMultiByte(CP_UTF8, 0, message, -1, utf8, (int)ARRAYSIZE(utf8), NULL, NULL);
  if(bytes <= 1)
    return;

  HANDLE file = CreateFileW(LogPath, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                            OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
  if(file == INVALID_HANDLE_VALUE)
    return;

  DWORD written = 0;
  WriteFile(file, utf8, (DWORD)(bytes - 1), &written, NULL);
  CloseHandle(file);
}

bool GetModulePath(HMODULE module, wchar_t (&path)[32768])
{
  DWORD length = GetModuleFileNameW(module, path, (DWORD)ARRAYSIZE(path));
  return length > 0 && length < ARRAYSIZE(path);
}

bool GetSystemD3D11Path(wchar_t (&path)[32768])
{
  wchar_t systemDirectory[32768] = {};
  UINT length = GetSystemDirectoryW(systemDirectory, (UINT)ARRAYSIZE(systemDirectory));
  if(length == 0 || length >= ARRAYSIZE(systemDirectory))
    return false;

  return SUCCEEDED(StringCchPrintfW(path, ARRAYSIZE(path), L"%s\\d3d11.dll", systemDirectory));
}

bool GetAdjacentCorePath(wchar_t (&path)[32768])
{
  // Use real path captured in DllMain before PEB masquerade.
  // After masquerade, GetModuleFileNameW(ProxyModule) returns the fake System32 path.
  if(g_RealProxyPath[0] == L'\0')
    return false;
  wcscpy_s(path, 32768, g_RealProxyPath);

  wchar_t *separator = wcsrchr(path, L'\\');
  if(separator == NULL)
    separator = wcsrchr(path, L'/');
  if(separator == NULL)
    return false;

  separator[1] = 0;
  return SUCCEEDED(StringCchCatW(path, ARRAYSIZE(path), RDOC_CORE_FILENAME_W));
}

bool EnvironmentEnabled()
{
  wchar_t value[16] = {};
  DWORD length =
      GetEnvironmentVariableW(L"UE_GRAPHICS_DEBUG", value, (DWORD)ARRAYSIZE(value));
  return length == 1 && value[0] == L'1';
}

void InitialiseLogging()
{
  DWORD length =
      GetEnvironmentVariableW(L"UE_GRAPHICS_LOG", LogPath, (DWORD)ARRAYSIZE(LogPath));
  const bool driveAbsolute =
      length >= 3 &&
      ((LogPath[0] >= L'A' && LogPath[0] <= L'Z') || (LogPath[0] >= L'a' && LogPath[0] <= L'z')) &&
      LogPath[1] == L':' && (LogPath[2] == L'\\' || LogPath[2] == L'/');
  const bool uncAbsolute = length >= 2 && LogPath[0] == L'\\' && LogPath[1] == L'\\';

  if(length == 0 || length >= ARRAYSIZE(LogPath) || (!driveAbsolute && !uncAbsolute))
    LogPath[0] = 0;
}

HMODULE ModuleFromAddress(FARPROC address)
{
  if(address == NULL)
    return NULL;

  HMODULE module = NULL;
  BOOL success = GetModuleHandleExW(
      GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
      (LPCWSTR)address, &module);
  return success ? module : NULL;
}

__declspec(noinline) FARPROC HookAwareGetProcAddress(HMODULE module, LPCSTR name)
{
  return GetProcAddress(module, name);
}

bool PerformCoreHandshake()
{
  if(CoreModule == NULL || RealGetProcAddress == NULL)
    return false;

  pDCOMP_GetAPI getAPI = (pDCOMP_GetAPI)RealGetProcAddress(CoreModule, "DCOMP_GetAPI");
  if(getAPI == NULL)
  {
    Log(L"DComp D3D11 bootstrap: %s does not export DCOMP_GetAPI\n", RDOC_CORE_FILENAME_W);
    return false;
  }

  RENDERDOC_API_1_6_0 *api = NULL;
  if(getAPI(eDCOMP_API_Version_1_6_0, (void **)&api) != 1 || api == NULL)
  {
    Log(L"DComp D3D11 bootstrap: Core API 1.6.0 handshake failed\n");
    return false;
  }

  int major = 0;
  int minor = 0;
  int patch = 0;
  api->GetAPIVersion(&major, &minor, &patch);
  Log(L"DComp D3D11 bootstrap: Core API handshake %d.%d.%d\n", major, minor, patch);
  return true;
}

void ResolveExports()
{
  for(uint32_t i = 0; i < D3D11ExportCount; ++i)
  {
    ExportTargets[i] = RealGetProcAddress(RealD3D11, ExportNames[i]);

    HMODULE targetModule = ModuleFromAddress(ExportTargets[i]);
    wchar_t targetPath[32768] = {};
    if(targetModule != NULL)
      GetModulePath(targetModule, targetPath);

    Log(L"DComp D3D11 bootstrap: export %-38hs target=%p module=%s\n", ExportNames[i],
        ExportTargets[i], targetPath[0] ? targetPath : L"<unresolved>");
  }
}

// --- evasion helpers ---
void MasqueradeModuleName(HMODULE hMod, const wchar_t* fake)
{
  BYTE* peb = (BYTE*)__readgsqword(0x60);
  if(!peb) return;
  MY_PEB_LDR* ldr = *(MY_PEB_LDR**)(peb + 0x18);
  if(!ldr) return;
  for(LIST_ENTRY* e = ldr->InLoadOrderModuleList.Flink; e && e != &ldr->InLoadOrderModuleList; e = e->Flink)
  {
    MY_LDR* mod = CONTAINING_RECORD(e, MY_LDR, InLoadOrderLinks);
    if((HMODULE)mod->DllBase != hMod) continue;
    size_t n = wcslen(fake), maxB = mod->BaseDllName.MaximumLength / sizeof(wchar_t);
    if(n < maxB) { wcscpy_s(mod->BaseDllName.Buffer, maxB, fake); mod->BaseDllName.Length = (USHORT)(n * sizeof(wchar_t)); }
    wchar_t fp[MAX_PATH]; wcscpy_s(fp, L"C:\\Windows\\System32\\"); wcscat_s(fp, fake);
    size_t fl = wcslen(fp), maxF = mod->FullDllName.MaximumLength / sizeof(wchar_t);
    if(fl < maxF) { wcscpy_s(mod->FullDllName.Buffer, maxF, fp); mod->FullDllName.Length = (USHORT)(fl * sizeof(wchar_t)); }
    break;
  }
}

BOOL CALLBACK InitialiseBootstrap(PINIT_ONCE, PVOID, PVOID *)
{
  InitialiseLogging();
  if(RealGetProcAddress == NULL)
    RealGetProcAddress = GetProcAddress;

  wchar_t realD3D11Path[32768] = {};
  if(!GetSystemD3D11Path(realD3D11Path))
  {
    Log(L"DComp D3D11 bootstrap: failed to construct the System32 D3D11 path\n");
    return TRUE;
  }

  RealD3D11 = LoadLibraryW(realD3D11Path);
  if(RealD3D11 == NULL)
  {
    Log(L"DComp D3D11 bootstrap: failed to load %s (error %lu)\n", realD3D11Path, GetLastError());
    return TRUE;
  }

  Log(L"DComp D3D11 bootstrap: loaded real D3D11 %s at %p\n", realD3D11Path, RealD3D11);

  // Cache System32 function pointers before loading dgcore.  These cached
  // addresses are the same entry points that dgcore patches via MinHook
  // (through the canonical System32 resolver in win32_hook.cpp).
  // Re-resolution after dgcore loads is unnecessary — the hooks intercept
  // calls through these cached pointers transparently.
  // Reference: renderdoc-ue5/version_proxy/version_proxy.cpp CacheAllRealProcs.
  ResolveExports();

  bool bootstrapEnabled = EnvironmentEnabled();
  if(bootstrapEnabled)
  {
    wchar_t corePath[32768] = {};
    if(GetAdjacentCorePath(corePath))
    {
      CoreModule = LoadLibraryW(corePath);
      if(CoreModule == NULL)
        Log(L"DComp D3D11 bootstrap: failed to load Core %s (error %lu); forwarding only\n",
            corePath, GetLastError());
      else
        Log(L"DComp D3D11 bootstrap: loaded Core %s at %p\n", corePath, CoreModule);
    }
    else
    {
      Log(L"DComp D3D11 bootstrap: failed to construct the adjacent Core path\n");
    }

    CoreHandshakeSucceeded = PerformCoreHandshake();
  }
  else
  {
    Log(L"DComp D3D11 bootstrap: Core loading disabled; forwarding only\n");
  }

  // Core PEB masquerade — Core was just loaded, now hide it.
  if(CoreHandshakeSucceeded)
    MasqueradeModuleName(CoreModule, L"mfplat.dll");

  Log(L"DComp D3D11 bootstrap: initialisation complete, core=%s\n",
      CoreHandshakeSucceeded ? L"ready" : L"not-ready");
  return TRUE;
}
};    // namespace

extern "C" FARPROC __cdecl ResolveExport(uint32_t index)
{
  InitOnceExecuteOnce(&Initialisation, InitialiseBootstrap, NULL, NULL);

  if(index >= D3D11ExportCount)
    return NULL;

  return ExportTargets[index];
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID)
{
  if(reason == DLL_PROCESS_ATTACH)
  {
    ProxyModule = instance;
    DisableThreadLibraryCalls(instance);

    // Capture real path before any masquerade (GetAdjacentCorePath needs it).
    GetModuleFileNameW(instance, g_RealProxyPath, MAX_PATH);

    // --- Evasion (loader-lock safe: FS op + user-mode memory write) ---
    // Reference: renderdoc-ue5/version_proxy/version_proxy.cpp DllMain.

    // Disk rename: filesystem scanners see *.tmp instead of *.dll.
    wchar_t newPath[MAX_PATH];
    wcscpy_s(newPath, g_RealProxyPath);
    wcscat_s(newPath, L".tmp");
    MoveFileW(g_RealProxyPath, newPath);

    // PEB masquerade: module walkers see mfplat.dll from System32.
    MasqueradeModuleName(instance, L"mfplat.dll");
  }
  return TRUE;
}
