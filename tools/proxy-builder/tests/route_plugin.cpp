#define WIN32_LEAN_AND_MEAN
#include <windows.h>
static LONG SawCore=0;
extern "C" __declspec(dllexport) LONG PluginSawCore() { return SawCore; }
BOOL WINAPI DllMain(HMODULE,DWORD reason,LPVOID)
{
  if(reason==DLL_PROCESS_ATTACH) {
    HMODULE core=GetModuleHandleW(L"dgcore.dll");
    auto count=core ? reinterpret_cast<LONG (*)()>(GetProcAddress(core,"TestHandshakeCount")) : nullptr;
    SawCore=count ? count() : 0;
  }
  return TRUE;
}
