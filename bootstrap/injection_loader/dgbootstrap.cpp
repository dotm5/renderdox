#include <windows.h>

#include "../../renderdoc/generated/product_identity.h"

#ifndef LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR
#define LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR 0x00000100
#endif

#ifndef LOAD_LIBRARY_SEARCH_SYSTEM32
#define LOAD_LIBRARY_SEARCH_SYSTEM32 0x00000800
#endif

#define ARRAY_COUNT(a) (sizeof(a) / sizeof((a)[0]))

// Keep this bootstrap independent of the CRT. MSVC can synthesize these calls
// for local array initialisation even when the source does not call them.
#pragma function(memcpy, memset)
extern "C" void *__cdecl memset(void *destination, int value, size_t count)
{
  volatile unsigned char *output = static_cast<volatile unsigned char *>(destination);
  while(count-- > 0)
    *output++ = static_cast<unsigned char>(value);
  return destination;
}

extern "C" void *__cdecl memcpy(void *destination, const void *source, size_t count)
{
  volatile unsigned char *output = static_cast<volatile unsigned char *>(destination);
  const volatile unsigned char *input = static_cast<const volatile unsigned char *>(source);
  while(count-- > 0)
    *output++ = *input++;
  return destination;
}

enum BootstrapState
{
  BootstrapNotStarted = 0,
  BootstrapThreadScheduled = 1,
  BootstrapWorkerStarted = 2,
  BootstrapWaiting = 3,
  BootstrapLoadingCore = 4,
  BootstrapCoreLoaded = 5,
};

enum DelaySource
{
  DelayFromDefault = 0,
  DelayFromEnvironment = 1,
  DelayFromFile = 2,
};

static HMODULE g_module = NULL;
static volatile LONG g_state = BootstrapNotStarted;
static volatile LONG g_lastError = ERROR_SUCCESS;
static volatile LONG g_delayMs = 32;

static char *AppendText(char *cursor, char *end, const char *text)
{
  while(cursor < end && *text != 0)
    *cursor++ = *text++;

  return cursor;
}

static char *AppendUnsigned(char *cursor, char *end, ULONGLONG value)
{
  char digits[32];
  DWORD count = 0;

  do
  {
    digits[count++] = char('0' + value % 10);
    value /= 10;
  } while(value != 0 && count < ARRAY_COUNT(digits));

  while(count > 0 && cursor < end)
    *cursor++ = digits[--count];

  return cursor;
}

static char *AppendHex(char *cursor, char *end, ULONG_PTR value)
{
  static const char hex[] = "0123456789ABCDEF";
  char digits[sizeof(ULONG_PTR) * 2];
  DWORD count = 0;

  do
  {
    digits[count++] = hex[value & 0xf];
    value >>= 4;
  } while(value != 0 && count < ARRAY_COUNT(digits));

  cursor = AppendText(cursor, end, "0x");

  while(count > 0 && cursor < end)
    *cursor++ = digits[--count];

  return cursor;
}

static BOOL BuildAdjacentPath(const wchar_t *leafName, wchar_t *path, DWORD pathCount)
{
  DWORD length = GetModuleFileNameW(g_module, path, pathCount);
  if(length == 0 || length >= pathCount)
    return FALSE;

  while(length > 0 && path[length - 1] != L'\\' && path[length - 1] != L'/')
    --length;

  if(length == 0)
    return FALSE;

  DWORD leafLength = 0;
  while(leafName[leafLength] != 0)
    ++leafLength;

  if(length + leafLength + 1 > pathCount)
    return FALSE;

  for(DWORD i = 0; i <= leafLength; ++i)
    path[length + i] = leafName[i];

  return TRUE;
}

static BOOL ParseWideDelay(const wchar_t *text, DWORD *delay)
{
  while(*text == L' ' || *text == L'\t' || *text == L'\r' || *text == L'\n')
    ++text;

  if(*text < L'0' || *text > L'9')
    return FALSE;

  DWORD value = 0;
  while(*text >= L'0' && *text <= L'9')
  {
    if(value > 2000 / 10)
      return FALSE;

    value = value * 10 + DWORD(*text - L'0');
    if(value > 2000)
      return FALSE;

    ++text;
  }

  while(*text == L' ' || *text == L'\t' || *text == L'\r' || *text == L'\n')
    ++text;

  if(*text != 0)
    return FALSE;

  *delay = value;
  return TRUE;
}

static BOOL ParseAnsiDelay(const char *text, DWORD textLength, DWORD *delay)
{
  DWORD index = 0;
  while(index < textLength &&
        (text[index] == ' ' || text[index] == '\t' || text[index] == '\r' || text[index] == '\n'))
    ++index;

  if(index >= textLength || text[index] < '0' || text[index] > '9')
    return FALSE;

  DWORD value = 0;
  while(index < textLength && text[index] >= '0' && text[index] <= '9')
  {
    if(value > 2000 / 10)
      return FALSE;

    value = value * 10 + DWORD(text[index] - '0');
    if(value > 2000)
      return FALSE;

    ++index;
  }

  while(index < textLength &&
        (text[index] == ' ' || text[index] == '\t' || text[index] == '\r' || text[index] == '\n'))
    ++index;

  if(index != textLength)
    return FALSE;

  *delay = value;
  return TRUE;
}

static DWORD ReadDelay(DelaySource *source)
{
  wchar_t environmentValue[32] = {};
  DWORD environmentLength =
      GetEnvironmentVariableW(L"DCOMP_STAGE_DELAY_MS", environmentValue, ARRAY_COUNT(environmentValue));
  DWORD delay = 0;

  if(environmentLength > 0 && environmentLength < ARRAY_COUNT(environmentValue) &&
     ParseWideDelay(environmentValue, &delay))
  {
    *source = DelayFromEnvironment;
    return delay;
  }

  wchar_t configPath[1024] = {};
  if(BuildAdjacentPath(L"dgbootstrap.delay-ms", configPath, ARRAY_COUNT(configPath)))
  {
    HANDLE file = CreateFileW(configPath, GENERIC_READ,
                              FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
                              OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if(file != INVALID_HANDLE_VALUE)
    {
      char contents[32] = {};
      DWORD bytesRead = 0;
      BOOL readSucceeded = ReadFile(file, contents, ARRAY_COUNT(contents), &bytesRead, NULL);
      CloseHandle(file);

      if(readSucceeded && ParseAnsiDelay(contents, bytesRead, &delay))
      {
        *source = DelayFromFile;
        return delay;
      }
    }
  }

  *source = DelayFromDefault;
  return 32;
}

static const char *DelaySourceName(DelaySource source)
{
  if(source == DelayFromEnvironment)
    return "environment";
  if(source == DelayFromFile)
    return "file";
  return "default";
}

static void WriteStageLog(const char *stage, DWORD delay, DelaySource source, DWORD errorCode,
                          HMODULE coreModule, ULONGLONG elapsedMs)
{
  wchar_t logPath[1024] = {};
  if(!BuildAdjacentPath(L"dgbootstrap.log", logPath, ARRAY_COUNT(logPath)))
    return;

  HANDLE file = CreateFileW(logPath, FILE_APPEND_DATA,
                            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
                            OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
  if(file == INVALID_HANDLE_VALUE)
    return;

  char line[512];
  char *cursor = line;
  char *end = line + ARRAY_COUNT(line);

  cursor = AppendText(cursor, end, "[DGBOOTSTRAP] pid=");
  cursor = AppendUnsigned(cursor, end, GetCurrentProcessId());
  cursor = AppendText(cursor, end, " tid=");
  cursor = AppendUnsigned(cursor, end, GetCurrentThreadId());
  cursor = AppendText(cursor, end, " tick=");
  cursor = AppendUnsigned(cursor, end, GetTickCount64());
  cursor = AppendText(cursor, end, " stage=");
  cursor = AppendText(cursor, end, stage);
  cursor = AppendText(cursor, end, " delay_ms=");
  cursor = AppendUnsigned(cursor, end, delay);
  cursor = AppendText(cursor, end, " delay_source=");
  cursor = AppendText(cursor, end, DelaySourceName(source));
  cursor = AppendText(cursor, end, " elapsed_ms=");
  cursor = AppendUnsigned(cursor, end, elapsedMs);
  cursor = AppendText(cursor, end, " error=");
  cursor = AppendUnsigned(cursor, end, errorCode);
  cursor = AppendText(cursor, end, " core=");
  cursor = AppendHex(cursor, end, reinterpret_cast<ULONG_PTR>(coreModule));
  cursor = AppendText(cursor, end, "\r\n");

  DWORD bytesWritten = 0;
  WriteFile(file, line, DWORD(cursor - line), &bytesWritten, NULL);
  CloseHandle(file);
}

static void SetFailure(DWORD errorCode)
{
  InterlockedExchange(&g_lastError, LONG(errorCode));
  InterlockedExchange(&g_state, LONG(0x80000000u | (errorCode & 0x7fffffffu)));
}

static DWORD WINAPI LoadCoreWorker(LPVOID)
{
  InterlockedExchange(&g_state, BootstrapWorkerStarted);

  DelaySource source = DelayFromDefault;
  DWORD delay = ReadDelay(&source);
  InterlockedExchange(&g_delayMs, LONG(delay));
  WriteStageLog("worker-start", delay, source, ERROR_SUCCESS, NULL, 0);

  InterlockedExchange(&g_state, BootstrapWaiting);
  if(delay != 0)
    Sleep(delay);

  wchar_t corePath[1024] = {};
  if(!BuildAdjacentPath(RDOC_CORE_FILENAME_W, corePath, ARRAY_COUNT(corePath)))
  {
    DWORD errorCode = ERROR_BUFFER_OVERFLOW;
    SetFailure(errorCode);
    WriteStageLog("core-path-failed", delay, source, errorCode, NULL, 0);
    return errorCode;
  }

  InterlockedExchange(&g_state, BootstrapLoadingCore);
  WriteStageLog("core-load-begin", delay, source, ERROR_SUCCESS, NULL, 0);

  ULONGLONG loadStart = GetTickCount64();
  HMODULE coreModule = LoadLibraryExW(
      corePath, NULL, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
  DWORD errorCode = coreModule == NULL ? GetLastError() : ERROR_SUCCESS;

  if(coreModule == NULL)
  {
    WriteStageLog("core-load-fallback", delay, source, errorCode, NULL,
                  GetTickCount64() - loadStart);
    SetLastError(ERROR_SUCCESS);
    coreModule = LoadLibraryW(corePath);
    errorCode = coreModule == NULL ? GetLastError() : ERROR_SUCCESS;
  }

  ULONGLONG elapsed = GetTickCount64() - loadStart;
  if(coreModule == NULL)
  {
    SetFailure(errorCode);
    WriteStageLog("core-load-failed", delay, source, errorCode, NULL, elapsed);
    return errorCode;
  }

  InterlockedExchange(&g_lastError, ERROR_SUCCESS);
  InterlockedExchange(&g_state, BootstrapCoreLoaded);
  WriteStageLog("core-load-success", delay, source, ERROR_SUCCESS, coreModule, elapsed);
  return ERROR_SUCCESS;
}

extern "C" __declspec(dllexport) DWORD WINAPI DGBootstrap_GetState()
{
  return DWORD(InterlockedCompareExchange(&g_state, 0, 0));
}

extern "C" __declspec(dllexport) DWORD WINAPI DGBootstrap_GetLastError()
{
  return DWORD(InterlockedCompareExchange(&g_lastError, 0, 0));
}

extern "C" __declspec(dllexport) DWORD WINAPI DGBootstrap_GetDelayMs()
{
  return DWORD(InterlockedCompareExchange(&g_delayMs, 0, 0));
}

extern "C" BOOL WINAPI dll_entry(HMODULE module, DWORD reason, LPVOID)
{
  if(reason == DLL_PROCESS_ATTACH)
  {
    g_module = module;
    DisableThreadLibraryCalls(module);
    InterlockedExchange(&g_state, BootstrapThreadScheduled);

    HANDLE worker = CreateThread(NULL, 0, LoadCoreWorker, NULL, 0, NULL);
    if(worker != NULL)
      CloseHandle(worker);
    else
      SetFailure(GetLastError());
  }

  return TRUE;
}
