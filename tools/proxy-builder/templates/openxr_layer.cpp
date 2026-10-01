// OpenXR API layer: loader negotiation and per-instance/session dispatch.
// Uses Khronos headers; DComp-specific implementation is original code.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <cstring>
#include <mutex>
#include <unordered_map>
#include "openxr/openxr.h"
#include "openxr/openxr_loader_negotiation.h"
#include "api/app/renderdoc_app.h"
#include "host_config.h"
extern bool PBEnsureCore();
extern RENDERDOC_API_1_6_0 *PBApi;
namespace {
struct InstanceDispatch {
  PFN_xrGetInstanceProcAddr query;
  PFN_xrCreateSession create;
  PFN_xrDestroySession destroySession;
  PFN_xrDestroyInstance destroyInstance;
  PFN_xrBeginFrame begin;
  PFN_xrEndFrame end;
};
struct SessionDispatch { InstanceDispatch dispatch; void *device; XrInstance instance; uint64_t frame; };
std::mutex Tables;
std::recursive_mutex Capture;
std::unordered_map<XrInstance,InstanceDispatch> Instances;
std::unordered_map<XrSession,SessionDispatch> Sessions;
XrSession Active = XR_NULL_HANDLE;
void *ActiveDevice = nullptr;
// Binding layouts from the OpenXR platform ABI. Keep graphics handles opaque:
// no D3D/Vulkan SDK or driver is linked into this bootstrap layer.
struct DeviceBinding { XrStructureType type; const void *next; void *device; };
struct VulkanBinding { XrStructureType type; const void *next; void *instance; void *physical; void *device; uint32_t family; uint32_t index; };
struct GLBinding { XrStructureType type; const void *next; void *dc; void *rc; };
void *Device(const void *chain) {
  auto next = static_cast<const XrBaseInStructure *>(chain);
  const XrBaseInStructure *seen[64] = {};
  for(size_t i=0; next && i<64; ++i) {
    for(size_t j=0;j<i;++j) if(seen[j]==next) return nullptr;
    seen[i]=next;
    if(next->type==XR_TYPE_GRAPHICS_BINDING_D3D11_KHR || next->type==XR_TYPE_GRAPHICS_BINDING_D3D12_KHR)
      return reinterpret_cast<const DeviceBinding *>(next)->device;
    if(next->type==XR_TYPE_GRAPHICS_BINDING_VULKAN_KHR)
      return RENDERDOC_DEVICEPOINTER_FROM_VKINSTANCE(reinterpret_cast<const VulkanBinding *>(next)->instance);
    if(next->type==XR_TYPE_GRAPHICS_BINDING_OPENGL_WIN32_KHR)
      return reinterpret_cast<const GLBinding *>(next)->rc;
    next=next->next;
  }
  return nullptr;
}
}

static XrResult XRAPI_CALL PBXRCreateSession(XrInstance instance,const XrSessionCreateInfo *info,XrSession *session)
{
  InstanceDispatch dispatch = {};
  { std::lock_guard<std::mutex> lock(Tables); auto it=Instances.find(instance); if(it==Instances.end()) return XR_ERROR_HANDLE_INVALID; dispatch=it->second; }
  if(!info || !session) return XR_ERROR_VALIDATION_FAILURE;
  XrResult result=dispatch.create(instance,info,session);
  if(XR_SUCCEEDED(result)) { std::lock_guard<std::mutex> lock(Tables); Sessions[*session]={dispatch,Device(info->next),instance,0}; }
  return result;
}
static XrResult XRAPI_CALL PBXRDestroySession(XrSession session)
{
  std::lock_guard<std::recursive_mutex> capture(Capture);
  SessionDispatch value = {};
  { std::lock_guard<std::mutex> lock(Tables); auto it=Sessions.find(session); if(it==Sessions.end()) return XR_ERROR_HANDLE_INVALID; value=it->second; }
  XrResult result=value.dispatch.destroySession(session);
  if(XR_SUCCEEDED(result)) {
    if(Active==session && PBApi) { PBApi->EndFrameCapture(ActiveDevice,nullptr); Active=XR_NULL_HANDLE; ActiveDevice=nullptr; }
    std::lock_guard<std::mutex> lock(Tables); Sessions.erase(session);
  }
  return result;
}
static XrResult XRAPI_CALL PBXRDestroyInstance(XrInstance instance)
{
  std::lock_guard<std::recursive_mutex> capture(Capture);
  InstanceDispatch value = {};
  { std::lock_guard<std::mutex> lock(Tables); auto it=Instances.find(instance); if(it==Instances.end()) return XR_ERROR_HANDLE_INVALID; value=it->second; }
  XrResult result=value.destroyInstance(instance);
  if(XR_SUCCEEDED(result)) {
    std::lock_guard<std::mutex> lock(Tables);
    for(auto it=Sessions.begin();it!=Sessions.end();) {
      if(it->second.instance==instance) {
        if(Active==it->first && PBApi) { PBApi->EndFrameCapture(ActiveDevice,nullptr); Active=XR_NULL_HANDLE; ActiveDevice=nullptr; }
        it=Sessions.erase(it);
      } else ++it;
    }
    Instances.erase(instance);
  }
  return result;
}
static XrResult XRAPI_CALL PBXRBegin(XrSession session,const XrFrameBeginInfo *info)
{
  std::lock_guard<std::recursive_mutex> capture(Capture);
  SessionDispatch value = {};
  { std::lock_guard<std::mutex> lock(Tables); auto it=Sessions.find(session); if(it==Sessions.end()) return XR_ERROR_HANDLE_INVALID; value=it->second; }
  XrResult result=value.dispatch.begin(session,info);
  if(result!=XR_SUCCESS) return result;
  if(PBApi && value.device && Active==XR_NULL_HANDLE && !PBApi->IsFrameCapturing() &&
      value.frame>=PB_XR_FIRST_FRAME && value.frame-PB_XR_FIRST_FRAME<PB_XR_FRAME_COUNT) {
    PBApi->StartFrameCapture(value.device,nullptr);
    if(PBApi->IsFrameCapturing()) { Active=session; ActiveDevice=value.device; }
  }
  { std::lock_guard<std::mutex> lock(Tables); auto it=Sessions.find(session); if(it!=Sessions.end()) ++it->second.frame; }
  return result;
}
static XrResult XRAPI_CALL PBXREnd(XrSession session,const XrFrameEndInfo *info)
{
  std::lock_guard<std::recursive_mutex> capture(Capture);
  SessionDispatch value = {};
  { std::lock_guard<std::mutex> lock(Tables); auto it=Sessions.find(session); if(it==Sessions.end()) return XR_ERROR_HANDLE_INVALID; value=it->second; }
  // Runtime/compositor work is outside the application's capture boundary.
  if(Active==session && PBApi) { PBApi->EndFrameCapture(ActiveDevice,nullptr); Active=XR_NULL_HANDLE; ActiveDevice=nullptr; }
  return value.dispatch.end(session,info);
}
static XrResult XRAPI_CALL PBXRQuery(XrInstance instance,const char *name,PFN_xrVoidFunction *function)
{
  if(!name || !function) return XR_ERROR_VALIDATION_FAILURE;
  *function=nullptr;
  if(!strcmp(name,"xrGetInstanceProcAddr")) { *function=reinterpret_cast<PFN_xrVoidFunction>(PBXRQuery); return XR_SUCCESS; }
  InstanceDispatch value = {};
  { std::lock_guard<std::mutex> lock(Tables); auto it=Instances.find(instance); if(it==Instances.end()) return XR_ERROR_HANDLE_INVALID; value=it->second; }
  XrResult result=value.query(instance,name,function);
  if(XR_FAILED(result) || !*function) return result;
  if(!strcmp(name,"xrCreateSession")) *function=reinterpret_cast<PFN_xrVoidFunction>(PBXRCreateSession);
  else if(!strcmp(name,"xrDestroySession")) *function=reinterpret_cast<PFN_xrVoidFunction>(PBXRDestroySession);
  else if(!strcmp(name,"xrDestroyInstance")) *function=reinterpret_cast<PFN_xrVoidFunction>(PBXRDestroyInstance);
  else if(!strcmp(name,"xrBeginFrame")) *function=reinterpret_cast<PFN_xrVoidFunction>(PBXRBegin);
  else if(!strcmp(name,"xrEndFrame")) *function=reinterpret_cast<PFN_xrVoidFunction>(PBXREnd);
  return result;
}
static XrResult XRAPI_CALL PBXRCreate(const XrInstanceCreateInfo *info,const XrApiLayerCreateInfo *layer,XrInstance *instance)
{
  if(!info || !layer || !instance || !layer->nextInfo ||
      layer->structType!=XR_LOADER_INTERFACE_STRUCT_API_LAYER_CREATE_INFO ||
      layer->structVersion!=XR_API_LAYER_CREATE_INFO_STRUCT_VERSION || layer->structSize!=sizeof(*layer) ||
      layer->nextInfo->structType!=XR_LOADER_INTERFACE_STRUCT_API_LAYER_NEXT_INFO ||
      layer->nextInfo->structVersion!=XR_API_LAYER_NEXT_INFO_STRUCT_VERSION || layer->nextInfo->structSize!=sizeof(*layer->nextInfo) ||
      !layer->nextInfo->nextGetInstanceProcAddr || !layer->nextInfo->nextCreateApiLayerInstance) return XR_ERROR_INITIALIZATION_FAILED;
  PBEnsureCore();
  XrApiLayerCreateInfo next=*layer; next.nextInfo=layer->nextInfo->next;
  XrResult result=layer->nextInfo->nextCreateApiLayerInstance(info,&next,instance);
  if(XR_FAILED(result)) return result;
  InstanceDispatch d = {}; d.query=layer->nextInfo->nextGetInstanceProcAddr;
#define PB_XR_GET(field,name) d.query(*instance,name,reinterpret_cast<PFN_xrVoidFunction *>(&d.field))
  PB_XR_GET(create,"xrCreateSession"); PB_XR_GET(destroySession,"xrDestroySession");
  PB_XR_GET(destroyInstance,"xrDestroyInstance"); PB_XR_GET(begin,"xrBeginFrame"); PB_XR_GET(end,"xrEndFrame");
#undef PB_XR_GET
  if(!d.create || !d.destroySession || !d.destroyInstance || !d.begin || !d.end) {
    if(d.destroyInstance) d.destroyInstance(*instance);
    *instance=XR_NULL_HANDLE; return XR_ERROR_INITIALIZATION_FAILED;
  }
  std::lock_guard<std::mutex> lock(Tables); Instances[*instance]=d;
  return result;
}
extern "C" XrResult XRAPI_CALL xrNegotiateLoaderApiLayerInterface(const XrNegotiateLoaderInfo *loader,const char *name,XrNegotiateApiLayerRequest *request)
{
  if(!loader || !request || !name || strcmp(name,"XR_APILAYER_DCOMP_capture") ||
      loader->structType!=XR_LOADER_INTERFACE_STRUCT_LOADER_INFO || loader->structVersion!=XR_LOADER_INFO_STRUCT_VERSION || loader->structSize!=sizeof(*loader) ||
      request->structType!=XR_LOADER_INTERFACE_STRUCT_API_LAYER_REQUEST || request->structVersion!=XR_API_LAYER_INFO_STRUCT_VERSION || request->structSize!=sizeof(*request) ||
      loader->minInterfaceVersion>1 || loader->maxInterfaceVersion<1 ||
      loader->minApiVersion>XR_MAKE_VERSION(1,0,0) || loader->maxApiVersion<XR_MAKE_VERSION(1,0,0)) return XR_ERROR_INITIALIZATION_FAILED;
  PBEnsureCore();
  request->layerInterfaceVersion=1;
  request->layerApiVersion=XR_MAKE_VERSION(1,0,0);
  request->getInstanceProcAddr=PBXRQuery;
  request->createApiLayerInstance=PBXRCreate;
  return XR_SUCCESS;
}
