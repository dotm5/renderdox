/******************************************************************************
 * The MIT License (MIT)
 *
 * Copyright (c) 2026 RenderTest contributors
 ******************************************************************************/

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <dxgi1_2.h>
#include <stdio.h>
#include <strsafe.h>
#include <wchar.h>
#include <windows.h>
#include "api/app/renderdoc_app.h"
#include "generated/product_identity.h"

namespace
{
typedef HRESULT(WINAPI *CreateFactoryProc)(REFIID riid, void **factory);
typedef HRESULT(WINAPI *CreateFactory2Proc)(UINT flags, REFIID riid, void **factory);

struct ThreadData
{
  CreateFactoryProc createFactory;
  LONG failures;
};

DWORD WINAPI CreateFactoryThread(LPVOID parameter)
{
  ThreadData *data = (ThreadData *)parameter;
  IDXGIFactory1 *factory = NULL;
  HRESULT result = data->createFactory(__uuidof(IDXGIFactory1), (void **)&factory);
  if(FAILED(result) || factory == NULL)
  {
    InterlockedIncrement(&data->failures);
    return 1;
  }

  factory->Release();
  return 0;
}

bool GetExecutableDirectory(wchar_t (&directory)[32768])
{
  DWORD length = GetModuleFileNameW(NULL, directory, (DWORD)ARRAYSIZE(directory));
  if(length == 0 || length >= ARRAYSIZE(directory))
    return false;

  wchar_t *separator = wcsrchr(directory, L'\\');
  if(separator == NULL)
    return false;

  separator[1] = 0;
  return true;
}

bool ExpectCore(int argc, wchar_t **argv)
{
  for(int i = 1; i < argc; ++i)
    if(wcscmp(argv[i], L"--expect-core") == 0)
      return true;
  return false;
}

bool CreateAndReleaseFactory(CreateFactoryProc createFactory, REFIID iid)
{
  IUnknown *factory = NULL;
  HRESULT result = createFactory(iid, (void **)&factory);
  if(FAILED(result) || factory == NULL)
    return false;

  factory->Release();
  return true;
}

bool CreateAndReleaseFactory2(CreateFactory2Proc createFactory, REFIID iid)
{
  IUnknown *factory = NULL;
  HRESULT result = createFactory(0, iid, (void **)&factory);
  if(FAILED(result) || factory == NULL)
    return false;

  factory->Release();
  return true;
}
};    // namespace

int wmain(int argc, wchar_t **argv)
{
  wchar_t directory[32768] = {};
  if(!GetExecutableDirectory(directory))
  {
    fwprintf(stderr, L"Could not locate the smoke-test executable directory\n");
    return 1;
  }

  wchar_t proxyPath[32768] = {};
  if(FAILED(StringCchPrintfW(proxyPath, ARRAYSIZE(proxyPath), L"%sdxgi.dll", directory)))
    return 1;

  HMODULE proxy = LoadLibraryW(proxyPath);
  if(proxy == NULL)
  {
    fwprintf(stderr, L"Could not load proxy %s: %lu\n", proxyPath, GetLastError());
    return 1;
  }

  CreateFactoryProc createFactory = (CreateFactoryProc)GetProcAddress(proxy, "CreateDXGIFactory");
  CreateFactoryProc createFactory1 = (CreateFactoryProc)GetProcAddress(proxy, "CreateDXGIFactory1");
  CreateFactory2Proc createFactory2 =
      (CreateFactory2Proc)GetProcAddress(proxy, "CreateDXGIFactory2");
  if(createFactory == NULL || createFactory1 == NULL || createFactory2 == NULL)
  {
    fwprintf(stderr, L"Proxy does not export all required DXGI factory entry points\n");
    return 1;
  }

  ThreadData data = {createFactory1, 0};
  HANDLE threads[8] = {};
  for(size_t i = 0; i < ARRAYSIZE(threads); ++i)
    threads[i] = CreateThread(NULL, 0, CreateFactoryThread, &data, 0, NULL);

  DWORD wait = WaitForMultipleObjects((DWORD)ARRAYSIZE(threads), threads, TRUE, 30000);
  for(HANDLE thread : threads)
    if(thread != NULL)
      CloseHandle(thread);

  if(wait != WAIT_OBJECT_0 || data.failures != 0)
  {
    fwprintf(stderr, L"Concurrent factory calls failed: wait=%lu failures=%ld\n", wait,
             data.failures);
    return 1;
  }

  if(!CreateAndReleaseFactory(createFactory, __uuidof(IDXGIFactory)) ||
     !CreateAndReleaseFactory2(createFactory2, __uuidof(IDXGIFactory2)))
  {
    fwprintf(stderr, L"CreateDXGIFactory or CreateDXGIFactory2 failed\n");
    return 1;
  }

  wchar_t systemDirectory[32768] = {};
  wchar_t systemDXGIPath[32768] = {};
  UINT systemLength = GetSystemDirectoryW(systemDirectory, (UINT)ARRAYSIZE(systemDirectory));
  if(systemLength == 0 || systemLength >= ARRAYSIZE(systemDirectory) ||
     FAILED(StringCchPrintfW(systemDXGIPath, ARRAYSIZE(systemDXGIPath), L"%s\\dxgi.dll",
                             systemDirectory)))
    return 1;

  HMODULE realDXGI = GetModuleHandleW(systemDXGIPath);
  if(realDXGI == NULL || realDXGI == proxy)
  {
    fwprintf(stderr, L"Canonical system DXGI was not loaded distinctly\n");
    return 1;
  }

  HMODULE core = GetModuleHandleW(RDOC_CORE_FILENAME_W);
  bool expectCore = ExpectCore(argc, argv);
  if(expectCore != (core != NULL))
  {
    fwprintf(stderr, L"Core expectation failed: expected=%d module=%p\n", expectCore, core);
    return 1;
  }

  if(core != NULL)
  {
    pRENDERDOC_GetAPI getAPI = (pRENDERDOC_GetAPI)GetProcAddress(core, "RENDERDOC_GetAPI");
    RENDERDOC_API_1_6_0 *api = NULL;
    if(getAPI == NULL || getAPI(eRENDERDOC_API_Version_1_6_0, (void **)&api) != 1 || api == NULL)
    {
      fwprintf(stderr, L"Core API handshake failed\n");
      return 1;
    }

    int major = 0;
    int minor = 0;
    int patch = 0;
    api->GetAPIVersion(&major, &minor, &patch);
    wprintf(L"Core API %d.%d.%d\n", major, minor, patch);
  }

  wprintf(L"DXGI_PROXY_SMOKE_OK proxy=%p system=%p core=%p\n", proxy, realDXGI, core);
  return 0;
}
