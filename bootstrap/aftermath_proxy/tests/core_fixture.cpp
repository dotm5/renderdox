#define WIN32_LEAN_AND_MEAN
#include <windows.h>

namespace
{
volatile LONG Handshakes = 0;
}

extern "C" __declspec(dllexport) int __cdecl DCOMP_GetAPI(int, void **api)
{
  if(api == NULL)
    return 0;
  *api = (void *)1;
  InterlockedIncrement(&Handshakes);
  return 1;
}

extern "C" __declspec(dllexport) LONG __cdecl TestHandshakeCount()
{
  return InterlockedCompareExchange(&Handshakes, 0, 0);
}
