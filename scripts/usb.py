"""Identity derived from sysfs; no serial, camera node or network profile is pinned."""
import fcntl,os,re,secrets,subprocess,sys
from pathlib import Path
from common import ROOT
sys.path.insert(0,str(ROOT/'tools/pika-recorder'))
from device import discover

def prepare(c):
    lockroot=Path(c['scanner_lock_root']).expanduser().resolve() if c.get('scanner_lock_root') else c['data_dir']
    lock=(lockroot/'.creality-usb-bridge-test.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    # Also catch legacy launchers whose lock is in a different checkout.
    process=subprocess.run(['pgrep','-x','CrealityScan.ex'],capture_output=True)
    if process.returncode!=1:raise RuntimeError('Close other CrealityScan sessions before opening the scanner')
    ds=[d for d in discover()if not c.get('scanner_serial') or d['serial']==c['scanner_serial']]
    if len(ds)!=1:raise RuntimeError('Expected one Pika; configure scanner_serial if multiple are connected')
    d=ds[0];nodes=d['nodes'];parent=Path(d['usb_path']);serial=d['serial']
    if not re.fullmatch('[A-Za-z0-9_-]{1,64}',serial):raise RuntimeError('Unexpected serial syntax')
    required=[nodes[k]for k in ('0:0','0:1','2:0','2:1')]
    owners=subprocess.run(['fuser',*required],capture_output=True)
    if owners.returncode!=1:raise RuntimeError('Scanner camera endpoints are busy or ownership could not be checked')
    hid=[str(Path('/dev')/p.name)for p in Path('/sys/class/hidraw').glob('*')if parent in (p/'device').resolve().parents]
    if not all(os.access(n,os.R_OK|os.W_OK)for n in required+hid):raise RuntimeError('Missing camera/HID permissions; see docs/USB.md')
    raw=(parent/'descriptors').read_bytes();hub=parent.parent
    e={'PIKA_CAMERA_BACKEND':'v4l2','PIKA_SDK_IDENTITY':'1','PIKA_CAMERA_TOKEN':secrets.token_hex(24),
       'PIKA_CONTROL_PORT':'38574','PIKA_CAMERA_PORT':'38573','PIKA_NODE_0':nodes['0:0'],'PIKA_NODE_1':nodes['2:0'],
       'PIKA_METADATA_0':nodes['0:1'],'PIKA_METADATA_1':nodes['2:1'],
       'PIKA_USB_SERIAL':serial,'PIKA_USB_REVISION':str(int((parent/'bcdDevice').read_text(),16)),
       'PIKA_USB_HUB':hub.name,'PIKA_USB_PORT':str(int(parent.name.split('.')[-1]if '.'in parent.name else parent.name.split('-')[-1])),
       'PIKA_USB_PORTS':(hub/'maxchild').read_text().strip(),'PIKA_USB_DESCRIPTOR':raw[:18].hex(),
       'PIKA_USB_CONFIG':raw[18:].hex(),'PIKA_USB_ADDRESS':(parent/'devnum').read_text().strip()}
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
    return e,required+hid,lock
