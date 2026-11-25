"""Identity derived from sysfs; no serial, camera node or network profile is pinned."""
import fcntl,os,re,secrets,subprocess,sys
from pathlib import Path
from common import ROOT
import models,stateio
sys.path.insert(0,str(ROOT/'tools/pika-recorder'))
from device import discover

V4L,HIDRAW=Path('/sys/class/video4linux'),Path('/sys/class/hidraw')
PRODUCTS={m.pid:[guid for _,guid in m.units] for m in models.MODELS.values()}

def select(c):
    """The connected scanner to use and its model; explains anything else."""
    ds=[d for d in discover(PRODUCTS,V4L)if not c.get('scanner_serial') or d['serial']==c['scanner_serial']]
    if not ds:
        from survey import other_scanners
        others=other_scanners()
        if others:raise RuntimeError(f'Found {", ".join(others)}, but USB support covers only the Creality Pika '
                                     '(and the Sermoon S1, experimentally) so far. Run "python3 scripts/creality.py survey" '
                                     'and share its output in a hardware report so support can be looked into.')
        raise RuntimeError('No supported Creality scanner found over USB. Connect it and try again; see docs/USB.md if it is connected.')
    if len(ds)>1:raise RuntimeError('More than one scanner is connected; set scanner_serial in the config to choose one')
    d=ds[0];model=models.BY_PID[d['pid']]
    if model.experimental and model.key not in c.get('experimental_scanners',[]):
        raise RuntimeError(f'USB support for the {model.name} is experimental ({model.note}). To try it, run '
                           f'"python3 scripts/creality.py experimental {model.key}" in the project folder, then start CrealityScan again.')
    return d,model

def device_nodes(d):
    """The camera/metadata nodes and HID nodes of a discovered scanner."""
    parent=Path(d['usb_path'])
    return ([d['nodes'][k]for k in ('0:0','0:1','2:0','2:1')if k in d['nodes']],
            [str(Path('/dev')/p.name)for p in HIDRAW.glob('*')if parent in (p/'device').resolve().parents])

def blocked(nodes):
    return [n for n in nodes if not os.access(n,os.R_OK|os.W_OK)]

def connected():
    try:return discover(PRODUCTS,V4L)
    except RuntimeError:return []

def access_problems():
    """(model, nodes this user cannot open) for each connected supported scanner with any."""
    found=[(models.BY_PID[d['pid']],blocked(sum(device_nodes(d),[])))for d in connected()]
    return [(m,nodes)for m,nodes in found if nodes]

def access_message(model,nodes):
    """Short enough for a desktop notification; the important part first."""
    from onboard import access_command,udev_rule_installed
    which=', '.join(nodes)
    if udev_rule_installed(model.pid):
        return (f'Scanner access blocked: {which}. Unplug and replug the scanner. If that does not help, '
                f'install the rule again in a terminal: {access_command()}')
    return (f'Scanner access blocked: {which}. Fix once in a terminal, then unplug and replug the scanner: '
            f'{access_command()}')

def check_helpers(e,model):
    """Older helper builds know only the Pika; say so instead of failing inside the app."""
    helper=ROOT/'build/sdk-frame-helper'
    r=subprocess.run([str(helper),'--check-profile'],env={'PATH':'/usr/bin:/bin',**e},capture_output=True,text=True)
    if r.returncode:raise RuntimeError(f'The helper programs in {ROOT/"build"} do not support the {model.name}. '
                                       'Run "python3 scripts/creality.py setup" to update them.')
    return r.stdout

def read(p):
    try:return Path(p).read_text().strip()
    except OSError:return ''

def missing_modes(model,nodes):
    """Profile modes the cameras do not list, for the launch log."""
    import survey
    notes=[]
    for endpoint,key in enumerate(('0:0','2:0')):
        try:offered={(f,w,h,round(r)) for _,f,_,sizes in survey.enumerate_formats(nodes[key]) for w,h,rates in sizes or () for r in rates}
        except OSError as e:notes.append(f'endpoint {endpoint}: cannot list formats: {e.strerror}');continue
        for fourcc,w,h,rates in model.modes[endpoint]:
            if fourcc in ('NV12','BGR3'):continue  # decoded from MJPG by the frame helper
            gone=[r for r in rates if (fourcc,w,h,r) not in offered]
            if gone:notes.append(f'endpoint {endpoint}: camera does not list {fourcc} {w}x{h} at {",".join(map(str,gone))} fps')
    return notes

def prepare(c,log=None):
    lockroot=Path(c['scanner_lock_root']).expanduser().resolve() if c.get('scanner_lock_root') else c['data_dir']
    lock=(lockroot/'.creality-usb-bridge-test.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    # Also catch legacy launchers whose lock is in a different checkout.
    process=subprocess.run(['pgrep','-x','CrealityScan.ex'],capture_output=True)
    if process.returncode!=1:raise RuntimeError('Close other CrealityScan sessions before opening the scanner')
    d,model=select(c)
    nodes=d['nodes'];parent=Path(d['usb_path']);serial=d['serial']
    if not re.fullmatch('[A-Za-z0-9_-]{1,64}',serial):raise RuntimeError('Unexpected serial syntax')
    required=[nodes[k]for k in ('0:0','0:1','2:0','2:1')]
    owners=subprocess.run(['fuser',*required],capture_output=True)
    if owners.returncode!=1:raise RuntimeError('Scanner camera endpoints are busy or ownership could not be checked')
    hid=device_nodes(d)[1]
    if blocked(required+hid):raise RuntimeError(access_message(model,blocked(required+hid)))
    raw=(parent/'descriptors').read_bytes();hub=parent.parent
    e={'PIKA_CAMERA_BACKEND':'v4l2','PIKA_SDK_IDENTITY':'1','PIKA_CAMERA_TOKEN':secrets.token_hex(24),
       'PIKA_CONTROL_PORT':'38574','PIKA_CAMERA_PORT':'38573','PIKA_NODE_0':nodes['0:0'],'PIKA_NODE_1':nodes['2:0'],
       'PIKA_METADATA_0':nodes['0:1'],'PIKA_METADATA_1':nodes['2:1'],
       'PIKA_USB_SERIAL':serial,'PIKA_USB_REVISION':str(int((parent/'bcdDevice').read_text(),16)),
       'PIKA_USB_HUB':hub.name,'PIKA_USB_PORT':str(int(parent.name.split('.')[-1]if '.'in parent.name else parent.name.split('-')[-1])),
       'PIKA_USB_PORTS':(hub/'maxchild').read_text().strip(),'PIKA_USB_DESCRIPTOR':raw[:18].hex(),
       'PIKA_USB_CONFIG':raw[18:].hex(),'PIKA_USB_ADDRESS':(parent/'devnum').read_text().strip()}
    e.update(models.environment(model,raw))
    units,problems=models.unit_report(model,models.camera_units(raw))
    for problem in problems:print(f'Warning: {model.name} {problem}; continuing (experimental).',flush=True)
    # Camera names as Windows shows them: the USB interface names.
    for i,number in enumerate((0,2)):
        name=read(parent/f'{parent.name}:1.{number}'/'interface')
        if name:e[f'PIKA_CAMERA_NAME_{i}']=name
    strings={raw[14]:(parent/'manufacturer').read_text().strip(),raw[15]:(parent/'product').read_text().strip(),raw[16]:serial}
    pos=18
    while pos+2<=len(raw)and raw[pos]:
        size,kind=raw[pos:pos+2]
        if kind==2 and size>=9:strings[raw[pos+6]]=(parent/'configuration').read_text().strip()
        if kind==4 and size>=9:
            p=parent/(parent.name+':1.'+str(raw[pos+2]))/'interface'
            if p.exists():strings[raw[pos+8]]=p.read_text().strip()
        pos+=size
    for k,v in strings.items():
        if k:e['PIKA_USB_STRING_'+str(k)]=v
    profile=check_helpers(e,model) if model.key!='pika' else ''
    if log:
        import survey
        status=' (experimental)' if model.experimental else ''
        shown={k:v for k,v in e.items() if k.startswith(('PIKA_MODES','PIKA_XU','PIKA_USB_PID','PIKA_USB_PRODUCT','PIKA_MODEL','PIKA_CAMERA_NAME'))}
        text=[f'Scanner: {model.name}{status}, USB 2bc5:{model.pid}',*(f'{k}={v}' for k,v in sorted(shown.items())),
              'Extension units:',*units,*(f'Warning: {p}' for p in problems),*missing_modes(model,nodes),profile,survey.report()]
        stateio.write_new(Path(log)/'scanner.txt','\n'.join(t for t in text if t)+'\n')
    return e,required+hid,lock
