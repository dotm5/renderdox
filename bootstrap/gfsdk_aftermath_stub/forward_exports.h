// Aftermath forwarding exports - real forwarding functions (not linker forwarders).
//
// Previously these were #pragma comment(linker, "/export:NAME=GFSDK_Aftermath_Lib_orig.NAME")
// linker-level forwarders, which never execute our code and cannot log call timing.
// Now each export is a real function implemented in aftermath_forward.cpp that:
//   1. logs the call timestamp (relative to process start)
//   2. resolves the original function from GFSDK_Aftermath_Lib_orig.dll
//   3. forwards the call (x64 ABI: parameters pass through registers/stack untouched)

#pragma once

// x64 ABI note: all of these functions use the single Microsoft x64 calling
// convention, so a no-arg wrapper that does not touch RCX/RDX/R8/R9 and does not
// adjust the stack transparently forwards up to 4 register args plus any stack
// args (x64 callers clean the stack). Aftermath functions take <= 4 args.
extern "C" __declspec(dllexport) intptr_t GFSDK_Aftermath_DX11_CreateContextHandle();
extern "C" __declspec(dllexport) intptr_t GFSDK_Aftermath_DX11_Initialize();
extern "C" __declspec(dllexport) intptr_t GFSDK_Aftermath_DX12_CreateContextHandle();
extern "C" __declspec(dllexport) intptr_t GFSDK_Aftermath_DX12_Initialize();
extern "C" __declspec(dllexport) intptr_t GFSDK_Aftermath_GetData();
extern "C" __declspec(dllexport) intptr_t GFSDK_Aftermath_GetDeviceStatus();
extern "C" __declspec(dllexport) intptr_t GFSDK_Aftermath_GetPageFaultInformation();
extern "C" __declspec(dllexport) intptr_t GFSDK_Aftermath_ReleaseContextHandle();
extern "C" __declspec(dllexport) intptr_t GFSDK_Aftermath_SetEventMarker();
