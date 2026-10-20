"""Detect the GPU name as the diagnostics match it. Standard library only, so it
can run under the system interpreter with `python3 -I`."""
import ctypes as C


def detect():
    """Name of the strongest OpenCL GPU as the probes match it (e.g. 'AMD Radeon RX 6800 XT').
    Discrete GPUs (own memory) win over integrated ones, then more compute units."""
    try:
        cl = C.CDLL('libOpenCL.so.1')
    except OSError:
        return None
    cl.clGetPlatformIDs.argtypes = [C.c_uint, C.POINTER(C.c_void_p), C.POINTER(C.c_uint)]
    cl.clGetDeviceIDs.argtypes = [C.c_void_p, C.c_uint64, C.c_uint, C.POINTER(C.c_void_p), C.POINTER(C.c_uint)]
    cl.clGetDeviceInfo.argtypes = [C.c_void_p, C.c_uint, C.c_size_t, C.c_void_p, C.c_void_p]
    def info(device, param, kind):
        value = kind()
        return None if cl.clGetDeviceInfo(device, param, C.sizeof(value), C.byref(value), None) else value
    platforms = (C.c_void_p*16)(); count = C.c_uint(); found = []
    if cl.clGetPlatformIDs(16, platforms, C.byref(count)):
        return None
    for platform in platforms[:min(count.value, 16)]:
        devices = (C.c_void_p*16)(); n = C.c_uint()
        if cl.clGetDeviceIDs(platform, 4, 16, devices, C.byref(n)):  # CL_DEVICE_TYPE_GPU
            continue
        for device in devices[:min(n.value, 16)]:
            name = None
            for param in (0x4038, 0x102B):  # CL_DEVICE_BOARD_NAME_AMD, CL_DEVICE_NAME
                buf = info(device, param, lambda: C.create_string_buffer(256))
                text = buf.value.decode(errors='replace').split(' (')[0].strip() if buf else ''
                if text and not text.startswith('gfx'):
                    name = text; break
            unified = info(device, 0x1035, C.c_uint)  # CL_DEVICE_HOST_UNIFIED_MEMORY
            units = info(device, 0x1002, C.c_uint)    # CL_DEVICE_MAX_COMPUTE_UNITS
            if name:
                found.append((not (unified and unified.value), units.value if units else 0, name))
    return max(found)[2] if found else None


if __name__ == '__main__':
    print(detect() or '')
