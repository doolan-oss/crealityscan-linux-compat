/* App-local RX 6800 XT allocation fix. The stock SDK requests host-allocated
 * buffers even for repeatedly accessed GPU scratch data. On this ROCm stack
 * that makes kernels and completion waits much slower. Preserve kernels,
 * command ordering, access flags, COPY_HOST_PTR and explicit USE_HOST_PTR.
 * Enabled only by the separate USB Fast / profiling launcher. */
#define _GNU_SOURCE
#define CL_TARGET_OPENCL_VERSION 220
#include <CL/cl.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static pthread_once_t once = PTHREAD_ONCE_INIT;
static __typeof__(&clCreateBuffer) create_buffer;
static __typeof__(&clGetContextInfo) context_info;
static __typeof__(&clGetDeviceInfo) device_info;
static int enabled;
static void initialize(void) {
    void *lib = dlopen("libOpenCL.so.1", RTLD_NOW | RTLD_LOCAL);
    if (lib) {
        create_buffer = (__typeof__(create_buffer))dlsym(lib, "clCreateBuffer");
        context_info = (__typeof__(context_info))dlsym(lib, "clGetContextInfo");
        device_info = (__typeof__(device_info))dlsym(lib, "clGetDeviceInfo");
    }
    const char *opt = getenv("CREALITY_DGG_DEVICE_MEMORY");
    const char *prefix = getenv("WINEPREFIX");
    const char *guard = getenv("CREALITY_PREFIX_GUARD");
    enabled = opt && !strcmp(opt, "1") && prefix && guard &&
        !strcmp(prefix, guard);
}
static int target_context(cl_context context) {
    cl_device_id device;
    size_t bytes = 0;
    char name[256] = {0};
    cl_uint vendor = 0;
    return context_info && device_info &&
        !context_info(context, CL_CONTEXT_DEVICES, sizeof(device), &device, &bytes) &&
        bytes == sizeof(device) &&
        !device_info(device, CL_DEVICE_VENDOR_ID, sizeof(vendor), &vendor, NULL) &&
        vendor == 0x1002 &&
        !device_info(device, CL_DEVICE_NAME, sizeof(name), name, NULL) &&
        (!strcmp(name, "gfx1030") || strstr(name, "6800 XT"));
}
cl_mem clCreateBuffer(cl_context context, cl_mem_flags flags, size_t size,
                      void *host, cl_int *error) {
    pthread_once(&once, initialize);
    if (!create_buffer) {
        if (error) *error = CL_INVALID_OPERATION;
        return NULL;
    }
    cl_mem_flags original = flags;
    if (enabled && (flags & CL_MEM_ALLOC_HOST_PTR) &&
        !(flags & CL_MEM_USE_HOST_PTR) && target_context(context))
        flags &= ~CL_MEM_ALLOC_HOST_PTR;
    cl_mem memory = create_buffer(context, flags, size, host, error);
    /* Allocation failure must not turn a previously viable host allocation
     * into an app failure. Preserve the driver's original path as fallback. */
    if (!memory && flags != original) {
        fprintf(stderr, "DGG device memory: device allocation failed (%zu bytes); using original flags\n", size);
        return create_buffer(context, original, size, host, error);
    }
    if (flags != original)
        fprintf(stderr, "DGG device memory: buffer=%p bytes=%zu flags=%llu->%llu\n",
            (void *)memory, size, (unsigned long long)original, (unsigned long long)flags);
    return memory;
}
