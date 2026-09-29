#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>

extern "C" __declspec(dllexport) uint64_t WINAPI GFSDK_Aftermath_DX12_Initialize(
    uint64_t a, uint64_t b, uint64_t c, uint64_t d, uint64_t e, uint64_t f)
{
  return a + 3 * b + 5 * c + 7 * d + 11 * e + 13 * f;
}

extern "C" __declspec(dllexport) double WINAPI GFSDK_Aftermath_GetShaderHash(
    double a, double b, double c, double d)
{
  return a + 3 * b + 5 * c + 7 * d;
}
