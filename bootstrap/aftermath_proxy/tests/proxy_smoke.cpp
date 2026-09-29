#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <wchar.h>

namespace
{
typedef uint64_t(WINAPI *IntegerExport)(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t,
                                        uint64_t);
typedef double(WINAPI *FloatingExport)(double, double, double, double);

struct WorkerData
{
  HANDLE start;
  IntegerExport call;
  volatile LONG failures;
};

uint64_t Expected(uint64_t a, uint64_t b, uint64_t c, uint64_t d, uint64_t e, uint64_t f)
{
  return a + 3 * b + 5 * c + 7 * d + 11 * e + 13 * f;
}

DWORD WINAPI ConcurrentCall(LPVOID parameter)
{
  WorkerData *data = (WorkerData *)parameter;
  WaitForSingleObject(data->start, INFINITE);
  const uint64_t a = GetCurrentThreadId();
  if(data->call(a, 2, 3, 4, 5, 6) != Expected(a, 2, 3, 4, 5, 6))
    InterlockedIncrement(&data->failures);
  return 0;
}

bool GetProxyPath(wchar_t (&path)[32768])
{
  const DWORD length = GetModuleFileNameW(NULL, path, 32768);
  if(length == 0 || length >= 32768)
    return false;
  wchar_t *separator = wcsrchr(path, L'\\');
  if(separator == NULL)
    return false;
  separator[1] = 0;
  return wcscat_s(path, 32768, L"GFSDK_Aftermath_Lib.x64.dll") == 0;
}
}    // namespace

int wmain(int argc, wchar_t **argv)
{
  const bool expectCore = argc == 2 &&
                          (wcscmp(argv[1], L"--marker") == 0 ||
                           wcscmp(argv[1], L"--env") == 0);
  const bool enableByEnvironment =
      argc == 2 && (wcscmp(argv[1], L"--env") == 0 ||
                    wcscmp(argv[1], L"--missing-core") == 0);
  SetEnvironmentVariableW(L"DCOMP_BOOTSTRAP_ENABLE",
                          enableByEnvironment ? L"1" : L"0");
  wchar_t proxyPath[32768] = {};
  if(!GetProxyPath(proxyPath))
    return 1;

  HMODULE proxy = LoadLibraryW(proxyPath);
  if(proxy == NULL)
  {
    fwprintf(stderr, L"proxy load failed: %lu\n", GetLastError());
    return 1;
  }

  IntegerExport integerCall =
      (IntegerExport)GetProcAddress(proxy, "GFSDK_Aftermath_DX12_Initialize");
  FloatingExport floatingCall =
      (FloatingExport)GetProcAddress(proxy, "GFSDK_Aftermath_GetShaderHash");
  if(integerCall == NULL || floatingCall == NULL)
    return 2;

  HANDLE start = CreateEventW(NULL, TRUE, FALSE, NULL);
  if(start == NULL)
    return 3;
  WorkerData data = {start, integerCall, 0};
  HANDLE threads[16] = {};
  for(size_t i = 0; i < 16; ++i)
  {
    threads[i] = CreateThread(NULL, 0, ConcurrentCall, &data, 0, NULL);
    if(threads[i] == NULL)
      return 4;
  }

  SetEvent(start);
  const DWORD waited = WaitForMultipleObjects(16, threads, TRUE, 30000);
  for(HANDLE thread : threads)
    CloseHandle(thread);
  CloseHandle(start);
  if(waited != WAIT_OBJECT_0 || data.failures != 0)
  {
    fwprintf(stderr, L"concurrent first calls failed: wait=%lu failures=%ld\n", waited,
             data.failures);
    return 5;
  }

  if(integerCall(11, 12, 13, 14, 15, 16) != Expected(11, 12, 13, 14, 15, 16))
    return 6;
  if(floatingCall(1.25, 2.5, 3.75, 4.5) !=
     1.25 + 3 * 2.5 + 5 * 3.75 + 7 * 4.5)
    return 7;

  if(GetModuleHandleW(L"GFSDK_Aftermath_Lib_orig.dll") == NULL &&
     GetModuleHandleW(L"GFSDK_Aftermath_Lib.x64.orig.dll") == NULL &&
     GetModuleHandleW(L"GFSDK_Aftermath_Lib_orig.x64.dll") == NULL)
    return 8;

  if(expectCore)
  {
    typedef LONG(__cdecl *HandshakeCount)();
    bool handshook = false;
    for(int attempt = 0; attempt < 250; ++attempt)
    {
      HMODULE core = GetModuleHandleW(L"dgcore.dll");
      HandshakeCount count =
          core ? (HandshakeCount)GetProcAddress(core, "TestHandshakeCount") : NULL;
      if(count != NULL && count() > 0)
      {
        handshook = true;
        break;
      }
      Sleep(20);
    }
    if(!handshook)
      return 9;
  }
  else if(GetModuleHandleW(L"dgcore.dll") != NULL)
  {
    return 10;
  }

  puts("aftermath proxy smoke: PASS");
  return 0;
}
