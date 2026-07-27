// process_injector.cpp
// Monitors for a target process and injects the DComp core DLL at the earliest
// possible moment via SetThreadContext hijack.
//
// Usage: process_injector.exe <dll_path> [process_name]
//   dll_path:     full path to dcomp.dll
//   process_name: target exe name (default: NRC-Win64-Shipping.exe)

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <limits.h>

// ============================================================================
// Inject DLL via SetThreadContext hijack (from RenderDoc's InjectDLL)
// ============================================================================
static bool InjectDLL(DWORD pid, const wchar_t *dllPath)
{
    HANDLE hProcess = OpenProcess(
        PROCESS_CREATE_THREAD | PROCESS_VM_OPERATION | PROCESS_VM_WRITE |
        PROCESS_VM_READ | PROCESS_QUERY_INFORMATION,
        FALSE, pid);
    if(!hProcess)
    {
        printf("[!] OpenProcess(%lu) failed: %lu\n", pid, GetLastError());
        return false;
    }

    HMODULE kernel32 = GetModuleHandleA("kernel32.dll");
    FARPROC loadLibraryW = GetProcAddress(kernel32, "LoadLibraryW");

    const SIZE_T pathSize = (wcslen(dllPath) + 1) * sizeof(wchar_t);
    const SIZE_T shellcodeSize = 64;
    const SIZE_T totalSize = pathSize + shellcodeSize;

    void *remoteMem = VirtualAllocEx(hProcess, NULL, totalSize, MEM_COMMIT, PAGE_EXECUTE_READWRITE);
    if(!remoteMem)
    {
        printf("[!] VirtualAllocEx failed: %lu\n", GetLastError());
        CloseHandle(hProcess);
        return false;
    }

    WriteProcessMemory(hProcess, remoteMem, (void *)dllPath, pathSize, NULL);

    // Build x64 shellcode: call LoadLibraryW(dllPath), then jmp back to origRip
    uint8_t shellcode[64] = {0};
    uintptr_t dllPathAddr = (uintptr_t)remoteMem;
    uintptr_t loadLibAddr = (uintptr_t)loadLibraryW;

    size_t si = 0;
    shellcode[si++] = 0x48; shellcode[si++] = 0x83; shellcode[si++] = 0xEC; shellcode[si++] = 0x28; // sub rsp, 0x28
    shellcode[si++] = 0x48; shellcode[si++] = 0xB9; memcpy(&shellcode[si], &dllPathAddr, 8); si += 8; // mov rcx, dllPath
    shellcode[si++] = 0x48; shellcode[si++] = 0xB8; memcpy(&shellcode[si], &loadLibAddr, 8); si += 8; // mov rax, LoadLibraryW
    shellcode[si++] = 0xFF; shellcode[si++] = 0xD0; // call rax
    shellcode[si++] = 0x48; shellcode[si++] = 0x83; shellcode[si++] = 0xC4; shellcode[si++] = 0x28; // add rsp, 0x28
    shellcode[si++] = 0x48; shellcode[si++] = 0xB8; // mov rax, <origRip placeholder>
    size_t origRipOffset = si; si += 8;
    shellcode[si++] = 0xFF; shellcode[si++] = 0xE0; // jmp rax

    // Find main thread
    HANDLE hMainThread = NULL;
    DWORD mainTid = 0;
    ULONGLONG earliestCreate = ULLONG_MAX;

    HANDLE hSnap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    if(hSnap != INVALID_HANDLE_VALUE)
    {
        THREADENTRY32 te = {sizeof(te)};
        if(Thread32First(hSnap, &te))
        {
            do
            {
                if(te.th32OwnerProcessID == pid)
                {
                    HANDLE hT = OpenThread(
                        THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT |
                        THREAD_SET_CONTEXT | THREAD_QUERY_INFORMATION,
                        FALSE, te.th32ThreadID);
                    if(hT)
                    {
                        FILETIME ct, et, kt, ut;
                        if(GetThreadTimes(hT, &ct, &et, &kt, &ut))
                        {
                            ULONGLONG ctime = ((ULONGLONG)ct.dwHighDateTime << 32) | ct.dwLowDateTime;
                            if(ctime < earliestCreate)
                            {
                                if(hMainThread) CloseHandle(hMainThread);
                                earliestCreate = ctime;
                                hMainThread = hT;
                                mainTid = te.th32ThreadID;
                            }
                            else
                            {
                                CloseHandle(hT);
                            }
                        }
                        else
                        {
                            CloseHandle(hT);
                        }
                    }
                }
            } while(Thread32Next(hSnap, &te));
        }
        CloseHandle(hSnap);
    }

    bool success = false;

    if(hMainThread)
    {
        printf("[*] Found main thread TID=%lu, suspending...\n", mainTid);
        SuspendThread(hMainThread);

        CONTEXT ctx = {};
        ctx.ContextFlags = CONTEXT_FULL;
        if(GetThreadContext(hMainThread, &ctx))
        {
            uintptr_t origRip = ctx.Rip;
            printf("[*] Original RIP=0x%llx\n", (unsigned long long)origRip);

            memcpy(&shellcode[origRipOffset], &origRip, 8);

            uintptr_t shellcodeAddr = (uintptr_t)remoteMem + pathSize;
            WriteProcessMemory(hProcess, (void *)shellcodeAddr, shellcode, shellcodeSize, NULL);

            ctx.Rip = shellcodeAddr;
            SetThreadContext(hMainThread, &ctx);
            ResumeThread(hMainThread);

            printf("[*] Shellcode injected, waiting for LoadLibrary...\n");

            for(int w = 0; w < 2000; w++)
            {
                Sleep(5);
                SuspendThread(hMainThread);
                CONTEXT ctx2 = {};
                ctx2.ContextFlags = CONTEXT_CONTROL;
                GetThreadContext(hMainThread, &ctx2);
                bool done = (ctx2.Rip == origRip ||
                             ctx2.Rip < (uintptr_t)remoteMem ||
                             ctx2.Rip >= (uintptr_t)remoteMem + totalSize);
                ResumeThread(hMainThread);
                if(done)
                {
                    printf("[+] Shellcode completed, DLL loaded\n");
                    success = true;
                    break;
                }
            }

            if(!success)
                printf("[!] Shellcode did not complete in time\n");
        }
        else
        {
            printf("[!] GetThreadContext failed: %lu\n", GetLastError());
            ResumeThread(hMainThread);
        }

        CloseHandle(hMainThread);
    }
    else
    {
        printf("[*] No main thread found, using CreateRemoteThread fallback...\n");
        HANDLE hThread = CreateRemoteThread(
            hProcess, NULL, 0,
            (LPTHREAD_START_ROUTINE)loadLibraryW, remoteMem, 0, NULL);
        if(hThread)
        {
            WaitForSingleObject(hThread, 10000);
            CloseHandle(hThread);
            success = true;
            printf("[+] CreateRemoteThread completed\n");
        }
        else
        {
            printf("[!] CreateRemoteThread failed: %lu\n", GetLastError());
        }
    }

    VirtualFreeEx(hProcess, remoteMem, 0, MEM_RELEASE);
    CloseHandle(hProcess);
    return success;
}

// ============================================================================
// Poll for new process creation
// ============================================================================
static DWORD WaitForProcess(const wchar_t *processName)
{
    printf("[*] Waiting for %ls to start...\n", processName);
    printf("[*] Please launch the game via the launcher now.\n\n");

    DWORD seenPids[256] = {0};
    int seenCount = 0;

    // Record existing instances
    HANDLE hSnap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if(hSnap != INVALID_HANDLE_VALUE)
    {
        PROCESSENTRY32W pe = {sizeof(pe)};
        if(Process32FirstW(hSnap, &pe))
        {
            do
            {
                if(_wcsicmp(pe.szExeFile, processName) == 0 && seenCount < 256)
                    seenPids[seenCount++] = pe.th32ProcessID;
            } while(Process32NextW(hSnap, &pe));
        }
        CloseHandle(hSnap);
    }

    // Poll for new instance
    while(true)
    {
        Sleep(50);

        hSnap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        if(hSnap == INVALID_HANDLE_VALUE) continue;

        PROCESSENTRY32W pe = {sizeof(pe)};
        if(Process32FirstW(hSnap, &pe))
        {
            do
            {
                if(_wcsicmp(pe.szExeFile, processName) == 0)
                {
                    bool seen = false;
                    for(int j = 0; j < seenCount; j++)
                    {
                        if(seenPids[j] == pe.th32ProcessID) { seen = true; break; }
                    }

                    if(!seen)
                    {
                        CloseHandle(hSnap);
                        printf("[+] Detected %ls (PID=%lu)\n", processName, pe.th32ProcessID);
                        return pe.th32ProcessID;
                    }
                }
            } while(Process32NextW(hSnap, &pe));
        }
        CloseHandle(hSnap);
    }
}

// ============================================================================
int wmain(int argc, wchar_t *argv[])
{
    printf("=== DComp Process Injector ===\n\n");

    if(argc < 2)
    {
        printf("Usage: process_injector.exe <dcomp.dll path> [process_name]\n");
        printf("Example: process_injector.exe F:\\dcomp\\dcomp.dll\n");
        return 1;
    }

    const wchar_t *dllPath = argv[1];
    const wchar_t *processName = argc >= 3 ? argv[2] : L"NRC-Win64-Shipping.exe";

    DWORD attrs = GetFileAttributesW(dllPath);
    if(attrs == INVALID_FILE_ATTRIBUTES)
    {
        printf("[!] DLL not found: %ls\n", dllPath);
        return 1;
    }

    printf("[*] DLL: %ls\n", dllPath);
    printf("[*] Target: %ls\n\n", processName);

    DWORD pid = WaitForProcess(processName);

    // Brief delay for process to load kernel32 minimally
    Sleep(100);

    printf("[*] Injecting into PID %lu...\n", pid);
    bool ok = InjectDLL(pid, dllPath);

    if(ok)
    {
        printf("\n[+] SUCCESS! dcomp.dll injected.\n");
        printf("[*] Open dcompui.exe to attach and capture frames (F12).\n");
    }
    else
    {
        printf("\n[!] FAILED to inject.\n");
    }

    printf("\nPress Enter to exit...\n");
    getwchar();
    return ok ? 0 : 1;
}
