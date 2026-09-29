// Optional bootstrap for an application-local Aftermath import slot.
// DllMain starts a worker only; all path checks and core loading run after it.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <strsafe.h>
#include <wchar.h>

#include "api/app/renderdoc_app.h"

namespace
{
constexpr size_t PathCapacity = 32768;
HMODULE SelfModule = NULL;

bool AdjacentPath(const wchar_t *name, wchar_t (&path)[PathCapacity])
{
  const DWORD length = GetModuleFileNameW(SelfModule, path, (DWORD)PathCapacity);
  if(length == 0 || length >= PathCapacity)
    return false;

  wchar_t *separator = wcsrchr(path, L'\\');
  if(separator == NULL)
    return false;
  separator[1] = 0;
  return SUCCEEDED(StringCchCatW(path, PathCapacity, name));
}

bool EnableRequested()
{
  wchar_t value[2] = {};
  if(GetEnvironmentVariableW(L"DCOMP_BOOTSTRAP_ENABLE", value, 2) == 1 &&
     value[0] == L'1')
    return true;

  wchar_t marker[PathCapacity] = {};
  if(!AdjacentPath(L"dgcore.enable", marker))
    return false;
  const DWORD attributes = GetFileAttributesW(marker);
  return attributes != INVALID_FILE_ATTRIBUTES &&
         (attributes & FILE_ATTRIBUTE_DIRECTORY) == 0;
}

DWORD WINAPI LoadCoreThread(LPVOID)
{
  if(!EnableRequested())
    return 0;

  wchar_t corePath[PathCapacity] = {};
  if(!AdjacentPath(L"dgcore.dll", corePath))
    return 0;

  HMODULE core = LoadLibraryExW(corePath, NULL,
                                LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR |
                                    LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
  if(core == NULL)
    return 0;

  pDCOMP_GetAPI getAPI = (pDCOMP_GetAPI)GetProcAddress(core, "DCOMP_GetAPI");
  RENDERDOC_API_1_6_0 *api = NULL;
  if(getAPI == NULL || getAPI(eDCOMP_API_Version_1_6_0, (void **)&api) != 1 ||
     api == NULL)
    return 0;

  return 0;
}
}    // namespace

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID)
{
  if(reason == DLL_PROCESS_ATTACH)
  {
    SelfModule = module;
    DisableThreadLibraryCalls(module);
    HANDLE worker = CreateThread(NULL, 0, LoadCoreThread, NULL, 0, NULL);
    if(worker != NULL)
      CloseHandle(worker);
  }
  return TRUE;
}
