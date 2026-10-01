#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdint>
#include <cstdio>
extern "C" __declspec(dllimport) volatile uint32_t ExportedData;
extern "C" __declspec(dllimport) volatile uint32_t DataAlias;
int main()
{
  // C++ compilers may assume two separately declared globals have distinct
  // addresses. Inspect the actual IAT-resolved pointers at runtime.
  volatile uint32_t *volatile first=&ExportedData;
  volatile uint32_t *volatile alias=&DataAlias;
  if(*first!=42 || *alias!=42 || first!=alias) return 1;
  HMODULE original=GetModuleHandleW(L"fixture_orig.dll");
  if(!original || reinterpret_cast<uintptr_t>(GetProcAddress(original,"ExportedData"))!=reinterpret_cast<uintptr_t>(first)) return 2;
  *first=123; if(*alias!=123) return 3;
  printf("{\"staticDataImport\":true,\"sharedOriginalStorage\":true}\n"); return 0;
}
