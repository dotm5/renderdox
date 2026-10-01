#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <cstdint>
#include <cstring>
#include "api/app/renderdoc_app.h"
static volatile LONG Handshakes=0, Starts=0, Ends=0, Capturing=0, HandshakeEntered=0, ReentryPassed=0;
static RENDERDOC_DevicePointer LastDevice=nullptr;
static void __cdecl Start(RENDERDOC_DevicePointer device,RENDERDOC_WindowHandle) { LastDevice=device; InterlockedIncrement(&Starts); InterlockedExchange(&Capturing,1); }
static uint32_t __cdecl End(RENDERDOC_DevicePointer,RENDERDOC_WindowHandle) { InterlockedIncrement(&Ends); InterlockedExchange(&Capturing,0); return 1; }
static uint32_t __cdecl IsCapturing() { return InterlockedCompareExchange(&Capturing,0,0); }
static RENDERDOC_API_1_6_0 Api = {};
extern "C" __declspec(dllexport) int __cdecl DCOMP_GetAPI(DCOMP_Version version,void **out)
{
  if(!out || version!=eDCOMP_API_Version_1_6_0) return 0;
  wchar_t gateName[192]={};
  if(GetEnvironmentVariableW(L"PB_TEST_API_GATE",gateName,ARRAYSIZE(gateName))) {
    HANDLE gate=OpenEventW(SYNCHRONIZE,FALSE,gateName);
    if(!gate) return 0;
    InterlockedExchange(&HandshakeEntered,1);
    DWORD wait=WaitForSingleObject(gate,10000);
    CloseHandle(gate);
    if(wait!=WAIT_OBJECT_0) return 0;
  }
  wchar_t option[8]={};
  if(GetEnvironmentVariableW(L"PB_TEST_CORE_REENTER",option,ARRAYSIZE(option))==1 && option[0]==L'1') {
    using Sum=uint64_t (*)(uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t);
    HMODULE proxy=GetModuleHandleW(L"fixture.dll");
    auto sum=proxy ? reinterpret_cast<Sum>(GetProcAddress(proxy,"Sum8")) : nullptr;
    if(!sum || sum(1,2,3,4,5,6,7,8)!=204) return 0;
    InterlockedExchange(&ReentryPassed,1);
  }
  if(GetEnvironmentVariableW(L"PB_TEST_API_FAIL",option,ARRAYSIZE(option))==1 && option[0]==L'1') return 0;
  Api.StartFrameCapture=Start; Api.EndFrameCapture=End; Api.IsFrameCapturing=IsCapturing;
  InterlockedIncrement(&Handshakes); *out=&Api; return 1;
}
extern "C" __declspec(dllexport) LONG TestHandshakeCount() { return InterlockedCompareExchange(&Handshakes,0,0); }
extern "C" __declspec(dllexport) LONG TestHandshakeEntered() { return InterlockedCompareExchange(&HandshakeEntered,0,0); }
extern "C" __declspec(dllexport) LONG TestReentryPassed() { return InterlockedCompareExchange(&ReentryPassed,0,0); }
extern "C" __declspec(dllexport) LONG TestStartCount() { return InterlockedCompareExchange(&Starts,0,0); }
extern "C" __declspec(dllexport) LONG TestEndCount() { return InterlockedCompareExchange(&Ends,0,0); }
extern "C" __declspec(dllexport) void *TestLastDevice() { return LastDevice; }
using Query=FARPROC (WINAPI *)(void *,const char *);
struct VkNegotiation { int type; void *next; uint32_t version; Query instance; Query device; Query physical; };
static void WINAPI VkMarker() {}
extern "C" __declspec(dllexport) FARPROC WINAPI VK_LAYER_DCOMP_CaptureGetInstanceProcAddr(void *,const char *name)
{ return name && !strcmp(name,"vkOwnedMarker") ? reinterpret_cast<FARPROC>(VkMarker) : nullptr; }
extern "C" __declspec(dllexport) FARPROC WINAPI VK_LAYER_DCOMP_CaptureGetDeviceProcAddr(void *handle,const char *name)
{ return VK_LAYER_DCOMP_CaptureGetInstanceProcAddr(handle,name); }
extern "C" __declspec(dllexport) int WINAPI VK_LAYER_DCOMP_CaptureNegotiateLoaderLayerInterfaceVersion(VkNegotiation *value)
{
  if(!value || value->version<2) return -3;
  value->version=2; value->instance=VK_LAYER_DCOMP_CaptureGetInstanceProcAddr;
  value->device=VK_LAYER_DCOMP_CaptureGetDeviceProcAddr; value->physical=nullptr; return 0;
}
extern "C" __declspec(dllexport) int WINAPI VK_LAYER_DCOMP_CaptureEnumerateInstanceExtensionProperties(const char *,uint32_t *count,void *)
{ if(!count) return -3; *count=0; return 0; }
