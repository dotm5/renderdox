// Owned DX12 closure probe. No binary or vtable patches are made by this sample.
#include <windows.h>
#include <wrl/client.h>
#include <initguid.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <d3dcompiler.h>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <climits>
#include <cstring>
#include <thread>
#include <atomic>
#include "../../renderdoc/api/app/renderdoc_app.h"
using Microsoft::WRL::ComPtr;

static void Check(HRESULT hr)
{
  if(FAILED(hr))
  {
    std::printf("HRESULT=%08lx\n", (unsigned long)hr);
    throw std::runtime_error("DX call failed");
  }
}
static void Identity(const char *site, IUnknown *a, IUnknown *b)
{
  ComPtr<IUnknown> x, y;
  Check(a->QueryInterface(IID_PPV_ARGS(&x)));
  Check(b->QueryInterface(IID_PPV_ARGS(&y)));
  std::printf("identity site=%s equal=%d\n", site, x.Get() == y.Get());
}
static LRESULT CALLBACK WindowProc(HWND w, UINT m, WPARAM p, LPARAM l)
{
  return DefWindowProc(w, m, p, l);
}

static DWORD WINAPI Watchdog(void *)
{
  Sleep(20000);
  std::printf("FAIL: sample exceeded 20s watchdog\n");
  ExitProcess(124);
  return 0;
}

int main(int argc, char **argv)
{
  setvbuf(stdout, nullptr, _IONBF, 0);
  // Own process only; even a hung runtime/factory must not leave a test client behind.
  HANDLE watchdog = CreateThread(nullptr, 0, Watchdog, nullptr, 0, nullptr);
  if(watchdog) CloseHandle(watchdog);
  if(argc < 3)
    return 2;
  try
  {
    const std::string mode = argv[1];
    HMODULE core = GetModuleHandleW(L"dgcore.dll");
    auto getAPI = core ? (pDCOMP_GetAPI)GetProcAddress(core, "DCOMP_GetAPI") : nullptr;
    RENDERDOC_API_1_7_0 *api = nullptr;
    if(!getAPI || !getAPI(eRENDERDOC_API_Version_1_7_0, (void **)&api))
      throw std::runtime_error("capture injection/API missing");
    api->SetCaptureFilePathTemplate(argv[2]);
    api->MaskOverlayBits(0, 0);

    WNDCLASSW wc = {};
    wc.lpfnWndProc = WindowProc;
    wc.hInstance = GetModuleHandleW(nullptr);
    wc.lpszClassName = L"DX12ClosureProbe";
    RegisterClassW(&wc);
    HWND window = CreateWindowW(wc.lpszClassName, L"DX12 closure", WS_OVERLAPPEDWINDOW,
                                100, 100, 336, 279, nullptr, nullptr, wc.hInstance, nullptr);
    if(!window) throw std::runtime_error("window creation failed");
    ShowWindow(window, SW_SHOW);

    ComPtr<IDXGIFactory4> factory;
    Check(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)));
    ComPtr<ID3D12Device> device, aliasDevice, secondDevice;
    ComPtr<IDXGIFactory4> secondFactory;
    ComPtr<ID3D12CommandQueue> secondQueue;
    if(mode == "agility" || mode == "agility-preload" || mode == "agility-second")
    {
      if(argc < 4) return 77;
      std::string sdkPath = argv[3];
      if(sdkPath.back() != '\\' && sdkPath.back() != '/') sdkPath += '\\';
      HMODULE sdk = mode == "agility-preload" ?
          LoadLibraryA((sdkPath + "D3D12Core.dll").c_str()) : nullptr;
      auto getInterface = (PFN_D3D12_GET_INTERFACE)GetProcAddress(
          GetModuleHandleW(L"d3d12.dll"), "D3D12GetInterface");
      ComPtr<ID3D12SDKConfiguration1> config;
      ComPtr<ID3D12SDKConfiguration> baseConfig;
      ComPtr<ID3D12DeviceFactory> deviceFactory;
      if(!getInterface) { std::printf("SKIP agility missing exports\n"); return 77; }
      HRESULT hr = getInterface(CLSID_D3D12SDKConfiguration, IID_PPV_ARGS(&baseConfig));
      if(FAILED(hr)) { std::printf("SKIP agility config=%08lx\n", (unsigned long)hr); return 77; }
      hr = baseConfig.As(&config);
      if(FAILED(hr)) { std::printf("SKIP agility config1=%08lx\n", (unsigned long)hr); return 77; }
      std::printf("agility configuration1 obtained\n");
      if(!sdk) sdk = LoadLibraryA((sdkPath + "D3D12Core.dll").c_str());
      if(!sdk) { std::printf("SKIP agility load error=%lu\n", GetLastError()); return 77; }
      auto version = (UINT *)GetProcAddress(sdk, "D3D12SDKVersion");
      if(!version) { std::printf("SKIP agility missing version\n"); return 77; }
      hr = config->CreateDeviceFactory(*version, sdkPath.c_str(), IID_PPV_ARGS(&deviceFactory));
      if(FAILED(hr)) { std::printf("agility factory=%08lx\n", (unsigned long)hr); return 77; }
      Check(deviceFactory->CreateDevice(nullptr, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)));
      std::printf("agility sdk=%u\n", *version);
      if(mode == "agility-second")
      {
        ComPtr<ID3D12DeviceFactory> factory2;
        Check(config->CreateDeviceFactory(*version, sdkPath.c_str(), IID_PPV_ARGS(&factory2)));
        Check(CreateDXGIFactory2(0, IID_PPV_ARGS(&secondFactory)));
        ComPtr<IDXGIAdapter> warp;
        Check(secondFactory->EnumWarpAdapter(IID_PPV_ARGS(&warp)));
        Check(factory2->CreateDevice(warp.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&secondDevice)));
        D3D12_COMMAND_QUEUE_DESC q = {};
        Check(secondDevice->CreateCommandQueue(&q, IID_PPV_ARGS(&secondQueue)));
        std::printf("agility second-device-factory completed\n");
      }
      // Runtime and wrapped device keep SDK use valid; leave the module mapped until process exit.
    }
    else if(mode == "factory-root")
    {
      auto getInterface = (PFN_D3D12_GET_INTERFACE)GetProcAddress(
          GetModuleHandleW(L"d3d12.dll"), "D3D12GetInterface");
      ComPtr<ID3D12DeviceFactory> nativeFactory;
      if(!getInterface) throw std::runtime_error("missing D3D12GetInterface");
      Check(getInterface(CLSID_D3D12DeviceFactory, IID_PPV_ARGS(&nativeFactory)));
      Check(nativeFactory->CreateDevice(nullptr, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)));
      std::printf("direct DeviceFactory root completed\n");
    }
    else
      Check(D3D12CreateDevice(nullptr, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)));

    ComPtr<ID3D12Device1> device1;
    Check(device.As(&device1));
    Identity("device-version", device.Get(), device1.Get());

    // Intentionally query a valid but unrecognised IID on both wrapper families.
    GUID unknown = {0x728b67e1, 0xd117, 0x4ddf, {0x93,0x18,0x2c,0x88,0xf0,0x18,0x12,0x01}};
    void *unsupported = nullptr;
    HRESULT unknownDevice = device->QueryInterface(unknown, &unsupported);
    HRESULT unknownFactory = factory->QueryInterface(unknown, &unsupported);
    std::printf("unknown-qi device=%08lx factory=%08lx\n",
                (unsigned long)unknownDevice, (unsigned long)unknownFactory);

    if(mode == "second")
    {
      Check(CreateDXGIFactory2(0, IID_PPV_ARGS(&secondFactory)));
      // DX12 device creation on the same adapter may return the existing singleton.
      Check(D3D12CreateDevice(nullptr, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&aliasDevice)));
      Identity("repeated-device-create", device.Get(), aliasDevice.Get());
      ComPtr<IDXGIAdapter> warp;
      Check(secondFactory->EnumWarpAdapter(IID_PPV_ARGS(&warp)));
      Check(D3D12CreateDevice(warp.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&secondDevice)));
      D3D12_COMMAND_QUEUE_DESC q = {};
      Check(secondDevice->CreateCommandQueue(&q, IID_PPV_ARGS(&secondQueue)));
      std::printf("second-root distinct-luid=%d\n",
                  device->GetAdapterLuid().LowPart != secondDevice->GetAdapterLuid().LowPart ||
                  device->GetAdapterLuid().HighPart != secondDevice->GetAdapterLuid().HighPart);
    }

    D3D12_COMMAND_QUEUE_DESC q = {};
    ComPtr<ID3D12CommandQueue> queue;
    Check(device->CreateCommandQueue(&q, IID_PPV_ARGS(&queue)));
    ComPtr<ID3D12Device> queueDevice;
    Check(queue->GetDevice(IID_PPV_ARGS(&queueDevice)));
    Identity("queue-getdevice", device.Get(), queueDevice.Get());

    DXGI_SWAP_CHAIN_DESC1 desc = {};
    desc.Width = 320; desc.Height = 240;
    desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    desc.SampleDesc.Count = 1; desc.BufferCount = 2;
    desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD;
    ComPtr<IDXGISwapChain1> swap1;
    Check(factory->CreateSwapChainForHwnd(queue.Get(), window, &desc, nullptr, nullptr, &swap1));
    ComPtr<IDXGISwapChain3> swap;
    Check(swap1.As(&swap));
    Identity("swap-version", swap1.Get(), swap.Get());
    // All positive modes exercise the repaired return path.
    {
      ComPtr<ID3D12CommandQueue> typedQueue, unknownQueue;
      ComPtr<ID3D12Device> typedDevice, unknownDevice;
      ComPtr<IUnknown> unknownOwner;
      HRESULT queueHr = swap->GetDevice(IID_PPV_ARGS(&typedQueue));
      HRESULT deviceHr = swap->GetDevice(IID_PPV_ARGS(&typedDevice));
      Check(swap->GetDevice(IID_PPV_ARGS(&unknownOwner)));
      HRESULT unknownQueueHr = unknownOwner.As(&unknownQueue);
      HRESULT unknownDeviceHr = unknownOwner.As(&unknownDevice);
      std::printf("swap-getdevice queue=%08lx device=%08lx unknown-queue=%08lx unknown-device=%08lx\n",
                  (unsigned long)queueHr, (unsigned long)deviceHr,
                  (unsigned long)unknownQueueHr, (unsigned long)unknownDeviceHr);
      if(SUCCEEDED(queueHr)) Identity("swap-getdevice-typed-queue", queue.Get(), typedQueue.Get());
      if(SUCCEEDED(deviceHr)) Identity("swap-getdevice-typed-device", device.Get(), typedDevice.Get());
      if(SUCCEEDED(unknownQueueHr)) Identity("swap-getdevice-iunknown-queue", queue.Get(), unknownQueue.Get());
      if(SUCCEEDED(unknownDeviceHr)) Identity("swap-getdevice-iunknown-device", device.Get(), unknownDevice.Get());
      auto refcount = [](IUnknown *object) { object->AddRef(); return object->Release(); };
      const ULONG deviceRefs = refcount(device.Get()), queueRefs = refcount(queue.Get());
      for(unsigned n = 0; n < 64; ++n)
      {
        ComPtr<ID3D12Device> typed;
        ComPtr<IUnknown> unknown;
        Check(swap->GetDevice(IID_PPV_ARGS(&typed)));
        Check(swap->GetDevice(IID_PPV_ARGS(&unknown)));
      }
      bool balanced = deviceRefs == refcount(device.Get()) && queueRefs == refcount(queue.Get());
      std::printf("getdevice-reference-balance equal=%d\n", balanced);
      if(!balanced) throw std::runtime_error("GetDevice wrapper references unbalanced");
      // Use the formerly escaped device to create, record and submit real work.
      ComPtr<ID3D12CommandQueue> returnedQueue;
      ComPtr<ID3D12CommandAllocator> returnedAllocator;
      ComPtr<ID3D12GraphicsCommandList> returnedList;
      ComPtr<ID3D12Device> returnedOwner;
      Check(unknownDevice->CreateCommandQueue(&q, IID_PPV_ARGS(&returnedQueue)));
      Check(returnedQueue->GetDevice(IID_PPV_ARGS(&returnedOwner)));
      Identity("returned-device-created-queue", device.Get(), returnedOwner.Get());
      Check(unknownDevice->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,
                                                 IID_PPV_ARGS(&returnedAllocator)));
      Check(unknownDevice->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT,
                                            returnedAllocator.Get(), nullptr, IID_PPV_ARGS(&returnedList)));
      Check(returnedList->Close());
      ID3D12CommandList *work[] = {returnedList.Get()};
      returnedQueue->ExecuteCommandLists(1, work);

    }
    ComPtr<IDXGIFactory4> parentA, parentB;
    Check(swap->GetParent(IID_PPV_ARGS(&parentA)));
    Check(swap->GetParent(IID_PPV_ARGS(&parentB)));
    Identity("factory-self-repeat", factory.Get(), factory.Get());
    Identity("parent-self-repeat", parentA.Get(), parentA.Get());
    ComPtr<IUnknown> unknownParent;
    ComPtr<IDXGIObject> objectParent;
    Check(swap->GetParent(IID_PPV_ARGS(&unknownParent)));
    Check(swap->GetParent(IID_PPV_ARGS(&objectParent)));
    Identity("factory-parent-iunknown", factory.Get(), unknownParent.Get());
    Identity("factory-parent-idxgiobject", factory.Get(), objectParent.Get());
    Identity("factory-parent-repeat", parentA.Get(), parentB.Get());
    Identity("factory-parent-original", factory.Get(), parentA.Get());
    std::atomic<unsigned> mismatches(0);
    std::thread workers[4];
    for(auto &worker : workers)
      worker = std::thread([&]() {
        for(unsigned n = 0; n < 32; ++n)
        {
          ComPtr<IDXGIFactory4> parent;
          ComPtr<IUnknown> expected, actual;
          if(FAILED(swap->GetParent(IID_PPV_ARGS(&parent))) ||
             FAILED(parentA.As(&expected)) || FAILED(parent.As(&actual)) ||
             expected.Get() != actual.Get()) ++mismatches;
        }
      });
    for(auto &worker : workers) worker.join();
    std::printf("factory-concurrent-parent mismatches=%u\n", mismatches.load());
    // Keep one wrapper reference while releasing the original root and reacquiring its parent.
    factory.Reset(); parentB.Reset();
    Check(swap->GetParent(IID_PPV_ARGS(&parentB)));
    Identity("factory-after-root-release", parentA.Get(), parentB.Get());
    Check(parentB.As(&factory));
    // The adapter retains the real factory, but no wrapper reference survives
    // each iteration. Exercise weak-cache retirement and concurrent recreation.
    ComPtr<IDXGIFactory4> transientFactory;
    ComPtr<IDXGIAdapter> adapter;
    Check(CreateDXGIFactory2(0, IID_PPV_ARGS(&transientFactory)));
    Check(transientFactory->EnumAdapters(0, &adapter));
    transientFactory.Reset();
    mismatches = 0;
    for(auto &worker : workers)
      worker = std::thread([&]() {
        for(unsigned n = 0; n < 64; ++n)
        {
          ComPtr<IDXGIFactory4> first, next;
          ComPtr<IUnknown> x, y;
          if(FAILED(adapter->GetParent(IID_PPV_ARGS(&first))) ||
             FAILED(adapter->GetParent(IID_PPV_ARGS(&next))) ||
             FAILED(first.As(&x)) || FAILED(next.As(&y)) || x.Get() != y.Get())
            ++mismatches;
        }
      });
    for(auto &worker : workers) worker.join();
    std::printf("factory-retire-reacquire mismatches=%u\n", mismatches.load());

    D3D12_DESCRIPTOR_HEAP_DESC hd = {};
    hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV; hd.NumDescriptors = 2;
    ComPtr<ID3D12DescriptorHeap> heap;
    Check(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&heap)));
    UINT increment = device->GetDescriptorHandleIncrementSize(hd.Type);
    ComPtr<ID3D12Resource> buffers[2];
    auto makeBuffers = [&]() {
      for(UINT i = 0; i < 2; i++)
      {
        Check(swap->GetBuffer(i, IID_PPV_ARGS(&buffers[i])));
        auto handle = heap->GetCPUDescriptorHandleForHeapStart();
        handle.ptr += i * increment;
        device->CreateRenderTargetView(buffers[i].Get(), nullptr, handle);
      }
    };
    makeBuffers();
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> list;
    Check(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)));
    Check(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr,
                                  IID_PPV_ARGS(&list)));
    Check(list->Close());
    ComPtr<ID3D12Fence> fence;
    Check(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)));
    HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if(!event) throw std::runtime_error("fence event failed");
    UINT64 fenceValue = 0;
    auto wait = [&]() {
      Check(queue->Signal(fence.Get(), ++fenceValue));
      Check(fence->SetEventOnCompletion(fenceValue, event));
      if(WaitForSingleObject(event, 10000) != WAIT_OBJECT_0)
        throw std::runtime_error("GPU fence timeout");
    };

    const char *shader =
        "float4 VS(uint id:SV_VertexID):SV_Position {"
        "float2 p[3]={float2(0,0.75),float2(0.75,-0.75),float2(-0.75,-0.75)};"
        "return float4(p[id],0,1); }"
        "float4 PS():SV_Target {return float4(0.9,0.3,0.1,1);}";
    ComPtr<ID3DBlob> vs, ps, sigBlob, error;
    Check(D3DCompile(shader, strlen(shader), nullptr, nullptr, nullptr, "VS", "vs_5_0", 0, 0, &vs, &error));
    Check(D3DCompile(shader, strlen(shader), nullptr, nullptr, nullptr, "PS", "ps_5_0", 0, 0, &ps, &error));
    D3D12_ROOT_SIGNATURE_DESC rsd = {};
    rsd.Flags = D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT;
    Check(D3D12SerializeRootSignature(&rsd, D3D_ROOT_SIGNATURE_VERSION_1, &sigBlob, &error));
    ComPtr<ID3D12RootSignature> signature;
    Check(device->CreateRootSignature(0, sigBlob->GetBufferPointer(), sigBlob->GetBufferSize(),
                                     IID_PPV_ARGS(&signature)));
    D3D12_GRAPHICS_PIPELINE_STATE_DESC pd = {};
    pd.pRootSignature = signature.Get();
    pd.VS = {vs->GetBufferPointer(), vs->GetBufferSize()};
    pd.PS = {ps->GetBufferPointer(), ps->GetBufferSize()};
    pd.BlendState.RenderTarget[0].RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
    pd.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
    pd.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
    pd.RasterizerState.DepthClipEnable = TRUE;
    pd.SampleMask = UINT_MAX; pd.SampleDesc.Count = 1;
    pd.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
    pd.NumRenderTargets = 1; pd.RTVFormats[0] = desc.Format;
    ComPtr<ID3D12PipelineState> pipeline;
    Check(device->CreateGraphicsPipelineState(&pd, IID_PPV_ARGS(&pipeline)));

    for(UINT frame = 0; frame < 2; frame++)
    {
      if(frame == 1 && secondDevice)
      {
        // Render the second capture on the distinct WARP device/queue, rather
        // than treating successful creation as proof of second-device capture.
        list.Reset(); allocator.Reset(); pipeline.Reset(); signature.Reset();
        buffers[0].Reset(); buffers[1].Reset(); heap.Reset(); fence.Reset();
        swap.Reset(); swap1.Reset();
        device = secondDevice; queue = secondQueue; factory = secondFactory;
        Check(factory->CreateSwapChainForHwnd(queue.Get(), window, &desc, nullptr, nullptr, &swap1));
        Check(swap1.As(&swap));
        ComPtr<IDXGIFactory4> parent;
        ComPtr<ID3D12Device> owner;
        Check(swap->GetParent(IID_PPV_ARGS(&parent)));
        Check(queue->GetDevice(IID_PPV_ARGS(&owner)));
        Identity("second-factory-parent", factory.Get(), parent.Get());
        Identity("second-queue-device", device.Get(), owner.Get());
        increment = device->GetDescriptorHandleIncrementSize(hd.Type);
        Check(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&heap)));
        makeBuffers();
        Check(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)));
        Check(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr,
                                       IID_PPV_ARGS(&list)));
        Check(list->Close());
        Check(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)));
        fenceValue = 0;
        Check(device->CreateRootSignature(0, sigBlob->GetBufferPointer(), sigBlob->GetBufferSize(),
                                         IID_PPV_ARGS(&signature)));
        pd.pRootSignature = signature.Get();
        Check(device->CreateGraphicsPipelineState(&pd, IID_PPV_ARGS(&pipeline)));
      }
      LUID captureAdapter = device->GetAdapterLuid();
      std::printf("capture-device frame=%u luid=%08lx:%08lx\n", frame,
                  (unsigned long)captureAdapter.HighPart, (unsigned long)captureAdapter.LowPart);
      if(frame == 1 && mode == "resize")
      {
        buffers[0].Reset(); buffers[1].Reset();
        desc.Width = 400; desc.Height = 300;
        Check(swap->ResizeBuffers(2, desc.Width, desc.Height, desc.Format, 0));
        makeBuffers();
        std::printf("resize completed width=400 height=300\n");
      }
      api->StartFrameCapture(nullptr, window);
      if(!api->IsFrameCapturing()) throw std::runtime_error("capture did not start");
      Check(allocator->Reset());
      Check(list->Reset(allocator.Get(), pipeline.Get()));
      UINT index = swap->GetCurrentBackBufferIndex();
      D3D12_RESOURCE_BARRIER barrier = {};
      barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
      barrier.Transition = {buffers[index].Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                            D3D12_RESOURCE_STATE_PRESENT, D3D12_RESOURCE_STATE_RENDER_TARGET};
      list->ResourceBarrier(1, &barrier);
      auto rt = heap->GetCPUDescriptorHandleForHeapStart(); rt.ptr += index * increment;
      const float clear[4] = {0.1f, 0.2f, 0.3f, 1.0f};
      list->ClearRenderTargetView(rt, clear, 0, nullptr);
      list->OMSetRenderTargets(1, &rt, FALSE, nullptr);
      list->SetGraphicsRootSignature(signature.Get());
      D3D12_VIEWPORT viewport = {0,0,(float)desc.Width,(float)desc.Height,0,1};
      D3D12_RECT scissor = {0,0,(LONG)desc.Width,(LONG)desc.Height};
      list->RSSetViewports(1, &viewport); list->RSSetScissorRects(1, &scissor);
      list->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
      list->DrawInstanced(3, 1, 0, 0);
      barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_RENDER_TARGET;
      barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_PRESENT;
      list->ResourceBarrier(1, &barrier);
      Check(list->Close());
      ID3D12CommandList *submit[] = {list.Get()};
      queue->ExecuteCommandLists(1, submit);
      Check(swap->Present(0, 0));
      wait();
      if(!api->EndFrameCapture(nullptr, window)) throw std::runtime_error("capture did not finish");
      std::printf("capture completed frame=%u\n", frame);
    }
    CloseHandle(event);
    DestroyWindow(window);
    return 0;
  }
  catch(const std::exception &e)
  {
    std::printf("FAIL: %s\n", e.what());
    return 1;
  }
}
