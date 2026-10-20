import json,os,subprocess,tempfile
from pathlib import Path
from common import ROOT,dependencies,digest

NAMES=['pikacam.dll','mf.dll','sdk-proxy.dll','usb-opencl.so','dgg-device-memory.so','v4l2-helper','sdk-frame-helper','bridge-probe.exe','real-frame-probe.exe','sdk-connect-probe.exe','control-probe.exe','opencl-probe.exe','graphics-probe.exe']
# Release builds link libyuv/libjpeg statically: distributions name libyuv differently.
PORTABLE_YUV=['-Wl,-Bstatic','-lyuv','-ljpeg','-Wl,-Bdynamic','-lstdc++','-lm']

def build(c,portable=False):
    dependencies(c)
    out=ROOT/'build';out.mkdir(exist_ok=True)
    runner=c['runner'];src=ROOT/'src/usb-bridge'
    def run(args):subprocess.run([str(a)for a in args],check=True)
    with tempfile.TemporaryDirectory(prefix='.build-',dir=ROOT) as temp:
        tmp=Path(temp)
        flags=['--target=x86_64-w64-mingw32','-D__WINE__','-D__MSVCRT__','-O2','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-fno-stack-protector','-isystem',runner/'include/wine/msvcrt','-isystem',runner/'include/wine/windows']
        libs=[runner/'lib/wine/x86_64-windows'/('lib'+n+'.a')for n in ('kernel32','ucrtbase','mfplat','mfuuid','uuid','ole32','ws2_32','strmiids','setupapi','cfgmgr32','hid')]
        for name in ('bridge','probe','real-frame-probe','sdk-connect-probe','control-probe','sdk-proxy'):
            run(['clang',*flags,'-c',src/(name+'.c'),'-o',tmp/(name+'.obj')])
        for dll,obj,definition in [('pikacam','bridge','pikacam'),('mf','bridge','mf-proxy'),('sdk-proxy','sdk-proxy','sdk-proxy')]:
            run(['lld-link','/dll','/entry:DllMain' if dll=='sdk-proxy' else '/noentry','/nodefaultlib','/def:'+str(src/(definition+'.def')),'/out:'+str(tmp/(dll+'.dll')),tmp/(obj+'.obj'),*libs])
        for obj,name in [('probe','bridge-probe'),('real-frame-probe','real-frame-probe'),('sdk-connect-probe','sdk-connect-probe'),('control-probe','control-probe')]:
            run(['lld-link','/subsystem:console','/entry:mainCRTStartup','/nodefaultlib','/out:'+str(tmp/(name+'.exe')),tmp/(obj+'.obj'),*libs,runner/'lib/wine/x86_64-windows/libmfreadwrite.a'])
        for name in ('v4l2-helper','sdk-frame-helper'):
            yuv=(PORTABLE_YUV if portable else ['-lyuv']) if name=='sdk-frame-helper' else []
            run(['gcc','-O2','-Wall','-Wextra','-Werror',src/(name+'.c'),'-o',tmp/name,*yuv])
        for name in ('usb-opencl','dgg-device-memory'):
            run(['gcc','-O2','-Wall','-Wextra','-Werror','-fPIC','-shared',ROOT/'src/opencl'/(name+'.c'),'-ldl','-pthread','-o',tmp/(name+'.so')])
        for name in ('kernel32','user32','gdi32','opengl32'):
            run(['llvm-dlltool','-m','i386:x86-64','-d',ROOT/'src/probes'/(name+'.def'),'-l',tmp/(name+'.lib')])
        for name,ls in [('opencl-probe',['kernel32']),('graphics-probe',['kernel32','user32','gdi32','opengl32'])]:
            run(['clang','--target=x86_64-pc-windows-msvc','-O2','-ffreestanding','-fno-stack-protector','-c',ROOT/'src/probes'/(name+'.c'),'-o',tmp/(name+'.obj')])
            run(['lld-link','/subsystem:console','/entry:mainCRTStartup','/nodefaultlib','/out:'+str(tmp/(name+'.exe')),tmp/(name+'.obj'),*[tmp/(l+'.lib')for l in ls]])
        for name in NAMES:os.replace(tmp/name,out/name)
        (out/'manifest.json').write_text(json.dumps({n:digest(out/n)for n in NAMES},indent=2)+'\n')
    print('Build complete:',out)
