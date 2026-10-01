#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <unknwn.h>
#include "openxr/openxr.h"
#include "openxr/openxr_loader_negotiation.h"
using Int=uint64_t (*)(uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t);
using Count=LONG (*)();
using Init=int (*)();
#define CHECK(test) do { if(!(test)) { printf("FAIL line %d: %s\n",__LINE__,#test); return 1; } } while(0)
static LONG CoreCount(const char *name) {
  HMODULE core=GetModuleHandleW(L"dgcore.dll");
  auto fn=core ? reinterpret_cast<Count>(GetProcAddress(core,name)) : nullptr;
  return fn ? fn() : 0;
}
static bool WaitCore() { for(int i=0;i<300;++i) { if(CoreCount("TestHandshakeCount")==1) return true; Sleep(10); } return false; }
static XrInstance Instance1=reinterpret_cast<XrInstance>(1), Instance2=reinterpret_cast<XrInstance>(2);
static uintptr_t InstanceCounter=0, SessionCounter=0;
static uint64_t Marker1() { return 1; }
static uint64_t Marker2() { return 2; }
static XrResult XRAPI_CALL XRCreateSession(XrInstance,const XrSessionCreateInfo *,XrSession *out) { *out=reinterpret_cast<XrSession>(++SessionCounter); return XR_SUCCESS; }
static XrResult XRAPI_CALL XRDestroySession(XrSession) { return XR_SUCCESS; }
static XrResult XRAPI_CALL XRDestroyInstance(XrInstance) { return XR_SUCCESS; }
static XrResult XRAPI_CALL XRBegin(XrSession,const XrFrameBeginInfo *) { return XR_SUCCESS; }
static XrResult XRAPI_CALL XREnd(XrSession,const XrFrameEndInfo *) { return XR_SUCCESS; }
static XrResult XRAPI_CALL XRQuery(XrInstance instance,const char *name,PFN_xrVoidFunction *out)
{
  *out=nullptr;
  if(!strcmp(name,"xrCreateSession")) *out=reinterpret_cast<PFN_xrVoidFunction>(XRCreateSession);
  else if(!strcmp(name,"xrDestroySession")) *out=reinterpret_cast<PFN_xrVoidFunction>(XRDestroySession);
  else if(!strcmp(name,"xrDestroyInstance")) *out=reinterpret_cast<PFN_xrVoidFunction>(XRDestroyInstance);
  else if(!strcmp(name,"xrBeginFrame")) *out=reinterpret_cast<PFN_xrVoidFunction>(XRBegin);
  else if(!strcmp(name,"xrEndFrame")) *out=reinterpret_cast<PFN_xrVoidFunction>(XREnd);
  else if(!strcmp(name,"xrOwnedMarker")) *out=reinterpret_cast<PFN_xrVoidFunction>(instance==Instance1 ? Marker1 : Marker2);
  return *out ? XR_SUCCESS : XR_ERROR_FUNCTION_UNSUPPORTED;
}
static XrResult XRAPI_CALL XRCreate(const XrInstanceCreateInfo *,const XrApiLayerCreateInfo *next,XrInstance *out)
{ if(next->nextInfo) return XR_ERROR_INITIALIZATION_FAILED; *out=reinterpret_cast<XrInstance>(++InstanceCounter); return XR_SUCCESS; }
static int TestXR(HMODULE host)
{
  auto negotiate=reinterpret_cast<PFN_xrNegotiateLoaderApiLayerInterface>(GetProcAddress(host,"xrNegotiateLoaderApiLayerInterface"));
  CHECK(negotiate);
  XrNegotiateLoaderInfo loader={}; loader.structType=XR_LOADER_INTERFACE_STRUCT_LOADER_INFO; loader.structVersion=1; loader.structSize=sizeof(loader);
  loader.minInterfaceVersion=1; loader.maxInterfaceVersion=1; loader.minApiVersion=XR_MAKE_VERSION(1,0,0); loader.maxApiVersion=XR_MAKE_VERSION(1,1,0);
  XrNegotiateApiLayerRequest request={}; request.structType=XR_LOADER_INTERFACE_STRUCT_API_LAYER_REQUEST; request.structVersion=1; request.structSize=sizeof(request);
  CHECK(negotiate(nullptr,"XR_APILAYER_DCOMP_capture",&request)==XR_ERROR_INITIALIZATION_FAILED);
  CHECK(negotiate(&loader,"wrong_layer",&request)==XR_ERROR_INITIALIZATION_FAILED);
  CHECK(negotiate(&loader,"XR_APILAYER_DCOMP_capture",&request)==XR_SUCCESS);
  CHECK(CoreCount("TestHandshakeCount")==1);
  XrApiLayerNextInfo next={}; next.structType=XR_LOADER_INTERFACE_STRUCT_API_LAYER_NEXT_INFO; next.structVersion=1; next.structSize=sizeof(next);
  next.nextGetInstanceProcAddr=XRQuery; next.nextCreateApiLayerInstance=XRCreate;
  XrApiLayerCreateInfo layer={}; layer.structType=XR_LOADER_INTERFACE_STRUCT_API_LAYER_CREATE_INFO; layer.structVersion=1; layer.structSize=sizeof(layer); layer.nextInfo=&next;
  XrInstanceCreateInfo info={}; info.type=XR_TYPE_INSTANCE_CREATE_INFO;
  XrInstance instances[2]={};
  for(int i=0;i<2;++i) CHECK(request.createApiLayerInstance(&info,&layer,&instances[i])==XR_SUCCESS);
  CHECK(instances[0]==Instance1 && instances[1]==Instance2);
  PFN_xrVoidFunction marker=nullptr;
  CHECK(request.getInstanceProcAddr(instances[0],"xrOwnedMarker",&marker)==XR_SUCCESS && marker==reinterpret_cast<PFN_xrVoidFunction>(Marker1));
  CHECK(request.getInstanceProcAddr(instances[1],"xrOwnedMarker",&marker)==XR_SUCCESS && marker==reinterpret_cast<PFN_xrVoidFunction>(Marker2));
  CHECK(request.getInstanceProcAddr(instances[0],"unknown",&marker)==XR_ERROR_FUNCTION_UNSUPPORTED && !marker);
  PFN_xrCreateSession create=nullptr; PFN_xrBeginFrame begin=nullptr; PFN_xrEndFrame end=nullptr;
  PFN_xrDestroySession destroy=nullptr; PFN_xrDestroyInstance destroyInstance=nullptr;
  CHECK(request.getInstanceProcAddr(instances[0],"xrCreateSession",reinterpret_cast<PFN_xrVoidFunction *>(&create))==XR_SUCCESS);
  CHECK(request.getInstanceProcAddr(instances[0],"xrBeginFrame",reinterpret_cast<PFN_xrVoidFunction *>(&begin))==XR_SUCCESS);
  CHECK(request.getInstanceProcAddr(instances[0],"xrEndFrame",reinterpret_cast<PFN_xrVoidFunction *>(&end))==XR_SUCCESS);
  CHECK(request.getInstanceProcAddr(instances[0],"xrDestroySession",reinterpret_cast<PFN_xrVoidFunction *>(&destroy))==XR_SUCCESS);
  CHECK(request.getInstanceProcAddr(instances[0],"xrDestroyInstance",reinterpret_cast<PFN_xrVoidFunction *>(&destroyInstance))==XR_SUCCESS);
  struct Binding { XrStructureType type; const void *next; void *device; } binding={XR_TYPE_GRAPHICS_BINDING_D3D12_KHR,nullptr,reinterpret_cast<void *>(0x1234)};
  // An unrelated header preceding the graphics binding verifies full pNext walking.
  XrBaseInStructure preceding={XR_TYPE_UNKNOWN,reinterpret_cast<XrBaseInStructure *>(&binding)};
  XrSessionCreateInfo sessionInfo={}; sessionInfo.type=XR_TYPE_SESSION_CREATE_INFO; sessionInfo.next=&preceding;
  XrSession sessions[2]={}; CHECK(create(instances[0],&sessionInfo,&sessions[0])==XR_SUCCESS); CHECK(create(instances[1],&sessionInfo,&sessions[1])==XR_SUCCESS);
  XrFrameBeginInfo frame={}; frame.type=XR_TYPE_FRAME_BEGIN_INFO;
  XrFrameEndInfo finish={}; finish.type=XR_TYPE_FRAME_END_INFO;
  CHECK(begin(sessions[0],&frame)==XR_SUCCESS && CoreCount("TestStartCount")==1);
  CHECK(begin(sessions[1],&frame)==XR_SUCCESS && CoreCount("TestStartCount")==1);
  CHECK(end(sessions[1],&finish)==XR_SUCCESS && CoreCount("TestEndCount")==0);
  CHECK(end(sessions[0],&finish)==XR_SUCCESS && CoreCount("TestEndCount")==1);
  CHECK(begin(sessions[0],&frame)==XR_SUCCESS && CoreCount("TestStartCount")==1);
  CHECK(end(sessions[0],&finish)==XR_SUCCESS && CoreCount("TestEndCount")==1);
  CHECK(destroy(sessions[0])==XR_SUCCESS && destroy(sessions[1])==XR_SUCCESS);
  CHECK(destroyInstance(instances[0])==XR_SUCCESS && destroyInstance(instances[1])==XR_SUCCESS);
  CHECK(request.getInstanceProcAddr(instances[0],"xrOwnedMarker",&marker)==XR_ERROR_HANDLE_INVALID);
  return 0;
}
struct FactoryInterface : IUnknown { virtual uint64_t STDMETHODCALLTYPE CreateOwnedDevice(uint64_t)=0; };
int wmain(int argc,wchar_t **argv)
{
  SetErrorMode(SEM_FAILCRITICALERRORS|SEM_NOGPFAULTERRORBOX);
  if(argc<3) return 2;
  // DATA forwarders follow Windows loader search rules. Register the owned
  // fixture folder, matching deployment beside the application's executable.
  wchar_t directory[32768]={}; wcscpy_s(directory,argv[2]);
  wchar_t *last=wcsrchr(directory,L'\\'); if(last) *last=0;
  SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
  DLL_DIRECTORY_COOKIE cookie=AddDllDirectory(directory); CHECK(cookie);
  const wchar_t *mode=argv[1];
  HANDLE gate=nullptr;
  if(!wcscmp(mode,L"worker-no-block")) {
    wchar_t name[96]={}; swprintf_s(name,L"Local\\PBTestGate_%lu",GetCurrentProcessId());
    gate=CreateEventW(nullptr,TRUE,FALSE,name); CHECK(gate);
    CHECK(SetEnvironmentVariableW(L"PB_TEST_API_GATE",name));
  }
  if(!wcscmp(mode,L"reentrant-core") || !wcscmp(mode,L"reentrant-core-fail"))
    CHECK(SetEnvironmentVariableW(L"PB_TEST_CORE_REENTER",L"1"));
  if(!wcscmp(mode,L"reentrant-core-fail")) CHECK(SetEnvironmentVariableW(L"PB_TEST_API_FAIL",L"1"));
  HMODULE proxy=LoadLibraryExW(argv[2],nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS); CHECK(proxy);
  auto init=reinterpret_cast<Init>(GetProcAddress(proxy,"DCompProxyInitialize"));
  auto check=reinterpret_cast<Init>(GetProcAddress(proxy,"DCompProxyCheckProvider"));
  auto error=reinterpret_cast<Count>(GetProcAddress(proxy,"DCompProxyGetLastError"));
  auto sum=reinterpret_cast<Int>(GetProcAddress(proxy,"Sum8"));
  if(!wcscmp(mode,L"worker-load-only") || !wcscmp(mode,L"aftermath")) {
    // No Initialize or SDK function has been invoked: loading the carrier
    // alone must start Core, while the original remains lazily unloaded.
    CHECK(WaitCore());
    CHECK(!GetModuleHandleW(L"fixture_orig.dll"));
    CHECK(!GetModuleHandleW(L"GFSDK_Aftermath_Lib_orig.dll"));
    CHECK(!GetModuleHandleW(L"GFSDK_Aftermath_Lib.x64.orig.dll"));
    CHECK(!GetModuleHandleW(L"GFSDK_Aftermath_Lib_orig.x64.dll"));
    CHECK(sum && sum(1,2,3,4,5,6,7,8)==204);
  } else if(!wcscmp(mode,L"worker-no-block")) {
    for(int i=0;i<300 && !CoreCount("TestHandshakeEntered");++i) Sleep(10);
    CHECK(CoreCount("TestHandshakeEntered")==1 && CoreCount("TestHandshakeCount")==0);
    ULONGLONG start=GetTickCount64();
    CHECK(sum && sum(1,2,3,4,5,6,7,8)==204 && GetTickCount64()-start<2500);
    CHECK(CoreCount("TestHandshakeCount")==0); CHECK(SetEvent(gate)); CHECK(WaitCore()); CloseHandle(gate);
  } else if(!wcscmp(mode,L"reentrant-core") || !wcscmp(mode,L"reentrant-core-fail")) {
    CHECK(sum && sum(1,2,3,4,5,6,7,8)==204);
    if(!wcscmp(mode,L"reentrant-core-fail")) { printf("FAIL required Core failure was bypassed\n"); return 1; }
    CHECK(CoreCount("TestReentryPassed")==1 && CoreCount("TestHandshakeCount")==1);
    CHECK(sum(1,2,3,4,5,6,7,8)==204 && CoreCount("TestHandshakeCount")==1);
  } else if(!wcscmp(mode,L"aftermath-first-call")) {
    CHECK(!GetModuleHandleW(L"dgcore.dll"));
    CHECK(sum && sum(1,2,3,4,5,6,7,8)==204 && CoreCount("TestHandshakeCount")==1);
  } else if(!wcscmp(mode,L"required-worker-plugin-fail")) {
    CHECK(WaitCore());
    CHECK(sum && sum(1,2,3,4,5,6,7,8)==204);
    printf("FAIL required plugin failure was bypassed\n"); return 1;
  } else if(!wcscmp(mode,L"openxr")) CHECK(TestXR(proxy)==0);
  else if(!wcscmp(mode,L"host")) { CHECK(init && init()==1 && CoreCount("TestHandshakeCount")==1); }
  else if(!wcscmp(mode,L"missing-core")) { CHECK(init && init()==0); CHECK(error && error()!=0); }
  else if(!wcscmp(mode,L"bad-provider")) { CHECK(check && check()==0); CHECK(error && error()==ERROR_CRC); }
  else if(!wcscmp(mode,L"cycle")) { CHECK(check && check()==0); CHECK(error && error()==ERROR_CIRCULAR_DEPENDENCY); }
  else if(!wcscmp(mode,L"module-load")) {
    CHECK(sum && sum(1,2,3,4,5,6,7,8)==204 && CoreCount("TestHandshakeCount")==0);
    CHECK(argc==4 && LoadLibraryW(argv[3])); CHECK(WaitCore());
  } else if(!wcscmp(mode,L"export")) {
    auto floating=reinterpret_cast<double (*)(double,double,double,double,double,double,double,double)>(GetProcAddress(proxy,"Float8"));
    CHECK(floating && floating(1,2,3,4,5,6,7,8)==204 && CoreCount("TestHandshakeCount")==0);
    CHECK(sum && sum(1,2,3,4,5,6,7,8)==204 && CoreCount("TestHandshakeCount")==1);
  } else if(!wcscmp(mode,L"data")) {
    auto value=reinterpret_cast<uint32_t *>(GetProcAddress(proxy,"ExportedData"));
    auto alias=reinterpret_cast<uint32_t *>(GetProcAddress(proxy,"DataAlias"));
    HMODULE original=GetModuleHandleW(L"fixture_orig.dll"); CHECK(original && value && value==alias && *value==42);
    CHECK(value==reinterpret_cast<uint32_t *>(GetProcAddress(original,"ExportedData"))); *value=91; CHECK(*alias==91);
    CHECK(sum && sum(1,2,3,4,5,6,7,8)==204);
  } else if(!wcscmp(mode,L"nvapi")) {
    auto query=reinterpret_cast<FARPROC (__cdecl *)(uint32_t)>(GetProcAddress(proxy,"nvapi_QueryInterface")); CHECK(query);
    CHECK(query(0x1234)==reinterpret_cast<FARPROC>(sum)); CHECK(reinterpret_cast<Int>(query(0x1234))(1,2,3,4,5,6,7,8)==204);
    CHECK(!query(0)); CHECK(reinterpret_cast<uint64_t (*)()>(query(0x9999))()==73);
  } else if(!wcscmp(mode,L"mixed")) {
    auto nv=reinterpret_cast<FARPROC (__cdecl *)(uint32_t)>(GetProcAddress(proxy,"nvapi_QueryInterface"));
    auto vk=reinterpret_cast<FARPROC (WINAPI *)(void *,const char *)>(GetProcAddress(proxy,"vkGetDeviceProcAddr"));
    CHECK(nv && vk && nv(0x1234)==reinterpret_cast<FARPROC>(sum) && vk(nullptr,"vkSum8")==reinterpret_cast<FARPROC>(sum));
    CHECK(reinterpret_cast<Int>(nv(0x1234))(1,2,3,4,5,6,7,8)==204);
    CHECK(reinterpret_cast<Int>(vk(nullptr,"vkSum8"))(1,2,3,4,5,6,7,8)==204);
    CHECK(!nv(0) && !vk(nullptr,"missing") && CoreCount("TestHandshakeCount")==1);
  } else if(!wcscmp(mode,L"vulkan")) {
    auto query=reinterpret_cast<FARPROC (WINAPI *)(void *,const char *)>(GetProcAddress(proxy,"vkGetDeviceProcAddr")); CHECK(query);
    CHECK(query(reinterpret_cast<void *>(1),"vkSum8")==reinterpret_cast<FARPROC>(sum));
    CHECK(reinterpret_cast<Int>(query(reinterpret_cast<void *>(1),"vkSum8"))(1,2,3,4,5,6,7,8)==204);
    CHECK(reinterpret_cast<uint64_t (*)()>(query(reinterpret_cast<void *>(99),"vkSum8"))()==73);
    CHECK(!query(nullptr,"unknown") && !query(nullptr,nullptr));
    CHECK(query(nullptr,"vkGetDeviceProcAddr")==reinterpret_cast<FARPROC>(query));
  } else if(!wcscmp(mode,L"agility")) {
    auto get=reinterpret_cast<HRESULT (WINAPI *)(REFCLSID,REFIID,void **)>(GetProcAddress(proxy,"D3D12GetInterface")); CHECK(get);
    FactoryInterface *factory=nullptr; GUID id={}; CHECK(get(id,id,reinterpret_cast<void **>(&factory))==S_OK && factory);
    CHECK(factory->CreateOwnedDevice(25)==42); factory->Release(); CHECK(CoreCount("TestHandshakeCount")==1);
  } else if(!wcscmp(mode,L"vulkan-layer")) {
    using Query=FARPROC (WINAPI *)(void *,const char *);
    struct Version { int type; void *next; uint32_t version; Query instance; Query device; Query physical; } value={};
    value.version=2;
    auto negotiate=reinterpret_cast<int (WINAPI *)(Version *)>(GetProcAddress(proxy,"VK_LAYER_DCOMP_CaptureNegotiateLoaderLayerInterfaceVersion")); CHECK(negotiate);
    CHECK(negotiate(&value)==0 && value.version==2 && value.instance && value.device);
    CHECK(value.instance(nullptr,"vkOwnedMarker") && !value.instance(nullptr,"unknown")); CHECK(CoreCount("TestHandshakeCount")==1);
  } else {
    CHECK(sum && sum(1,2,3,4,5,6,7,8)==204); CHECK(CoreCount("TestHandshakeCount")==1);
    auto saw=reinterpret_cast<Count>(GetProcAddress(proxy,"OriginalSawCore")); CHECK(saw && saw()==1);
    if(!wcscmp(mode,L"plugin")) { CHECK(argc==4); HMODULE plugin=GetModuleHandleW(argv[3]); CHECK(plugin);
      auto seen=reinterpret_cast<Count>(GetProcAddress(plugin,"PluginSawCore")); CHECK(seen && seen()==1); }
  }
  printf("{\"routePassed\":true,\"handshakes\":%ld}\n",CoreCount("TestHandshakeCount"));
  return 0;
}
