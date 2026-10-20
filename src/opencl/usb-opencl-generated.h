/* Measured metadata only; no vendor program body or argument expression.
 * Offset is zero-based in the exact caller-provided program after concatenation.
 * Layout safety was checked against that program during private validation. */
#define TARGET_SOURCE_LENGTH 3451u
#define TARGET_SOURCE_FNV UINT64_C(8154106478165571556)
#define TARGET_ATOMIC_OFFSET 3103u
#define ATOMIC_SHORT_HELPER "/* OpenCL 1.2: replace one 16-bit field atomically using a 32-bit CAS,\n * preserving the neighbouring 16 bits. Only aligned, allocated 32-bit\n * words on the validated little-endian AMD device are used. */\ninline short creality_atomic_short_xchg(volatile __global short *p, int value) {\n    uint shift = (uint)((size_t)p & 2u) * 8u;\n    volatile __global uint *word = (volatile __global uint *)\n        ((volatile __global uchar *)p - ((size_t)p & 2u));\n    uint mask = 0xffffu << shift;\n    uint old = atomic_cmpxchg(word, 0u, 0u);\n    for (;;) {\n        uint replacement = (old & ~mask) | ((uint)(ushort)value << shift);\n        uint observed = atomic_cmpxchg(word, old, replacement);\n        if (observed == old) return (short)(old >> shift);\n        old = observed;\n    }\n}\n"
