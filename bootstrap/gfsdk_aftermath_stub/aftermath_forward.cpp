// aftermath_forward.cpp
// Resolves the 9 original Aftermath function pointers from the renamed original
// DLL (GFSDK_Aftermath_Lib_orig.dll, sitting next to this module) and logs every
// forwarded call with a timestamp so we can reconstruct the game's Aftermath /
// RHI initialization ordering.
//
// The actual export wrappers live in aftermath_forward.asm (they save/restore
// RCX/RDX/R8/R9 around the log call and then jump to g_OrigAftermath[i]).

#include <windows.h>
#include <stdio.h>
#include <wchar.h>

#define LOG_PATH L"C:\\rdoc_probe\\aftermath_calls.log"
#define ORIG_NAME L"GFSDK_Aftermath_Lib_orig.dll"

extern "C" intptr_t g_OrigAftermath[9] = {};

// Export names as ANSI (GetProcAddress takes LPCSTR).
static const char *k_ExportNames[9] = {
    "GFSDK_Aftermath_DX11_CreateContextHandle",
    "GFSDK_Aftermath_DX11_Initialize",
    "GFSDK_Aftermath_DX12_CreateContextHandle",
    "GFSDK_Aftermath_DX12_Initialize",
    "GFSDK_Aftermath_GetData",
    "GFSDK_Aftermath_GetDeviceStatus",
    "GFSDK_Aftermath_GetPageFaultInformation",
    "GFSDK_Aftermath_ReleaseContextHandle",
    "GFSDK_Aftermath_SetEventMarker",
};

static const wchar_t *k_ExportNamesW[9] = {
    L"GFSDK_Aftermath_DX11_CreateContextHandle",
    L"GFSDK_Aftermath_DX11_Initialize",
    L"GFSDK_Aftermath_DX12_CreateContextHandle",
    L"GFSDK_Aftermath_DX12_Initialize",
    L"GFSDK_Aftermath_GetData",
    L"GFSDK_Aftermath_GetDeviceStatus",
    L"GFSDK_Aftermath_GetPageFaultInformation",
    L"GFSDK_Aftermath_ReleaseContextHandle",
    L"GFSDK_Aftermath_SetEventMarker",
};

static volatile ULONGLONG g_StartTick = 0;
static volatile LONG g_Resolved = 0;
static HMODULE g_OrigModule = NULL;

// Get this module's own directory so we can find GFSDK_Aftermath_Lib_orig.dll.
static void GetModuleDir(wchar_t *out, size_t cap)
{
    out[0] = 0;
    HMODULE self = NULL;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                           GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       (LPCWSTR)&g_OrigAftermath, &self);
    if (self == NULL)
        return;
    wchar_t path[MAX_PATH];
    DWORD got = GetModuleFileNameW(self, path, MAX_PATH);
    if (got == 0 || got >= MAX_PATH)
        return;
    wchar_t *slash = wcsrchr(path, L'\\');
    if (slash == NULL)
        return;
    slash[1] = 0;
    wcsncpy_s(out, cap, path, _TRUNCATE);
}

// Lazily resolve all 9 originals once (called on the game thread, not DllMain,
// so LoadLibrary is safe). Concurrent first calls are serialized by Interlocked.
static void ResolveOriginals(void)
{
    if (InterlockedCompareExchange(&g_Resolved, 1, 0) != 0)
        return;

    wchar_t dir[MAX_PATH];
    GetModuleDir(dir, MAX_PATH);

    wchar_t origPath[MAX_PATH];
    _snwprintf_s(origPath, MAX_PATH, _TRUNCATE, L"%ls%ls", dir, ORIG_NAME);

    HMODULE mod = LoadLibraryW(origPath);
    if (mod == NULL)
        return;

    g_OrigModule = mod;
    for (int i = 0; i < 9; i++)
        g_OrigAftermath[i] = (intptr_t)GetProcAddress(mod, k_ExportNames[i]);
}
static void AppendLog(ULONGLONG elapsedMs, const wchar_t *name)
{
    HANDLE h = CreateFileW(LOG_PATH, FILE_APPEND_DATA,
                           FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                           OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return;

    wchar_t buf[512];
    int n = _snwprintf_s(buf, 512, _TRUNCATE,
                         L"%llu\t%ls\tpid=%lu\ttid=%lu\n",
                         (unsigned long long)elapsedMs, name,
                         (unsigned long)GetCurrentProcessId(),
                         (unsigned long)GetCurrentThreadId());
    if (n > 0)
    {
        char utf8[1024];
        int bytes = WideCharToMultiByte(CP_UTF8, 0, buf, n, utf8, (int)sizeof(utf8), NULL, NULL);
        DWORD written;
        WriteFile(h, utf8, (DWORD)bytes, &written, NULL);
    }
    CloseHandle(h);
}

// Called from the asm wrappers before forwarding.
extern "C" void LogAftermathCall(int index)
{
    if (g_StartTick == 0)
        g_StartTick = GetTickCount64();

    ResolveOriginals();

    if (index >= 0 && index < 9)
        AppendLog(GetTickCount64() - g_StartTick, k_ExportNamesW[index]);
}
