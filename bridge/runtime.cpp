// Minimal runtime helpers for an XP binary with no modern C runtime dependency.
// The bridge uses Windows allocation, string and I/O APIs instead of the CRT.
#include <stddef.h>
extern "C" void* __cdecl memset(void* target, int value, size_t count) {
    unsigned char* out = static_cast<unsigned char*>(target);
    while (count--) *out++ = static_cast<unsigned char>(value);
    return target;
}
extern "C" void* __cdecl memcpy(void* target, const void* source, size_t count) {
    unsigned char* out = static_cast<unsigned char*>(target);
    const unsigned char* in = static_cast<const unsigned char*>(source);
    while (count--) *out++ = *in++;
    return target;
}
