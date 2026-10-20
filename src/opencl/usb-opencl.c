/* Experimental process-local fix; no DLL, driver or prefix binary patch.
 * Exact source fingerprint plus token offset and prefix/opt-in guards.
 * Unmatched sources pass through unchanged. Generated header contains only
 * our helper text and the fingerprint of the locally captured SDK source. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "usb-opencl-generated.h"
typedef void *(*create_fn)(void *, unsigned, const char **, const size_t *, int *);
static create_fn original_create;
static pthread_once_t initialized = PTHREAD_ONCE_INIT;
static void initialize(void) {
    void *lib = dlopen("libOpenCL.so.1", RTLD_NOW | RTLD_LOCAL);
    if (lib) original_create = (create_fn)dlsym(lib,"clCreateProgramWithSource");
}
void *clCreateProgramWithSource(void *context, unsigned count,
    const char **strings, const size_t *lengths, int *error) {
    pthread_once(&initialized,initialize);
    if (!original_create) { if(error)*error=-59; return NULL; }
    const char *enabled=getenv("CREALITY_BLUE_LASER_FIX");
    const char *prefix=getenv("WINEPREFIX");
    const char *guard=getenv("CREALITY_PREFIX_GUARD");
    if (!enabled || strcmp(enabled,"1") || !prefix || !guard || strcmp(prefix,guard)
        || !strings || !count || count>1024)
        return original_create(context,count,strings,lengths,error);
    size_t total=0;
    for(unsigned i=0;i<count;i++) {
        if(!strings[i])return original_create(context,count,strings,lengths,error);
        size_t n=lengths && lengths[i]?lengths[i]:strlen(strings[i]);
        if(n>16*1024*1024 || total>16*1024*1024-n)
            return original_create(context,count,strings,lengths,error);
        total+=n;
    }
    char *source=malloc(total+1);
    if(!source)return original_create(context,count,strings,lengths,error);
    size_t offset=0;
    for(unsigned i=0;i<count;i++) {
        size_t n=lengths && lengths[i]?lengths[i]:strlen(strings[i]);
        memcpy(source+offset,strings[i],n);offset+=n;
    }
    source[total]=0;
    while(total && source[total-1]==0)total--;
    uint64_t hash=UINT64_C(14695981039346656037);
    for(size_t i=0;i<total;i++){hash^=(unsigned char)source[i];hash*=UINT64_C(1099511628211);}
    /* Only a standard OpenCL builtin name is stored here. The arguments and
     * all vendor program text come from the caller at runtime. The full-source
     * fingerprint pins the already-validated layout and exact token position;
     * any different program passes through, even if it uses the same builtin.
     * This is a version guard, not authentication of untrusted input. */
    static const char old_name[]="atomic_xchg";
    static const char new_name[]="creality_atomic_short_xchg";
    const size_t left=TARGET_ATOMIC_OFFSET,old_len=sizeof(old_name)-1;
    if(total!=TARGET_SOURCE_LENGTH || hash!=TARGET_SOURCE_FNV ||
       left>total || old_len>total-left ||
       memcmp(source+left,old_name,old_len)) {
        free(source);return original_create(context,count,strings,lengths,error);
    }
    size_t helper_len=strlen(ATOMIC_SHORT_HELPER);
    size_t size=helper_len+total+sizeof(new_name)-sizeof(old_name);
    char *patched=malloc(size+1);
    if(!patched){free(source);return original_create(context,count,strings,lengths,error);}
    memcpy(patched,ATOMIC_SHORT_HELPER,helper_len);
    memcpy(patched+helper_len,source,left);
    memcpy(patched+helper_len+left,new_name,sizeof(new_name)-1);
    size_t rest=total-left-old_len,end=helper_len+left+sizeof(new_name)-1;
    memcpy(patched+end,source+left+old_len,rest);patched[size]=0;
    fprintf(stderr,"Blue-laser compatibility: exact program fingerprint matched; applying 16-bit atomic CAS\n");
    const char *program_source=patched;
    void *result=original_create(context,1,&program_source,&size,error);
    free(patched);free(source);return result;
}
