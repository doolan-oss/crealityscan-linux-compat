"""Configuration and sandbox boundaries. No shell evaluation of config values."""
import fcntl,hashlib,json,os,subprocess
import integrity
from integrity import tree_digest, installation_path
from display import MODES
from exports import EXPORTS_MOUNT, check_dir, default_dir
import stateio
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RUNTIME_ROOT=Path('/run/creality-source')
LOCK=json.loads((ROOT/'config/versions.lock.json').read_text())
ENV_KEYS={'OCL_ICD_VENDORS','RUSTICL_ENABLE','ROCR_VISIBLE_DEVICES','DRI_PRIME','DXVK_FILTER_DEVICE_NAME','HSA_ENABLE_SDMA'}
def digest(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def expect(p,h):
    if digest(p)!=h:raise RuntimeError(f'Unsupported or changed dependency: {p}')
def load(path):
    c=json.loads(Path(path).read_text())
    for k in ('runner','installer','dxvk_dir','data_dir'):
        p=Path(c[k]).expanduser()
        if not p.is_absolute():raise ValueError(f'{k} must be absolute (or start with ~)')
        c[k]=p.resolve()
    if not c.get('gpu_name') or not isinstance(c['gpu_name'],str):raise ValueError('gpu_name must identify intended GPU')
    env=c.get('environment',{})
    if not isinstance(env,dict) or set(env)-ENV_KEYS or not all(isinstance(v,str) and '\0' not in v for v in env.values()):raise ValueError('Unsupported environment configuration')
    for key in ('blue_laser_fix','device_memory_fix'):
        if not isinstance(c.get(key),bool):raise ValueError(f'{key} must be boolean')
    if not isinstance(c.get('allow_host_network',False),bool):raise ValueError('allow_host_network must be boolean')
    c['display']=c.get('display') or 'desktop'
    if c['display'] not in MODES:raise ValueError('display must be "desktop" or "isolated"')
    c['prefix']=c['data_dir']/'prefix'
    # Never expose the checkout/trust store through the writable state mount.
    protected=(ROOT, integrity.TRUST_ROOT, installation_path(c).parent, c['runner'])
    for p in protected:
        if p.is_relative_to(c['data_dir']) or c['data_dir'].is_relative_to(p):
            raise ValueError('data_dir must be separate from source, trust and runner directories')
    c['exports_dir']=check_dir(c.get('exports_dir') or default_dir(),(*protected,c['data_dir']))
    return c

def dependencies(c,installer=False):
    if tree_digest(c['runner']) != LOCK['runner_tree_sha256']:
        raise RuntimeError('Complete Wine runner inventory/content mismatch')
    for name in ('wine','wineserver'):expect(c['runner']/'bin'/name,LOCK[name+'_sha256'])
    expect(c['runner']/'lib/wine/x86_64-windows/mf.dll',LOCK['mf_sha256'])
    # Installs made with an earlier pinned DXVK keep working; new installs use LOCK['dxvk'].
    accepted=[LOCK['dxvk'],*({n:h for n,h in a.items() if n.endswith('.dll')} for a in LOCK.get('dxvk_also_accepted',[]))]
    if not any(all((c['dxvk_dir']/n).is_file() and digest(c['dxvk_dir']/n)==h for n,h in a.items()) for a in accepted):
        raise RuntimeError(f'Unsupported or changed dependency: DXVK in {c["dxvk_dir"]}')
    if installer:expect(c['installer'],LOCK['installer_sha256'])

def owned(c,create=False):
    state=c['data_dir'];mark=state/'community-owner.json'
    if not mark.exists():
        if not create:raise RuntimeError('Run install first')
        if state.exists() and any(state.iterdir()):raise RuntimeError('Refusing unowned nonempty data_dir; choose a NEW directory')
        stateio.ensure_directory(state)
        stateio.write_new(mark,json.dumps({'format':1,'owner':'crealityscan-linux-community'})+'\n')
    if json.loads(stateio.read_text(mark))!={'format':1,'owner':'crealityscan-linux-community'}:raise RuntimeError('Invalid ownership marker')
    if c['prefix'].is_symlink():raise RuntimeError('Prefix symlinks are refused')
    lockpath=installation_path(c).with_suffix('.lock')
    stateio.ensure_directory(lockpath.parent)
    try:f=stateio.open_file(lockpath,'xb')
    except FileExistsError:f=stateio.open_file(lockpath)
    try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        f.close()
        raise
    return f

def winpath(path):return 'Z:'+str(Path(path).resolve()).replace('/','\\')

def environment(c,log,backend='disabled'):
    # Avoid inherited prefixes, preloads or overrides accidentally affecting other apps.
    e={'PATH':'/usr/bin:/bin','WINEPREFIX':str(c['prefix']),'WINEARCH':'win64',
       'CREALITY_PREFIX_GUARD':str(c['prefix']),'CREALITY_GPU_NAME':c['gpu_name'],
       'WINEDLLOVERRIDES':'opencl=b;winemenubuilder.exe=d;msvcp140,msvcp140_1,vcruntime140,vcruntime140_1,concrt140=n,b;d3d11,dxgi=n;mf=n;mfstock=b,n;OrbbecSDK=n',
       'WINEDEBUG':'-all','WINEFSYNC':'1','PROTON_NO_NTSYNC':'1','HSA_ENABLE_SDMA':'0',
       'PIKA_CAMERA_BACKEND':backend,'PIKA_CAPTURE_OUTPUT':str(log),'DXVK_LOG_PATH':str(log)}
    e.update(c.get('environment',{}))
    preload=[]
    if c['blue_laser_fix']:preload.append(str(RUNTIME_ROOT/'build/usb-opencl.so'));e['CREALITY_BLUE_LASER_FIX']='1'
    if c['device_memory_fix']:preload.append(str(RUNTIME_ROOT/'build/dgg-device-memory.so'));e['CREALITY_DGG_DEVICE_MEMORY']='1'
    if preload:e['LD_PRELOAD']=':'.join(preload)
    return e

def sandbox(c,log,e,*,display=None,gpu=True,network=False,devices=(),installer=False,code_files=(),exports=None):
    if network and not c.get('allow_host_network',False):
        raise RuntimeError('Wi-Fi shares host network services and abstract sockets. Read SECURITY.md and explicitly set allow_host_network=true to opt in.')
    # Empty mount namespace: no host home, /etc secrets, /run sockets or root bind.
    cmd=['bwrap','--die-with-parent','--new-session','--unshare-pid','--unshare-ipc',
         '--unshare-uts','--unshare-net','--tmpfs','/',
         '--ro-bind','/usr','/usr','--dev','/dev','--proc','/proc',
         '--tmpfs','/tmp','--tmpfs','/run']
    for name in ('bin','sbin','lib','lib64'):
        p=Path('/')/name
        if p.is_symlink():cmd+=['--symlink',os.readlink(p),str(p)]
        elif p.exists():cmd+=['--ro-bind',str(p),str(p)]
    # Public runtime configuration only; never bind all of /etc or /opt.
    for name in ('ld.so.cache','ld.so.conf','ld.so.conf.d','fonts','OpenCL','vulkan',
                 'glvnd','localtime','nsswitch.conf','passwd','group'):
        p=Path('/etc')/name
        if p.exists():cmd+=['--ro-bind',str(p.resolve()),str(p)]
    if network:
        # Separate network namespace is deliberately replaced only for Wi-Fi.
        cmd.remove('--unshare-net')
        for name in ('hosts','resolv.conf'):
            p=Path('/etc')/name
            if p.exists():cmd+=['--ro-bind',str(p.resolve()),str(p)]
    if gpu:
        for p in (Path('/sys'),Path('/opt/rocm')):
            if p.exists():
                cmd+=['--ro-bind',str(p.resolve()),str(p.resolve())]
                if p.is_symlink():cmd+=['--symlink',str(p.resolve()),str(p)]
        for dev in ('/dev/dri','/dev/kfd'):
            if Path(dev).exists():cmd+=['--dev-bind',dev,dev]
    cmd+=['--ro-bind',str(c['runner']),str(c['runner']),
          '--bind',str(c['data_dir']),str(c['data_dir'])]
    for part in ('scripts','src/usb-bridge','build'):
        cmd+=['--ro-bind',str(ROOT/part),str(RUNTIME_ROOT/part)]
    if installer:cmd+=['--ro-bind',str(c['installer']),str(c['installer'])]
    for name in code_files:
        p=c['prefix']/name
        cmd+=['--ro-bind',str(p),str(p)]
    if display:
        # Only the selected X server's socket and cookie; never the Wayland socket.
        cmd+=['--ro-bind',str(display.socket),str(display.socket)]
        e['DISPLAY']=display.name
        if display.xauthority:
            cmd+=['--ro-bind',str(display.xauthority),'/run/xauthority'];e['XAUTHORITY']='/run/xauthority'
    if exports:cmd+=['--bind',str(exports),EXPORTS_MOUNT]
    if devices and Path('/run/udev').exists():cmd+=['--ro-bind','/run/udev','/run/udev']
    for dev in devices:cmd+=['--dev-bind',str(dev),str(dev)]
    cmd+=['--clearenv','--chdir',str(c['prefix'])]
    e['HOME']=str(c['prefix']/'home')
    e['USER']='scanner';e['LOGNAME']='scanner';e['LANG']='C.UTF-8'
    for k,v in e.items():cmd+=['--setenv',k,v]
    return cmd
