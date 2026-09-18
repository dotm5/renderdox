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

#include <winsock2.h>
#include "core/core.h"
#include "generated/product_identity.h"
#include "hooks/hooks.h"
#include "os/os_specific.h"
#include "strings/string_utils.h"

#include <string>
#include <set>
#include <vector>
#include <mutex>
#include <atomic>
#include <MinHook.h>

extern uintptr_t FindRemoteDLL(HANDLE hProcess, DWORD pid, rdcstr libName);

typedef int(WSAAPI *PFN_WSASTARTUP)(__in WORD wVersionRequested, __out LPWSADATA lpWSAData);
typedef int(WSAAPI *PFN_WSACLEANUP)();

typedef BOOL(WINAPI *PFN_CREATE_PROCESS_A)(LPCSTR lpApplicationName, LPSTR lpCommandLine,
                                           LPSECURITY_ATTRIBUTES lpProcessAttributes,
                                           LPSECURITY_ATTRIBUTES lpThreadAttributes,
                                           BOOL bInheritHandles, DWORD dwCreationFlags,
                                           LPVOID lpEnvironment, LPCSTR lpCurrentDirectory,
                                           LPSTARTUPINFOA lpStartupInfo,
                                           LPPROCESS_INFORMATION lpProcessInformation);

typedef BOOL(WINAPI *PFN_CREATE_PROCESS_W)(LPCWSTR lpApplicationName, LPWSTR lpCommandLine,
                                           LPSECURITY_ATTRIBUTES lpProcessAttributes,
                                           LPSECURITY_ATTRIBUTES lpThreadAttributes,
                                           BOOL bInheritHandles, DWORD dwCreationFlags,
                                           LPVOID lpEnvironment, LPCWSTR lpCurrentDirectory,
                                           LPSTARTUPINFOW lpStartupInfo,
                                           LPPROCESS_INFORMATION lpProcessInformation);

typedef BOOL(WINAPI *PFN_CREATE_PROCESS_AS_USER_A)(
    HANDLE hToken, LPCSTR lpApplicationName, LPSTR lpCommandLine,
    LPSECURITY_ATTRIBUTES lpProcessAttributes, LPSECURITY_ATTRIBUTES lpThreadAttributes,
    BOOL bInheritHandles, DWORD dwCreationFlags, LPVOID lpEnvironment, LPCSTR lpCurrentDirectory,
    LPSTARTUPINFOA lpStartupInfo, LPPROCESS_INFORMATION lpProcessInformation);

typedef BOOL(WINAPI *PFN_CREATE_PROCESS_AS_USER_W)(
    HANDLE hToken, LPCWSTR lpApplicationName, LPWSTR lpCommandLine,
    LPSECURITY_ATTRIBUTES lpProcessAttributes, LPSECURITY_ATTRIBUTES lpThreadAttributes,
    BOOL bInheritHandles, DWORD dwCreationFlags, LPVOID lpEnvironment, LPCWSTR lpCurrentDirectory,
    LPSTARTUPINFOW lpStartupInfo, LPPROCESS_INFORMATION lpProcessInformation);

typedef BOOL(WINAPI *PFN_CREATE_PROCESS_WITH_LOGON_W)(LPCWSTR lpUsername, LPCWSTR lpDomain,
                                                      LPCWSTR lpPassword, DWORD dwLogonFlags,
                                                      LPCWSTR lpApplicationName, LPWSTR lpCommandLine,
                                                      DWORD dwCreationFlags, LPVOID lpEnvironment,
                                                      LPCWSTR lpCurrentDirectory,
                                                      LPSTARTUPINFOW lpStartupInfo,
                                                      LPPROCESS_INFORMATION lpProcessInformation);

typedef BOOL(WINAPI *PFN_CREATE_PROCESS_INTERNAL_A)(
    HANDLE hToken, LPCSTR lpApplicationName, LPSTR lpCommandLine,
    LPSECURITY_ATTRIBUTES lpProcessAttributes, LPSECURITY_ATTRIBUTES lpThreadAttributes,
    BOOL bInheritHandles, DWORD dwCreationFlags, LPVOID lpEnvironment, LPCSTR lpCurrentDirectory,
    LPSTARTUPINFOA lpStartupInfo, LPPROCESS_INFORMATION lpProcessInformation, PHANDLE hNewToken);

typedef BOOL(WINAPI *PFN_CREATE_PROCESS_INTERNAL_W)(
    HANDLE hToken, LPCWSTR lpApplicationName, LPWSTR lpCommandLine,
    LPSECURITY_ATTRIBUTES lpProcessAttributes, LPSECURITY_ATTRIBUTES lpThreadAttributes,
    BOOL bInheritHandles, DWORD dwCreationFlags, LPVOID lpEnvironment, LPCWSTR lpCurrentDirectory,
    LPSTARTUPINFOW lpStartupInfo, LPPROCESS_INFORMATION lpProcessInformation, PHANDLE hNewToken);

#ifndef NT_SUCCESS
#define NT_SUCCESS(Status) (((NTSTATUS)(Status)) >= 0)
#endif

#ifndef THREAD_CREATE_FLAGS_CREATE_SUSPENDED
#define THREAD_CREATE_FLAGS_CREATE_SUSPENDED 0x00000001
#endif

#ifndef PROCESS_CREATE_FLAGS_SUSPENDED
#define PROCESS_CREATE_FLAGS_SUSPENDED 0x00000200
#endif

typedef LONG NTSTATUS;

typedef struct _UNICODE_STRING_LOCAL
{
  USHORT Length;
  USHORT MaximumLength;
  PWSTR Buffer;
} UNICODE_STRING_LOCAL;

typedef struct _RTL_USER_PROCESS_PARAMETERS_LOCAL
{
  BYTE Reserved1[16];
  PVOID Reserved2[10];
  UNICODE_STRING_LOCAL ImagePathName;
  UNICODE_STRING_LOCAL CommandLine;
} RTL_USER_PROCESS_PARAMETERS_LOCAL;

typedef NTSTATUS(NTAPI *PFN_NT_CREATE_USER_PROCESS)(
    PHANDLE ProcessHandle, PHANDLE ThreadHandle, ACCESS_MASK ProcessDesiredAccess,
    ACCESS_MASK ThreadDesiredAccess, void *ProcessObjectAttributes, void *ThreadObjectAttributes,
    ULONG ProcessFlags, ULONG ThreadFlags, void *ProcessParameters, void *CreateInfo,
    void *AttributeList);

typedef NTSTATUS(NTAPI *PFN_NT_CREATE_THREAD_EX)(
    PHANDLE ThreadHandle, ACCESS_MASK DesiredAccess, void *ObjectAttributes,
    HANDLE ProcessHandle, PVOID StartRoutine, PVOID Argument, ULONG CreateFlags,
    ULONG_PTR ZeroBits, SIZE_T StackSize, SIZE_T MaximumStackSize, void *AttributeList);

typedef NTSTATUS(NTAPI *PFN_NT_CREATE_PROCESS_EX)(
    PHANDLE ProcessHandle, ACCESS_MASK DesiredAccess, void *ObjectAttributes,
    HANDLE ParentProcess, ULONG Flags, HANDLE SectionHandle, HANDLE DebugPort,
    HANDLE ExceptionPort, ULONG JobMemberLevel);

typedef NTSTATUS(NTAPI *PFN_NT_CREATE_PROCESS)(
    PHANDLE ProcessHandle, ACCESS_MASK DesiredAccess, void *ObjectAttributes,
    HANDLE ParentProcess, BOOLEAN InheritObjectTable, HANDLE SectionHandle,
    HANDLE DebugPort, HANDLE ExceptionPort);

typedef NTSTATUS(NTAPI *PFN_NT_CREATE_THREAD)(
    PHANDLE ThreadHandle, ACCESS_MASK DesiredAccess, void *ObjectAttributes,
    HANDLE ProcessHandle, void *ClientId, void *ThreadContext, void *InitialTeb,
    BOOLEAN CreateSuspended);

typedef HANDLE(WINAPI *PFN_CREATE_REMOTE_THREAD)(
    HANDLE hProcess, LPSECURITY_ATTRIBUTES lpThreadAttributes, SIZE_T dwStackSize,
    LPTHREAD_START_ROUTINE lpStartAddress, LPVOID lpParameter, DWORD dwCreationFlags,
    LPDWORD lpThreadId);

typedef HANDLE(WINAPI *PFN_CREATE_REMOTE_THREAD_EX)(
    HANDLE hProcess, LPSECURITY_ATTRIBUTES lpThreadAttributes, SIZE_T dwStackSize,
    LPTHREAD_START_ROUTINE lpStartAddress, LPVOID lpParameter, DWORD dwCreationFlags,
    LPPROC_THREAD_ATTRIBUTE_LIST lpAttributeList, LPDWORD lpThreadId);

typedef BOOL(WINAPI *PFN_CREATE_PROCESS_WITH_TOKEN_W)(
    HANDLE hToken, DWORD dwLogonFlags, LPCWSTR lpApplicationName, LPWSTR lpCommandLine,
    DWORD dwCreationFlags, LPVOID lpEnvironment, LPCWSTR lpCurrentDirectory,
    LPSTARTUPINFOW lpStartupInfo, LPPROCESS_INFORMATION lpProcessInformation);

typedef void(WINAPI *PFN_EXIT_PROCESS)(UINT uExitCode);
typedef NTSTATUS(NTAPI *PFN_NT_TERMINATE_PROCESS)(HANDLE ProcessHandle, NTSTATUS ExitStatus);

typedef struct _PROCESS_HANDLE_TABLE_ENTRY_INFO
{
  HANDLE HandleValue;
  ULONG_PTR HandleCount;
  ULONG_PTR PointerCount;
  ULONG GrantedAccess;
  ULONG ObjectTypeIndex;
  ULONG HandleAttributes;
  ULONG Reserved;
} PROCESS_HANDLE_TABLE_ENTRY_INFO;

typedef struct _PROCESS_HANDLE_SNAPSHOT_INFORMATION
{
  ULONG_PTR NumberOfHandles;
  ULONG_PTR Reserved;
  PROCESS_HANDLE_TABLE_ENTRY_INFO Handles[1];
} PROCESS_HANDLE_SNAPSHOT_INFORMATION;

static rdcstr GetExecutableBasename(LPCWSTR lpApplicationName, LPCWSTR lpCommandLine)
{
  const bool useApplicationName = lpApplicationName != NULL && lpApplicationName[0] != L'\0';
  const wchar_t *value = useApplicationName ? lpApplicationName : lpCommandLine;

  if(value == NULL)
    return "";

  while(*value == L' ' || *value == L'\t')
    value++;

  const wchar_t *begin = value;
  const wchar_t *end = value;

  if(*begin == L'"')
  {
    begin++;
    end = begin;
    while(*end != L'\0' && *end != L'"')
      end++;
  }
  else if(useApplicationName)
  {
    while(*end != L'\0')
      end++;
    while(end > begin && (end[-1] == L' ' || end[-1] == L'\t'))
      end--;
  }
  else
  {
    while(*end != L'\0' && *end != L' ' && *end != L'\t')
      end++;
  }

  if(end == begin)
    return "";

  return strlower(get_basename(StringFormat::Wide2UTF8(rdcwstr(begin, end - begin))));
}

static bool IsExcludedChildTool(LPCWSTR lpApplicationName, LPCWSTR lpCommandLine)
{
  const rdcstr executable = GetExecutableBasename(lpApplicationName, lpCommandLine);
  const char *excluded[] = {
      RDOC_UI_FILENAME,           RDOC_COMMAND_FILENAME,           RDOC_UI_STUB_FILENAME,
      RDOC_CANONICAL_UI_FILENAME, RDOC_CANONICAL_COMMAND_FILENAME, RDOC_CANONICAL_UI_STUB_FILENAME,
  };

  for(const char *filename : excluded)
    if(executable == filename)
      return true;

  return false;
}

#if ENABLED(ENABLE_UNIT_TESTS)

#include "catch/catch.hpp"

TEST_CASE("Win32 child-tool exclusion parses only the executable token", "[win32][process]")
{
  CHECK(IsExcludedChildTool(L"C:\\Tools\\dgcoreui.exe", NULL));
  CHECK(IsExcludedChildTool(L"C:\\TOOLS\\DGCORECMD.EXE", L"ignored.exe"));
  CHECK(IsExcludedChildTool(NULL, L"  \"C:\\Program Files\\DComp\\dgcorestub.exe\" --foo"));
  CHECK(IsExcludedChildTool(NULL, L"C:\\Tools\\dgcoreui.exe --foo"));

  CHECK_FALSE(
      IsExcludedChildTool(NULL, L"\"C:\\Games\\owned.exe\" --viewer C:\\Tools\\dgcoreui.exe"));
  CHECK_FALSE(IsExcludedChildTool(NULL, L"C:\\dgcoreui.exe\\owned.exe --foo"));
  CHECK_FALSE(IsExcludedChildTool(NULL, L"'C:\\Tools\\dgcoreui.exe' --foo"));
  CHECK_FALSE(IsExcludedChildTool(L"C:\\Games\\owned.exe", L"dgcoreui.exe --foo"));
}

#endif

static std::set<DWORD> s_HandledPids;
static std::mutex s_HandledPidsMutex;
static std::atomic<bool> s_ExitScanned(false);

class SysHook : LibraryHook
{
public:
  SysHook()
  {
    // we start with a refcount of 1 because we initialise WSA ourselves for our own sockets.
    m_WSARefCount = 1;
  }

  void RegisterHooks()
  {
#if defined(DCOMP_DIAGNOSTIC_DISABLE_WIN32_SYSTEM_HOOKS) && \
    DCOMP_DIAGNOSTIC_DISABLE_WIN32_SYSTEM_HOOKS
    if(Process::IsDCompDiagnosticTargetProcess())
    {
      RDCLOG("[DCOMP-AB] Win32 system hooks disabled in diagnostic target");
      return;
    }
#endif

    RDCLOG("Registering Win32 system hooks");

    bool disableWSAHooks = false;
#if defined(DCOMP_DIAGNOSTIC_DISABLE_WSA_HOOKS) && DCOMP_DIAGNOSTIC_DISABLE_WSA_HOOKS
    disableWSAHooks = Process::IsDCompDiagnosticTargetProcess();
#endif

    // register libraries that we care about. We don't need a callback when they are loaded
    LibraryHooks::RegisterLibraryHook("kernel32.dll", NULL);
    LibraryHooks::RegisterLibraryHook("kernelbase.dll", NULL);
    LibraryHooks::RegisterLibraryHook("advapi32.dll", NULL);
    LibraryHooks::RegisterLibraryHook("api-ms-win-core-processthreads-l1-1-0.dll", NULL);
    LibraryHooks::RegisterLibraryHook("api-ms-win-core-processthreads-l1-1-1.dll", NULL);
    LibraryHooks::RegisterLibraryHook("api-ms-win-core-processthreads-l1-1-2.dll", NULL);
    if(!disableWSAHooks)
      LibraryHooks::RegisterLibraryHook("ws2_32.dll", NULL);

    // we want to hook CreateProcess purely so that we can recursively insert our hooks (if we so
    // wish)
    CreateProcessA.Register("kernel32.dll", "CreateProcessA", CreateProcessA_hook);
    CreateProcessW.Register("kernel32.dll", "CreateProcessW", CreateProcessW_hook);

    Kernel32CreateProcessInternalA.Register("kernel32.dll", "CreateProcessInternalA",
                                            Kernel32CreateProcessInternalA_hook);
    Kernel32CreateProcessInternalW.Register("kernel32.dll", "CreateProcessInternalW",
                                            Kernel32CreateProcessInternalW_hook);

    KernelbaseCreateProcessA.Register("kernelbase.dll", "CreateProcessA", KernelbaseCreateProcessA_hook);
    KernelbaseCreateProcessW.Register("kernelbase.dll", "CreateProcessW", KernelbaseCreateProcessW_hook);

    KernelbaseCreateProcessInternalA.Register("kernelbase.dll", "CreateProcessInternalA",
                                              KernelbaseCreateProcessInternalA_hook);
    KernelbaseCreateProcessInternalW.Register("kernelbase.dll", "CreateProcessInternalW",
                                              KernelbaseCreateProcessInternalW_hook);

    NtCreateUserProcess.Register("ntdll.dll", "NtCreateUserProcess", NtCreateUserProcess_hook);
    NtCreateThreadEx.Register("ntdll.dll", "NtCreateThreadEx", NtCreateThreadEx_hook);
    NtCreateProcessEx.Register("ntdll.dll", "NtCreateProcessEx", NtCreateProcessEx_hook);
    NtCreateProcess.Register("ntdll.dll", "NtCreateProcess", NtCreateProcess_hook);
    NtCreateThread.Register("ntdll.dll", "NtCreateThread", NtCreateThread_hook);

    CreateProcessAsUserA.Register("advapi32.dll", "CreateProcessAsUserA", CreateProcessAsUserA_hook);
    CreateProcessAsUserW.Register("advapi32.dll", "CreateProcessAsUserW", CreateProcessAsUserW_hook);

    CreateProcessWithLogonW.Register("advapi32.dll", "CreateProcessWithLogonW",
                                     CreateProcessWithLogonW_hook);
    CreateProcessWithTokenW.Register("advapi32.dll", "CreateProcessWithTokenW",
                                     CreateProcessWithTokenW_hook);

    Kernel32CreateRemoteThread.Register("kernel32.dll", "CreateRemoteThread",
                                        Kernel32CreateRemoteThread_hook);
    Kernel32CreateRemoteThreadEx.Register("kernel32.dll", "CreateRemoteThreadEx",
                                          Kernel32CreateRemoteThreadEx_hook);
    // kernelbase.dll!CreateRemoteThreadEx is forwarded from kernel32.dll, no need to double hook

    NtTerminateProcess.Register("ntdll.dll", "NtTerminateProcess", NtTerminateProcess_hook);
    ExitProcess.Register("kernel32.dll", "ExitProcess", ExitProcess_hook);

    // handle API set exports if they exist. These don't really exist so we don't have to worry
    // about double hooking, and also they call into the 'real' implementation in kernelbase.dll
    API110CreateProcessA.Register("api-ms-win-core-processthreads-l1-1-0.dll", "CreateProcessA",
                                  API110CreateProcessA_hook);
    API110CreateProcessW.Register("api-ms-win-core-processthreads-l1-1-0.dll", "CreateProcessW",
                                  API110CreateProcessW_hook);
    API110CreateProcessAsUserW.Register("api-ms-win-core-processthreads-l1-1-0.dll",
                                        "CreateProcessAsUserW", API110CreateProcessAsUserW_hook);

    API111CreateProcessA.Register("api-ms-win-core-processthreads-l1-1-1.dll", "CreateProcessA",
                                  API111CreateProcessA_hook);
    API111CreateProcessW.Register("api-ms-win-core-processthreads-l1-1-1.dll", "CreateProcessW",
                                  API111CreateProcessW_hook);
    API111CreateProcessAsUserW.Register("api-ms-win-core-processthreads-l1-1-0.dll",
                                        "CreateProcessAsUserW", API111CreateProcessAsUserW_hook);

    API112CreateProcessA.Register("api-ms-win-core-processthreads-l1-1-2.dll", "CreateProcessA",
                                  API112CreateProcessA_hook);
    API112CreateProcessW.Register("api-ms-win-core-processthreads-l1-1-2.dll", "CreateProcessW",
                                  API112CreateProcessW_hook);
    API112CreateProcessAsUserW.Register("api-ms-win-core-processthreads-l1-1-0.dll",
                                        "CreateProcessAsUserW", API112CreateProcessAsUserW_hook);

    if(!disableWSAHooks)
    {
      WSAStartup.Register("ws2_32.dll", "WSAStartup", WSAStartup_hook);
      WSACleanup.Register("ws2_32.dll", "WSACleanup", WSACleanup_hook);
    }
    else
    {
      RDCLOG("[DCOMP-AB] Winsock hooks disabled in diagnostic target");
    }

    m_RecurseSlot = Threading::AllocateTLSSlot();
    Threading::SetTLSValue(m_RecurseSlot, NULL);

    // Start anti-unhook watchdog thread
    Threading::CloseThread(Threading::CreateThread([]() {
      HMODULE hNtdll = GetModuleHandleA("ntdll.dll");
      HMODULE hKernelbase = GetModuleHandleA("kernelbase.dll");
      void *pNtCreateUser = hNtdll ? (void *)GetProcAddress(hNtdll, "NtCreateUserProcess") : NULL;
      void *pNtCreateThread = hNtdll ? (void *)GetProcAddress(hNtdll, "NtCreateThreadEx") : NULL;
      void *pCreateProcInternal =
          hKernelbase ? (void *)GetProcAddress(hKernelbase, "CreateProcessInternalW") : NULL;

      RDCLOG("[SYS_WATCHDOG] Anti-unhook watchdog active in PID %u", GetCurrentProcessId());

      for(int iter = 0; iter < 600; iter++)
      {
        Threading::Sleep(50);

        if(pNtCreateUser)
        {
          uint8_t bytes[14] = {0};
          memcpy(bytes, pNtCreateUser, 14);
          bool isHooked = (bytes[0] == 0xE9 || (bytes[0] == 0xFF && bytes[1] == 0x25));
          if(!isHooked)
          {
            RDCLOG(
                "[SYS_WATCHDOG] NtCreateUserProcess was UNHOOKED in PID %u at iter %d! Bytes: "
                "%02X %02X %02X %02X %02X %02X. Re-hooking...",
                GetCurrentProcessId(), iter, bytes[0], bytes[1], bytes[2], bytes[3], bytes[4],
                bytes[5]);
            MH_EnableHook(pNtCreateUser);
          }
        }

        if(pNtCreateThread)
        {
          uint8_t bytes[14] = {0};
          memcpy(bytes, pNtCreateThread, 14);
          bool isHooked = (bytes[0] == 0xE9 || (bytes[0] == 0xFF && bytes[1] == 0x25));
          if(!isHooked)
          {
            RDCLOG(
                "[SYS_WATCHDOG] NtCreateThreadEx was UNHOOKED in PID %u at iter %d! Bytes: "
                "%02X %02X %02X %02X %02X %02X. Re-hooking...",
                GetCurrentProcessId(), iter, bytes[0], bytes[1], bytes[2], bytes[3], bytes[4],
                bytes[5]);
            MH_EnableHook(pNtCreateThread);
          }
        }

        if(pCreateProcInternal)
        {
          uint8_t bytes[14] = {0};
          memcpy(bytes, pCreateProcInternal, 14);
          bool isHooked = (bytes[0] == 0xE9 || (bytes[0] == 0xFF && bytes[1] == 0x25));
          if(!isHooked)
          {
            RDCLOG(
                "[SYS_WATCHDOG] CreateProcessInternalW was UNHOOKED in PID %u at iter %d! Bytes: "
                "%02X %02X %02X %02X %02X %02X. Re-hooking...",
                GetCurrentProcessId(), iter, bytes[0], bytes[1], bytes[2], bytes[3], bytes[4],
                bytes[5]);
            MH_EnableHook(pCreateProcInternal);
          }
        }
      }
    }));

    // Start child process handle sentinel thread (detects direct syscalls, unhooked calls, etc.)
    Threading::CloseThread(Threading::CreateThread([]() {
      DWORD myPid = GetCurrentProcessId();
      {
        std::lock_guard<std::mutex> lock(s_HandledPidsMutex);
        s_HandledPids.insert(myPid);
      }

      RDCLOG("[HANDLE_SENTINEL] Child handle sentinel active in PID %u (1ms polling)", myPid);

      for(int loop = 0; loop < 15000; loop++)
      {
        Threading::Sleep(1);

        if(!RenderDoc::Inst().GetCaptureOptions().hookIntoChildren)
          continue;

        ScanHandles();
      }
    }));
  }

  static void CheckAndInjectCandidateHandle(HANDLE hCandidate, DWORD myPid)
  {
    if(hCandidate == NULL || hCandidate == INVALID_HANDLE_VALUE)
      return;

    DWORD pid = GetProcessId(hCandidate);
    if(pid == 0 || pid == myPid)
      return;

    {
      std::lock_guard<std::mutex> lock(s_HandledPidsMutex);
      if(s_HandledPids.count(pid) > 0)
        return;
      s_HandledPids.insert(pid);
    }

    wchar_t exePath[MAX_PATH] = {0};
    DWORD pathLen = MAX_PATH;
    QueryFullProcessImageNameW(hCandidate, 0, exePath, &pathLen);

    RDCLOG("[HANDLE_SENTINEL] Discovered new child/target process PID %u (path: %ls) via handle %p in PID %u! Injecting dgcore...",
           pid, exePath, hCandidate, myPid);

    if(IsExcludedChildTool(exePath, NULL))
    {
      RDCLOG("[HANDLE_SENTINEL] Process PID %u is excluded child tool, skipping", pid);
      return;
    }

    CaptureOptions childOptions = RenderDoc::Inst().GetCaptureOptions();
#if defined(DCOMP_SINGLE_GENERATION_CHILD_HOOK) && DCOMP_SINGLE_GENERATION_CHILD_HOOK
    childOptions.hookIntoChildren = false;
#endif

    rdcpair<RDResult, uint32_t> res = Process::InjectIntoProcess(
        pid, {}, RenderDoc::Inst().GetCaptureFileTemplate(), childOptions, false, hCandidate);

    if(res.first == ResultCode::Succeeded)
    {
      RDCLOG("[HANDLE_SENTINEL] Successfully injected child PID %u via handle %p, ident=%u",
             pid, hCandidate, res.second);
      RenderDoc::Inst().AddChildProcess(pid, res.second);
    }
    else
    {
      RDCERR("[HANDLE_SENTINEL] Failed to inject child PID %u via handle %p: %s",
             pid, hCandidate, res.first.message.c_str());
    }
  }

  static void ScanHandles()
  {
    DWORD myPid = GetCurrentProcessId();

    typedef NTSTATUS(NTAPI * PFN_NT_QUERY_INFORMATION_PROCESS)(HANDLE, ULONG, PVOID, ULONG, PULONG);
    static PFN_NT_QUERY_INFORMATION_PROCESS pfnNtQueryInfoProcess =
        (PFN_NT_QUERY_INFORMATION_PROCESS)GetProcAddress(GetModuleHandleA("ntdll.dll"),
                                                         "NtQueryInformationProcess");

    bool usedQuery = false;
    if(pfnNtQueryInfoProcess)
    {
      static std::vector<uint8_t> handleBuf(256 * 1024);
      ULONG retLen = 0;
      NTSTATUS status = pfnNtQueryInfoProcess(GetCurrentProcess(), 51 /* ProcessHandleInformation */,
                                             handleBuf.data(), (ULONG)handleBuf.size(), &retLen);
      if(status == 0xC0000004 /* STATUS_INFO_LENGTH_MISMATCH */ && retLen > handleBuf.size())
      {
        handleBuf.resize(retLen + 4096);
        status = pfnNtQueryInfoProcess(GetCurrentProcess(), 51, handleBuf.data(),
                                      (ULONG)handleBuf.size(), &retLen);
      }

      if(NT_SUCCESS(status))
      {
        usedQuery = true;
        PROCESS_HANDLE_SNAPSHOT_INFORMATION *info =
            (PROCESS_HANDLE_SNAPSHOT_INFORMATION *)handleBuf.data();
        
        static int s_ScanCounter = 0;
        if(++s_ScanCounter % 1000 == 0)
        {
          RDCLOG("[HANDLE_SENTINEL] PID %u heartbeat: %u handles in table", myPid, (unsigned)info->NumberOfHandles);
        }

        for(ULONG_PTR i = 0; i < info->NumberOfHandles; i++)
        {
          CheckAndInjectCandidateHandle(info->Handles[i].HandleValue, myPid);
        }
      }
    }

    if(!usedQuery)
    {
      for(uintptr_t hVal = 4; hVal < 0x4000; hVal += 4)
      {
        CheckAndInjectCandidateHandle((HANDLE)hVal, myPid);
      }
    }
  }

private:
  static SysHook syshooks;

  int m_WSARefCount;
  uint64_t m_RecurseSlot = 0;

  bool CheckRecurse()
  {
    if(Threading::GetTLSValue(m_RecurseSlot) == NULL)
    {
      Threading::SetTLSValue(m_RecurseSlot, (void *)1);
      return false;
    }

    return true;
  }
  void EndRecurse() { Threading::SetTLSValue(m_RecurseSlot, NULL); }
  HookedFunction<PFN_CREATE_PROCESS_A> CreateProcessA;
  HookedFunction<PFN_CREATE_PROCESS_W> CreateProcessW;
  HookedFunction<PFN_CREATE_PROCESS_INTERNAL_A> Kernel32CreateProcessInternalA;
  HookedFunction<PFN_CREATE_PROCESS_INTERNAL_W> Kernel32CreateProcessInternalW;
  HookedFunction<PFN_CREATE_PROCESS_A> KernelbaseCreateProcessA;
  HookedFunction<PFN_CREATE_PROCESS_W> KernelbaseCreateProcessW;
  HookedFunction<PFN_CREATE_PROCESS_INTERNAL_A> KernelbaseCreateProcessInternalA;
  HookedFunction<PFN_CREATE_PROCESS_INTERNAL_W> KernelbaseCreateProcessInternalW;
  HookedFunction<PFN_NT_CREATE_USER_PROCESS> NtCreateUserProcess;
  HookedFunction<PFN_NT_CREATE_THREAD_EX> NtCreateThreadEx;
  HookedFunction<PFN_NT_CREATE_PROCESS_EX> NtCreateProcessEx;
  HookedFunction<PFN_NT_CREATE_PROCESS> NtCreateProcess;
  HookedFunction<PFN_NT_CREATE_THREAD> NtCreateThread;
  HookedFunction<PFN_CREATE_REMOTE_THREAD> Kernel32CreateRemoteThread;
  HookedFunction<PFN_CREATE_REMOTE_THREAD_EX> Kernel32CreateRemoteThreadEx;
  HookedFunction<PFN_CREATE_REMOTE_THREAD_EX> KernelbaseCreateRemoteThreadEx;
  HookedFunction<PFN_CREATE_PROCESS_WITH_TOKEN_W> CreateProcessWithTokenW;
  HookedFunction<PFN_EXIT_PROCESS> ExitProcess;
  HookedFunction<PFN_NT_TERMINATE_PROCESS> NtTerminateProcess;


  HookedFunction<PFN_CREATE_PROCESS_A> API110CreateProcessA;
  HookedFunction<PFN_CREATE_PROCESS_W> API110CreateProcessW;
  HookedFunction<PFN_CREATE_PROCESS_A> API111CreateProcessA;
  HookedFunction<PFN_CREATE_PROCESS_W> API111CreateProcessW;
  HookedFunction<PFN_CREATE_PROCESS_A> API112CreateProcessA;
  HookedFunction<PFN_CREATE_PROCESS_W> API112CreateProcessW;

  HookedFunction<PFN_CREATE_PROCESS_AS_USER_A> CreateProcessAsUserA;
  HookedFunction<PFN_CREATE_PROCESS_AS_USER_W> CreateProcessAsUserW;

  HookedFunction<PFN_CREATE_PROCESS_AS_USER_W> API110CreateProcessAsUserW;
  HookedFunction<PFN_CREATE_PROCESS_AS_USER_W> API111CreateProcessAsUserW;
  HookedFunction<PFN_CREATE_PROCESS_AS_USER_W> API112CreateProcessAsUserW;

  HookedFunction<PFN_CREATE_PROCESS_WITH_LOGON_W> CreateProcessWithLogonW;

  HookedFunction<PFN_WSASTARTUP> WSAStartup;
  HookedFunction<PFN_WSACLEANUP> WSACleanup;

  static int WSAAPI WSAStartup_hook(WORD wVersionRequested, LPWSADATA lpWSAData)
  {
    int ret = syshooks.WSAStartup()(wVersionRequested, lpWSAData);

    // only increment the refcount if the function succeeded
    if(ret == 0)
      syshooks.m_WSARefCount++;

    return ret;
  }

  static int WSAAPI WSACleanup_hook()
  {
    // don't let the application murder our sockets with a mismatched WSACleanup() call
    if(syshooks.m_WSARefCount == 1)
    {
      RDCLOG("WSACleanup called with (to the application) no WSAStartup! Ignoring.");
      SetLastError(WSANOTINITIALISED);
      return SOCKET_ERROR;
    }

    // decrement refcount and call the real thing
    syshooks.m_WSARefCount--;
    return syshooks.WSACleanup()();
  }

  static BOOL WINAPI
  Hooked_CreateProcess(const char *entryPoint,
                       std::function<BOOL(DWORD dwCreationFlags, LPVOID pEnvironment,
                                          LPPROCESS_INFORMATION lpProcessInformation)>
                           realFunc,
                       DWORD dwCreationFlags, bool inject, LPVOID pEnvironment,
                       LPPROCESS_INFORMATION lpProcessInformation)
  {
#if (defined(DCOMP_DIAGNOSTIC_PASSTHROUGH_NONINJECTED_CHILDREN) && \
     DCOMP_DIAGNOSTIC_PASSTHROUGH_NONINJECTED_CHILDREN) ||               \
    (defined(DCOMP_DIAGNOSTIC_PASSTHROUGH_ALL_NONINJECTED_CHILDREN) &&   \
     DCOMP_DIAGNOSTIC_PASSTHROUGH_ALL_NONINJECTED_CHILDREN)
    const bool passThroughAll =
#if defined(DCOMP_DIAGNOSTIC_PASSTHROUGH_ALL_NONINJECTED_CHILDREN) && \
    DCOMP_DIAGNOSTIC_PASSTHROUGH_ALL_NONINJECTED_CHILDREN
        true;
#else
        false;
#endif
    if(!inject && (passThroughAll || Process::IsDCompDiagnosticTargetProcess()))
    {
      RDCLOG("[DCOMP-AB] passing through %s flags=0x%08x", entryPoint, dwCreationFlags);
      return realFunc(dwCreationFlags, pEnvironment, lpProcessInformation);
    }
#endif

    bool recursive = syshooks.CheckRecurse();

    RDCLOG("[SYS_HOOK] Intercepted %s: flags=0x%08x, inject=%d, recurse=%d", entryPoint,
           dwCreationFlags, (int)inject, (int)recursive);

    if(recursive)
      return realFunc(dwCreationFlags, pEnvironment, lpProcessInformation);

    PROCESS_INFORMATION dummy;
    RDCEraseEl(dummy);

    // not sure if this is valid, but I need the PID so I'll fill in my own struct to ensure that.
    if(lpProcessInformation == NULL)
    {
      lpProcessInformation = &dummy;
    }
    else
    {
      *lpProcessInformation = dummy;
    }

    bool resume = (dwCreationFlags & CREATE_SUSPENDED) == 0;
    dwCreationFlags |= CREATE_SUSPENDED;

    rdcstr envA;
    std::wstring envW;
    void *env = pEnvironment;
    const bool unicode_env = (dwCreationFlags & CREATE_UNICODE_ENVIRONMENT) != 0;

// give ourselves access to the ANSI version if we want it
#undef GetEnvironmentStrings

    static_assert(std::is_same<decltype(GetEnvironmentStrings()), char *>::value,
                  "GetEnvironmentStrings macro is messing up");

    // if we have no existing environment, take it from the current env strings that will be used
    // implicitly so we can patch it
    if(!env)
      env = unicode_env ? (void *)GetEnvironmentStringsW() : (void *)GetEnvironmentStrings();

    // patch the environment string to remove vulkan layer variable
    if(unicode_env)
    {
      const wchar_t *cur = (const wchar_t *)env;

      // loop over every A=B\0 string
      while(*cur)
      {
        // if it is NOT the vulkan env var, append it to our block
        if(wcsncmp(cur, CONCAT(L, RENDERDOC_VULKAN_LAYER_VAR), sizeof(RENDERDOC_VULKAN_LAYER_VAR) - 1))
        {
          envW += cur;
          envW.push_back(L'\0');
        }

        cur += wcslen(cur) + 1;
      }

#if defined(DCOMP_DIAGNOSTIC_VARIANT_ID) && DCOMP_DIAGNOSTIC_VARIANT_ID != 0
      if(inject && !Process::IsDCompDiagnosticTargetProcess())
      {
        envW += L"DCOMP_DIAGNOSTIC_TARGET_PROCESS=1";
        envW.push_back(L'\0');
      }
#endif

      // append the extra \0 to terminate the block
      envW.push_back(L'\0');

      // use the patched block
      env = (void *)envW.data();
    }
    else
    {
      const char *cur = (const char *)env;

      // loop over every A=B\0 string
      while(*cur)
      {
        // if it is NOT the vulkan env var, append it to our block
        if(strncmp(cur, RENDERDOC_VULKAN_LAYER_VAR, sizeof(RENDERDOC_VULKAN_LAYER_VAR) - 1))
        {
          envA += cur;
          envA.push_back('\0');
        }

        cur += strlen(cur) + 1;
      }

#if defined(DCOMP_DIAGNOSTIC_VARIANT_ID) && DCOMP_DIAGNOSTIC_VARIANT_ID != 0
      if(inject && !Process::IsDCompDiagnosticTargetProcess())
      {
        envA += "DCOMP_DIAGNOSTIC_TARGET_PROCESS=1";
        envA.push_back('\0');
      }
#endif

      // append the extra \0 to terminate the block
      envA.push_back('\0');

      // use the patched block
      env = (void *)envA.data();
    }

    RDCDEBUG("Calling real %s", entryPoint);
    BOOL ret = realFunc(dwCreationFlags, env, lpProcessInformation);
    RDCDEBUG("Called real %s", entryPoint);

    if(ret && inject)
    {
      RDCLOG("[SYS_HOOK] %s successfully created child PID %u, handle %p, injecting dgcore...",
             entryPoint, lpProcessInformation ? lpProcessInformation->dwProcessId : 0,
             lpProcessInformation ? lpProcessInformation->hProcess : NULL);

      // inherit logfile and capture options
      CaptureOptions childOptions = RenderDoc::Inst().GetCaptureOptions();

#if defined(DCOMP_SINGLE_GENERATION_CHILD_HOOK) && DCOMP_SINGLE_GENERATION_CHILD_HOOK
      // The current process was selected for capture, but its helper processes are not. This
      // preserves launcher -> game injection without recursively altering login or utility children.
      childOptions.hookIntoChildren = false;
      RDCDEBUG("Injecting child with further child hooks disabled");
#endif

      rdcpair<RDResult, uint32_t> res = Process::InjectIntoProcess(
          lpProcessInformation->dwProcessId, {}, RenderDoc::Inst().GetCaptureFileTemplate(),
          childOptions, false, lpProcessInformation->hProcess);

      if(res.first == ResultCode::Succeeded)
        RenderDoc::Inst().AddChildProcess((uint32_t)lpProcessInformation->dwProcessId, res.second);
      else
        RDCERR("[SYS_HOOK] Failed to inject into child PID %u: %s",
               lpProcessInformation ? lpProcessInformation->dwProcessId : 0,
               res.first.message.c_str());
    }
    else if(ret && !inject)
    {
      RDCLOG("[SYS_HOOK] %s created child PID %u, but NOT injecting (inject=false)",
             entryPoint, lpProcessInformation ? lpProcessInformation->dwProcessId : 0);
    }
    else if(!ret)
    {
      RDCLOG("[SYS_HOOK] %s realFunc failed, err=%u", entryPoint, GetLastError());
    }

    if(resume)
    {
      ResumeThread(lpProcessInformation->hThread);
    }

    // ensure we clean up after ourselves
    if(dummy.dwProcessId != 0)
    {
      CloseHandle(dummy.hProcess);
      CloseHandle(dummy.hThread);
    }

    syshooks.EndRecurse();

    return ret;
  }

  static bool ShouldInject(LPCWSTR lpApplicationName, LPCWSTR lpCommandLine)
  {
    if(!RenderDoc::Inst().GetCaptureOptions().hookIntoChildren)
    {
      RDCLOG("[SYS_HOOK] ShouldInject=false (hookIntoChildren=0) for app='%ls', cmd='%ls'",
             lpApplicationName ? lpApplicationName : L"(null)",
             lpCommandLine ? lpCommandLine : L"(null)");
      return false;
    }

    if(IsExcludedChildTool(lpApplicationName, lpCommandLine))
    {
      RDCLOG("[SYS_HOOK] ShouldInject=false (excluded) for app='%ls', cmd='%ls'",
             lpApplicationName ? lpApplicationName : L"(null)",
             lpCommandLine ? lpCommandLine : L"(null)");
      return false;
    }

    RDCLOG("[SYS_HOOK] ShouldInject=true for app='%ls', cmd='%ls'",
           lpApplicationName ? lpApplicationName : L"(null)",
           lpCommandLine ? lpCommandLine : L"(null)");
    return true;
  }

  static bool ShouldInject(LPCSTR lpApplicationName, LPCSTR lpCommandLine)
  {
    if(!RenderDoc::Inst().GetCaptureOptions().hookIntoChildren)
      return false;

    return ShouldInject(lpApplicationName ? StringFormat::UTF82Wide(lpApplicationName).c_str() : NULL,
                        lpCommandLine ? StringFormat::UTF82Wide(lpCommandLine).c_str() : NULL);
  }

  static BOOL WINAPI CreateProcessA_hook(
      __in_opt LPCSTR lpApplicationName, __inout_opt LPSTR lpCommandLine,
      __in_opt LPSECURITY_ATTRIBUTES lpProcessAttributes,
      __in_opt LPSECURITY_ATTRIBUTES lpThreadAttributes, __in BOOL bInheritHandles,
      __in DWORD dwCreationFlags, __in_opt LPVOID lpEnvironment, __in_opt LPCSTR lpCurrentDirectory,
      __in LPSTARTUPINFOA lpStartupInfo, __out LPPROCESS_INFORMATION lpProcessInformation)
  {
    return Hooked_CreateProcess(
        "CreateProcessA",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.CreateProcessA()(lpApplicationName, lpCommandLine, lpProcessAttributes,
                                           lpThreadAttributes, bInheritHandles, flags, env,
                                           lpCurrentDirectory, lpStartupInfo, pi);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static BOOL WINAPI CreateProcessW_hook(__in_opt LPCWSTR lpApplicationName,
                                         __inout_opt LPWSTR lpCommandLine,
                                         __in_opt LPSECURITY_ATTRIBUTES lpProcessAttributes,
                                         __in_opt LPSECURITY_ATTRIBUTES lpThreadAttributes,
                                         __in BOOL bInheritHandles, __in DWORD dwCreationFlags,
                                         __in_opt LPVOID lpEnvironment,
                                         __in_opt LPCWSTR lpCurrentDirectory,
                                         __in LPSTARTUPINFOW lpStartupInfo,
                                         __out LPPROCESS_INFORMATION lpProcessInformation)
  {
    return Hooked_CreateProcess(
        "CreateProcessW",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.CreateProcessW()(lpApplicationName, lpCommandLine, lpProcessAttributes,
                                           lpThreadAttributes, bInheritHandles, flags, env,
                                           lpCurrentDirectory, lpStartupInfo, pi);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static BOOL WINAPI KernelbaseCreateProcessA_hook(
      __in_opt LPCSTR lpApplicationName, __inout_opt LPSTR lpCommandLine,
      __in_opt LPSECURITY_ATTRIBUTES lpProcessAttributes,
      __in_opt LPSECURITY_ATTRIBUTES lpThreadAttributes, __in BOOL bInheritHandles,
      __in DWORD dwCreationFlags, __in_opt LPVOID lpEnvironment, __in_opt LPCSTR lpCurrentDirectory,
      __in LPSTARTUPINFOA lpStartupInfo, __out LPPROCESS_INFORMATION lpProcessInformation)
  {
    return Hooked_CreateProcess(
        "kernelbase!CreateProcessA",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.KernelbaseCreateProcessA()(
              lpApplicationName, lpCommandLine, lpProcessAttributes, lpThreadAttributes,
              bInheritHandles, flags, env, lpCurrentDirectory, lpStartupInfo, pi);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static BOOL WINAPI KernelbaseCreateProcessW_hook(
      __in_opt LPCWSTR lpApplicationName, __inout_opt LPWSTR lpCommandLine,
      __in_opt LPSECURITY_ATTRIBUTES lpProcessAttributes,
      __in_opt LPSECURITY_ATTRIBUTES lpThreadAttributes, __in BOOL bInheritHandles,
      __in DWORD dwCreationFlags, __in_opt LPVOID lpEnvironment,
      __in_opt LPCWSTR lpCurrentDirectory, __in LPSTARTUPINFOW lpStartupInfo,
      __out LPPROCESS_INFORMATION lpProcessInformation)
  {
    return Hooked_CreateProcess(
        "kernelbase!CreateProcessW",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.KernelbaseCreateProcessW()(
              lpApplicationName, lpCommandLine, lpProcessAttributes, lpThreadAttributes,
              bInheritHandles, flags, env, lpCurrentDirectory, lpStartupInfo, pi);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static BOOL WINAPI Kernel32CreateProcessInternalA_hook(
      HANDLE hToken, LPCSTR lpApplicationName, LPSTR lpCommandLine,
      LPSECURITY_ATTRIBUTES lpProcessAttributes, LPSECURITY_ATTRIBUTES lpThreadAttributes,
      BOOL bInheritHandles, DWORD dwCreationFlags, LPVOID lpEnvironment,
      LPCSTR lpCurrentDirectory, LPSTARTUPINFOA lpStartupInfo,
      LPPROCESS_INFORMATION lpProcessInformation, PHANDLE hNewToken)
  {
    return Hooked_CreateProcess(
        "kernel32!CreateProcessInternalA",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.Kernel32CreateProcessInternalA()(
              hToken, lpApplicationName, lpCommandLine, lpProcessAttributes, lpThreadAttributes,
              bInheritHandles, flags, env, lpCurrentDirectory, lpStartupInfo, pi, hNewToken);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static BOOL WINAPI Kernel32CreateProcessInternalW_hook(
      HANDLE hToken, LPCWSTR lpApplicationName, LPWSTR lpCommandLine,
      LPSECURITY_ATTRIBUTES lpProcessAttributes, LPSECURITY_ATTRIBUTES lpThreadAttributes,
      BOOL bInheritHandles, DWORD dwCreationFlags, LPVOID lpEnvironment,
      LPCWSTR lpCurrentDirectory, LPSTARTUPINFOW lpStartupInfo,
      LPPROCESS_INFORMATION lpProcessInformation, PHANDLE hNewToken)
  {
    return Hooked_CreateProcess(
        "kernel32!CreateProcessInternalW",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.Kernel32CreateProcessInternalW()(
              hToken, lpApplicationName, lpCommandLine, lpProcessAttributes, lpThreadAttributes,
              bInheritHandles, flags, env, lpCurrentDirectory, lpStartupInfo, pi, hNewToken);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static BOOL WINAPI KernelbaseCreateProcessInternalA_hook(
      HANDLE hToken, LPCSTR lpApplicationName, LPSTR lpCommandLine,
      LPSECURITY_ATTRIBUTES lpProcessAttributes, LPSECURITY_ATTRIBUTES lpThreadAttributes,
      BOOL bInheritHandles, DWORD dwCreationFlags, LPVOID lpEnvironment,
      LPCSTR lpCurrentDirectory, LPSTARTUPINFOA lpStartupInfo,
      LPPROCESS_INFORMATION lpProcessInformation, PHANDLE hNewToken)
  {
    return Hooked_CreateProcess(
        "kernelbase!CreateProcessInternalA",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.KernelbaseCreateProcessInternalA()(
              hToken, lpApplicationName, lpCommandLine, lpProcessAttributes, lpThreadAttributes,
              bInheritHandles, flags, env, lpCurrentDirectory, lpStartupInfo, pi, hNewToken);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static BOOL WINAPI KernelbaseCreateProcessInternalW_hook(
      HANDLE hToken, LPCWSTR lpApplicationName, LPWSTR lpCommandLine,
      LPSECURITY_ATTRIBUTES lpProcessAttributes, LPSECURITY_ATTRIBUTES lpThreadAttributes,
      BOOL bInheritHandles, DWORD dwCreationFlags, LPVOID lpEnvironment,
      LPCWSTR lpCurrentDirectory, LPSTARTUPINFOW lpStartupInfo,
      LPPROCESS_INFORMATION lpProcessInformation, PHANDLE hNewToken)
  {
    return Hooked_CreateProcess(
        "kernelbase!CreateProcessInternalW",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.KernelbaseCreateProcessInternalW()(
              hToken, lpApplicationName, lpCommandLine, lpProcessAttributes, lpThreadAttributes,
              bInheritHandles, flags, env, lpCurrentDirectory, lpStartupInfo, pi, hNewToken);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static NTSTATUS NTAPI NtCreateUserProcess_hook(
      PHANDLE ProcessHandle, PHANDLE ThreadHandle, ACCESS_MASK ProcessDesiredAccess,
      ACCESS_MASK ThreadDesiredAccess, void *ProcessObjectAttributes,
      void *ThreadObjectAttributes, ULONG ProcessFlags, ULONG ThreadFlags,
      void *ProcessParameters, void *CreateInfo, void *AttributeList)
  {
    bool recursive = syshooks.CheckRecurse();

    if(recursive)
    {
      return syshooks.NtCreateUserProcess()(
          ProcessHandle, ThreadHandle, ProcessDesiredAccess, ThreadDesiredAccess,
          ProcessObjectAttributes, ThreadObjectAttributes, ProcessFlags, ThreadFlags,
          ProcessParameters, CreateInfo, AttributeList);
    }

    std::wstring appPathStr;
    std::wstring cmdLineStr;
    if(ProcessParameters)
    {
      RTL_USER_PROCESS_PARAMETERS_LOCAL *params =
          (RTL_USER_PROCESS_PARAMETERS_LOCAL *)ProcessParameters;
      if(params->ImagePathName.Buffer && params->ImagePathName.Length > 0)
        appPathStr.assign(params->ImagePathName.Buffer, params->ImagePathName.Length / sizeof(wchar_t));
      if(params->CommandLine.Buffer && params->CommandLine.Length > 0)
        cmdLineStr.assign(params->CommandLine.Buffer, params->CommandLine.Length / sizeof(wchar_t));
    }
    const wchar_t *appPath = appPathStr.c_str();
    const wchar_t *cmdLine = cmdLineStr.c_str();

    RDCLOG("[SYS_HOOK] Intercepted ntdll!NtCreateUserProcess directly! app='%ls', cmd='%ls', ProcessFlags=0x%08x, ThreadFlags=0x%08x",
           appPath, cmdLine, ProcessFlags, ThreadFlags);

    bool inject = ShouldInject(appPath, cmdLine);

    bool resume = false;
    if(inject)
    {
      if((ThreadFlags & THREAD_CREATE_FLAGS_CREATE_SUSPENDED) == 0)
      {
        resume = true;
        ThreadFlags |= THREAD_CREATE_FLAGS_CREATE_SUSPENDED;
      }
      ProcessDesiredAccess |= PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION |
                              PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ | SYNCHRONIZE;
      ThreadDesiredAccess |= THREAD_SUSPEND_RESUME | THREAD_QUERY_INFORMATION;
    }

    NTSTATUS status = syshooks.NtCreateUserProcess()(
        ProcessHandle, ThreadHandle, ProcessDesiredAccess, ThreadDesiredAccess,
        ProcessObjectAttributes, ThreadObjectAttributes, ProcessFlags, ThreadFlags,
        ProcessParameters, CreateInfo, AttributeList);

    if(NT_SUCCESS(status) && inject && ProcessHandle && *ProcessHandle)
    {
      DWORD pid = GetProcessId(*ProcessHandle);
      RDCLOG("[SYS_HOOK] NtCreateUserProcess successfully created child PID %u, handle %p, status 0x%08x. Injecting dgcore...",
             pid, *ProcessHandle, (uint32_t)status);

      CaptureOptions childOptions = RenderDoc::Inst().GetCaptureOptions();
#if defined(DCOMP_SINGLE_GENERATION_CHILD_HOOK) && DCOMP_SINGLE_GENERATION_CHILD_HOOK
      childOptions.hookIntoChildren = false;
      RDCDEBUG("Injecting child with further child hooks disabled");
#endif

      rdcpair<RDResult, uint32_t> res = Process::InjectIntoProcess(
          pid, {}, RenderDoc::Inst().GetCaptureFileTemplate(), childOptions, false, *ProcessHandle);

      if(res.first == ResultCode::Succeeded)
      {
        RDCLOG("[SYS_HOOK] NtCreateUserProcess child PID %u injected successfully, ident=%u", pid, res.second);
        RenderDoc::Inst().AddChildProcess(pid, res.second);
      }
      else
      {
        RDCERR("[SYS_HOOK] NtCreateUserProcess failed to inject child PID %u: %s", pid,
               res.first.message.c_str());
      }
    }
    else if(NT_SUCCESS(status) && !inject)
    {
      DWORD pid = (ProcessHandle && *ProcessHandle) ? GetProcessId(*ProcessHandle) : 0;
      RDCLOG("[SYS_HOOK] NtCreateUserProcess created child PID %u, but NOT injecting (inject=false)", pid);
    }
    else if(!NT_SUCCESS(status))
    {
      RDCLOG("[SYS_HOOK] NtCreateUserProcess failed, NTSTATUS=0x%08x", (uint32_t)status);
    }

    if(resume && ThreadHandle && *ThreadHandle)
    {
      ResumeThread(*ThreadHandle);
    }

    syshooks.EndRecurse();
    return status;
  }

  static NTSTATUS NTAPI NtCreateProcessEx_hook(
      PHANDLE ProcessHandle, ACCESS_MASK DesiredAccess, void *ObjectAttributes,
      HANDLE ParentProcess, ULONG Flags, HANDLE SectionHandle, HANDLE DebugPort,
      HANDLE ExceptionPort, ULONG JobMemberLevel)
  {
    bool recursive = syshooks.CheckRecurse();
    if(recursive)
    {
      return syshooks.NtCreateProcessEx()(
          ProcessHandle, DesiredAccess, ObjectAttributes, ParentProcess, Flags,
          SectionHandle, DebugPort, ExceptionPort, JobMemberLevel);
    }

    DesiredAccess |= PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION |
                     PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ | SYNCHRONIZE;

    NTSTATUS status = syshooks.NtCreateProcessEx()(
        ProcessHandle, DesiredAccess, ObjectAttributes, ParentProcess, Flags,
        SectionHandle, DebugPort, ExceptionPort, JobMemberLevel);

    if(NT_SUCCESS(status) && ProcessHandle && *ProcessHandle)
    {
      DWORD pid = GetProcessId(*ProcessHandle);
      RDCLOG("[SYS_HOOK] NtCreateProcessEx created child PID %u, handle %p, status 0x%08x",
             pid, *ProcessHandle, (uint32_t)status);
    }

    syshooks.EndRecurse();
    return status;
  }

  static NTSTATUS NTAPI NtCreateThreadEx_hook(
      PHANDLE ThreadHandle, ACCESS_MASK DesiredAccess, void *ObjectAttributes,
      HANDLE ProcessHandle, PVOID StartRoutine, PVOID Argument, ULONG CreateFlags,
      ULONG_PTR ZeroBits, SIZE_T StackSize, SIZE_T MaximumStackSize, void *AttributeList)
  {
    bool recursive = syshooks.CheckRecurse();
    if(recursive)
    {
      return syshooks.NtCreateThreadEx()(
          ThreadHandle, DesiredAccess, ObjectAttributes, ProcessHandle, StartRoutine,
          Argument, CreateFlags, ZeroBits, StackSize, MaximumStackSize, AttributeList);
    }

    DWORD targetPid = 0;
    if(ProcessHandle != NULL && ProcessHandle != GetCurrentProcess())
    {
      targetPid = GetProcessId(ProcessHandle);
    }

    if(targetPid != 0 && targetPid != GetCurrentProcessId())
    {
      RDCLOG("[SYS_HOOK] NtCreateThreadEx called for REMOTE process PID %u! CreateFlags=0x%08x",
             targetPid, CreateFlags);

      bool resume = false;
      if((CreateFlags & THREAD_CREATE_FLAGS_CREATE_SUSPENDED) == 0)
      {
        resume = true;
        CreateFlags |= THREAD_CREATE_FLAGS_CREATE_SUSPENDED;
      }

      NTSTATUS status = syshooks.NtCreateThreadEx()(
          ThreadHandle, DesiredAccess, ObjectAttributes, ProcessHandle, StartRoutine,
          Argument, CreateFlags, ZeroBits, StackSize, MaximumStackSize, AttributeList);

      if(NT_SUCCESS(status) && RenderDoc::Inst().GetCaptureOptions().hookIntoChildren)
      {
        RDCLOG("[SYS_HOOK] Remote thread created in PID %u, injecting dgcore...", targetPid);
        CaptureOptions childOptions = RenderDoc::Inst().GetCaptureOptions();
#if defined(DCOMP_SINGLE_GENERATION_CHILD_HOOK) && DCOMP_SINGLE_GENERATION_CHILD_HOOK
        childOptions.hookIntoChildren = false;
#endif
        rdcpair<RDResult, uint32_t> res = Process::InjectIntoProcess(
            targetPid, {}, RenderDoc::Inst().GetCaptureFileTemplate(), childOptions, false, ProcessHandle);

        if(res.first == ResultCode::Succeeded)
        {
          RDCLOG("[SYS_HOOK] PID %u injected successfully via NtCreateThreadEx, ident=%u", targetPid, res.second);
          RenderDoc::Inst().AddChildProcess(targetPid, res.second);
        }
        else
        {
          RDCERR("[SYS_HOOK] Failed to inject PID %u via NtCreateThreadEx: %s", targetPid, res.first.message.c_str());
        }
      }

      if(resume && ThreadHandle && *ThreadHandle)
      {
        ResumeThread(*ThreadHandle);
      }

      syshooks.EndRecurse();
      return status;
    }

    NTSTATUS status = syshooks.NtCreateThreadEx()(
        ThreadHandle, DesiredAccess, ObjectAttributes, ProcessHandle, StartRoutine,
        Argument, CreateFlags, ZeroBits, StackSize, MaximumStackSize, AttributeList);

    syshooks.EndRecurse();
    return status;
  }

  static NTSTATUS NTAPI NtCreateProcess_hook(
      PHANDLE ProcessHandle, ACCESS_MASK DesiredAccess, void *ObjectAttributes,
      HANDLE ParentProcess, BOOLEAN InheritObjectTable, HANDLE SectionHandle,
      HANDLE DebugPort, HANDLE ExceptionPort)
  {
    bool recursive = syshooks.CheckRecurse();
    if(recursive)
    {
      return syshooks.NtCreateProcess()(ProcessHandle, DesiredAccess, ObjectAttributes,
                                        ParentProcess, InheritObjectTable, SectionHandle,
                                        DebugPort, ExceptionPort);
    }

    DesiredAccess |= PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION |
                     PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ | SYNCHRONIZE;

    NTSTATUS status = syshooks.NtCreateProcess()(ProcessHandle, DesiredAccess, ObjectAttributes,
                                                ParentProcess, InheritObjectTable, SectionHandle,
                                                DebugPort, ExceptionPort);

    if(NT_SUCCESS(status) && ProcessHandle && *ProcessHandle)
    {
      DWORD pid = GetProcessId(*ProcessHandle);
      RDCLOG("[SYS_HOOK] NtCreateProcess created child PID %u, handle %p, status 0x%08x",
             pid, *ProcessHandle, (uint32_t)status);
    }

    syshooks.EndRecurse();
    return status;
  }

  static NTSTATUS NTAPI NtCreateThread_hook(
      PHANDLE ThreadHandle, ACCESS_MASK DesiredAccess, void *ObjectAttributes,
      HANDLE ProcessHandle, void *ClientId, void *ThreadContext, void *InitialTeb,
      BOOLEAN CreateSuspended)
  {
    bool recursive = syshooks.CheckRecurse();
    if(recursive)
    {
      return syshooks.NtCreateThread()(ThreadHandle, DesiredAccess, ObjectAttributes,
                                       ProcessHandle, ClientId, ThreadContext, InitialTeb,
                                       CreateSuspended);
    }

    DWORD targetPid = 0;
    if(ProcessHandle != NULL && ProcessHandle != GetCurrentProcess())
      targetPid = GetProcessId(ProcessHandle);

    if(targetPid != 0 && targetPid != GetCurrentProcessId())
    {
      RDCLOG("[SYS_HOOK] NtCreateThread called for REMOTE process PID %u! CreateSuspended=%d",
             targetPid, (int)CreateSuspended);

      BOOLEAN forceSuspended = TRUE;
      NTSTATUS status = syshooks.NtCreateThread()(
          ThreadHandle, DesiredAccess, ObjectAttributes, ProcessHandle, ClientId,
          ThreadContext, InitialTeb, forceSuspended);

      if(NT_SUCCESS(status) && RenderDoc::Inst().GetCaptureOptions().hookIntoChildren)
      {
        RDCLOG("[SYS_HOOK] Remote thread created in PID %u via NtCreateThread, injecting dgcore...", targetPid);
        CaptureOptions childOptions = RenderDoc::Inst().GetCaptureOptions();
#if defined(DCOMP_SINGLE_GENERATION_CHILD_HOOK) && DCOMP_SINGLE_GENERATION_CHILD_HOOK
        childOptions.hookIntoChildren = false;
#endif
        rdcpair<RDResult, uint32_t> res = Process::InjectIntoProcess(
            targetPid, {}, RenderDoc::Inst().GetCaptureFileTemplate(), childOptions, false, ProcessHandle);

        if(res.first == ResultCode::Succeeded)
        {
          RDCLOG("[SYS_HOOK] PID %u injected successfully via NtCreateThread, ident=%u", targetPid, res.second);
          RenderDoc::Inst().AddChildProcess(targetPid, res.second);
        }
        else
        {
          RDCERR("[SYS_HOOK] Failed to inject PID %u via NtCreateThread: %s", targetPid, res.first.message.c_str());
        }
      }

      if(!CreateSuspended && ThreadHandle && *ThreadHandle)
        ResumeThread(*ThreadHandle);

      syshooks.EndRecurse();
      return status;
    }

    NTSTATUS status = syshooks.NtCreateThread()(
        ThreadHandle, DesiredAccess, ObjectAttributes, ProcessHandle, ClientId,
        ThreadContext, InitialTeb, CreateSuspended);
    syshooks.EndRecurse();
    return status;
  }

  static HANDLE WINAPI Kernel32CreateRemoteThread_hook(
      HANDLE hProcess, LPSECURITY_ATTRIBUTES lpThreadAttributes, SIZE_T dwStackSize,
      LPTHREAD_START_ROUTINE lpStartAddress, LPVOID lpParameter, DWORD dwCreationFlags,
      LPDWORD lpThreadId)
  {
    bool recursive = syshooks.CheckRecurse();
    if(recursive)
    {
      return syshooks.Kernel32CreateRemoteThread()(hProcess, lpThreadAttributes, dwStackSize,
                                                   lpStartAddress, lpParameter, dwCreationFlags,
                                                   lpThreadId);
    }

    DWORD targetPid = 0;
    if(hProcess != NULL && hProcess != GetCurrentProcess())
      targetPid = GetProcessId(hProcess);

    if(targetPid != 0 && targetPid != GetCurrentProcessId())
    {
      RDCLOG("[SYS_HOOK] CreateRemoteThread called for REMOTE PID %u! flags=0x%08x", targetPid, dwCreationFlags);
      bool resume = false;
      if((dwCreationFlags & CREATE_SUSPENDED) == 0)
      {
        resume = true;
        dwCreationFlags |= CREATE_SUSPENDED;
      }

      HANDLE hThread = syshooks.Kernel32CreateRemoteThread()(
          hProcess, lpThreadAttributes, dwStackSize, lpStartAddress, lpParameter, dwCreationFlags, lpThreadId);

      if(hThread != NULL && RenderDoc::Inst().GetCaptureOptions().hookIntoChildren)
      {
        RDCLOG("[SYS_HOOK] Remote thread created in PID %u via CreateRemoteThread, injecting dgcore...", targetPid);
        CaptureOptions childOptions = RenderDoc::Inst().GetCaptureOptions();
#if defined(DCOMP_SINGLE_GENERATION_CHILD_HOOK) && DCOMP_SINGLE_GENERATION_CHILD_HOOK
        childOptions.hookIntoChildren = false;
#endif
        rdcpair<RDResult, uint32_t> res = Process::InjectIntoProcess(
            targetPid, {}, RenderDoc::Inst().GetCaptureFileTemplate(), childOptions, false, hProcess);

        if(res.first == ResultCode::Succeeded)
        {
          RDCLOG("[SYS_HOOK] PID %u injected successfully via CreateRemoteThread, ident=%u", targetPid, res.second);
          RenderDoc::Inst().AddChildProcess(targetPid, res.second);
        }
        else
        {
          RDCERR("[SYS_HOOK] Failed to inject PID %u via CreateRemoteThread: %s", targetPid, res.first.message.c_str());
        }
      }

      if(resume && hThread != NULL)
        ResumeThread(hThread);

      syshooks.EndRecurse();
      return hThread;
    }

    HANDLE ret = syshooks.Kernel32CreateRemoteThread()(hProcess, lpThreadAttributes, dwStackSize,
                                                      lpStartAddress, lpParameter, dwCreationFlags, lpThreadId);
    syshooks.EndRecurse();
    return ret;
  }

  static HANDLE WINAPI
  Kernel32CreateRemoteThreadEx_hook(HANDLE hProcess, LPSECURITY_ATTRIBUTES lpThreadAttributes,
                                   SIZE_T dwStackSize, LPTHREAD_START_ROUTINE lpStartAddress,
                                   LPVOID lpParameter, DWORD dwCreationFlags,
                                   LPPROC_THREAD_ATTRIBUTE_LIST lpAttributeList, LPDWORD lpThreadId)
  {
    bool recursive = syshooks.CheckRecurse();
    if(recursive)
    {
      return syshooks.Kernel32CreateRemoteThreadEx()(hProcess, lpThreadAttributes, dwStackSize,
                                                     lpStartAddress, lpParameter, dwCreationFlags,
                                                     lpAttributeList, lpThreadId);
    }

    DWORD targetPid = 0;
    if(hProcess != NULL && hProcess != GetCurrentProcess())
      targetPid = GetProcessId(hProcess);

    if(targetPid != 0 && targetPid != GetCurrentProcessId())
    {
      RDCLOG("[SYS_HOOK] CreateRemoteThreadEx called for REMOTE PID %u! flags=0x%08x", targetPid, dwCreationFlags);
      bool resume = false;
      if((dwCreationFlags & CREATE_SUSPENDED) == 0)
      {
        resume = true;
        dwCreationFlags |= CREATE_SUSPENDED;
      }

      HANDLE hThread = syshooks.Kernel32CreateRemoteThreadEx()(
          hProcess, lpThreadAttributes, dwStackSize, lpStartAddress, lpParameter, dwCreationFlags,
          lpAttributeList, lpThreadId);

      if(hThread != NULL && RenderDoc::Inst().GetCaptureOptions().hookIntoChildren)
      {
        RDCLOG("[SYS_HOOK] Remote thread created in PID %u via CreateRemoteThreadEx, injecting dgcore...", targetPid);
        CaptureOptions childOptions = RenderDoc::Inst().GetCaptureOptions();
#if defined(DCOMP_SINGLE_GENERATION_CHILD_HOOK) && DCOMP_SINGLE_GENERATION_CHILD_HOOK
        childOptions.hookIntoChildren = false;
#endif
        rdcpair<RDResult, uint32_t> res = Process::InjectIntoProcess(
            targetPid, {}, RenderDoc::Inst().GetCaptureFileTemplate(), childOptions, false, hProcess);

        if(res.first == ResultCode::Succeeded)
        {
          RDCLOG("[SYS_HOOK] PID %u injected successfully via CreateRemoteThreadEx, ident=%u", targetPid, res.second);
          RenderDoc::Inst().AddChildProcess(targetPid, res.second);
        }
        else
        {
          RDCERR("[SYS_HOOK] Failed to inject PID %u via CreateRemoteThreadEx: %s", targetPid, res.first.message.c_str());
        }
      }

      if(resume && hThread != NULL)
        ResumeThread(hThread);

      syshooks.EndRecurse();
      return hThread;
    }

    HANDLE ret = syshooks.Kernel32CreateRemoteThreadEx()(
        hProcess, lpThreadAttributes, dwStackSize, lpStartAddress, lpParameter, dwCreationFlags,
        lpAttributeList, lpThreadId);
    syshooks.EndRecurse();
    return ret;
  }

  static HANDLE WINAPI
  KernelbaseCreateRemoteThreadEx_hook(HANDLE hProcess, LPSECURITY_ATTRIBUTES lpThreadAttributes,
                                     SIZE_T dwStackSize, LPTHREAD_START_ROUTINE lpStartAddress,
                                     LPVOID lpParameter, DWORD dwCreationFlags,
                                     LPPROC_THREAD_ATTRIBUTE_LIST lpAttributeList, LPDWORD lpThreadId)
  {
    bool recursive = syshooks.CheckRecurse();
    if(recursive)
    {
      return syshooks.KernelbaseCreateRemoteThreadEx()(hProcess, lpThreadAttributes, dwStackSize,
                                                       lpStartAddress, lpParameter, dwCreationFlags,
                                                       lpAttributeList, lpThreadId);
    }

    DWORD targetPid = 0;
    if(hProcess != NULL && hProcess != GetCurrentProcess())
      targetPid = GetProcessId(hProcess);

    if(targetPid != 0 && targetPid != GetCurrentProcessId())
    {
      RDCLOG("[SYS_HOOK] kernelbase!CreateRemoteThreadEx called for REMOTE PID %u! flags=0x%08x", targetPid, dwCreationFlags);
      bool resume = false;
      if((dwCreationFlags & CREATE_SUSPENDED) == 0)
      {
        resume = true;
        dwCreationFlags |= CREATE_SUSPENDED;
      }

      HANDLE hThread = syshooks.KernelbaseCreateRemoteThreadEx()(
          hProcess, lpThreadAttributes, dwStackSize, lpStartAddress, lpParameter, dwCreationFlags,
          lpAttributeList, lpThreadId);

      if(hThread != NULL && RenderDoc::Inst().GetCaptureOptions().hookIntoChildren)
      {
        RDCLOG("[SYS_HOOK] Remote thread created in PID %u via kernelbase!CreateRemoteThreadEx, injecting dgcore...", targetPid);
        CaptureOptions childOptions = RenderDoc::Inst().GetCaptureOptions();
#if defined(DCOMP_SINGLE_GENERATION_CHILD_HOOK) && DCOMP_SINGLE_GENERATION_CHILD_HOOK
        childOptions.hookIntoChildren = false;
#endif
        rdcpair<RDResult, uint32_t> res = Process::InjectIntoProcess(
            targetPid, {}, RenderDoc::Inst().GetCaptureFileTemplate(), childOptions, false, hProcess);

        if(res.first == ResultCode::Succeeded)
        {
          RDCLOG("[SYS_HOOK] PID %u injected successfully via kernelbase!CreateRemoteThreadEx, ident=%u", targetPid, res.second);
          RenderDoc::Inst().AddChildProcess(targetPid, res.second);
        }
        else
        {
          RDCERR("[SYS_HOOK] Failed to inject PID %u via kernelbase!CreateRemoteThreadEx: %s", targetPid, res.first.message.c_str());
        }
      }

      if(resume && hThread != NULL)
        ResumeThread(hThread);

      syshooks.EndRecurse();
      return hThread;
    }

    HANDLE ret = syshooks.KernelbaseCreateRemoteThreadEx()(
        hProcess, lpThreadAttributes, dwStackSize, lpStartAddress, lpParameter, dwCreationFlags,
        lpAttributeList, lpThreadId);
    syshooks.EndRecurse();
    return ret;
  }

  static BOOL WINAPI CreateProcessWithTokenW_hook(
      HANDLE hToken, DWORD dwLogonFlags, LPCWSTR lpApplicationName, LPWSTR lpCommandLine,
      DWORD dwCreationFlags, LPVOID lpEnvironment, LPCWSTR lpCurrentDirectory,
      LPSTARTUPINFOW lpStartupInfo, LPPROCESS_INFORMATION lpProcessInformation)
  {
    return Hooked_CreateProcess(
        "advapi32!CreateProcessWithTokenW",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.CreateProcessWithTokenW()(hToken, dwLogonFlags, lpApplicationName,
                                                   lpCommandLine, flags, env, lpCurrentDirectory,
                                                   lpStartupInfo, pi);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static NTSTATUS NTAPI NtTerminateProcess_hook(HANDLE ProcessHandle, NTSTATUS ExitStatus)
  {
    bool recursive = syshooks.CheckRecurse();
    if(recursive)
    {
      return syshooks.NtTerminateProcess()(ProcessHandle, ExitStatus);
    }

    if(ProcessHandle == NULL || ProcessHandle == GetCurrentProcess() || ProcessHandle == (HANDLE)-1)
    {
      if(RenderDoc::Inst().GetCaptureOptions().hookIntoChildren)
      {
        if(!s_ExitScanned.exchange(true))
        {
          RDCLOG("[SYS_HOOK] NtTerminateProcess called on self in PID %u! Scanning handles before exit...",
                 GetCurrentProcessId());
          ScanHandles();
        }
      }
    }

    syshooks.EndRecurse();
    return syshooks.NtTerminateProcess()(ProcessHandle, ExitStatus);
  }

  static void WINAPI ExitProcess_hook(UINT uExitCode)
  {
    bool recursive = syshooks.CheckRecurse();
    if(recursive)
    {
      syshooks.ExitProcess()(uExitCode);
      return;
    }

    if(RenderDoc::Inst().GetCaptureOptions().hookIntoChildren)
    {
      if(!s_ExitScanned.exchange(true))
      {
        RDCLOG("[SYS_HOOK] ExitProcess called in PID %u! Scanning handles before exit...",
               GetCurrentProcessId());
        ScanHandles();
      }
    }

    syshooks.EndRecurse();
    syshooks.ExitProcess()(uExitCode);
  }

  static BOOL WINAPI API110CreateProcessA_hook(
      __in_opt LPCSTR lpApplicationName, __inout_opt LPSTR lpCommandLine,
      __in_opt LPSECURITY_ATTRIBUTES lpProcessAttributes,
      __in_opt LPSECURITY_ATTRIBUTES lpThreadAttributes, __in BOOL bInheritHandles,
      __in DWORD dwCreationFlags, __in_opt LPVOID lpEnvironment, __in_opt LPCSTR lpCurrentDirectory,
      __in LPSTARTUPINFOA lpStartupInfo, __out LPPROCESS_INFORMATION lpProcessInformation)
  {
    return Hooked_CreateProcess(
        "CreateProcessA",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.API110CreateProcessA()(
              lpApplicationName, lpCommandLine, lpProcessAttributes, lpThreadAttributes,
              bInheritHandles, flags, env, lpCurrentDirectory, lpStartupInfo, pi);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static BOOL WINAPI API110CreateProcessW_hook(
      __in_opt LPCWSTR lpApplicationName, __inout_opt LPWSTR lpCommandLine,
      __in_opt LPSECURITY_ATTRIBUTES lpProcessAttributes,
      __in_opt LPSECURITY_ATTRIBUTES lpThreadAttributes, __in BOOL bInheritHandles,
      __in DWORD dwCreationFlags, __in_opt LPVOID lpEnvironment, __in_opt LPCWSTR lpCurrentDirectory,
      __in LPSTARTUPINFOW lpStartupInfo, __out LPPROCESS_INFORMATION lpProcessInformation)
  {
    return Hooked_CreateProcess(
        "CreateProcessW",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.API110CreateProcessW()(
              lpApplicationName, lpCommandLine, lpProcessAttributes, lpThreadAttributes,
              bInheritHandles, flags, env, lpCurrentDirectory, lpStartupInfo, pi);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static BOOL WINAPI API111CreateProcessA_hook(
      __in_opt LPCSTR lpApplicationName, __inout_opt LPSTR lpCommandLine,
      __in_opt LPSECURITY_ATTRIBUTES lpProcessAttributes,
      __in_opt LPSECURITY_ATTRIBUTES lpThreadAttributes, __in BOOL bInheritHandles,
      __in DWORD dwCreationFlags, __in_opt LPVOID lpEnvironment, __in_opt LPCSTR lpCurrentDirectory,
      __in LPSTARTUPINFOA lpStartupInfo, __out LPPROCESS_INFORMATION lpProcessInformation)
  {
    return Hooked_CreateProcess(
        "CreateProcessA",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.API111CreateProcessA()(
              lpApplicationName, lpCommandLine, lpProcessAttributes, lpThreadAttributes,
              bInheritHandles, flags, env, lpCurrentDirectory, lpStartupInfo, pi);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static BOOL WINAPI API111CreateProcessW_hook(
      __in_opt LPCWSTR lpApplicationName, __inout_opt LPWSTR lpCommandLine,
      __in_opt LPSECURITY_ATTRIBUTES lpProcessAttributes,
      __in_opt LPSECURITY_ATTRIBUTES lpThreadAttributes, __in BOOL bInheritHandles,
      __in DWORD dwCreationFlags, __in_opt LPVOID lpEnvironment, __in_opt LPCWSTR lpCurrentDirectory,
      __in LPSTARTUPINFOW lpStartupInfo, __out LPPROCESS_INFORMATION lpProcessInformation)
  {
    return Hooked_CreateProcess(
        "CreateProcessW",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.API111CreateProcessW()(
              lpApplicationName, lpCommandLine, lpProcessAttributes, lpThreadAttributes,
              bInheritHandles, flags, env, lpCurrentDirectory, lpStartupInfo, pi);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static BOOL WINAPI API112CreateProcessA_hook(
      __in_opt LPCSTR lpApplicationName, __inout_opt LPSTR lpCommandLine,
      __in_opt LPSECURITY_ATTRIBUTES lpProcessAttributes,
      __in_opt LPSECURITY_ATTRIBUTES lpThreadAttributes, __in BOOL bInheritHandles,
      __in DWORD dwCreationFlags, __in_opt LPVOID lpEnvironment, __in_opt LPCSTR lpCurrentDirectory,
      __in LPSTARTUPINFOA lpStartupInfo, __out LPPROCESS_INFORMATION lpProcessInformation)
  {
    return Hooked_CreateProcess(
        "CreateProcessA",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.API112CreateProcessA()(
              lpApplicationName, lpCommandLine, lpProcessAttributes, lpThreadAttributes,
              bInheritHandles, flags, env, lpCurrentDirectory, lpStartupInfo, pi);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static BOOL WINAPI API112CreateProcessW_hook(
      __in_opt LPCWSTR lpApplicationName, __inout_opt LPWSTR lpCommandLine,
      __in_opt LPSECURITY_ATTRIBUTES lpProcessAttributes,
      __in_opt LPSECURITY_ATTRIBUTES lpThreadAttributes, __in BOOL bInheritHandles,
      __in DWORD dwCreationFlags, __in_opt LPVOID lpEnvironment, __in_opt LPCWSTR lpCurrentDirectory,
      __in LPSTARTUPINFOW lpStartupInfo, __out LPPROCESS_INFORMATION lpProcessInformation)
  {
    return Hooked_CreateProcess(
        "CreateProcessW",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.API112CreateProcessW()(
              lpApplicationName, lpCommandLine, lpProcessAttributes, lpThreadAttributes,
              bInheritHandles, flags, env, lpCurrentDirectory, lpStartupInfo, pi);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static BOOL WINAPI CreateProcessAsUserA_hook(
      HANDLE hToken, LPCSTR lpApplicationName, LPSTR lpCommandLine,
      LPSECURITY_ATTRIBUTES lpProcessAttributes, LPSECURITY_ATTRIBUTES lpThreadAttributes,
      BOOL bInheritHandles, DWORD dwCreationFlags, LPVOID lpEnvironment, LPCSTR lpCurrentDirectory,
      LPSTARTUPINFOA lpStartupInfo, LPPROCESS_INFORMATION lpProcessInformation)
  {
    return Hooked_CreateProcess(
        "CreateProcessAsUserA",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.CreateProcessAsUserA()(
              hToken, lpApplicationName, lpCommandLine, lpProcessAttributes, lpThreadAttributes,
              bInheritHandles, flags, env, lpCurrentDirectory, lpStartupInfo, pi);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static BOOL WINAPI CreateProcessAsUserW_hook(
      HANDLE hToken, LPCWSTR lpApplicationName, LPWSTR lpCommandLine,
      LPSECURITY_ATTRIBUTES lpProcessAttributes, LPSECURITY_ATTRIBUTES lpThreadAttributes,
      BOOL bInheritHandles, DWORD dwCreationFlags, LPVOID lpEnvironment, LPCWSTR lpCurrentDirectory,
      LPSTARTUPINFOW lpStartupInfo, LPPROCESS_INFORMATION lpProcessInformation)
  {
    return Hooked_CreateProcess(
        "CreateProcessAsUserW",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.CreateProcessAsUserW()(
              hToken, lpApplicationName, lpCommandLine, lpProcessAttributes, lpThreadAttributes,
              bInheritHandles, flags, env, lpCurrentDirectory, lpStartupInfo, pi);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static BOOL WINAPI CreateProcessWithLogonW_hook(LPCWSTR lpUsername, LPCWSTR lpDomain,
                                                  LPCWSTR lpPassword, DWORD dwLogonFlags,
                                                  LPCWSTR lpApplicationName, LPWSTR lpCommandLine,
                                                  DWORD dwCreationFlags, LPVOID lpEnvironment,
                                                  LPCWSTR lpCurrentDirectory,
                                                  LPSTARTUPINFOW lpStartupInfo,
                                                  LPPROCESS_INFORMATION lpProcessInformation)
  {
    return Hooked_CreateProcess(
        "CreateProcessAsUserW",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.CreateProcessWithLogonW()(lpUsername, lpDomain, lpPassword, dwLogonFlags,
                                                    lpApplicationName, lpCommandLine, flags, env,
                                                    lpCurrentDirectory, lpStartupInfo, pi);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static BOOL WINAPI API110CreateProcessAsUserW_hook(
      HANDLE hToken, LPCWSTR lpApplicationName, LPWSTR lpCommandLine,
      LPSECURITY_ATTRIBUTES lpProcessAttributes, LPSECURITY_ATTRIBUTES lpThreadAttributes,
      BOOL bInheritHandles, DWORD dwCreationFlags, LPVOID lpEnvironment, LPCWSTR lpCurrentDirectory,
      LPSTARTUPINFOW lpStartupInfo, LPPROCESS_INFORMATION lpProcessInformation)
  {
    return Hooked_CreateProcess(
        "CreateProcessAsUserW",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.API110CreateProcessAsUserW()(
              hToken, lpApplicationName, lpCommandLine, lpProcessAttributes, lpThreadAttributes,
              bInheritHandles, flags, env, lpCurrentDirectory, lpStartupInfo, pi);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static BOOL WINAPI API111CreateProcessAsUserW_hook(
      HANDLE hToken, LPCWSTR lpApplicationName, LPWSTR lpCommandLine,
      LPSECURITY_ATTRIBUTES lpProcessAttributes, LPSECURITY_ATTRIBUTES lpThreadAttributes,
      BOOL bInheritHandles, DWORD dwCreationFlags, LPVOID lpEnvironment, LPCWSTR lpCurrentDirectory,
      LPSTARTUPINFOW lpStartupInfo, LPPROCESS_INFORMATION lpProcessInformation)
  {
    return Hooked_CreateProcess(
        "CreateProcessAsUserW",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.API111CreateProcessAsUserW()(
              hToken, lpApplicationName, lpCommandLine, lpProcessAttributes, lpThreadAttributes,
              bInheritHandles, flags, env, lpCurrentDirectory, lpStartupInfo, pi);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }

  static BOOL WINAPI API112CreateProcessAsUserW_hook(
      HANDLE hToken, LPCWSTR lpApplicationName, LPWSTR lpCommandLine,
      LPSECURITY_ATTRIBUTES lpProcessAttributes, LPSECURITY_ATTRIBUTES lpThreadAttributes,
      BOOL bInheritHandles, DWORD dwCreationFlags, LPVOID lpEnvironment, LPCWSTR lpCurrentDirectory,
      LPSTARTUPINFOW lpStartupInfo, LPPROCESS_INFORMATION lpProcessInformation)
  {
    return Hooked_CreateProcess(
        "CreateProcessAsUserW",
        [=](DWORD flags, LPVOID env, LPPROCESS_INFORMATION pi) {
          return syshooks.API112CreateProcessAsUserW()(
              hToken, lpApplicationName, lpCommandLine, lpProcessAttributes, lpThreadAttributes,
              bInheritHandles, flags, env, lpCurrentDirectory, lpStartupInfo, pi);
        },
        dwCreationFlags, ShouldInject(lpApplicationName, lpCommandLine), lpEnvironment,
        lpProcessInformation);
  }
};

SysHook SysHook::syshooks;
