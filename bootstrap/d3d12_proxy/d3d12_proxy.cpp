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
#include "api/app/renderdoc_app.h"
#include "generated/product_identity.h"

namespace
{
enum D3D12Export : uint32_t
{
  D3D12Ordinal99,
  SetAppCompatStringPointer,
  D3D12CreateDevice,
  D3D12GetDebugInterface,
  D3D12CoreCreateLayeredDevice,
  D3D12CoreGetLayeredDeviceSize,
  D3D12CoreRegisterLayers,
  D3D12CreateRootSignatureDeserializer,
  D3D12CreateVersionedRootSignatureDeserializer,
  D3D12DeviceRemovedExtendedData,
  D3D12EnableExperimentalFeatures,
  D3D12GetInterface,
  D3D12PIXEventsReplaceBlock,
  D3D12PIXGetThreadInfo,
  D3D12PIXNotifyWakeFromFenceSignal,
  D3D12PIXReportCounter,
  D3D12SerializeRootSignature,
  D3D12SerializeVersionedRootSignature,
  GetBehaviorValue,
  D3D12ExportCount,
};

const char *const ExportNames[D3D12ExportCount] = {
    NULL,
    "SetAppCompatStringPointer",
    "D3D12CreateDevice",
    "D3D12GetDebugInterface",
    "D3D12CoreCreateLayeredDevice",
    "D3D12CoreGetLayeredDeviceSize",
    "D3D12CoreRegisterLayers",
    "D3D12CreateRootSignatureDeserializer",
    "D3D12CreateVersionedRootSignatureDeserializer",
    "D3D12DeviceRemovedExtendedData",
    "D3D12EnableExperimentalFeatures",
    "D3D12GetInterface",
    "D3D12PIXEventsReplaceBlock",
    "D3D12PIXGetThreadInfo",
    "D3D12PIXNotifyWakeFromFenceSignal",
    "D3D12PIXReportCounter",
    "D3D12SerializeRootSignature",
    "D3D12SerializeVersionedRootSignature",
    "GetBehaviorValue",
};

typedef FARPROC(WINAPI *GetProcAddressProc)(HMODULE module, LPCSTR name);

HMODULE ProxyModule = NULL;
HMODULE RealD3D12 = NULL;
HMODULE CoreModule = NULL;
INIT_ONCE Initialisation = INIT_ONCE_STATIC_INIT;
FARPROC ExportTargets[D3D12ExportCount] = {};
FARPROC RealExportTargets[D3D12ExportCount] = {};
GetProcAddressProc RealGetProcAddress = NULL;
wchar_t LogPath[32768] = {};
bool CoreHandshakeSucceeded = false;
bool HookTargetsActive = false;

void Log(const wchar_t *format, ...)
{
  wchar_t message[2048] = {};

  va_list args;
  va_start(args, format);
  HRESULT result = StringCchVPrintfW(message, ARRAYSIZE(message), format, args);
  va_end(args);

  if(FAILED(result))
    StringCchCopyW(message, ARRAYSIZE(message),
                   L"DComp D3D12 bootstrap: log formatting failed\n");

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

bool GetSystemD3D12Path(wchar_t (&path)[32768])
{
  wchar_t systemDirectory[32768] = {};
  UINT length = GetSystemDirectoryW(systemDirectory, (UINT)ARRAYSIZE(systemDirectory));
  if(length == 0 || length >= ARRAYSIZE(systemDirectory))
    return false;

  return SUCCEEDED(StringCchPrintfW(path, ARRAYSIZE(path), L"%s\\d3d12.dll", systemDirectory));
}

bool GetAdjacentCorePath(wchar_t (&path)[32768])
{
  if(!GetModulePath(ProxyModule, path))
    return false;

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
    Log(L"DComp D3D12 bootstrap: %s does not export DCOMP_GetAPI\n", RDOC_CORE_FILENAME_W);
    return false;
  }

  RENDERDOC_API_1_6_0 *api = NULL;
  if(getAPI(eDCOMP_API_Version_1_6_0, (void **)&api) != 1 || api == NULL)
  {
    Log(L"DComp D3D12 bootstrap: Core API 1.6.0 handshake failed\n");
    return false;
  }

  int major = 0;
  int minor = 0;
  int patch = 0;
  api->GetAPIVersion(&major, &minor, &patch);
  Log(L"DComp D3D12 bootstrap: Core API handshake %d.%d.%d\n", major, minor, patch);
  return true;
}

void ResolveExports(bool useHookAwareLookup)
{
  for(uint32_t i = 0; i < D3D12ExportCount; ++i)
  {
    LPCSTR identifier =
        i == D3D12Ordinal99 ? MAKEINTRESOURCEA(99) : ExportNames[i];
    FARPROC target = useHookAwareLookup ? HookAwareGetProcAddress(RealD3D12, identifier)
                                        : RealGetProcAddress(RealD3D12, identifier);
    ExportTargets[i] = target;
    if(!useHookAwareLookup)
      RealExportTargets[i] = target;

    HMODULE targetModule = ModuleFromAddress(target);
    wchar_t targetPath[32768] = {};
    if(targetModule != NULL)
      GetModulePath(targetModule, targetPath);

    if(i == D3D12Ordinal99)
      Log(L"DComp D3D12 bootstrap: export ordinal #99 target=%p module=%s\n", target,
          targetPath[0] ? targetPath : L"<unresolved>");
    else
      Log(L"DComp D3D12 bootstrap: export %-38hs target=%p module=%s\n", ExportNames[i],
          target, targetPath[0] ? targetPath : L"<unresolved>");
  }
}

void RestoreRealExports()
{
  for(uint32_t i = 0; i < D3D12ExportCount; ++i)
    ExportTargets[i] = RealExportTargets[i];
}

bool VerifyHookTargets()
{
  const D3D12Export required[] = {
      D3D12CreateDevice,
      D3D12GetDebugInterface,
      D3D12GetInterface,
      D3D12EnableExperimentalFeatures,
  };

  for(D3D12Export index : required)
  {
    if(ExportTargets[index] == NULL || ModuleFromAddress(ExportTargets[index]) != CoreModule)
      return false;
  }

  return true;
}

BOOL CALLBACK InitialiseBootstrap(PINIT_ONCE, PVOID, PVOID *)
{
  InitialiseLogging();
  if(RealGetProcAddress == NULL)
    RealGetProcAddress = GetProcAddress;

  wchar_t realD3D12Path[32768] = {};
  if(!GetSystemD3D12Path(realD3D12Path))
  {
    Log(L"DComp D3D12 bootstrap: failed to construct the System32 D3D12 path\n");
    return TRUE;
  }

  RealD3D12 = LoadLibraryW(realD3D12Path);
  if(RealD3D12 == NULL)
  {
    Log(L"DComp D3D12 bootstrap: failed to load %s (error %lu)\n", realD3D12Path, GetLastError());
    return TRUE;
  }

  Log(L"DComp D3D12 bootstrap: loaded real D3D12 %s at %p\n", realD3D12Path, RealD3D12);

  // Resolve a stable real forwarding table before loading the Core. D3D12's public loader remains
  // the System32 d3d12.dll even when an application selects a private Agility SDK D3D12Core.dll.
  ResolveExports(false);

  bool bootstrapEnabled = EnvironmentEnabled();
  if(bootstrapEnabled)
  {
    wchar_t corePath[32768] = {};
    if(GetAdjacentCorePath(corePath))
    {
      CoreModule = LoadLibraryW(corePath);
      if(CoreModule == NULL)
        Log(L"DComp D3D12 bootstrap: failed to load Core %s (error %lu); forwarding only\n",
            corePath, GetLastError());
      else
        Log(L"DComp D3D12 bootstrap: loaded Core %s at %p\n", corePath, CoreModule);
    }
    else
    {
      Log(L"DComp D3D12 bootstrap: failed to construct the adjacent Core path\n");
    }

    CoreHandshakeSucceeded = PerformCoreHandshake();
  }
  else
  {
    Log(L"DComp D3D12 bootstrap: Core loading disabled; forwarding only\n");
  }

  if(CoreHandshakeSucceeded)
  {
    ResolveExports(true);
    HookTargetsActive = VerifyHookTargets();

    if(!HookTargetsActive)
    {
      Log(L"DComp D3D12 bootstrap: Core loaded but D3D12 hook targets were not active; "
          L"falling back to the pre-Core real exports\n");
      RestoreRealExports();
    }
  }

  Log(L"DComp D3D12 bootstrap: initialisation complete, core=%s hooks=%s\n",
      CoreHandshakeSucceeded ? L"ready" : L"not-ready", HookTargetsActive ? L"active" : L"inactive");
  return TRUE;
}
};    // namespace

extern "C" FARPROC __cdecl ResolveExport(uint32_t index)
{
  InitOnceExecuteOnce(&Initialisation, InitialiseBootstrap, NULL, NULL);

  if(index >= D3D12ExportCount)
    return NULL;

  return ExportTargets[index];
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID)
{
  if(reason == DLL_PROCESS_ATTACH)
  {
    ProxyModule = instance;
    DisableThreadLibraryCalls(instance);
    // Capture the unmodified import before an already-loaded Core can patch this proxy after
    // DllMain returns. No module loading is performed while the loader lock is held.
    RealGetProcAddress = GetProcAddress;
  }

  return TRUE;
}
