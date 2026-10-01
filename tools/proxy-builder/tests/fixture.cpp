#include <cstdint>
extern "C" uint64_t Sum8(uint64_t a, uint64_t b, uint64_t c, uint64_t d,
                        uint64_t e, uint64_t f, uint64_t g, uint64_t h)
{ return a + b * 2 + c * 3 + d * 4 + e * 5 + f * 6 + g * 7 + h * 8; }
extern "C" double Float8(double a, double b, double c, double d,
                         double e, double f, double g, double h)
{ return a + b * 2 + c * 3 + d * 4 + e * 5 + f * 6 + g * 7 + h * 8; }
extern "C" int ExportedData = 42;
