#include <stdio.h>
#include <windows.h>
#include <psapi.h>
#include <dbghelp.h>
#include "forward_exports.h"
#include "api/app/renderdoc_app.h"

// ---------------------------------------------------------------------------
// GFSDK Aftermath forwarding stub + DComp capture engine bootstrap.
//
// This DLL is statically imported by Strinova-Win64-Shipping.exe (import slot
// #4, early in the loader order). It forwards the 9 GFSDK_Aftermath_* exports
// to the renamed original, and - when the DComp capture engine is enabled -
// loads dgcore.dll from the adjacent directory.
//
// dgcore is loaded on a worker thread created from DllMain, exactly like the
// official RenderDoc shim (renderdocshim.cpp). DllMain itself must stay minimal
// to avoid loader-lock deadlock; CreateThread is safe in DllMain.
// ---------------------------------------------------------------------------

#define DCOMP_BOOTSTRAP_ENABLE_VAR L"DCOMP_BOOTSTRAP_ENABLE"
#define DCOMP_BOOTSTRAP_LOG_VAR    L"DCOMP_BOOTSTRAP_LOG"
#define DCOMP_CORE_FILENAME        L"dgcore.dll"
#define FIXED_LOG_PATH             L"C:\\rdoc_probe\\gfsdk_bootstrap.log"

static HMODULE g_CoreModule = NULL;
static volatile LONG g_LoadStarted = 0;

// Reference timestamp (ms since process start) written to the Aftermath log so
// the core-load thread can record when dgcore actually started loading.
extern "C" volatile ULONGLONG g_ProcessStartTick = 0;
extern "C" ULONGLONG GetProcessElapsedMs(void);

ULONGLONG GetProcessElapsedMs(void)
{
    return GetTickCount64() - g_ProcessStartTick;
}

// ---------------------------------------------------------------------------
// Minimal logger: writes to a fixed path so diagnostics survive env-var
// inheritance problems. kernel32-only, no CRT.
// ---------------------------------------------------------------------------
static void BootstrapLog(const wchar_t *fmt, ...)
{
    wchar_t buf[2048];
    va_list args;
    va_start(args, fmt);
    _vsnwprintf_s(buf, 2048, _TRUNCATE, fmt, args);
    va_end(args);

    OutputDebugStringW(buf);

    HANDLE h = CreateFileW(FIXED_LOG_PATH, FILE_APPEND_DATA,
                           FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                           OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return;

    char utf8[4096];
    int bytes = WideCharToMultiByte(CP_UTF8, 0, buf, -1, utf8, (int)sizeof(utf8), NULL, NULL);
    if (bytes > 1) {
        DWORD written;
        WriteFile(h, utf8, (DWORD)(bytes - 1), &written, NULL);
    }
    CloseHandle(h);
}

// ---------------------------------------------------------------------------
// Observability marker: proves this DLL loaded and when.
// ---------------------------------------------------------------------------
static void WriteLoadMarker(void)
{
    if (!CreateDirectoryW(L"C:\\rdoc_probe", NULL) && GetLastError() != ERROR_ALREADY_EXISTS)
        return;

    HANDLE h = CreateFileW(L"C:\\rdoc_probe\\gfsdk_aftermath_loaded.txt",
                           GENERIC_WRITE, FILE_SHARE_READ, NULL,
                           CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return;

    SYSTEMTIME st;
    GetLocalTime(&st);
    char buf[256];
    int n = wsprintfA(buf, "pid=%lu loaded_at=%02u:%02u:%02u.%03u reason=attach module=GFSDK_Aftermath_stub\n",
                      GetCurrentProcessId(),
                      (unsigned)st.wHour, (unsigned)st.wMinute,
                      (unsigned)st.wSecond, (unsigned)st.wMilliseconds);
    DWORD written;
    WriteFile(h, buf, (DWORD)n, &written, NULL);
    CloseHandle(h);
}

// ---------------------------------------------------------------------------
// Compute the directory of this module, then construct the adjacent path
// <ourdir>\dgcore.dll.
// ---------------------------------------------------------------------------
static void GetAdjacentCorePath(wchar_t *outPath, size_t outLen)
{
    outPath[0] = 0;

    HMODULE self = NULL;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                           GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       (LPCWSTR)WriteLoadMarker, &self);
    if (self == NULL)
        return;

    wchar_t selfPath[MAX_PATH];
    DWORD got = GetModuleFileNameW(self, selfPath, MAX_PATH);
    if (got == 0 || got >= MAX_PATH)
        return;

    wchar_t *slash = wcsrchr(selfPath, L'\\');
    if (slash == NULL)
        return;
    slash[1] = 0;

    _snwprintf_s(outPath, outLen, _TRUNCATE, L"%ls%ls", selfPath, DCOMP_CORE_FILENAME);
}

// ---------------------------------------------------------------------------
// Worker thread: loads dgcore.dll off the loader lock. Returns 0.
// Delays briefly so the process environment is stable, and retries on
// transient failure (error 1114 = DLL init failure can occur if we load too
// early, before core system services are ready in the target process).
// ---------------------------------------------------------------------------
#define CORE_LOAD_RETRIES 5
#define CORE_LOAD_RETRY_DELAY_MS 1500

static DWORD WINAPI LoadCoreThread(LPVOID param)
{
    (void)param;

    wchar_t corePath[MAX_PATH];
    GetAdjacentCorePath(corePath, MAX_PATH);

    if (corePath[0] == 0) {
        BootstrapLog(L"DComp GFSDK bootstrap: failed to resolve dgcore.dll path\n");
        return 0;
    }

    // No artificial delay: load dgcore as early as possible so its hooks are
    // registered before the game creates its main render device (D3D11 loads at
    // process start). The original 2.5 s Sleep was added to dodge the 1114
    // init failure, which the CRT upgrade to 14.51 already fixed.

    // The compiled diagnostic knobs (system-level IAT hooks, WSA hooks, overlay,
    // target control) only take effect in a process marked as a diagnostic
    // target, and the Core reads the marker during its own DllMain. Set it here,
    // before the Core is loaded, so the intended knob state applies to this
    // process. For the proxy route this is the desirable state: no
    // LoadLibrary/GetProcAddress IAT hooks and no child-process injection, which
    // are only needed by the injection/global-hook workflows.
    if (SetEnvironmentVariableW(L"DCOMP_DIAGNOSTIC_TARGET_PROCESS", L"1"))
        BootstrapLog(L"DComp GFSDK bootstrap: DCOMP_DIAGNOSTIC_TARGET_PROCESS=1 set for this process\n");
    else
        BootstrapLog(L"DComp GFSDK bootstrap: failed to set diagnostic target marker, error=%lu\n",
                     GetLastError());

    for (int attempt = 1; attempt <= CORE_LOAD_RETRIES; ++attempt) {
        BootstrapLog(L"DComp GFSDK bootstrap: attempt %d/%d loading %ls\n",
                     attempt, CORE_LOAD_RETRIES, corePath);

        HMODULE core = LoadLibraryW(corePath);
        if (core != NULL) {
            g_CoreModule = core;
            BootstrapLog(L"DComp GFSDK bootstrap: core loaded at %p\n", core);

            // ProxyOnly: skip every IAT patch and page-protection change. The ATS
            // component of the anti-cheat checks import tables and module memory
            // integrity, so on a protected target the only load-bearing hooks are
            // the graphics *entry* detours, which ProxyOnly keeps.
            typedef void(__cdecl *SetHookModeFn)(int);
            SetHookModeFn setHookMode =
                (SetHookModeFn)GetProcAddress(core, "DCOMP_SetHookMode");
            if (setHookMode != NULL) {
                setHookMode(0);
                BootstrapLog(L"DComp GFSDK bootstrap: DCOMP_SetHookMode(0) ProxyOnly applied\n");
            } else {
                BootstrapLog(L"DComp GFSDK bootstrap: DCOMP_SetHookMode not exported, mode unchanged\n");
            }

            // The overlay draws on the application's present path. On a target that
            // has to stay responsive at the first frame, that per-frame work is the
            // difference between a responsive window and the OS hang detector
            // snapshotting the process with every thread suspended. Capture and
            // replay do not depend on the overlay.
            pDCOMP_GetAPI getAPI = (pDCOMP_GetAPI)GetProcAddress(core, "DCOMP_GetAPI");
            RENDERDOC_API_1_6_0 *api = NULL;
            if(getAPI != NULL && getAPI(eDCOMP_API_Version_1_6_0, (void **)&api) == 1 &&
               api != NULL)
            {
                if(api->MaskOverlayBits != NULL)
                {
                    api->MaskOverlayBits(0, 0);   // clear every overlay bit => disabled
                    BootstrapLog(L"DComp GFSDK bootstrap: overlay masked off\n");
                }
            }
            else
            {
                BootstrapLog(L"DComp GFSDK bootstrap: API handshake failed, overlay untouched\n");
            }

            BootstrapLog(L"DComp GFSDK bootstrap: done, core module=%p\n", core);
            return 0;
        }

        DWORD err = GetLastError();
        BootstrapLog(L"DComp GFSDK bootstrap: attempt %d failed, error=%lu\n", attempt, err);

        if (attempt < CORE_LOAD_RETRIES) {
            BootstrapLog(L"DComp GFSDK bootstrap: retrying in %d ms...\n", CORE_LOAD_RETRY_DELAY_MS);
            Sleep(CORE_LOAD_RETRY_DELAY_MS);
        }
    }

    BootstrapLog(L"DComp GFSDK bootstrap: all attempts failed\n");
    return 0;
}

// ---------------------------------------------------------------------------
// Enable check: prefers the env var, falls back to an adjacent marker file
// <ourdir>\dgcore.enable. The marker file is more reliable than a user env var
// (Steam does not forward newly-set user env vars to already-running parents)
// and is stealthier (no environment footprint for ACE to scan).
// ---------------------------------------------------------------------------
static bool EnableRequested(void)
{
    wchar_t enable[16] = {};
    DWORD len = GetEnvironmentVariableW(DCOMP_BOOTSTRAP_ENABLE_VAR, enable, 16);
    if (len == 1 && enable[0] == L'1')
        return true;

    wchar_t selfPath[MAX_PATH];
    HMODULE self = NULL;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                           GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       (LPCWSTR)EnableRequested, &self);
    if (self && GetModuleFileNameW(self, selfPath, MAX_PATH)) {
        wchar_t *slash = wcsrchr(selfPath, L'\\');
        if (slash) {
            slash[1] = 0;
            wcscat_s(selfPath, MAX_PATH, L"dgcore.enable");
            if (GetFileAttributesW(selfPath) != INVALID_FILE_ATTRIBUTES)
                return true;
        }
    }

    return false;
}

static void StartCoreLoad(void)
{
    if (InterlockedCompareExchange(&g_LoadStarted, 1, 0) != 0)
        return;

    // Only load the core when explicitly enabled. Otherwise this DLL behaves as
    // a pure Aftermath forwarder and is invisible to the game.
    if (!EnableRequested()) {
        BootstrapLog(L"DComp GFSDK bootstrap: disabled (set %ls=1 or drop dgcore.enable)\n",
                     DCOMP_BOOTSTRAP_ENABLE_VAR);
        return;
    }

    BootstrapLog(L"DComp GFSDK bootstrap: enabled, spawning core load thread\n");

    HANDLE t = CreateThread(NULL, 0, LoadCoreThread, NULL, 0, NULL);
    if (t != NULL)
        CloseHandle(t);
}

// ---------------------------------------------------------------------------
// DX module load-timing observer.
//
// Polls GetModuleHandle for the graphics runtime DLLs every 50 ms for the first
// 60 s of process life and logs the first time each one appears, plus every
// state change, to C:\rdoc_probe\dx_load_timing.log. This reveals which RHI the
// game actually uses (D3D11 vs D3D12) and when each DLL loads relative to our
// own early load. Independent of dgcore - runs regardless of EnableRequested().
// ---------------------------------------------------------------------------
#define DX_OBSERVE_POLL_MS   50
#define DX_OBSERVE_DURATION_MS (60 * 1000)

// Fail-fast watchdog support, defined further below. The DX observer thread
// keeps the watchdog's module ranges current as the graphics stack loads.
#define WATCH_REFRESH_MS     5000
static void RefreshModuleTable(void);

struct DxModuleObserved
{
    const wchar_t *name;
    bool wasLoaded;
};

static void DxObserveLog(const wchar_t *fmt, ...)
{
    wchar_t buf[1024];
    va_list args;
    va_start(args, fmt);
    _vsnwprintf_s(buf, 1024, _TRUNCATE, fmt, args);
    va_end(args);

    HANDLE h = CreateFileW(L"C:\\rdoc_probe\\dx_load_timing.log",
                           FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return;

    char utf8[2048];
    int bytes = WideCharToMultiByte(CP_UTF8, 0, buf, -1, utf8, (int)sizeof(utf8), NULL, NULL);
    if (bytes > 1) {
        DWORD written;
        WriteFile(h, utf8, (DWORD)(bytes - 1), &written, NULL);
    }
    CloseHandle(h);
}

static DWORD WINAPI ObserveDxModulesThread(LPVOID param)
{
    (void)param;

    DxModuleObserved mods[] = {
        { L"d3d11.dll", false },
        { L"d3d12.dll", false },
        { L"dxgi.dll", false },
        { L"d3dcompiler_47.dll", false },
        { L"nvngx_dlss.dll", false },
        { L"libxess.dll", false },
    };
    const size_t nmods = sizeof(mods) / sizeof(mods[0]);

    ULONGLONG start = GetTickCount64();
    ULONGLONG lastRefresh = (ULONGLONG)-1;
    bool anyStateChange = true;  // dump initial snapshot

    while (true)
    {
        ULONGLONG elapsed = GetTickCount64() - start;
        bool stateChanged = false;

        // Keep the fail-fast watchdog's module ranges current as the process
        // loads more of the graphics stack.
        if (elapsed / WATCH_REFRESH_MS != lastRefresh)
        {
            lastRefresh = elapsed / WATCH_REFRESH_MS;
            RefreshModuleTable();
        }

        for (size_t i = 0; i < nmods; i++)
        {
            HMODULE h = GetModuleHandleW(mods[i].name);
            bool loaded = (h != NULL);
            if (loaded != mods[i].wasLoaded)
            {
                mods[i].wasLoaded = loaded;
                stateChanged = true;
                DxObserveLog(L"%llu\t%s\t%s\n",
                             (unsigned long long)elapsed,
                             mods[i].name,
                             loaded ? L"LOADED" : L"UNLOADED");
            }
        }

        if (anyStateChange)
        {
            // log a full snapshot line on the first poll
            wchar_t line[512];
            _snwprintf_s(line, 512, _TRUNCATE,
                         L"%llu\t[snapshot]", (unsigned long long)elapsed);
            DxObserveLog(line);
            anyStateChange = false;
        }

        if (elapsed >= DX_OBSERVE_DURATION_MS)
        {
            DxObserveLog(L"%llu\t[observer done]", (unsigned long long)elapsed);
            break;
        }

        Sleep(DX_OBSERVE_POLL_MS);
    }

    return 0;
}

static void StartDxObserver(void)
{
    // Always run the observer regardless of dgcore enable state.
    HANDLE t = CreateThread(NULL, 0, ObserveDxModulesThread, NULL, 0, NULL);
    if (t != NULL)
        CloseHandle(t);
}

// ---------------------------------------------------------------------------
// Thread-pool fail-fast watchdog.
//
// Windows 11 25H2's ntdll fail-fasts the process with STATUS_INVALID_PARAMETER
// (0xC000000D) from TppRaiseInvalidParameter when a thread-pool API is handed
// parameters the newer validation rejects. The exception is non-continuable,
// so the process is lost either way, but a vectored handler still runs first
// and can record the call chain that reached the raise site.
//
// No symbols are needed for that: a raw scan of the faulting thread's stack,
// keeping every word that lands inside a loaded module image, yields return
// addresses in call order. Offsets are reported module-relative so they can be
// matched against any build of that module.
// ---------------------------------------------------------------------------
#define TPWATCH_LOG_PATH     L"C:\\rdoc_probe\\tpwatch.log"
#define WATCH_MAX_MODULES    512
#define WATCH_MAX_REPORTED   48

// STATUS_INVALID_PARAMETER (0xC000000D) and STATUS_STACK_BUFFER_OVERRUN
// (0xC0000409) come from winnt.h.

struct WatchModuleRange
{
    ULONG64 base;
    ULONG64 end;
    wchar_t name[MAX_PATH];
};

static WatchModuleRange g_WatchModules[WATCH_MAX_MODULES];
static volatile LONG g_WatchModuleCount = 0;
static volatile LONG g_WatchdogArmed = 0;

static void WatchLogRaw(const char *text, int len)
{
    HANDLE h = CreateFileW(TPWATCH_LOG_PATH, FILE_APPEND_DATA,
                           FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                           OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return;

    DWORD written;
    WriteFile(h, text, (DWORD)len, &written, NULL);
    CloseHandle(h);
}

static void WatchLog(const wchar_t *fmt, ...)
{
    wchar_t buf[2048];
    va_list args;
    va_start(args, fmt);
    _vsnwprintf_s(buf, 2048, _TRUNCATE, fmt, args);
    va_end(args);

    OutputDebugStringW(buf);

    char utf8[4096];
    int bytes = WideCharToMultiByte(CP_UTF8, 0, buf, -1, utf8, (int)sizeof(utf8), NULL, NULL);
    if (bytes > 1)
        WatchLogRaw(utf8, bytes - 1);
}

static const wchar_t *WatchModuleFor(ULONG64 addr, ULONG64 *offsetOut)
{
    LONG count = g_WatchModuleCount;
    if (count > WATCH_MAX_MODULES)
        count = WATCH_MAX_MODULES;

    for (LONG i = 0; i < count; ++i)
    {
        if (addr >= g_WatchModules[i].base && addr < g_WatchModules[i].end)
        {
            if (offsetOut != NULL)
                *offsetOut = addr - g_WatchModules[i].base;
            return g_WatchModules[i].name;
        }
    }

    if (offsetOut != NULL)
        *offsetOut = 0;
    return NULL;
}

// Snapshot the loaded-module ranges. Called from a worker thread, never from
// DllMain: EnumProcessModulesEx can take the loader lock.
static void RefreshModuleTable(void)
{
    HMODULE mods[WATCH_MAX_MODULES];
    DWORD needed = 0;
    if (!EnumProcessModulesEx(GetCurrentProcess(), mods, sizeof(mods), &needed, LIST_MODULES_ALL))
        return;

    DWORD count = needed / sizeof(HMODULE);
    if (count > WATCH_MAX_MODULES)
        count = WATCH_MAX_MODULES;

    LONG written = 0;
    for (DWORD i = 0; i < count && written < WATCH_MAX_MODULES; ++i)
    {
        MODULEINFO mi = {};
        if (!GetModuleInformation(GetCurrentProcess(), mods[i], &mi, sizeof(mi)))
            continue;
        if (mi.lpBaseOfDll == NULL || mi.SizeOfImage == 0)
            continue;

        WatchModuleRange *r = &g_WatchModules[written];
        r->base = (ULONG64)mi.lpBaseOfDll;
        r->end = r->base + mi.SizeOfImage;
        if (GetModuleFileNameW(mods[i], r->name, MAX_PATH) == 0)
            r->name[0] = 0;
        ++written;
    }

    InterlockedExchange(&g_WatchModuleCount, written);
}

static LONG CALLBACK FailFastWatchdog(EXCEPTION_POINTERS *info)
{
    if (info == NULL || info->ExceptionRecord == NULL || info->ContextRecord == NULL)
        return EXCEPTION_CONTINUE_SEARCH;

    const DWORD code = info->ExceptionRecord->ExceptionCode;
    if (code != STATUS_INVALID_PARAMETER && code != STATUS_STACK_BUFFER_OVERRUN)
        return EXCEPTION_CONTINUE_SEARCH;

    ULONG64 faultAddr = (ULONG64)info->ExceptionRecord->ExceptionAddress;
    ULONG64 faultOff = 0;
    const wchar_t *faultMod = WatchModuleFor(faultAddr, &faultOff);

    WatchLog(L"\n=== fail-fast %08lx on tid %lu ===\n", code, GetCurrentThreadId());
    if (code == STATUS_INVALID_PARAMETER && info->ExceptionRecord->NumberParameters > 0)
        WatchLog(L"  raise status: %08llx\n",
                 (unsigned long long)info->ExceptionRecord->ExceptionInformation[0]);
    if (faultMod != NULL)
        WatchLog(L"  raise site : %ls+0x%llx (%p)\n", faultMod,
                 (unsigned long long)faultOff, (void *)faultAddr);
    else
        WatchLog(L"  raise site : %p (outside every loaded image)\n", (void *)faultAddr);

    // Walk the faulting thread's stack. Everything between the current RSP and
    // the stack base is committed, so the reads cannot fault. Non-canonical or
    // unrelated words are simply filtered out by the module-range test.
    ULONG64 teb = __readgsqword(0x30);
    ULONG64 stackBase = 0;
    ULONG64 stackLimit = 0;
    if (teb != 0)
    {
        stackBase = *(volatile ULONG64 *)(teb + 0x08);
        stackLimit = *(volatile ULONG64 *)(teb + 0x10);
    }

    ULONG64 sp = info->ContextRecord->Rsp;
    ULONG64 lo = (sp > stackLimit) ? sp : stackLimit;
    ULONG64 hi = (stackBase > lo) ? stackBase : lo;

    WatchLog(L"  rsp=%p  scan=[%p,%p)\n", (void *)sp, (void *)lo, (void *)hi);

    int reported = 0;
    for (ULONG64 p = lo; p + sizeof(ULONG64) <= hi && reported < WATCH_MAX_REPORTED;
         p += sizeof(ULONG64))
    {
        ULONG64 value = *(volatile ULONG64 *)p;
        ULONG64 off = 0;
        const wchar_t *mod = WatchModuleFor(value, &off);
        if (mod != NULL)
        {
            WatchLog(L"    +#%02x  %ls+0x%llx\n", (unsigned)(p - sp), mod,
                     (unsigned long long)off);
            ++reported;
        }
    }

    WatchLog(L"  (end of stack scan, %d frames reported)\n", reported);

    // Let the process die the way it was going to; we only recorded evidence.
    return EXCEPTION_CONTINUE_SEARCH;
}

static void StartFailFastWatchdog(void)
{
    if (InterlockedCompareExchange(&g_WatchdogArmed, 1, 0) != 0)
        return;

    // First in the chain: nothing else should be able to swallow the record.
    PVOID handle = AddVectoredExceptionHandler(1, FailFastWatchdog);
    WatchLog(L"DComp watchdog: vectored fail-fast handler %ls\n",
             handle != NULL ? L"installed" : L"INSTALL FAILED");
}

// ---------------------------------------------------------------------------
// First-frame hang capture.
//
// With the graphics hooks live the game goes unresponsive at the first frame:
// every thread ends up in Wait, the CPU time stops advancing and the window
// stops answering, sometimes for minutes. The game's anti-cheat denies
// cross-process OpenProcess, so neither an external debugger nor an outside
// MiniDumpWriteDump can reach it - but from inside the process both work, and
// that is where this watchdog runs.
//
// It polls the main window with a short SendMessageTimeout. After a few
// consecutive timeouts the message pump is not running, so it snapshots the
// whole process (thread stacks included) to a dump under C:\rdoc_probe.
// ---------------------------------------------------------------------------
// The window stops answering a few seconds into the first frame, so the
// watchdog is armed early and only needs a short settle once the window
// exists. The first dump therefore lands well inside the freeze.
#define HANG_POLL_MS         2000
#define HANG_STRIKES         3
#define HANG_ARM_DELAY_MS    (15 * 1000)
#define HANG_WINDOW_SETTLE_MS (3 * 1000)
#define HANG_MAX_DUMPS       3
#define HANG_DUMP_GAP_MS     (45 * 1000)
#define HANG_HEARTBEAT_MS    (15 * 1000)

struct WindowSearch
{
    DWORD pid;
    HWND best;
    LONG bestArea;
    DWORD bestThread;
};

static BOOL CALLBACK FindMainWindowCallback(HWND hwnd, LPARAM lParam)
{
    WindowSearch *search = (WindowSearch *)lParam;

    DWORD pid = 0;
    DWORD tid = GetWindowThreadProcessId(hwnd, &pid);
    if (pid != search->pid || !IsWindowVisible(hwnd))
        return TRUE;

    RECT rect;
    if (!GetWindowRect(hwnd, &rect))
        return TRUE;

    LONG area = (rect.right - rect.left) * (rect.bottom - rect.top);
    if (area > search->bestArea)
    {
        search->bestArea = area;
        search->best = hwnd;
        search->bestThread = tid;
    }

    return TRUE;
}

static bool WriteProcessDump(const wchar_t *reason)
{
    HMODULE dbghelp = GetModuleHandleW(L"dbghelp.dll");
    if (dbghelp == NULL)
        dbghelp = LoadLibraryW(L"dbghelp.dll");
    if (dbghelp == NULL)
    {
        WatchLog(L"DComp hang watchdog: dbghelp unavailable (error %lu), no dump\n", GetLastError());
        return false;
    }

    typedef BOOL(WINAPI * MiniDumpWriteDumpFn)(HANDLE, DWORD, HANDLE, MINIDUMP_TYPE,
                                               PMINIDUMP_EXCEPTION_INFORMATION,
                                               PMINIDUMP_USER_STREAM_INFORMATION,
                                               PMINIDUMP_CALLBACK_INFORMATION);
    MiniDumpWriteDumpFn writeDump =
        (MiniDumpWriteDumpFn)GetProcAddress(dbghelp, "MiniDumpWriteDump");
    if (writeDump == NULL)
    {
        WatchLog(L"DComp hang watchdog: MiniDumpWriteDump not found, no dump\n");
        return false;
    }

    SYSTEMTIME st;
    GetLocalTime(&st);
    wchar_t path[MAX_PATH];
    _snwprintf_s(path, MAX_PATH, _TRUNCATE,
                 L"C:\\rdoc_probe\\%ls_%lu_%02u%02u%02u.dmp", reason, GetCurrentProcessId(),
                 (unsigned)st.wHour, (unsigned)st.wMinute, (unsigned)st.wSecond);

    HANDLE file = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE)
    {
        WatchLog(L"DComp hang watchdog: cannot create %ls (error %lu)\n", path, GetLastError());
        return false;
    }

    // Thread and module metadata only: the stacks are what identify the block,
    // and a memory image of a shipping title would be needlessly large.
    MINIDUMP_TYPE type = (MINIDUMP_TYPE)(MiniDumpNormal | MiniDumpWithThreadInfo |
                                         MiniDumpWithUnloadedModules |
                                         MiniDumpWithProcessThreadData);

    ULONGLONG began = GetTickCount64();
    BOOL ok = writeDump(GetCurrentProcess(), GetCurrentProcessId(), file, type, NULL, NULL, NULL);
    DWORD err = ok ? 0 : GetLastError();
    CloseHandle(file);

    WatchLog(L"DComp hang watchdog: dump %ls (%llu ms) -> %ls\n", ok ? L"written" : L"FAILED",
             (unsigned long long)(GetTickCount64() - began), path);
    if (!ok)
        WatchLog(L"DComp hang watchdog: MiniDumpWriteDump error %lu\n", err);

    return ok == TRUE;
}

static DWORD WINAPI HangWatchThread(LPVOID param)
{
    (void)param;

    const DWORD pid = GetCurrentProcessId();
    const ULONGLONG startedAt = GetTickCount64();
    const ULONGLONG armedAt = startedAt + HANG_ARM_DELAY_MS;

    HWND window = NULL;
    DWORD windowThread = 0;
    ULONGLONG windowSeenAt = 0;
    ULONGLONG lastHeartbeat = 0;

    int strikes = 0;
    int dumps = 0;
    ULONGLONG lastDumpAt = 0;

    while (true)
    {
        Sleep(HANG_POLL_MS);
        ULONGLONG now = GetTickCount64();

        // Heartbeat: if these stop, this thread stopped too, which is a
        // different failure than "the test did not fire".
        if (now - lastHeartbeat >= HANG_HEARTBEAT_MS)
        {
            lastHeartbeat = now;
            WatchLog(L"DComp hang watchdog: heartbeat t=%llu s window=%p hung=%d\n",
                     (unsigned long long)((now - startedAt) / 1000), (void *)window,
                     (window != NULL && IsWindow(window)) ? IsHungAppWindow(window) : -1);
        }

        if (window == NULL || !IsWindow(window))
        {
            WindowSearch search = { pid, NULL, 0, 0 };
            EnumWindows(FindMainWindowCallback, (LPARAM)&search);
            window = search.best;
            windowThread = search.bestThread;
            windowSeenAt = now;
            strikes = 0;

            if (window != NULL)
                WatchLog(L"DComp hang watchdog: main window %p on tid %lu, watching\n",
                         (void *)window, windowThread);
            continue;
        }

        if (now < armedAt || now - windowSeenAt < HANG_WINDOW_SETTLE_MS)
            continue;

        // IsHungAppWindow is the unambiguous test: it asks the window manager
        // directly whether this window has stopped processing messages, so
        // there is no return-value/GetLastError ambiguity to misread.
        if (!IsHungAppWindow(window))
        {
            strikes = 0;
            continue;
        }

        ++strikes;
        if (strikes != HANG_STRIKES)
            continue;

        // Record what the classic timeout call says too, for the log only.
        DWORD_PTR result = 0;
        SetLastError(0);
        LRESULT answered = SendMessageTimeoutW(window, WM_NULL, 0, 0, SMTO_NORMAL, 250, &result);

        WatchLog(L"DComp hang watchdog: window %p (tid %lu) hung for %d polls (~%d s), "
                 L"SendMessageTimeout ret=%lld err=%lu\n",
                 (void *)window, windowThread, strikes, (strikes * HANG_POLL_MS) / 1000,
                 (long long)answered, answered ? 0UL : GetLastError());

        if (dumps >= HANG_MAX_DUMPS || now - lastDumpAt < HANG_DUMP_GAP_MS)
            continue;

        if (WriteProcessDump(L"hang"))
        {
            ++dumps;
            lastDumpAt = now;
            // Restart the count so a long freeze yields another sample once the
            // gap has elapsed, showing whether the block is moving.
            strikes = 0;
        }
    }

    return 0;
}

static void StartHangWatch(void)
{
    HANDLE t = CreateThread(NULL, 0, HangWatchThread, NULL, 0, NULL);
    if (t != NULL)
        CloseHandle(t);
}

// ---------------------------------------------------------------------------
// Probe: log which VC runtime modules are ALREADY loaded in this process when
// our DllMain runs. This reveals which MSVCP140/VCRUNTIME the game resolved,
// which is what dgcore will inherit when it imports the same DLL names.
// ---------------------------------------------------------------------------
static void ProbeLoadedVcRuntime(void)
{
    HMODULE mods[1024];
    DWORD needed = 0;
    if (!EnumProcessModulesEx(GetCurrentProcess(), mods, sizeof(mods), &needed,
                              LIST_MODULES_ALL))
        return;
    DWORD count = needed / sizeof(HMODULE);
    if (count > 1024)
        count = 1024;

    for (DWORD i = 0; i < count; ++i) {
        wchar_t name[MAX_PATH];
        DWORD n = GetModuleFileNameW(mods[i], name, MAX_PATH);
        if (n == 0 || n >= MAX_PATH)
            continue;
        wchar_t *slash = wcsrchr(name, L'\\');
        if (!slash)
            continue;
        if (_wcsicmp(slash + 1, L"MSVCP140.dll") == 0 ||
            _wcsicmp(slash + 1, L"VCRUNTIME140.dll") == 0 ||
            _wcsicmp(slash + 1, L"VCRUNTIME140_1.dll") == 0) {
            BootstrapLog(L"DComp GFSDK bootstrap: loaded VC runtime: %ls (from %ls)\n",
                         slash + 1, name);
        }
    }
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call, LPVOID lpReserved)
{
    (void)lpReserved;
    if (ul_reason_for_call == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hModule);
        if (g_ProcessStartTick == 0)
            g_ProcessStartTick = GetTickCount64();
        WriteLoadMarker();
        ProbeLoadedVcRuntime();
        StartFailFastWatchdog();
        StartHangWatch();
        StartDxObserver();
        StartCoreLoad();
    }
    return TRUE;
}
