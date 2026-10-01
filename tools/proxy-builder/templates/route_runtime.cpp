// DComp Proxy Builder route runtime. Original code; x64 forwarding ABI lives
// in the reviewed Aftermath assembly template. No DLL loading in DllMain.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <bcrypt.h>
#include <strsafe.h>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include "api/app/renderdoc_app.h"
#include "route_config.h"
#pragma comment(lib, "bcrypt.lib")

extern "C" intptr_t g_OrigAftermath[PB_EXPORT_COUNT] = {};
extern "C" volatile LONG g_ResolutionReady = 0;
HMODULE PBSelf = nullptr;
HMODULE PBCore = nullptr;
RENDERDOC_API_1_6_0 *PBApi = nullptr;
static INIT_ONCE OriginalOnce = INIT_ONCE_STATIC_INIT;
static INIT_ONCE CoreOnce = INIT_ONCE_STATIC_INIT;
static INIT_ONCE PluginOnce = INIT_ONCE_STATIC_INIT;
static HMODULE Original = nullptr;
static thread_local bool InOriginal = false;
static thread_local bool InCore = false;
static thread_local bool InPlugins = false;
static volatile LONG CoreState = 0;
static volatile LONG LastErrorCode = 0;
static HANDLE OriginalFile = INVALID_HANDLE_VALUE;
static std::vector<HMODULE> Plugins;
static bool PluginsOK = true;
static HANDLE ModuleEvent = nullptr;
static PVOID EntryHandler = nullptr;
static BYTE *EntryAddress = nullptr;
static BYTE EntryByte = 0;
static DWORD EntryProtection = 0;
static INIT_ONCE EntryOnce = INIT_ONCE_STATIC_INIT;
static volatile LONG EntryGateState = 0;

static std::wstring PBPath(const wchar_t *name, bool system = false)
{
  wchar_t path[32768] = {};
  if(system) {
    DWORD n = GetSystemDirectoryW(path, ARRAYSIZE(path));
    if(!n || n >= ARRAYSIZE(path)) return {};
    if(FAILED(StringCchCatW(path, ARRAYSIZE(path), L"\\"))) return {};
  } else if(name[0] && name[1] == L':') {
    return name;
  } else if(name[0] == L'\\' && name[1] == L'\\') {
    return name;
  } else {
    DWORD n = GetModuleFileNameW(PBSelf, path, ARRAYSIZE(path));
    if(!n || n >= ARRAYSIZE(path)) return {};
    wchar_t *last = wcsrchr(path, L'\\');
    if(!last) return {};
    last[1] = 0;
  }
  if(FAILED(StringCchCatW(path, ARRAYSIZE(path), name))) return {};
  return path;
}

static bool PBHash(HANDLE file, const char *expected)
{
  if(!expected[0]) return true;
  BCRYPT_ALG_HANDLE algorithm = nullptr;
  BCRYPT_HASH_HANDLE hash = nullptr;
  DWORD length = 0, written = 0;
  bool ok = BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0;
  if(ok) ok = BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH,
      reinterpret_cast<PUCHAR>(&length), sizeof(length), &written, 0) >= 0;
  std::vector<BYTE> object(length);
  if(ok) ok = BCryptCreateHash(algorithm, &hash, object.data(), length, nullptr, 0, 0) >= 0;
  BYTE buffer[65536], result[32];
  while(ok) {
    DWORD count = 0;
    if(!ReadFile(file, buffer, sizeof(buffer), &count, nullptr)) { ok = false; break; }
    if(!count) break;
    ok = BCryptHashData(hash, buffer, count, 0) >= 0;
  }
  if(ok) ok = BCryptFinishHash(hash, result, sizeof(result), 0) >= 0;
  if(ok) {
    const char hex[] = "0123456789abcdef";
    for(size_t i = 0; i < 32; ++i)
      if(expected[i*2] != hex[result[i] >> 4] || expected[i*2+1] != hex[result[i] & 15]) ok = false;
  }
  if(hash) BCryptDestroyHash(hash);
  if(algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
  return ok;
}

static bool PBSameFile(HANDLE a, HANDLE b)
{
  BY_HANDLE_FILE_INFORMATION x = {}, y = {};
  return GetFileInformationByHandle(a, &x) && GetFileInformationByHandle(b, &y) &&
      x.dwVolumeSerialNumber == y.dwVolumeSerialNumber &&
      x.nFileIndexHigh == y.nFileIndexHigh && x.nFileIndexLow == y.nFileIndexLow;
}

static HMODULE PBLoad(const std::wstring &path, const char *hash, HANDLE *retained = nullptr)
{
  if(path.empty()) { InterlockedExchange(&LastErrorCode, ERROR_BAD_PATHNAME); return nullptr; }
  HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr,
      OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
  if(file == INVALID_HANDLE_VALUE) { InterlockedExchange(&LastErrorCode, GetLastError()); return nullptr; }
  wchar_t selfPath[32768] = {};
  GetModuleFileNameW(PBSelf, selfPath, ARRAYSIZE(selfPath));
  HANDLE self = CreateFileW(selfPath, GENERIC_READ, FILE_SHARE_READ,
      nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
  bool recursive = self != INVALID_HANDLE_VALUE && PBSameFile(file, self);
  if(self != INVALID_HANDLE_VALUE) CloseHandle(self);
  if(recursive || !PBHash(file, hash)) {
    CloseHandle(file);
    InterlockedExchange(&LastErrorCode, recursive ? ERROR_CIRCULAR_DEPENDENCY : ERROR_CRC);
    return nullptr;
  }
  HMODULE module = LoadLibraryExW(path.c_str(), nullptr,
      LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
  if(!module || module == PBSelf) {
    InterlockedExchange(&LastErrorCode, module ? ERROR_CIRCULAR_DEPENDENCY : GetLastError());
    CloseHandle(file); return nullptr;
  }
  // A generated provider publishes an absolute path of its own next provider.
  // Walk that metadata before allowing a function-stub cycle to become callable.
  using Next = const wchar_t *(__cdecl *)();
  HMODULE visited[32] = {PBSelf};
  size_t count = 1;
  HMODULE cursor = module;
  while(cursor) {
    for(size_t i = 0; i < count; ++i) if(visited[i] == cursor) {
      CloseHandle(file); InterlockedExchange(&LastErrorCode, ERROR_CIRCULAR_DEPENDENCY); return nullptr;
    }
    if(count == ARRAYSIZE(visited)) {
      CloseHandle(file); InterlockedExchange(&LastErrorCode, ERROR_CIRCULAR_DEPENDENCY); return nullptr;
    }
    visited[count++] = cursor;
    auto next = reinterpret_cast<Next>(GetProcAddress(cursor, "DCompProxyNextProvider"));
    if(!next) break;
    const wchar_t *nextPath = next();
    if(!nextPath || !nextPath[0]) break;
    cursor = GetModuleHandleW(nextPath);
    // Don't execute uninitialised providers merely to inspect metadata. They
    // will repeat this check when resolving their own provider.
  }
  if(retained) *retained = file; else CloseHandle(file);
  return module;
}

static BOOL CALLBACK PBResolveOriginal(PINIT_ONCE, PVOID, PVOID *)
{
  InOriginal = true;
  for(size_t candidate = 0; candidate < PB_PROVIDER_COUNT; ++candidate) {
    Original = PBLoad(PBPath(PB_PROVIDER_CANDIDATES[candidate], PB_PROVIDER_SYSTEM), PB_PROVIDER_HASH, &OriginalFile);
    if(Original) break;
    LONG error = InterlockedCompareExchange(&LastErrorCode, 0, 0);
    // Try another rename only when this file is absent. Never hide an invalid
    // present original, a hash mismatch, dependency failure or a provider cycle.
    if(error != ERROR_FILE_NOT_FOUND && error != ERROR_PATH_NOT_FOUND) break;
  }
  if(Original) {
    for(int i = 0; i < PB_EXPORT_COUNT; ++i) {
      FARPROC target = GetProcAddress(Original, PB_LOOKUPS[i]);
      HMODULE owner = nullptr;
      if(target) GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
          GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, reinterpret_cast<LPCWSTR>(target), &owner);
      if(owner == PBSelf) { target = nullptr; InterlockedExchange(&LastErrorCode, ERROR_CIRCULAR_DEPENDENCY); }
      g_OrigAftermath[i] = reinterpret_cast<intptr_t>(target);
    }
  }
  InOriginal = false;
  return TRUE;
}

static bool PBEnabled()
{
  wchar_t setting[8] = {};
  DWORD n = GetEnvironmentVariableW(L"DCOMP_BOOTSTRAP_ENABLE", setting, ARRAYSIZE(setting));
  if(n == 1 && setting[0] == L'0') return false;
  if(n == 1 && setting[0] == L'1') return true;
  if constexpr(PB_ENABLE_DEFAULT) return true;
  DWORD a = GetFileAttributesW(PBPath(L"dgcore.enable").c_str());
  return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

static BOOL CALLBACK PBLoadCoreOnce(PINIT_ONCE, PVOID, PVOID *)
{
  InCore = true;
  InterlockedExchange(&CoreState, 1);
  if(!PBEnabled()) { InterlockedExchange(&CoreState, 3); InCore = false; return TRUE; }
  PBCore = PBLoad(PBPath(PB_CORE_PATH), PB_CORE_HASH);
  if(PBCore) {
    auto api = reinterpret_cast<pDCOMP_GetAPI>(GetProcAddress(PBCore, "DCOMP_GetAPI"));
    // DCOMP_GetAPI is not thread-safe. InitOnce is per DLL; a process mutex
    // also serializes handshakes from multiple generated proxy DLLs.
    wchar_t mutexName[96] = {};
    StringCchPrintfW(mutexName, ARRAYSIZE(mutexName), L"Local\\DCompProxyAPI_%lu", GetCurrentProcessId());
    HANDLE mutex = CreateMutexW(nullptr, FALSE, mutexName);
    DWORD wait = mutex ? WaitForSingleObject(mutex, INFINITE) : WAIT_FAILED;
    bool acquired = wait == WAIT_OBJECT_0 || wait == WAIT_ABANDONED;
    if(acquired && api && api(eDCOMP_API_Version_1_6_0, reinterpret_cast<void **>(&PBApi)) == 1 && PBApi)
      InterlockedExchange(&CoreState, 2);
    else { PBApi = nullptr; InterlockedExchange(&CoreState, 5); }
    if(acquired) ReleaseMutex(mutex);
    if(mutex) CloseHandle(mutex);
  } else InterlockedExchange(&CoreState, 4);
  InCore = false;
  return TRUE;
}

bool PBEnsureCore()
{
  if(!InCore) InitOnceExecuteOnce(&CoreOnce, PBLoadCoreOnce, nullptr, nullptr);
  return InterlockedCompareExchange(&CoreState, 0, 0) == 2;
}

static BOOL CALLBACK PBLoadPluginsOnce(PINIT_ONCE, PVOID, PVOID *)
{
  InPlugins = true;
  for(size_t i = 0; i < PB_PLUGIN_COUNT; ++i) {
    HMODULE module = PBLoad(PBPath(PB_PLUGINS[i].path), PB_PLUGINS[i].hash);
    if(module) Plugins.push_back(module); else PluginsOK = false;
  }
  InPlugins = false;
  return TRUE;
}

static void PBActivate()
{
  if(InCore) return;
  PBEnsureCore();
  if(!InPlugins) InitOnceExecuteOnce(&PluginOnce, PBLoadPluginsOnce, nullptr, nullptr);
}

extern "C" int __cdecl DCompProxyInitialize() { PBActivate(); return PBEnsureCore() && PluginsOK ? 1 : 0; }
extern "C" LONG __cdecl DCompProxyGetState() { return InterlockedCompareExchange(&CoreState, 0, 0); }
extern "C" LONG __cdecl DCompProxyGetLastError() { return InterlockedCompareExchange(&LastErrorCode, 0, 0); }
extern "C" int __cdecl DCompProxyCheckProvider()
{
  if(InOriginal) return 0;
  InitOnceExecuteOnce(&OriginalOnce, PBResolveOriginal, nullptr, nullptr);
  for(int i=0;i<PB_EXPORT_COUNT;++i) if(!g_OrigAftermath[i]) return 0;
  return Original ? 1 : 0;
}
extern "C" const wchar_t *__cdecl DCompProxyNextProvider()
{
  static thread_local std::wstring path;
  // Metadata queries run only during serialized provider initialization.
  if(path.empty()) {
    path = PBPath(PB_PROVIDER_PATH, PB_PROVIDER_SYSTEM);
    for(size_t candidate = 0; candidate < PB_PROVIDER_COUNT; ++candidate) {
      std::wstring option = PBPath(PB_PROVIDER_CANDIDATES[candidate], PB_PROVIDER_SYSTEM);
      DWORD attributes = GetFileAttributesW(option.c_str());
      if(attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_DIRECTORY)) {
        path = std::move(option); break;
      }
    }
  }
  return path.c_str();
}

extern "C" intptr_t ResolveAftermathExport(int index)
{
  if(index < 0 || index >= PB_EXPORT_COUNT || InOriginal) {
    RaiseFailFastException(nullptr, nullptr, 0); __assume(0);
  }
  if constexpr(PB_ACTIVATION == 1) PBActivate();
  else if constexpr(PB_ACTIVATION == 2) { if(PB_ACTIVATE_EXPORT[index]) PBActivate(); }
  if constexpr(PB_REQUIRE_CORE) {
    // Core's own handshake may re-enter a carrier export. Forward that internal
    // call to the original; waiting for our own InitOnce would deadlock, and
    // treating the in-progress state as failure would abort valid startup.
    if(!InCore) {
      // A worker may still be loading plugins. Join that InitOnce before
      // publishing a fast path; otherwise a later plugin failure is missed.
      if(!InPlugins) PBActivate();
      if(!PBEnsureCore() || (!InPlugins && !PluginsOK)) { RaiseFailFastException(nullptr, nullptr, 0); __assume(0); }
    }
  }
  InitOnceExecuteOnce(&OriginalOnce, PBResolveOriginal, nullptr, nullptr);
  intptr_t target = g_OrigAftermath[index];
  if(!target) { RaiseFailFastException(nullptr, nullptr, 0); __assume(0); }
  // Publish only after InitOnce has completed and this external call has met
  // its activation/required-Core gate. Reentrant Core/plugin calls must not
  // make later external calls skip a gate that has not completed yet.
  if constexpr(PB_FAST_FORWARD) {
    if(!InCore && !InPlugins) InterlockedExchange(&g_ResolutionReady, 1);
  }
  return target;
}

[[maybe_unused]] static DWORD WINAPI PBWorker(LPVOID) { PBActivate(); return 0; }
static VOID CALLBACK PBModuleNotification(ULONG, const void *, void *)
{
  // Loader notification runs under loader lock: signal only. Never resolve
  // exports, load DLLs, log or initialize Core in this callback.
  SetEvent(ModuleEvent);
}
[[maybe_unused]] static DWORD WINAPI PBWatchModules(LPVOID)
{
  ModuleEvent = CreateEventW(nullptr, FALSE, FALSE, nullptr);
  if(!ModuleEvent) { InterlockedExchange(&LastErrorCode, GetLastError()); return 0; }
  using Register = LONG (NTAPI *)(ULONG, decltype(&PBModuleNotification), void *, void **);
  using Unregister = LONG (NTAPI *)(void *);
  HMODULE ntdll = GetModuleHandleW(L"ntdll.dll");
  auto subscribe = reinterpret_cast<Register>(GetProcAddress(ntdll, "LdrRegisterDllNotification"));
  auto unsubscribe = reinterpret_cast<Unregister>(GetProcAddress(ntdll, "LdrUnregisterDllNotification"));
  void *cookie = nullptr;
  if(subscribe) subscribe(0, PBModuleNotification, nullptr, &cookie);
  for(;;) {
    bool ready = true;
    for(size_t i=0; i<PB_WATCH_COUNT; ++i) if(!GetModuleHandleW(PB_WATCH_MODULES[i])) ready = false;
    if(ready) { PBActivate(); break; }
    // A timed fallback also covers systems without loader notifications.
    WaitForSingleObject(ModuleEvent, 1000);
  }
  if(cookie && unsubscribe) unsubscribe(cookie);
  // Event/module lifetime is process-scoped; callbacks may have been queued.
  return 0;
}
static BOOL CALLBACK PBRestoreEntry(PINIT_ONCE, PVOID, PVOID *)
{
  PBActivate();
  *EntryAddress = EntryByte;
  FlushInstructionCache(GetCurrentProcess(), EntryAddress, 1);
  DWORD previous = 0;
  VirtualProtect(EntryAddress, 1, EntryProtection, &previous);
  InterlockedExchange(&EntryGateState, 2);
  return TRUE;
}
static LONG CALLBACK PBEntryException(PEXCEPTION_POINTERS exception)
{
  if(exception->ExceptionRecord->ExceptionCode != EXCEPTION_BREAKPOINT ||
      exception->ExceptionRecord->ExceptionAddress != EntryAddress) return EXCEPTION_CONTINUE_SEARCH;
  LONG state = InterlockedCompareExchange(&EntryGateState, 0, 0);
  if(!state || (state == 2 && *EntryAddress == 0xcc)) return EXCEPTION_CONTINUE_SEARCH;
  // All threads that encountered our breakpoint take the same InitOnce gate.
  InitOnceExecuteOnce(&EntryOnce, PBRestoreEntry, nullptr, nullptr);
  exception->ContextRecord->Rip = reinterpret_cast<DWORD64>(EntryAddress);
  return EXCEPTION_CONTINUE_EXECUTION;
}

[[maybe_unused]] static void PBInstallEntryGate()
{
  BYTE *base = reinterpret_cast<BYTE *>(GetModuleHandleW(nullptr));
  auto dos = reinterpret_cast<IMAGE_DOS_HEADER *>(base);
  auto nt = reinterpret_cast<IMAGE_NT_HEADERS64 *>(base + dos->e_lfanew);
  DWORD rva = nt->OptionalHeader.AddressOfEntryPoint;
  if(!rva || rva >= nt->OptionalHeader.SizeOfImage) { InterlockedExchange(&LastErrorCode, ERROR_BAD_EXE_FORMAT); return; }
  BYTE *entry = base + rva;
  MEMORY_BASIC_INFORMATION info = {};
  if(!VirtualQuery(entry, &info, sizeof(info)) || info.State != MEM_COMMIT ||
      !(info.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY)) || *entry == 0xcc) {
    InterlockedExchange(&LastErrorCode, ERROR_INVALID_ADDRESS); return;
  }
  EntryAddress = entry;
  EntryByte = *entry;
  EntryHandler = AddVectoredExceptionHandler(1, PBEntryException);
  if(!EntryHandler || !VirtualProtect(entry, 1, PAGE_EXECUTE_READWRITE, &EntryProtection)) {
    InterlockedExchange(&LastErrorCode, GetLastError()); return;
  }
  InterlockedExchange(&EntryGateState, 1);
  *entry = 0xcc;
  FlushInstructionCache(GetCurrentProcess(), entry, 1);
}

BOOL WINAPI DllMain(HMODULE self, DWORD reason, LPVOID)
{
  if(reason == DLL_PROCESS_ATTACH) {
    PBSelf = self;
    DisableThreadLibraryCalls(self);
    if constexpr(PB_ACTIVATION == 0) {
      HANDLE worker = CreateThread(nullptr, 0, PBWorker, nullptr, 0, nullptr);
      if(worker) CloseHandle(worker);
      else { InterlockedExchange(&LastErrorCode, GetLastError()); InterlockedExchange(&CoreState, 4); }
    } else if constexpr(PB_ACTIVATION == 3) PBInstallEntryGate();
    else if constexpr(PB_ACTIVATION == 5) {
      HANDLE worker = CreateThread(nullptr, 0, PBWatchModules, nullptr, 0, nullptr);
      if(worker) CloseHandle(worker);
    }
  }
  // Process-scoped module, Core, provider and VEH lifetimes. Active proxies
  // are never intended to be unloaded; a JVM/ASI host pins its bridge.
  return TRUE;
}
