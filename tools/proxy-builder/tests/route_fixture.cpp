#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <cstdint>
#include <cstring>
#include <unknwn.h>
extern "C" uint64_t Sum8(uint64_t a,uint64_t b,uint64_t c,uint64_t d,uint64_t e,uint64_t f,uint64_t g,uint64_t h)
{ return a+b*2+c*3+d*4+e*5+f*6+g*7+h*8; }
extern "C" double Float8(double a,double b,double c,double d,double e,double f,double g,double h)
{ return a+b*2+c*3+d*4+e*5+f*6+g*7+h*8; }
extern "C" uint32_t ExportedData = 42;
static uint64_t Hidden() { return 73; }
extern "C" FARPROC __cdecl nvapi_QueryInterface(uint32_t id)
{
  if(id==0x1234) return reinterpret_cast<FARPROC>(Sum8);
  if(id==0x9999) return reinterpret_cast<FARPROC>(Hidden);
  return nullptr;
}
extern "C" FARPROC WINAPI vkGetInstanceProcAddr(void *handle,const char *name);
extern "C" FARPROC WINAPI vkGetDeviceProcAddr(void *handle,const char *name)
{
  if(!name) return nullptr;
  if(!strcmp(name,"vkSum8")) return reinterpret_cast<FARPROC>(handle==reinterpret_cast<void *>(99) ? Hidden : reinterpret_cast<uint64_t (*)()>(Sum8));
  if(!strcmp(name,"vkOther")) return reinterpret_cast<FARPROC>(Hidden);
  if(!strcmp(name,"vkGetDeviceProcAddr")) return reinterpret_cast<FARPROC>(vkGetDeviceProcAddr);
  if(!strcmp(name,"vkGetInstanceProcAddr")) return reinterpret_cast<FARPROC>(vkGetInstanceProcAddr);
  return nullptr;
}
extern "C" FARPROC WINAPI vkGetInstanceProcAddr(void *handle,const char *name) { return vkGetDeviceProcAddr(handle,name); }
struct FactoryInterface : IUnknown { virtual uint64_t STDMETHODCALLTYPE CreateOwnedDevice(uint64_t value)=0; };
struct Factory : FactoryInterface {
  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID,void **out) override { if(!out) return E_POINTER; *out=this; return S_OK; }
  ULONG STDMETHODCALLTYPE AddRef() override { return 1; }
  ULONG STDMETHODCALLTYPE Release() override { return 1; }
  uint64_t STDMETHODCALLTYPE CreateOwnedDevice(uint64_t value) override { return value+17; }
};
static Factory TestFactory;
extern "C" HRESULT WINAPI D3D12GetInterface(REFCLSID,REFIID,void **out)
{ if(!out) return E_POINTER; *out=&TestFactory; return S_OK; }
extern "C" LONG OriginalSawCore()
{
  auto core=GetModuleHandleW(L"dgcore.dll");
  auto count=core ? reinterpret_cast<LONG (*)()>(GetProcAddress(core,"TestHandshakeCount")) : nullptr;
  return count ? count() : 0;
}
