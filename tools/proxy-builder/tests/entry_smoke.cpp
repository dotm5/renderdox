#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdio>
#include <cstdint>
extern "C" __declspec(dllimport) uint64_t Sum8(uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t);
int main()
{
  // This runs before the first imported function call. The optional entry-point
  // breakpoint must have completed Core handshake before CRT reaches main.
  HMODULE core=GetModuleHandleW(L"dgcore.dll");
  auto count=core ? reinterpret_cast<LONG (*)()>(GetProcAddress(core,"TestHandshakeCount")) : nullptr;
  if(!count || count()!=1) return 1;
  if(Sum8(1,2,3,4,5,6,7,8)!=204) return 2;
  printf("{\"coreBeforeMain\":true,\"handshakes\":%ld}\n",count()); return 0;
}
