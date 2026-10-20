"""Exercise the real interposer with an original synthetic fixture and fake ICD.
No captured SDK program is needed or distributed by these tests.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = b'kernel void example(global short *samples) { atomic_xchg(samples, 3); }\n'

STUB = r'''
#include <stddef.h>
static unsigned calls_count;
static const char **calls_strings;
static const size_t *calls_lengths;
static char saved[8192];
static size_t used;
void *clCreateProgramWithSource(void *ctx, unsigned count, const char **strings,
                               const size_t *lengths, int *error) {
    (void)ctx; calls_count=count; calls_strings=strings; calls_lengths=lengths;
    used=0;
    if(strings && count<=1024) for(unsigned i=0;i<count;i++) {
        if(!strings[i]) break;
        size_t n=lengths?lengths[i]:0;
        if(!n) while(strings[i][n]) n++;
        if(n>sizeof(saved)-used) break;
        for(size_t j=0;j<n;j++) saved[used++]=strings[i][j];
    }
    if(error)*error=0;
    return (void*)0x1234;
}
size_t saved_size(void){return used;}
const char *saved_data(void){return saved;}
unsigned saved_count(void){return calls_count;}
const void *saved_strings(void){return calls_strings;}
const void *saved_lengths(void){return calls_lengths;}
'''

CHILD = r'''
import ctypes as C, json, os, sys
cfg=json.loads(sys.argv[1]); fixture=bytes.fromhex(cfg['fixture'])
shim=C.CDLL(cfg['shim']); stub=C.CDLL('libOpenCL.so.1')
fn=shim.clCreateProgramWithSource
fn.argtypes=[C.c_void_p,C.c_uint,C.POINTER(C.c_char_p),C.POINTER(C.c_size_t),C.POINTER(C.c_int)]
fn.restype=C.c_void_p
stub.saved_size.restype=C.c_size_t;stub.saved_data.restype=C.c_void_p
stub.saved_strings.restype=C.c_void_p;stub.saved_lengths.restype=C.c_void_p
os.environ['WINEPREFIX']='/synthetic/test-prefix'
os.environ['CREALITY_PREFIX_GUARD']='/synthetic/test-prefix'
os.environ['CREALITY_BLUE_LASER_FIX']='1'
case=cfg['case'];parts=[fixture];lens=None;count=None
if case=='split':parts=[fixture[:50],fixture[50:]]
if case=='mismatch':parts=[fixture.replace(b'3',b'4')]
if case=='guard':os.environ['CREALITY_PREFIX_GUARD']='/different-prefix'
if case=='optout':os.environ.pop('CREALITY_BLUE_LASER_FIX')
if case=='no_guard':os.environ.pop('CREALITY_PREFIX_GUARD')
if case=='nul_tail':parts=[fixture+b'\0\0']
if case=='null_entry':parts=[None]
if case=='count_zero':count=0
if case=='count_limit':count=1025
strings=(C.c_char_p*len(parts))(*parts)
if case!='implicit':lens=(C.c_size_t*len(parts))(*(len(x) if x else 0 for x in parts))
if case=='zero_length':lens[0]=0
if case=='oversize':lens[0]=16*1024*1024+1
if case=='null_strings':strings=None
error=C.c_int(-99)
assert fn(None,len(parts) if count is None else count,strings,lens,C.byref(error))==0x1234
assert error.value==0
out=C.string_at(stub.saved_data(),stub.saved_size())
changed=case in ('plain','split','implicit','zero_length','nul_tail')
if changed:
    expected=cfg['helper'].encode()+fixture.replace(b'atomic_xchg',b'creality_atomic_short_xchg')
    assert out==expected,(case,'unexpected rewritten program')
    assert stub.saved_count()==1
else:
    assert stub.saved_strings()==(C.addressof(strings) if strings is not None else None)
    assert stub.saved_lengths()==(C.addressof(lens) if lens is not None else None)
    if case in ('mismatch','guard','optout','no_guard'):assert out==parts[0]
print('PASS',case)
'''


class OpenCLRewriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='creality-rewrite-test-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.path = Path(cls.temp.name)
        h = 14695981039346656037
        for b in FIXTURE:
            h = ((h ^ b) * 1099511628211) & ((1 << 64) - 1)
        header = (ROOT/'src/opencl/usb-opencl-generated.h').read_text()
        cls.helper = json.loads(re.search(r'^#define ATOMIC_SHORT_HELPER (.+)$', header, re.M)[1])
        # Alter metadata in a disposable build, never the production guard.
        for name, value in [('TARGET_SOURCE_LENGTH', str(len(FIXTURE))+'u'),
                            ('TARGET_SOURCE_FNV', f'UINT64_C({h})'),
                            ('TARGET_ATOMIC_OFFSET', str(FIXTURE.index(b'atomic_xchg'))+'u')]:
            header = re.sub(r'^#define '+name+r' .+$', '#define '+name+' '+value, header, flags=re.M)
        (cls.path/'usb-opencl-generated.h').write_text(header)
        (cls.path/'usb-opencl.c').write_text((ROOT/'src/opencl/usb-opencl.c').read_text())
        (cls.path/'stub.c').write_text(STUB)
        for source, output in [('stub.c', 'libOpenCL.so.1'), ('usb-opencl.c', 'rewrite.so')]:
            subprocess.run(['gcc','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                            str(cls.path/source),'-ldl','-pthread','-o',str(cls.path/output)],check=True)

    def run_case(self, case):
        cfg={'case':case,'shim':str(self.path/'rewrite.so'),'fixture':FIXTURE.hex(),'helper':self.helper}
        env=dict(os.environ, LD_LIBRARY_PATH=str(self.path))
        result=subprocess.run([sys.executable,'-c',CHILD,json.dumps(cfg)],env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_replacement_preserves_original_arguments_and_program(self):
        for case in ('plain','split','implicit','zero_length','nul_tail'):
            with self.subTest(case=case):self.run_case(case)

    def test_different_program_and_disabled_scope_passthrough(self):
        for case in ('mismatch','guard','optout','no_guard'):
            with self.subTest(case=case):self.run_case(case)

    def test_invalid_input_passthrough_without_reading_out_of_bounds(self):
        for case in ('null_entry','null_strings','count_zero','count_limit','oversize'):
            with self.subTest(case=case):self.run_case(case)


if __name__=='__main__':unittest.main()
