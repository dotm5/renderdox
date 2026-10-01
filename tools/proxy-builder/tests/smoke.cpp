#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <thread>
#include <vector>
#include <atomic>
#include <cmath>
#include <cstring>
// Owned test of Streamline-style lookup: resolve the proxy's physical EAT
// entries without asking GetProcAddress for the exported function address.
static FARPROC RawExport(HMODULE module, const char *name, WORD ordinal = 0)
{
  auto base = reinterpret_cast<unsigned char *>(module);
  auto dos = reinterpret_cast<IMAGE_DOS_HEADER *>(base);
  auto nt = reinterpret_cast<IMAGE_NT_HEADERS64 *>(base + dos->e_lfanew);
  const auto directory = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_EXPORT];
  auto exports = reinterpret_cast<IMAGE_EXPORT_DIRECTORY *>(base + directory.VirtualAddress);
  auto names = reinterpret_cast<DWORD *>(base + exports->AddressOfNames);
  auto ordinals = reinterpret_cast<WORD *>(base + exports->AddressOfNameOrdinals);
  auto functions = reinterpret_cast<DWORD *>(base + exports->AddressOfFunctions);
  DWORD index = MAXDWORD;
  if(name) {
    for(DWORD i=0; i<exports->NumberOfNames; ++i)
      if(!strcmp(name, reinterpret_cast<char *>(base + names[i]))) { index = ordinals[i]; break; }
  } else if(ordinal >= exports->Base) index = ordinal - exports->Base;
  if(index >= exports->NumberOfFunctions || !functions[index]) return nullptr;
  const DWORD address = functions[index];
  if(address >= directory.VirtualAddress && address < directory.VirtualAddress + directory.Size) return nullptr;
  return reinterpret_cast<FARPROC>(base + address);
}
int wmain(int argc, wchar_t **argv)
{
  if(argc != 2 && argc != 3) return 2;
  const bool rawEAT = argc == 3 && !wcscmp(argv[2], L"raw-eat");
  if(argc == 3 && !rawEAT) return 2;
  HMODULE proxy = LoadLibraryW(argv[1]);
  if(!proxy) return 3;
  using Int = uint64_t (*)(uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t);
  using Float = double (*)(double,double,double,double,double,double,double,double);
  auto sum = reinterpret_cast<Int>(rawEAT ? RawExport(proxy,"Sum8") : GetProcAddress(proxy,"Sum8"));
  auto alias = reinterpret_cast<Int>(rawEAT ? RawExport(proxy,"Alias") : GetProcAddress(proxy,"Alias"));
  auto ordinal = reinterpret_cast<Int>(rawEAT ? RawExport(proxy,nullptr,7) : GetProcAddress(proxy,MAKEINTRESOURCEA(7)));
  auto floating = reinterpret_cast<Float>(rawEAT ? RawExport(proxy,"Float8") : GetProcAddress(proxy,"Float8"));
  auto sleep = reinterpret_cast<void (WINAPI *)(DWORD)>(rawEAT ? RawExport(proxy,"ForwardSleep") : GetProcAddress(proxy,"ForwardSleep"));
  if(!sum || !alias || !ordinal || !floating || !sleep || GetProcAddress(proxy,"OrdinalOnly")) return 4;
  if(sum != alias || sum != ordinal) return 5;
  std::atomic<int> errors(0);
  std::vector<std::thread> threads;
  for(int i=0;i<16;++i) threads.emplace_back([&]() {
    for(int call=0;call<1000;++call)
      if(sum(1,2,3,4,5,6,7,8)!=204 || alias(1,2,3,4,5,6,7,8)!=204 ||
         ordinal(1,2,3,4,5,6,7,8)!=204 || std::abs(floating(1,2,3,4,5,6,7,8)-204.0)>0.0001) ++errors;
  });
  for(auto &thread : threads) thread.join();
  sleep(1);
  printf("{\"calls\":64000,\"threads\":16,\"errors\":%d,\"ordinalOnly\":true,\"forwarder\":true,\"rawEAT\":%s}\n",errors.load(), rawEAT ? "true" : "false");
  // Proxy/Core worker lifetime is process-scoped; do not unload active proxies.
  return errors.load() ? 1 : 0;
}
