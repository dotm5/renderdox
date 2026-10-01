// Owned compatibility fixture: explicit Core loading at three object phases.
// It writes measured HRESULTs; it does not inject into another process.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <wrl/client.h>
#include <cstdio>
#include <cwchar>
#include <stdexcept>
#include "api/app/renderdoc_app.h"

using Microsoft::WRL::ComPtr;
static FILE *report = nullptr;
static RENDERDOC_API_1_6_0 *api = nullptr;

static void Record(const char *stage, HRESULT hr)
{
  fprintf(report, "{\"stage\":\"%s\",\"hresult\":\"0x%08lx\",\"succeeded\":%s}\n",
          stage, static_cast<unsigned long>(hr), SUCCEEDED(hr) ? "true" : "false");
  fflush(report);
}

static void Check(const char *stage, HRESULT hr)
{
  Record(stage, hr);
  if(FAILED(hr)) throw std::runtime_error(stage);
}

static void LoadCore(const wchar_t *path)
{
  HMODULE core = LoadLibraryExW(path, nullptr,
      LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
  Check("load_core", core ? S_OK : HRESULT_FROM_WIN32(GetLastError()));
  auto getAPI = reinterpret_cast<pDCOMP_GetAPI>(GetProcAddress(core, "DCOMP_GetAPI"));
  Check("core_handshake", getAPI && getAPI(eDCOMP_API_Version_1_6_0, reinterpret_cast<void **>(&api)) == 1 && api ? S_OK : E_NOINTERFACE);
}

int wmain(int argc, wchar_t **argv)
{
  // phase, report.jsonl, optional absolute dgcore.dll, optional capture prefix.
  if(argc < 3 || (wcscmp(argv[1], L"baseline") && wcscmp(argv[1], L"early") &&
                 wcscmp(argv[1], L"after-factory") && wcscmp(argv[1], L"after-swapchain"))) return 2;
  if(wcscmp(argv[1], L"baseline") && argc < 4) return 2;
  if(_wfopen_s(&report, argv[2], L"wb") || !report) return 2;
  HWND window = nullptr;
  HANDLE fenceEvent = nullptr;
  int result = 0;
  try
  {
    fprintf(report, "{\"phase\":\"%ls\",\"pid\":%lu}\n", argv[1], GetCurrentProcessId());
    if(!wcscmp(argv[1], L"early")) LoadCore(argv[3]);
    ComPtr<IDXGIFactory4> factory;
    Check("create_factory", CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
    if(!wcscmp(argv[1], L"after-factory")) LoadCore(argv[3]);
    ComPtr<ID3D12Device> device;
    Check("create_device", D3D12CreateDevice(nullptr, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)));
    D3D12_COMMAND_QUEUE_DESC queueDesc = {};
    ComPtr<ID3D12CommandQueue> queue;
    Check("create_queue", device->CreateCommandQueue(&queueDesc, IID_PPV_ARGS(&queue)));
    window = CreateWindowExW(0, L"STATIC", L"DComp owned D3D12 fixture", WS_OVERLAPPEDWINDOW,
                            0, 0, 320, 240, nullptr, nullptr, GetModuleHandleW(nullptr), nullptr);
    Check("create_window", window ? S_OK : HRESULT_FROM_WIN32(GetLastError()));
    DXGI_SWAP_CHAIN_DESC1 desc = {};
    desc.Width = 320; desc.Height = 240; desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    desc.SampleDesc.Count = 1; desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    desc.BufferCount = 2; desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD;
    ComPtr<IDXGISwapChain1> swapchain1;
    Check("create_swapchain", factory->CreateSwapChainForHwnd(queue.Get(), window, &desc, nullptr, nullptr, &swapchain1));
    ComPtr<IDXGISwapChain3> swapchain;
    Check("query_swapchain3", swapchain1.As(&swapchain));
    if(!wcscmp(argv[1], L"after-swapchain")) LoadCore(argv[3]);
    if(api && argc >= 5)
    {
      char prefix[32768] = {};
      Check("capture_prefix_utf8", WideCharToMultiByte(CP_UTF8, 0, argv[4], -1, prefix, sizeof(prefix), nullptr, nullptr) ? S_OK : E_FAIL);
      api->SetCaptureFilePathTemplate(prefix);
    }
    ComPtr<ID3D12DescriptorHeap> heap;
    D3D12_DESCRIPTOR_HEAP_DESC heapDesc = {};
    heapDesc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV; heapDesc.NumDescriptors = 2;
    Check("create_rtv_heap", device->CreateDescriptorHeap(&heapDesc, IID_PPV_ARGS(&heap)));
    ComPtr<ID3D12Resource> buffers[2];
    const UINT stride = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
    D3D12_CPU_DESCRIPTOR_HANDLE rtv = heap->GetCPUDescriptorHandleForHeapStart();
    for(UINT i = 0; i < 2; ++i)
    {
      Check("get_buffer", swapchain->GetBuffer(i, IID_PPV_ARGS(&buffers[i])));
      device->CreateRenderTargetView(buffers[i].Get(), nullptr, rtv);
      rtv.ptr += stride;
    }
    ComPtr<ID3D12CommandAllocator> allocator;
    Check("create_allocator", device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)));
    ComPtr<ID3D12GraphicsCommandList> list;
    Check("create_list", device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr, IID_PPV_ARGS(&list)));
    Check("initial_close", list->Close());
    ComPtr<ID3D12Fence> fence;
    Check("create_fence", device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)));
    fenceEvent = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    Check("create_fence_event", fenceEvent ? S_OK : HRESULT_FROM_WIN32(GetLastError()));
    if(api) api->StartFrameCapture(nullptr, window);
    Record("capture_started", api && api->IsFrameCapturing() ? S_OK : E_FAIL);
    for(UINT64 frame = 1; frame <= 3; ++frame)
    {
      Check("reset_allocator", allocator->Reset());
      Check("reset_list", list->Reset(allocator.Get(), nullptr));
      UINT index = swapchain->GetCurrentBackBufferIndex();
      D3D12_RESOURCE_BARRIER barrier = {};
      barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
      barrier.Transition.pResource = buffers[index].Get();
      barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
      barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_PRESENT;
      barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_RENDER_TARGET;
      list->ResourceBarrier(1, &barrier);
      rtv = heap->GetCPUDescriptorHandleForHeapStart(); rtv.ptr += SIZE_T(index) * stride;
      const float colour[] = {0.1f * static_cast<float>(frame), 0.2f, 0.5f, 1.0f};
      list->ClearRenderTargetView(rtv, colour, 0, nullptr);
      barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_RENDER_TARGET;
      barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_PRESENT;
      list->ResourceBarrier(1, &barrier);
      Check("close_list", list->Close());
      ID3D12CommandList *commands[] = {list.Get()};
      queue->ExecuteCommandLists(1, commands);
      Check("present", swapchain->Present(0, 0));
      Check("signal", queue->Signal(fence.Get(), frame));
      Check("wait_fence_setup", fence->SetEventOnCompletion(frame, fenceEvent));
      Check("wait_fence", WaitForSingleObject(fenceEvent, 10000) == WAIT_OBJECT_0 ? S_OK : HRESULT_FROM_WIN32(ERROR_TIMEOUT));
    }
    if(api)
    {
      const uint32_t saved = api->EndFrameCapture(nullptr, window);
      Record("capture_saved", saved ? S_OK : E_FAIL);
      fprintf(report, "{\"captureCount\":%u}\n", api->GetNumCaptures());
    }
  }
  catch(const std::exception &error)
  {
    fprintf(report, "{\"failureStage\":\"%s\"}\n", error.what());
    result = 1;
  }
  if(fenceEvent) CloseHandle(fenceEvent);
  if(window) DestroyWindow(window);
  fprintf(report, "{\"terminal\":true,\"exitCode\":%d}\n", result);
  fclose(report);
  return result;
}
