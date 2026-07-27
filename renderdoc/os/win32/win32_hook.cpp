/******************************************************************************
 * The MIT License (MIT)
 *
 * Copyright (c) 2015-2026 Baldur Karlsson
 * Copyright (c) 2014 Crytek
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 ******************************************************************************/

// must be separate so that it's included first and not sorted by clang-format
#include <windows.h>
#include <winternl.h>

#include <delayimp.h>
#include <tlhelp32.h>
#include <algorithm>
#include <functional>
#include <map>
#include <set>
#include "common/common.h"
#include "common/threading.h"
#include "generated/product_identity.h"
#include "hooks/hooks.h"
#include "os/os_specific.h"
#include "strings/string_utils.h"

#define VERBOSE_DEBUG_HOOK OPTION_OFF

static bool GetCanonicalSystemModulePath(const rdcstr &libraryName, rdcwstr &modulePath)
{
  // These public graphics entry modules are operating-system components. A same-name bootstrap
  // proxy may already be loaded when hooks are registered, so onward calls must use the canonical
  // System32 module. Agility SDK applications still select their private implementation through
  // D3D12Core.dll; the public d3d12.dll loader remains the System32 component.
  if(_stricmp(libraryName.c_str(), "dxgi.dll") != 0 &&
     _stricmp(libraryName.c_str(), "d3d11.dll") != 0 &&
     _stricmp(libraryName.c_str(), "d3d12.dll") != 0)
    return false;

  rdcarray<wchar_t> systemDirectory;
  systemDirectory.resize(256);

  while(true)
  {
    UINT length = GetSystemDirectoryW(systemDirectory.data(), (UINT)systemDirectory.size());
    if(length == 0)
      return false;

    if((size_t)length < systemDirectory.size())
      break;

    // On insufficient space GetSystemDirectoryW returns the required size including the null.
    systemDirectory.resize(length);
  }

  const size_t directoryLength = wcslen(systemDirectory.data());
  const bool addSeparator = directoryLength > 0 && systemDirectory[directoryLength - 1] != L'\\' &&
                            systemDirectory[directoryLength - 1] != L'/';
  const rdcwstr wideLibraryName = StringFormat::UTF82Wide(libraryName);
  const size_t libraryNameLength = wideLibraryName.length();

  modulePath = rdcwstr(directoryLength + (addSeparator ? 1 : 0) + libraryNameLength);

  size_t offset = 0;
  memcpy(modulePath.data(), systemDirectory.data(), directoryLength * sizeof(wchar_t));
  offset += directoryLength;

  if(addSeparator)
    modulePath[offset++] = L'\\';

  memcpy(modulePath.data() + offset, wideLibraryName.c_str(),
         (libraryNameLength + 1) * sizeof(wchar_t));
  return true;
}

static bool ModulePathMatches(HMODULE module, const rdcwstr &expectedPath)
{
  if(module == NULL || expectedPath.c_str() == NULL || expectedPath.c_str()[0] == 0)
    return false;

  rdcarray<wchar_t> modulePath;
  modulePath.resize(512);

  while(true)
  {
    DWORD length = GetModuleFileNameW(module, modulePath.data(), (DWORD)modulePath.size());
    if(length == 0)
      return false;

    if((size_t)length < modulePath.size())
      return _wcsicmp(modulePath.data(), expectedPath.c_str()) == 0;

    // A Windows module path cannot exceed 32,767 characters. Fail closed if an invalid module
    // handle keeps reporting a truncated path.
    if(modulePath.size() >= 32768)
      return false;

    modulePath.resize(modulePath.size() * 2);
  }
}

static HMODULE GetLoadedCanonicalSystemModule(const rdcstr &libraryName)
{
  rdcwstr modulePath;
  if(!GetCanonicalSystemModulePath(libraryName, modulePath))
    return NULL;

  // Hook registration runs under the loader lock. Query only: the bootstrap must load the real
  // System32 DXGI before loading the Core if a same-name proxy is already present.
  HMODULE module = GetModuleHandleW(modulePath.c_str());
  if(module == NULL || !ModulePathMatches(module, modulePath))
    return NULL;

  return module;
}

static HMODULE GetPreferredOriginalModule(const rdcstr &libraryName, HMODULE fallback)
{
  HMODULE systemModule = GetLoadedCanonicalSystemModule(libraryName);
  return systemModule ? systemModule : fallback;
}

static bool ModuleHandleIsLoaded(HMODULE module)
{
  if(module == NULL)
    return false;

  HMODULE currentModule = NULL;
  BOOL success = GetModuleHandleExW(
      GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
      (LPCWSTR)module, &currentModule);
  return success && currentModule == module;
}

static bool IsValidImageRange(size_t imageSize, size_t rva, size_t byteCount)
{
  return rva < imageSize && byteCount <= imageSize - rva;
}

static bool IsReadableMemoryProtection(DWORD protection)
{
  if(protection & PAGE_GUARD)
    return false;

  const DWORD access = protection & 0xff;
  return access == PAGE_READONLY || access == PAGE_READWRITE || access == PAGE_WRITECOPY ||
         access == PAGE_EXECUTE_READ || access == PAGE_EXECUTE_READWRITE ||
         access == PAGE_EXECUTE_WRITECOPY;
}

static size_t GetReadableImageSpan(const byte *baseAddress, size_t imageSize, size_t rva)
{
  if(!IsValidImageRange(imageSize, rva, 1))
    return 0;

  const byte *current = baseAddress + rva;
  size_t remaining = imageSize - rva;
  size_t readable = 0;

  while(remaining > 0)
  {
    MEMORY_BASIC_INFORMATION memory = {};
    if(VirtualQuery(current, &memory, sizeof(memory)) != sizeof(memory) ||
       memory.AllocationBase != baseAddress || memory.State != MEM_COMMIT ||
       !IsReadableMemoryProtection(memory.Protect))
      break;

    const byte *regionBase = (const byte *)memory.BaseAddress;
    if(current < regionBase)
      break;

    const size_t regionOffset = (size_t)(current - regionBase);
    if(regionOffset >= memory.RegionSize)
      break;

    const size_t available = memory.RegionSize - regionOffset;
    const size_t advance = RDCMIN(available, remaining);
    if(advance == 0)
      break;

    readable += advance;
    remaining -= advance;
    current += advance;
  }

  return readable;
}

static const char *GetImageString(const byte *baseAddress, size_t imageSize, size_t rva)
{
  const size_t readable = GetReadableImageSpan(baseAddress, imageSize, rva);
  if(readable == 0)
    return NULL;

  const char *str = (const char *)(baseAddress + rva);
  return memchr(str, 0, readable) ? str : NULL;
}

// ---- Hook mode control ----
// IATAndInline: normal operation, patch IAT entries (default)
// ProxyOnly: skip all IAT patches and page protection changes.
//   Used when proxy DLLs (dxgi/d3d12/d3d11) intercept CreateDevice
//   entry points via DLL sideloading, making IAT modification unnecessary.
enum class HookMode { IATAndInline, ProxyOnly };
static HookMode g_HookMode = HookMode::IATAndInline;

extern "C" __declspec(dllexport) void DCOMP_SetHookMode(int mode)
{
  g_HookMode = (mode == 0) ? HookMode::ProxyOnly : HookMode::IATAndInline;
}

static bool IsProxyOnly()
{
  return g_HookMode == HookMode::ProxyOnly;
}

// Use ntdll!NtProtectVirtualMemory instead of kernel32!VirtualProtect
// to avoid "VirtualProtect" appearing in the static import table.
static BOOL ProtectPage(void *addr, SIZE_T size, DWORD newProtect, DWORD &oldProtect)
{
  HMODULE ntdll = GetModuleHandleA("ntdll.dll");
  if(!ntdll) return FALSE;

  typedef NTSTATUS(NTAPI * NtProtectVirtualMemory_t)(
      HANDLE, PVOID *, PSIZE_T, ULONG, PULONG);
  static NtProtectVirtualMemory_t pNtProtect = NULL;
  if(!pNtProtect)
    pNtProtect = (NtProtectVirtualMemory_t)GetProcAddress(ntdll, "NtProtectVirtualMemory");
  if(!pNtProtect) return FALSE;

  PVOID base = addr;
  SIZE_T sz = size;
  ULONG old = 0;
  NTSTATUS st = pNtProtect(GetCurrentProcess(), &base, &sz, newProtect, &old);
  oldProtect = (DWORD)old;
  return NT_SUCCESS(st);
}

// map from address of IAT entry, to original contents
std::map<void **, void *> s_InstalledHooks;
Threading::CriticalSection installedLock;

bool ApplyHook(FunctionHook &hook, void **IATentry, bool &already)
{
  if(IsProxyOnly())
    return true;  // skip all IAT patches in ProxyOnly mode

  DWORD oldProtection = PAGE_EXECUTE;

  if(*IATentry == hook.hook)
  {
    already = true;
    return true;
  }

#if ENABLED(VERBOSE_DEBUG_HOOK)
  RDCDEBUG("Patching IAT for %s: %p to %p", hook.function.c_str(), IATentry, hook.hook);
#endif

  {
    SCOPED_LOCK(installedLock);
    if(s_InstalledHooks.find(IATentry) == s_InstalledHooks.end())
      s_InstalledHooks[IATentry] = *IATentry;
  }

  if(!ProtectPage(IATentry, sizeof(void *), PAGE_READWRITE, oldProtection))
  {
    RDCERR("Failed to make IAT entry writeable 0x%p", IATentry);
    return false;
  }

  *IATentry = hook.hook;

  if(!ProtectPage(IATentry, sizeof(void *), oldProtection, oldProtection))
  {
    RDCERR("Failed to restore IAT entry protection 0x%p", IATentry);
    return false;
  }

  return true;
}

struct DllHookset
{
  HMODULE module = NULL;
  // Onward calls may need a different module from the handle used for matching imports and
  // GetProcAddress requests. In particular, a local dxgi.dll proxy remains a matched module while
  // original calls resolve directly against the already-loaded System32 DXGI.
  HMODULE originalModule = NULL;
  bool hooksfetched = false;
  // if we have multiple copies of the dll loaded (unlikely), the other module handles will be
  // stored here
  rdcarray<HMODULE> altmodules;
  rdcarray<FunctionHook> FunctionHooks;
  DWORD OrdinalBase = 0;
  rdcarray<rdcstr> OrdinalNames;
  rdcarray<FunctionLoadCallback> Callbacks;
  Threading::CriticalSection ordinallock;

  void FetchOrdinalNames()
  {
    SCOPED_LOCK(ordinallock);

    // return if we already fetched the ordinals
    if(!OrdinalNames.empty())
      return;

    byte *baseAddress = (byte *)module;

#if ENABLED(VERBOSE_DEBUG_HOOK)
    RDCDEBUG("FetchOrdinalNames");
#endif

    PIMAGE_DOS_HEADER dosheader = (PIMAGE_DOS_HEADER)baseAddress;

    if(dosheader->e_magic != 0x5a4d)
      return;

    char *PE00 = (char *)(baseAddress + dosheader->e_lfanew);
    PIMAGE_FILE_HEADER fileHeader = (PIMAGE_FILE_HEADER)(PE00 + 4);
    PIMAGE_OPTIONAL_HEADER optHeader =
        (PIMAGE_OPTIONAL_HEADER)((BYTE *)fileHeader + sizeof(IMAGE_FILE_HEADER));

    DWORD eatOffset = optHeader->DataDirectory[IMAGE_DIRECTORY_ENTRY_EXPORT].VirtualAddress;

    IMAGE_EXPORT_DIRECTORY *exportDesc = (IMAGE_EXPORT_DIRECTORY *)(baseAddress + eatOffset);

    WORD *ordinals = (WORD *)(baseAddress + exportDesc->AddressOfNameOrdinals);
    DWORD *names = (DWORD *)(baseAddress + exportDesc->AddressOfNames);

    DWORD count = RDCMIN(exportDesc->NumberOfFunctions, exportDesc->NumberOfNames);

    WORD maxOrdinal = 0;
    for(DWORD i = 0; i < count; i++)
      maxOrdinal = RDCMAX(maxOrdinal, ordinals[i]);

    OrdinalBase = exportDesc->Base;
    OrdinalNames.resize(maxOrdinal + 1);

    for(DWORD i = 0; i < count; i++)
    {
      OrdinalNames[ordinals[i]] = (char *)(baseAddress + names[i]);

#if ENABLED(VERBOSE_DEBUG_HOOK)
      RDCDEBUG("ordinal found: '%s' %u", OrdinalNames[ordinals[i]].c_str(), (uint32_t)ordinals[i]);
#endif
    }
  }
};

static void RefreshOriginalModule(const rdcstr &libraryName, DllHookset &hookset, HMODULE fallback)
{
  // The caller must hold CachedHookData::lock while selecting and rebinding original pointers.
  HMODULE selected = GetPreferredOriginalModule(libraryName, fallback);
  if(selected == NULL || selected == hookset.originalModule)
    return;

  HMODULE previous = hookset.originalModule;
  bool previousIsLoaded = ModuleHandleIsLoaded(previous);

  for(FunctionHook &hook : hookset.FunctionHooks)
  {
    if(hook.orig == NULL)
      continue;

    if(previous == NULL)
    {
      if(*hook.orig == NULL)
        *hook.orig = GetProcAddress(selected, hook.function.c_str());
    }
    else if(!previousIsLoaded)
    {
      // The old module was unloaded, so its export address cannot be queried safely.
      *hook.orig = GetProcAddress(selected, hook.function.c_str());
    }
    else
    {
      // Preserve first-hook precedence when multiple hooks intentionally share an original pointer.
      void *previousFunction = GetProcAddress(previous, hook.function.c_str());
      if(*hook.orig == previousFunction)
        *hook.orig = GetProcAddress(selected, hook.function.c_str());
    }
  }

  hookset.originalModule = selected;
}

struct CachedHookData
{
  bool hookAll = true;

  std::map<rdcstr, DllHookset> DllHooks;
  HMODULE ownmodule = NULL;
  Threading::CriticalSection lock;

  std::set<rdcstr> ignores;

  bool missedOrdinals = false;
  std::function<HMODULE(const rdcstr &, HANDLE, DWORD)> libraryIntercept;

  int32_t posthooking = 0;

  bool ShouldSkipImportPatching(const char *lowername)
  {
    // for safety (and because we don't need to), ignore these modules
    if(!_stricmp(lowername, "kernel32.dll") || !_stricmp(lowername, "powrprof.dll") ||
       !_stricmp(lowername, "CoreMessaging.dll") || !_stricmp(lowername, "opengl32.dll") ||
       !_stricmp(lowername, "gdi32.dll") || !_stricmp(lowername, "gdi32full.dll") ||
       !_stricmp(lowername, "windows.storage.dll") || !_stricmp(lowername, "nvoglv32.dll") ||
       !_stricmp(lowername, "nvoglv64.dll") || !_stricmp(lowername, "vulkan-1.dll") ||
       !_stricmp(lowername, "atio6axx.dll") || !_stricmp(lowername, "atioglxx.dll") ||
       !_stricmp(lowername, "nvcuda.dll") || strstr(lowername, "cudart") == lowername ||
       strstr(lowername, "msvcr") == lowername || strstr(lowername, "msvcp") == lowername ||
       strstr(lowername, "nv-vk") == lowername || strstr(lowername, "amdvlk") == lowername ||
       strstr(lowername, "igvk") == lowername || strstr(lowername, "nvopencl") == lowername ||
       strstr(lowername, "nvapi") == lowername)
      return true;

    return ignores.find(lowername) != ignores.end();
  }

  void ApplyHooks(const char *modName, HMODULE module)
  {
    char lowername[512] = {};

    {
      size_t i = 0;
      while(modName[i])
      {
        lowername[i] = (char)tolower(modName[i]);
        i++;
      }
      lowername[i] = 0;
    }

#if ENABLED(VERBOSE_DEBUG_HOOK)
    RDCDEBUG("=== ApplyHooks(%s, %p)", modName, module);
#endif

    // fraps seems to non-safely modify the assembly around the hook function, if
    // we modify its import descriptors it leads to a crash as it hooks OUR functions.
    // instead, skip modifying the import descriptors, it will hook the 'real' d3d functions
    // and we can call them and have fraps + renderdoc playing nicely together.
    // we also exclude some other overlay renderers here, such as steam's
    //
    // Also we exclude ourselves here - just in case the application has already loaded
    // our core DLL, or tries to load it.
    if(strstr(lowername, "fraps") || strstr(lowername, "gameoverlayrenderer") ||
       _strnicmp(lowername, RDOC_CORE_FILENAME, strlen(RDOC_CORE_FILENAME)) == 0)
      return;

    // set module pointer if we are hooking exports from this module
    for(auto it = DllHooks.begin(); it != DllHooks.end(); ++it)
    {
      if(!_stricmp(it->first.c_str(), modName))
      {
        SCOPED_LOCK(lock);

        // Refresh before checking alternate modules. A late-loaded canonical DXGI may already be in
        // the alternate list, but its presence must still move onward calls away from a proxy.
        RefreshOriginalModule(it->first, it->second, it->second.module ? it->second.module : module);

        if(it->second.module == NULL)
        {
          it->second.module = module;

          it->second.hooksfetched = true;

          // Fetch all original function pointers even if no module imports them. When a local DXGI
          // proxy coexists with the real System32 DXGI, keep the proxy as the matching module but
          // use the canonical module for onward calls.
          it->second.FetchOrdinalNames();
        }
        else if(it->second.module != module)
        {
          // if it's already in altmodules, bail
          bool already = false;

          for(size_t i = 0; i < it->second.altmodules.size(); i++)
          {
            if(it->second.altmodules[i] == module)
            {
              already = true;
              break;
            }
          }

          if(already)
            break;

          // check if the previous module is still valid
          SetLastError(0);
          char filename[MAX_PATH] = {};
          GetModuleFileNameA(it->second.module, filename, MAX_PATH - 1);
          DWORD err = GetLastError();
          char *slash = strrchr(filename, L'\\');

          rdcstr basename = slash ? strlower(rdcstr(slash + 1)) : "";

          if(err == 0 && basename == it->first)
          {
            // previous module is still loaded, add this to the alt modules list
            it->second.altmodules.push_back(module);
          }
          else
          {
            // previous module is no longer loaded or there's a new file there now, add this as the
            // new location
            RDCWARN("%s moved from %p to %p, re-initialising orig pointers", it->first.c_str(),
                    it->second.module, module);

            // we also need to re-initialise the hooks as the orig pointers are now stale
            HMODULE originalModule = GetPreferredOriginalModule(it->first, module);
            for(FunctionHook &hook : it->second.FunctionHooks)
            {
              if(hook.orig)
                *hook.orig = GetProcAddress(originalModule, hook.function.c_str());
            }

            it->second.module = module;
            it->second.originalModule = originalModule;
          }
        }
      }
    }

    if(ShouldSkipImportPatching(lowername))
      return;

    // the module could have been unloaded after our toolhelp snapshot, especially if we spent a
    // long time
    // dealing with a previous module (like adding our hooks).
    wchar_t modpath[1024] = {0};
    GetModuleFileNameW(module, modpath, 1023);
    if(modpath[0] == 0)
      return;

    // windows 11 and newer versions have weird hotpatch DLLs that don't act like real DLLs. The
    // LoadLibraryW below will fail for these DLLs even when using the module path provided.
    // Only check the path for DLLs that might be a windows-hotpatch but if it matches we'll skip
    // hooking these to avoid problems
    if(strstr(lowername, "hotpatch"))
    {
      wchar_t lowerpath[1024] = {};

      size_t i = 0;
      while(modpath[i])
      {
        lowerpath[i] = towlower(modpath[i]);
        i++;
      }
      lowerpath[i] = 0;

      if(wcsstr(lowerpath, L"\\windows\\winsxs\\"))
        return;
    }

    // increment the module reference count, so it doesn't disappear while we're processing it
    // there's a very small race condition here between if GetModuleFileName returns, the module is
    // unloaded then we load it again. The only way around that is inserting very scary locks
    // between here
    // and FreeLibrary that I want to avoid. Worst case, we load a dll, hook it, then unload it
    // again.
    HMODULE refcountModHandle = LoadLibraryW(modpath);
    RDCASSERTEQUAL(refcountModHandle, module);
    byte *baseAddress = (byte *)refcountModHandle;

    PIMAGE_DOS_HEADER dosheader = (PIMAGE_DOS_HEADER)baseAddress;

    if(dosheader->e_magic != 0x5a4d)
    {
      RDCDEBUG("Ignoring module %s, since magic is 0x%04x not 0x%04x", modName,
               (uint32_t)dosheader->e_magic, 0x5a4dU);
      FreeLibrary(refcountModHandle);
      return;
    }

    char *PE00 = (char *)(baseAddress + dosheader->e_lfanew);
    PIMAGE_FILE_HEADER fileHeader = (PIMAGE_FILE_HEADER)(PE00 + 4);
    PIMAGE_OPTIONAL_HEADER optHeader =
        (PIMAGE_OPTIONAL_HEADER)((BYTE *)fileHeader + sizeof(IMAGE_FILE_HEADER));

    DWORD iatOffset = optHeader->DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;

    IMAGE_IMPORT_DESCRIPTOR *importDesc = (IMAGE_IMPORT_DESCRIPTOR *)(baseAddress + iatOffset);

#if ENABLED(VERBOSE_DEBUG_HOOK)
    RDCDEBUG("=== import descriptors:");
#endif

    while(iatOffset && importDesc->FirstThunk)
    {
      const char *dllName = (const char *)(baseAddress + importDesc->Name);

#if ENABLED(VERBOSE_DEBUG_HOOK)
      RDCDEBUG("found IAT for %s", dllName);
#endif

      DllHookset *hookset = NULL;

      for(auto it = DllHooks.begin(); it != DllHooks.end(); ++it)
        if(!_stricmp(it->first.c_str(), dllName))
          hookset = &it->second;

      if(hookset && importDesc->OriginalFirstThunk > 0)
      {
        IMAGE_THUNK_DATA *origFirst =
            (IMAGE_THUNK_DATA *)(baseAddress + importDesc->OriginalFirstThunk);
        IMAGE_THUNK_DATA *first = (IMAGE_THUNK_DATA *)(baseAddress + importDesc->FirstThunk);

#if ENABLED(VERBOSE_DEBUG_HOOK)
        RDCDEBUG("Hooking imports for %s", dllName);
#endif

        while(origFirst->u1.AddressOfData)
        {
          void **IATentry = (void **)&first->u1.AddressOfData;

          struct hook_find
          {
            bool operator()(const FunctionHook &a, const char *b)
            {
              return strcmp(a.function.c_str(), b) < 0;
            }
          };

#if ENABLED(RDOC_X64)
          if(IMAGE_SNAP_BY_ORDINAL64(origFirst->u1.AddressOfData))
#else
          if(IMAGE_SNAP_BY_ORDINAL32(origFirst->u1.AddressOfData))
#endif
          {
            // low bits of origFirst->u1.AddressOfData contain an ordinal
            WORD ordinal = IMAGE_ORDINAL64(origFirst->u1.AddressOfData);

#if ENABLED(VERBOSE_DEBUG_HOOK)
            RDCDEBUG("Found ordinal import %u", (uint32_t)ordinal);
#endif

            if(!hookset->OrdinalNames.empty())
            {
              if(ordinal >= hookset->OrdinalBase)
              {
                // rebase into OrdinalNames index
                DWORD nameIndex = ordinal - hookset->OrdinalBase;

                // it's perfectly valid to have more functions than names, we only
                // list those with names - so ignore any others
                if(nameIndex < hookset->OrdinalNames.size())
                {
                  const char *importName = (const char *)hookset->OrdinalNames[nameIndex].c_str();

#if ENABLED(VERBOSE_DEBUG_HOOK)
                  RDCDEBUG("Located ordinal %u as %s", (uint32_t)ordinal, importName);
#endif

                  auto found =
                      std::lower_bound(hookset->FunctionHooks.begin(), hookset->FunctionHooks.end(),
                                       importName, hook_find());

                  if(found != hookset->FunctionHooks.end() &&
                     !strcmp(found->function.c_str(), importName) && ownmodule != module)
                  {
                    bool already = false;
                    bool applied;
                    {
                      SCOPED_LOCK(lock);
                      applied = ApplyHook(*found, IATentry, already);
                    }

                    // if we failed, or if it's already set and we're not doing a missedOrdinals
                    // second pass, then just bail out immediately as we've already hooked this
                    // module and there's no point wasting time re-hooking nothing
                    if(!applied || (already && !missedOrdinals))
                    {
#if ENABLED(VERBOSE_DEBUG_HOOK)
                      RDCDEBUG("Stopping hooking module, %d %d %d", (int)applied, (int)already,
                               (int)missedOrdinals);
#endif
                      FreeLibrary(refcountModHandle);
                      return;
                    }
                  }
                }
              }
              else
              {
                RDCERR("Import ordinal is below ordinal base in %s importing module %s", modName,
                       dllName);
              }
            }
            else
            {
#if ENABLED(VERBOSE_DEBUG_HOOK)
              RDCDEBUG("missed ordinals, will try again");
#endif
              // the very first time we try to apply hooks, we might apply them to a module
              // before we've looked up the ordinal names for the one it's linking against.
              // Subsequent times we're only loading one new module - and since it can't
              // link to itself we will have all ordinal names loaded.
              //
              // Setting this flag causes us to do a second pass right at the start
              missedOrdinals = true;
            }

            // continue
            origFirst++;
            first++;
            continue;
          }

          IMAGE_IMPORT_BY_NAME *import =
              (IMAGE_IMPORT_BY_NAME *)(baseAddress + origFirst->u1.AddressOfData);

          const char *importName = (const char *)import->Name;

#if ENABLED(VERBOSE_DEBUG_HOOK)
          RDCDEBUG("Found normal import %s", importName);
#endif

          auto found = std::lower_bound(hookset->FunctionHooks.begin(),
                                        hookset->FunctionHooks.end(), importName, hook_find());

          if(found != hookset->FunctionHooks.end() &&
             !strcmp(found->function.c_str(), importName) && ownmodule != module)
          {
            bool already = false;
            bool applied;
            {
              SCOPED_LOCK(lock);
              applied = ApplyHook(*found, IATentry, already);
            }

            // if we failed, or if it's already set and we're not doing a missedOrdinals
            // second pass, then just bail out immediately as we've already hooked this
            // module and there's no point wasting time re-hooking nothing
            if(!applied || (already && !missedOrdinals))
            {
#if ENABLED(VERBOSE_DEBUG_HOOK)
              RDCDEBUG("Stopping hooking module, %d %d %d", (int)applied, (int)already,
                       (int)missedOrdinals);
#endif
              FreeLibrary(refcountModHandle);
              return;
            }
          }

          origFirst++;
          first++;
        }
      }
      else
      {
        if(hookset)
        {
#if ENABLED(VERBOSE_DEBUG_HOOK)
          RDCDEBUG("!! Invalid IAT found for %s! %u %u", dllName, importDesc->OriginalFirstThunk,
                   importDesc->FirstThunk);
#endif
        }
      }

      importDesc++;
    }

    FreeLibrary(refcountModHandle);
  }

  void ApplyDelayHooks(const char *modName, HMODULE module)
  {
    char lowername[512] = {};

    size_t nameLength = strlen(modName);
    if(nameLength >= ARRAY_COUNT(lowername))
      return;

    for(size_t i = 0; i < nameLength; i++)
      lowername[i] = (char)tolower(modName[i]);

    // Keep the same exclusions as normal import patching. Delay-import support must not expand the
    // set of modules that RenderDoc is willing to modify.
    if(strstr(lowername, "fraps") || strstr(lowername, "gameoverlayrenderer") ||
       _strnicmp(lowername, RDOC_CORE_FILENAME, strlen(RDOC_CORE_FILENAME)) == 0 ||
       ShouldSkipImportPatching(lowername))
      return;

    // Windows hotpatch modules are not normal DLL mappings and are deliberately skipped by the
    // regular import path as well.
    if(strstr(lowername, "hotpatch"))
      return;

    HMODULE refcountModHandle = NULL;
    BOOL refcounted = GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS, (LPCWSTR)module,
                                         &refcountModHandle);
    if(!refcounted || refcountModHandle != module)
    {
      if(refcountModHandle)
        FreeLibrary(refcountModHandle);
      return;
    }

    const byte *baseAddress = (const byte *)refcountModHandle;
    MEMORY_BASIC_INFORMATION headerMemory = {};
    if(VirtualQuery(baseAddress, &headerMemory, sizeof(headerMemory)) != sizeof(headerMemory) ||
       headerMemory.AllocationBase != baseAddress || headerMemory.BaseAddress != baseAddress ||
       headerMemory.State != MEM_COMMIT || !IsReadableMemoryProtection(headerMemory.Protect) ||
       headerMemory.RegionSize < sizeof(IMAGE_DOS_HEADER))
    {
      FreeLibrary(refcountModHandle);
      return;
    }

    const IMAGE_DOS_HEADER *dosHeader = (const IMAGE_DOS_HEADER *)baseAddress;
    if(dosHeader->e_magic != IMAGE_DOS_SIGNATURE || dosHeader->e_lfanew <= 0 ||
       (size_t)dosHeader->e_lfanew > headerMemory.RegionSize ||
       sizeof(IMAGE_NT_HEADERS) > headerMemory.RegionSize - (size_t)dosHeader->e_lfanew)
    {
      FreeLibrary(refcountModHandle);
      return;
    }

    const IMAGE_NT_HEADERS *ntHeaders = (const IMAGE_NT_HEADERS *)(baseAddress + dosHeader->e_lfanew);

    if(ntHeaders->Signature != IMAGE_NT_SIGNATURE ||
       ntHeaders->FileHeader.SizeOfOptionalHeader < sizeof(IMAGE_OPTIONAL_HEADER) ||
       ntHeaders->OptionalHeader.NumberOfRvaAndSizes <= IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT)
    {
      FreeLibrary(refcountModHandle);
      return;
    }

#if ENABLED(RDOC_X64)
    if(ntHeaders->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC)
#else
    if(ntHeaders->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR32_MAGIC)
#endif
    {
      FreeLibrary(refcountModHandle);
      return;
    }

    const size_t imageSize = ntHeaders->OptionalHeader.SizeOfImage;
    const IMAGE_DATA_DIRECTORY &directory =
        ntHeaders->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT];

    if(directory.VirtualAddress == 0 || directory.Size < sizeof(ImgDelayDescr) ||
       GetReadableImageSpan(baseAddress, imageSize, directory.VirtualAddress) < directory.Size)
    {
      FreeLibrary(refcountModHandle);
      return;
    }

    const ImgDelayDescr *descriptors =
        (const ImgDelayDescr *)(baseAddress + directory.VirtualAddress);
    const size_t descriptorCount = directory.Size / sizeof(ImgDelayDescr);

    struct hook_find
    {
      bool operator()(const FunctionHook &a, const char *b)
      {
        return strcmp(a.function.c_str(), b) < 0;
      }
    };

    for(size_t descriptorIndex = 0; descriptorIndex < descriptorCount; descriptorIndex++)
    {
      const ImgDelayDescr &descriptor = descriptors[descriptorIndex];
      if(descriptor.rvaDLLName == 0)
        break;

      // The PE delay-load contract permits VA-based descriptors for legacy images. Only the
      // standard RVA form can be validated against SizeOfImage without trusting arbitrary
      // process pointers, so fail closed for every other attribute value.
      if(descriptor.grAttrs != uint32_t(dlattrRva) || descriptor.rvaINT == 0 || descriptor.rvaIAT == 0)
        continue;

      const char *dllName = GetImageString(baseAddress, imageSize, descriptor.rvaDLLName);
      if(dllName == NULL)
        continue;

      const rdcstr libraryName = strlower(rdcstr(dllName));
      auto hookIt = DllHooks.find(libraryName);
      if(hookIt == DllHooks.end())
        continue;

      DllHookset &hookset = hookIt->second;

      // Do not turn delay-IAT discovery into a loader. Original function pointers are valid only
      // after the target DLL has already been observed during the normal module pass.
      if(!ModuleHandleIsLoaded(hookset.module))
        continue;

      {
        SCOPED_LOCK(lock);
        RefreshOriginalModule(libraryName, hookset, hookset.module);
      }

      const size_t nameThunkCount =
          GetReadableImageSpan(baseAddress, imageSize, descriptor.rvaINT) / sizeof(IMAGE_THUNK_DATA);
      const size_t addressThunkCount =
          GetReadableImageSpan(baseAddress, imageSize, descriptor.rvaIAT) / sizeof(IMAGE_THUNK_DATA);
      const size_t thunkCount = RDCMIN(nameThunkCount, addressThunkCount);

      const IMAGE_THUNK_DATA *nameTable = (const IMAGE_THUNK_DATA *)(baseAddress + descriptor.rvaINT);
      IMAGE_THUNK_DATA *addressTable =
          (IMAGE_THUNK_DATA *)(const_cast<byte *>(baseAddress) + descriptor.rvaIAT);

      for(size_t thunkIndex = 0; thunkIndex < thunkCount; thunkIndex++)
      {
        const ULONG_PTR nameValue = nameTable[thunkIndex].u1.AddressOfData;
        if(nameValue == 0)
          break;

        const char *importName = NULL;

#if ENABLED(RDOC_X64)
        const bool importByOrdinal = IMAGE_SNAP_BY_ORDINAL64(nameValue);
        const WORD ordinal = IMAGE_ORDINAL64(nameValue);
#else
        const bool importByOrdinal = IMAGE_SNAP_BY_ORDINAL32(nameValue);
        const WORD ordinal = IMAGE_ORDINAL32(nameValue);
#endif

        if(importByOrdinal)
        {
          if(hookset.OrdinalNames.empty())
          {
            missedOrdinals = true;
            continue;
          }

          if(ordinal < hookset.OrdinalBase)
            continue;

          const DWORD nameIndex = ordinal - hookset.OrdinalBase;
          if(nameIndex >= hookset.OrdinalNames.size() || hookset.OrdinalNames[nameIndex].empty())
            continue;

          importName = hookset.OrdinalNames[nameIndex].c_str();
        }
        else
        {
          if(nameValue > imageSize ||
             GetReadableImageSpan(baseAddress, imageSize, (size_t)nameValue) < sizeof(WORD) + 1)
            continue;

          importName = GetImageString(baseAddress, imageSize, (size_t)nameValue + sizeof(WORD));
          if(importName == NULL)
            continue;
        }

        auto found = std::lower_bound(hookset.FunctionHooks.begin(), hookset.FunctionHooks.end(),
                                      importName, hook_find());

        if(found == hookset.FunctionHooks.end() ||
           strcmp(found->function.c_str(), importName) != 0 || ownmodule == module)
          continue;

        bool already = false;
        {
          SCOPED_LOCK(lock);
          ApplyHook(*found, (void **)&addressTable[thunkIndex].u1.Function, already);
        }
      }
    }

    FreeLibrary(refcountModHandle);
  }
};

static CachedHookData *s_HookData = NULL;

#ifdef UNICODE
#undef MODULEENTRY32
#undef Module32First
#undef Module32Next
#endif

static void ForAllModules(std::function<void(const MODULEENTRY32 &me32)> callback)
{
  HANDLE hModuleSnap = INVALID_HANDLE_VALUE;

  // up to 10 retries
  for(int i = 0; i < 10; i++)
  {
    hModuleSnap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, GetCurrentProcessId());

    if(hModuleSnap == INVALID_HANDLE_VALUE)
    {
      DWORD err = GetLastError();

      RDCWARN("CreateToolhelp32Snapshot() -> 0x%08x", err);

      // retry if error is ERROR_BAD_LENGTH
      if(err == ERROR_BAD_LENGTH)
        continue;
    }

    // didn't retry, or succeeded
    break;
  }

  if(hModuleSnap == INVALID_HANDLE_VALUE)
  {
    RDCERR("Couldn't create toolhelp dump of modules in process");
    return;
  }

  MODULEENTRY32 me32;
  RDCEraseEl(me32);
  me32.dwSize = sizeof(MODULEENTRY32);

  BOOL success = Module32First(hModuleSnap, &me32);

  if(success == FALSE)
  {
    DWORD err = GetLastError();

    RDCERR("Couldn't get first module in process: 0x%08x", err);
    CloseHandle(hModuleSnap);
    return;
  }

  do
  {
    callback(me32);
  } while(Module32Next(hModuleSnap, &me32));

  CloseHandle(hModuleSnap);
}

static void HookAllModules()
{
  if(!s_HookData->hookAll)
    return;

  rdcarray<MODULEENTRY32> modules;
  ForAllModules([&modules](const MODULEENTRY32 &me32) { modules.push_back(me32); });

  for(const MODULEENTRY32 &me32 : modules)
    s_HookData->ApplyHooks(me32.szModule, me32.hModule);

  // A separate pass ensures every already-loaded target DLL has populated its original function
  // pointers before any delay-IAT entry can be redirected to a hook.
  for(const MODULEENTRY32 &me32 : modules)
    s_HookData->ApplyDelayHooks(me32.szModule, me32.hModule);

  // check if we're already in this section of code, and if so don't go in again.
  int32_t prev = Atomic::CmpExch32(&s_HookData->posthooking, 0, 1);

  if(prev != 0)
    return;

  // for all loaded modules, call callbacks now
  for(auto it = s_HookData->DllHooks.begin(); it != s_HookData->DllHooks.end(); ++it)
  {
    if(it->second.module == NULL)
      continue;

    {
      SCOPED_LOCK(s_HookData->lock);
      RefreshOriginalModule(it->first, it->second, it->second.module);
    }

    if(!it->second.hooksfetched)
    {
      it->second.hooksfetched = true;
    }

    rdcarray<FunctionLoadCallback> callbacks;
    // don't call callbacks next time
    callbacks.swap(it->second.Callbacks);

    for(FunctionLoadCallback cb : callbacks)
      if(cb)
        cb(it->second.module, it->first.c_str());
  }

  Atomic::CmpExch32(&s_HookData->posthooking, 1, 0);
}

static bool IsAPISet(const wchar_t *filename)
{
  if(wcschr(filename, L'/') != 0 || wcschr(filename, L'\\') != 0)
    return false;

  wchar_t match[] = L"api-ms-win";

  if(wcslen(filename) < ARRAY_COUNT(match) - 1)
    return false;

  for(size_t i = 0; i < ARRAY_COUNT(match) - 1; i++)
    if(towlower(filename[i]) != match[i])
      return false;

  return true;
}

static bool IsAPISet(const char *filename)
{
  size_t len = strlen(filename);
  rdcwstr wfn(len);

  // assume ASCII not UTF, just upcast plainly to wchar_t
  for(size_t i = 0; i < len; i++)
    wfn[i] = wchar_t(filename[i]);

  return IsAPISet(wfn.c_str());
}

HMODULE WINAPI Hooked_LoadLibraryExA(LPCSTR lpLibFileName, HANDLE fileHandle, DWORD flags)
{
  bool dohook = true;

  if(s_HookData->libraryIntercept)
  {
    HMODULE ret = s_HookData->libraryIntercept(lpLibFileName, fileHandle, flags);
    if(ret)
      return ret;
    dohook = false;
  }

  if(flags == 0 && GetModuleHandleA(lpLibFileName))
    dohook = false;

  SetLastError(S_OK);

  // we can use the function naked, as when setting up the hook for LoadLibraryExA, our own module
  // was excluded from IAT patching
  HMODULE mod = LoadLibraryExA(lpLibFileName, fileHandle, flags);

#if ENABLED(VERBOSE_DEBUG_HOOK)
  RDCDEBUG("LoadLibraryA(%s)", lpLibFileName);
#endif

  DWORD err = GetLastError();

  if(dohook && mod && !IsAPISet(lpLibFileName))
    HookAllModules();

  SetLastError(err);

  return mod;
}

HMODULE WINAPI Hooked_LoadLibraryExW(LPCWSTR lpLibFileName, HANDLE fileHandle, DWORD flags)
{
  bool dohook = true;

  if(s_HookData->libraryIntercept)
  {
    HMODULE ret =
        s_HookData->libraryIntercept(StringFormat::Wide2UTF8(lpLibFileName), fileHandle, flags);
    if(ret)
      return ret;
    dohook = false;
  }

  DWORD flagsExcludingSearchOrders = flags;

  // if this is a pure "filename.dll" load, don't care about search-order flags since loaded DLLs are
  // always returned first regardless of the search order and so we can detect the DLL is already loaded
  if(wcschr(lpLibFileName, L'\\') == 0 && wcschr(lpLibFileName, L'/') == 0)
  {
    flagsExcludingSearchOrders &= ~(LOAD_LIBRARY_SEARCH_APPLICATION_DIR |
                                    LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32 |
                                    LOAD_LIBRARY_SEARCH_USER_DIRS | LOAD_WITH_ALTERED_SEARCH_PATH);

#ifdef LOAD_LIBRARY_SAFE_CURRENT_DIRS
    flagsExcludingSearchOrders &= ~LOAD_LIBRARY_SAFE_CURRENT_DIRS;
#endif
  }

  // if there are no flags (possibly with search path flags excluded) and we already have the
  // library loaded, don't hook anything
  if(flagsExcludingSearchOrders == 0 && GetModuleHandleW(lpLibFileName))
    dohook = false;

  if(flags & (LOAD_LIBRARY_AS_DATAFILE | LOAD_LIBRARY_AS_DATAFILE_EXCLUSIVE))
    dohook = false;

  SetLastError(S_OK);

#if ENABLED(VERBOSE_DEBUG_HOOK)
  RDCDEBUG("LoadLibraryW(%ls)", lpLibFileName);
#endif

  // we can use the function naked, as when setting up the hook for LoadLibraryExA, our own module
  // was excluded from IAT patching
  HMODULE mod = LoadLibraryExW(lpLibFileName, fileHandle, flags);

  DWORD err = GetLastError();

  if(dohook && mod && !IsAPISet(lpLibFileName))
    HookAllModules();

  SetLastError(err);

  return mod;
}

HMODULE WINAPI Hooked_LoadLibraryA(LPCSTR lpLibFileName)
{
  return Hooked_LoadLibraryExA(lpLibFileName, NULL, 0);
}

HMODULE WINAPI Hooked_LoadLibraryW(LPCWSTR lpLibFileName)
{
  return Hooked_LoadLibraryExW(lpLibFileName, NULL, 0);
}

static bool OrdinalAsString(void *func)
{
  return uint64_t(func) <= 0xffff;
}

FARPROC WINAPI Hooked_GetProcAddress(HMODULE mod, const LPCSTR func)
{
  if(mod == NULL || func == NULL || mod == s_HookData->ownmodule)
    return GetProcAddress(mod, func);

#if ENABLED(VERBOSE_DEBUG_HOOK)
  if(OrdinalAsString((void *)func))
    RDCDEBUG("Hooked_GetProcAddress(%p, %p)", mod, func);
  else
    RDCDEBUG("Hooked_GetProcAddress(%p, %s)", mod, func);
#endif

  for(auto it = s_HookData->DllHooks.begin(); it != s_HookData->DllHooks.end(); ++it)
  {
    {
      SCOPED_LOCK(s_HookData->lock);

      if(it->second.module == NULL)
      {
        it->second.module = GetModuleHandleA(it->first.c_str());
        if(it->second.module)
        {
          // Fill original pointers even when no import was patched.
          RefreshOriginalModule(it->first, it->second, it->second.module);

          it->second.FetchOrdinalNames();
        }
      }
      else
      {
        RefreshOriginalModule(it->first, it->second, it->second.module);
      }
    }

    bool match = (mod == it->second.module);

    if(!match && !it->second.altmodules.empty())
    {
      for(size_t i = 0; !match && i < it->second.altmodules.size(); i++)
        match = (mod == it->second.altmodules[i]);
    }

    if(match)
    {
#if ENABLED(VERBOSE_DEBUG_HOOK)
      RDCDEBUG("Located module %s", it->first.c_str());
#endif

      LPCSTR searchFunc = func;

      if(OrdinalAsString((void *)func))
      {
#if ENABLED(VERBOSE_DEBUG_HOOK)
        RDCDEBUG("Ordinal hook");
#endif

        uint32_t ordinal = (uint16_t)(uintptr_t(func) & 0xffff);

        if(ordinal < it->second.OrdinalBase)
        {
          RDCERR("Unexpected ordinal - lower than ordinalbase %u for %s",
                 (uint32_t)it->second.OrdinalBase, it->first.c_str());

          SetLastError(S_OK);
          return GetProcAddress(mod, func);
        }

        ordinal -= it->second.OrdinalBase;

        if(ordinal >= it->second.OrdinalNames.size())
        {
          RDCERR("Unexpected ordinal - higher than fetched ordinal names (%u) for %s",
                 (uint32_t)it->second.OrdinalNames.size(), it->first.c_str());

          SetLastError(S_OK);
          return GetProcAddress(mod, func);
        }

        searchFunc = it->second.OrdinalNames[ordinal].c_str();

#if ENABLED(VERBOSE_DEBUG_HOOK)
        RDCDEBUG("found ordinal %s", searchFunc);
#endif
      }

      FunctionHook search(searchFunc, NULL, NULL);

      auto found =
          std::lower_bound(it->second.FunctionHooks.begin(), it->second.FunctionHooks.end(), search);
      if(found != it->second.FunctionHooks.end() && !(search < *found))
      {
        FARPROC realfunc = GetProcAddress(mod, func);

#if ENABLED(VERBOSE_DEBUG_HOOK)
        RDCDEBUG("Found hooked function, returning hook pointer %p", found->hook);
#endif

        SetLastError(S_OK);

        if(realfunc == NULL)
          return NULL;

        return (FARPROC)found->hook;
      }
    }
  }

#if ENABLED(VERBOSE_DEBUG_HOOK)
  RDCDEBUG("No matching hook found, returning original");
#endif

  SetLastError(S_OK);

  return GetProcAddress(mod, func);
}
static void InitHookData()
{
  if(!s_HookData)
  {
    s_HookData = new CachedHookData;

    RDCASSERT(s_HookData->DllHooks.empty());
    s_HookData->DllHooks["kernel32.dll"].FunctionHooks.push_back(
        FunctionHook("LoadLibraryA", NULL, &Hooked_LoadLibraryA));
    s_HookData->DllHooks["kernel32.dll"].FunctionHooks.push_back(
        FunctionHook("LoadLibraryW", NULL, &Hooked_LoadLibraryW));
    s_HookData->DllHooks["kernel32.dll"].FunctionHooks.push_back(
        FunctionHook("LoadLibraryExA", NULL, &Hooked_LoadLibraryExA));
    s_HookData->DllHooks["kernel32.dll"].FunctionHooks.push_back(
        FunctionHook("LoadLibraryExW", NULL, &Hooked_LoadLibraryExW));
    s_HookData->DllHooks["kernel32.dll"].FunctionHooks.push_back(
        FunctionHook("GetProcAddress", NULL, &Hooked_GetProcAddress));

    for(const char *apiset :
        {"api-ms-win-core-libraryloader-l1-1-0.dll", "api-ms-win-core-libraryloader-l1-1-1.dll",
         "api-ms-win-core-libraryloader-l1-1-2.dll", "api-ms-win-core-libraryloader-l1-2-0.dll",
         "api-ms-win-core-libraryloader-l1-2-1.dll"})
    {
      s_HookData->DllHooks[apiset].FunctionHooks.push_back(
          FunctionHook("LoadLibraryA", NULL, &Hooked_LoadLibraryA));
      s_HookData->DllHooks[apiset].FunctionHooks.push_back(
          FunctionHook("LoadLibraryW", NULL, &Hooked_LoadLibraryW));
      s_HookData->DllHooks[apiset].FunctionHooks.push_back(
          FunctionHook("LoadLibraryExA", NULL, &Hooked_LoadLibraryExA));
      s_HookData->DllHooks[apiset].FunctionHooks.push_back(
          FunctionHook("LoadLibraryExW", NULL, &Hooked_LoadLibraryExW));
      s_HookData->DllHooks[apiset].FunctionHooks.push_back(
          FunctionHook("GetProcAddress", NULL, &Hooked_GetProcAddress));
    }

    GetModuleHandleEx(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        (LPCTSTR)&s_HookData, &s_HookData->ownmodule);
  }
}

void LibraryHooks::RegisterFunctionHook(const char *libraryName, const FunctionHook &hook)
{
  if(!_stricmp(libraryName, "kernel32.dll"))
  {
    if(hook.function == "LoadLibraryA" || hook.function == "LoadLibraryW" ||
       hook.function == "LoadLibraryExA" || hook.function == "LoadLibraryExW" ||
       hook.function == "GetProcAddress")
    {
      RDCERR("Cannot hook LoadLibrary* or GetProcAddress, as these are hooked internally");
      return;
    }
  }
  s_HookData->DllHooks[strlower(rdcstr(libraryName))].FunctionHooks.push_back(hook);
}

void LibraryHooks::RegisterLibraryHook(const char *libraryName, FunctionLoadCallback loadedCallback)
{
  s_HookData->DllHooks[strlower(rdcstr(libraryName))].Callbacks.push_back(loadedCallback);
}

void LibraryHooks::IgnoreLibrary(const char *libraryName)
{
  rdcstr lowername = libraryName;

  for(size_t i = 0; i < lowername.size(); i++)
    lowername[i] = (char)tolower(lowername[i]);

  s_HookData->ignores.insert(lowername);
}

void LibraryHooks::BeginHookRegistration()
{
  InitHookData();
}

// hook all functions for currently loaded modules.
// some of these hooks (as above) will hook LoadLibrary/GetProcAddress, to protect
void LibraryHooks::EndHookRegistration()
{
  for(auto it = s_HookData->DllHooks.begin(); it != s_HookData->DllHooks.end(); ++it)
    std::sort(it->second.FunctionHooks.begin(), it->second.FunctionHooks.end());

#if ENABLED(VERBOSE_DEBUG_HOOK)
  RDCDEBUG("Applying hooks");
#endif

  HookAllModules();

  if(s_HookData->missedOrdinals)
  {
#if ENABLED(VERBOSE_DEBUG_HOOK)
    RDCDEBUG("Missed ordinals - applying hooks again");
#endif

    // we need to do a second pass now that we know ordinal names to finally hook
    // some imports by ordinal only.
    HookAllModules();

    s_HookData->missedOrdinals = false;
  }

}

void LibraryHooks::Refresh()
{
  // don't need to refresh on windows
}

void LibraryHooks::ReplayInitialise()
{
}

void LibraryHooks::RemoveHooks()
{
  if(IsProxyOnly())
    return;  // nothing installed in ProxyOnly mode

  LibraryHooks::RemoveHookCallbacks();

  for(auto it = s_InstalledHooks.begin(); it != s_InstalledHooks.end(); ++it)
  {
    DWORD oldProtection = PAGE_EXECUTE;

    void **IATentry = it->first;

    if(!ProtectPage(IATentry, sizeof(void *), PAGE_READWRITE, oldProtection))
    {
      RDCERR("Failed to make IAT entry writeable 0x%p", IATentry);
      continue;
    }

    *IATentry = it->second;

    if(!ProtectPage(IATentry, sizeof(void *), oldProtection, oldProtection))
    {
      RDCERR("Failed to restore IAT entry protection 0x%p", IATentry);
      continue;
    }
  }
}

bool LibraryHooks::Detect(const char *identifier)
{
  bool ret = false;
  ForAllModules([&ret, identifier](const MODULEENTRY32 &me32) {
    if(GetProcAddress(me32.hModule, identifier) != NULL)
      ret = true;
  });
  return ret;
}

void Win32_RegisterManualModuleHooking()
{
  InitHookData();

  s_HookData->hookAll = false;
}

void Win32_InterceptLibraryLoads(std::function<HMODULE(const rdcstr &, HANDLE, DWORD)> callback)
{
  s_HookData->libraryIntercept = callback;
}

void Win32_ManualHookModule(rdcstr modName, HMODULE module)
{
  for(auto it = s_HookData->DllHooks.begin(); it != s_HookData->DllHooks.end(); ++it)
    std::sort(it->second.FunctionHooks.begin(), it->second.FunctionHooks.end());

  modName = strlower(modName);

  {
    SCOPED_LOCK(s_HookData->lock);

    DllHookset &hookset = s_HookData->DllHooks[modName];
    hookset.module = module;
    hookset.originalModule = GetPreferredOriginalModule(modName, module);

    for(FunctionHook &hook : hookset.FunctionHooks)
    {
      if(hook.orig)
        *hook.orig = GetProcAddress(hookset.originalModule, hook.function.c_str());
    }
  }

  s_HookData->ApplyHooks(modName.c_str(), module);
}

#if ENABLED(ENABLE_UNIT_TESTS)

#include "catch/catch.hpp"

TEST_CASE("Win32 hook originals select already-loaded canonical graphics runtimes",
           "[win32][hook-resolution]")
{
  rdcwstr systemDXGIPath;
  REQUIRE(GetCanonicalSystemModulePath("dxgi.dll", systemDXGIPath));

  rdcwstr systemD3D11Path;
  REQUIRE(GetCanonicalSystemModulePath("d3d11.dll", systemD3D11Path));

  rdcwstr systemD3D12Path;
  REQUIRE(GetCanonicalSystemModulePath("d3d12.dll", systemD3D12Path));

  rdcwstr rejectedPath;
  CHECK_FALSE(GetCanonicalSystemModulePath("../dxgi.dll", rejectedPath));
  CHECK(GetCanonicalSystemModulePath("DXGI.DLL", rejectedPath));
  CHECK(_wcsicmp(rejectedPath.c_str(), systemDXGIPath.c_str()) == 0);
  CHECK(GetCanonicalSystemModulePath("D3D11.DLL", rejectedPath));
  CHECK(_wcsicmp(rejectedPath.c_str(), systemD3D11Path.c_str()) == 0);
  CHECK(GetCanonicalSystemModulePath("D3D12.DLL", rejectedPath));
  CHECK(_wcsicmp(rejectedPath.c_str(), systemD3D12Path.c_str()) == 0);

  HMODULE coreModule = GetModuleHandleA(RDOC_CORE_FILENAME);
  REQUIRE(coreModule != NULL);
  CHECK(ModuleHandleIsLoaded(coreModule));
  CHECK_FALSE(ModuleHandleIsLoaded(NULL));
  CHECK_FALSE(ModulePathMatches(coreModule, systemDXGIPath));
  CHECK_FALSE(ModulePathMatches(coreModule, systemD3D11Path));
  CHECK_FALSE(ModulePathMatches(coreModule, systemD3D12Path));

  HMODULE systemDXGI = LoadLibraryW(systemDXGIPath.c_str());
  REQUIRE(systemDXGI != NULL);
  REQUIRE(ModulePathMatches(systemDXGI, systemDXGIPath));
  CHECK(GetLoadedCanonicalSystemModule("dxgi.dll") == systemDXGI);
  CHECK(GetPreferredOriginalModule("dxgi.dll", coreModule) == systemDXGI);

  HMODULE systemD3D11 = LoadLibraryW(systemD3D11Path.c_str());
  REQUIRE(systemD3D11 != NULL);
  REQUIRE(ModulePathMatches(systemD3D11, systemD3D11Path));
  CHECK(GetLoadedCanonicalSystemModule("d3d11.dll") == systemD3D11);
  CHECK(GetPreferredOriginalModule("d3d11.dll", coreModule) == systemD3D11);

  HMODULE systemD3D12 = LoadLibraryW(systemD3D12Path.c_str());
  REQUIRE(systemD3D12 != NULL);
  REQUIRE(ModulePathMatches(systemD3D12, systemD3D12Path));
  CHECK(GetLoadedCanonicalSystemModule("d3d12.dll") == systemD3D12);
  CHECK(GetPreferredOriginalModule("d3d12.dll", coreModule) == systemD3D12);

  FARPROC createFactory = GetProcAddress(systemDXGI, "CreateDXGIFactory1");
  REQUIRE(createFactory != NULL);
  FARPROC createD3D11Device = GetProcAddress(systemD3D11, "D3D11CreateDevice");
  REQUIRE(createD3D11Device != NULL);
  FARPROC createD3D12Device = GetProcAddress(systemD3D12, "D3D12CreateDevice");
  REQUIRE(createD3D12Device != NULL);

  void *originalFactory = NULL;
  void *originalD3D11CreateDevice = NULL;
  void *originalD3D12CreateDevice = NULL;
  CachedHookData hookData;
  DllHookset &dxgiHookset = hookData.DllHooks["dxgi.dll"];
  dxgiHookset.originalModule = coreModule;
  dxgiHookset.FunctionHooks.push_back(FunctionHook("CreateDXGIFactory1", &originalFactory, NULL));
  DllHookset &d3d11Hookset = hookData.DllHooks["d3d11.dll"];
  d3d11Hookset.originalModule = coreModule;
  d3d11Hookset.FunctionHooks.push_back(
      FunctionHook("D3D11CreateDevice", &originalD3D11CreateDevice, NULL));
  DllHookset &d3d12Hookset = hookData.DllHooks["d3d12.dll"];
  d3d12Hookset.originalModule = coreModule;
  d3d12Hookset.FunctionHooks.push_back(
      FunctionHook("D3D12CreateDevice", &originalD3D12CreateDevice, NULL));
  {
    SCOPED_LOCK(hookData.lock);
    RefreshOriginalModule("dxgi.dll", dxgiHookset, coreModule);
    RefreshOriginalModule("d3d11.dll", d3d11Hookset, coreModule);
    RefreshOriginalModule("d3d12.dll", d3d12Hookset, coreModule);
  }
  CHECK(dxgiHookset.originalModule == systemDXGI);
  CHECK(originalFactory == (void *)createFactory);
  CHECK(d3d11Hookset.originalModule == systemD3D11);
  CHECK(originalD3D11CreateDevice == (void *)createD3D11Device);
  CHECK(d3d12Hookset.originalModule == systemD3D12);
  CHECK(originalD3D12CreateDevice == (void *)createD3D12Device);

  MEMORY_BASIC_INFORMATION memory = {};
  REQUIRE(VirtualQuery(createFactory, &memory, sizeof(memory)) == sizeof(memory));
  CHECK(memory.AllocationBase == systemDXGI);
  REQUIRE(VirtualQuery(createD3D11Device, &memory, sizeof(memory)) == sizeof(memory));
  CHECK(memory.AllocationBase == systemD3D11);
  REQUIRE(VirtualQuery(createD3D12Device, &memory, sizeof(memory)) == sizeof(memory));
  CHECK(memory.AllocationBase == systemD3D12);

  FreeLibrary(systemD3D12);
  FreeLibrary(systemD3D11);
  FreeLibrary(systemDXGI);
}

#endif

// android only hooking functions, not used on win32
ScopedSuppressHooking::ScopedSuppressHooking()
{
}

ScopedSuppressHooking::~ScopedSuppressHooking()
{
}
