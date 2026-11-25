#!/usr/bin/python3
"""Scoped UVC control transport; only explicitly supplied nodes verified as the
selected scanner model (PIKA_USB_PID, default the Pika's 0c0b).
Protocol: 64-byte token; <4I op,endpoint,selector,length>; request bytes;
reply <2I errno,length> + bytes. XU ops 1 GET_LEN, 2 GET_CUR, 3 SET_CUR, with
the extension unit in selector bits 8-15 (0, from helpers-v1 bridges, means 4).
Units and selectors are limited to PIKA_XU (see scanner-profile.h).
Standard ops 10 QUERYCTRL, 11 G_CTRL, 12 S_CTRL use real V4L2 IDs.
One operation per connection. No network except private loopback.
"""
import ctypes as C
import errno
import fcntl
import json
import os
from pathlib import Path
import signal
import socketserver
import struct
import sys
import threading
# The launcher's scanner models (scripts/ is mounted beside src/ in the sandbox).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
from models import camera_units, selectors

class Xu(C.Structure):
    _fields_ = [('unit', C.c_ubyte), ('selector', C.c_ubyte), ('query', C.c_ubyte),
                ('size', C.c_ushort), ('data', C.c_void_p)]
libc = C.CDLL(None, use_errno=True)
assert C.sizeof(Xu) == 16
XU_QUERY = 0xC0107521
G_CTRL, S_CTRL, QUERYCTRL = 0xC008561B, 0xC008561C, 0xC0445624
nodes = sys.argv[1:]
if len(nodes) != 2:
    raise SystemExit('usage: control-helper.py /dev/videoDEPTH /dev/videoRGB')
token = os.environ['PIKA_CAMERA_TOKEN'].encode()
if not 16 <= len(token) <= 63: raise SystemExit('invalid token')
expected_serial = os.environ['PIKA_USB_SERIAL']
expected_pid = os.environ.get('PIKA_USB_PID', '0c0b').lower()
# unit -> (GUID in descriptor byte order, allowed selector bitmask)
units = {int(u): (bytes.fromhex(g), int(m, 16)) for u, g, m in
         (item.split(':') for item in os.environ.get('PIKA_XU', '4:a15157a5c5f35e4a8d5a6854b8fa2716:7').split(';'))}

locks = [threading.RLock(), threading.RLock()]
state = []
for index, node in enumerate(nodes):
    resolved = Path('/sys/class/video4linux', Path(node).name, 'device').resolve(strict=True)
    interface = resolved
    while not (interface / 'bInterfaceNumber').exists(): interface = interface.parent
    parent = interface.parent
    assert (parent/'idVendor').read_text().strip() == '2bc5'
    assert (parent/'idProduct').read_text().strip() == expected_pid
    assert (parent/'serial').read_text().strip() == expected_serial
    assert int((interface/'bInterfaceNumber').read_text().strip(),16) == index*2
    # Verify the measured XU descriptors, rather than relying only on the product ID.
    cameras = camera_units((parent/'descriptors').read_bytes())
    present = {(u, bytes.fromhex(g)) for _, found in cameras for u, g, m in found}
    assert all((unit, guid) in present for unit, (guid, mask) in units.items())
    # Controls this camera's own descriptors list; uvcvideo refuses others (ENOENT).
    mine = next((found for number, found in cameras if number == index*2), [])
    declared = {}
    for u, g, m in mine: declared.setdefault(u, m)
    print(f'UNITS endpoint={index} interface={index*2}: ' +
          ('; '.join(f'unit {u} {g} selectors {selectors(m)}' for u, g, m in mine) or 'none'), flush=True)
    fd = os.open(node, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
    state.append({'fd':fd,'saved':{},'declared':declared})

def xu(fd, unit, selector, query, length, payload=b''):
    if unit not in units or not 1 <= selector <= 32 or not units[unit][1] >> (selector-1) & 1 or not 1 <= length <= 1024:
        raise OSError(errno.EINVAL,'XU bounds')
    data = C.create_string_buffer(length)
    if payload: C.memmove(data,payload,min(length,len(payload)))
    arg = Xu(unit,selector,query,length,C.addressof(data))
    if libc.ioctl(fd,XU_QUERY,C.byref(arg)) < 0:
        e=C.get_errno(); raise OSError(e,os.strerror(e))
    return data.raw

def ctrl_get(fd, key):
    data=bytearray(struct.pack('<Ii',key,0)); fcntl.ioctl(fd,G_CTRL,data,True)
    return struct.unpack('<Ii',data)[1]

def ctrl_set(fd,key,value):
    data=bytearray(struct.pack('<Ii',key,value)); fcntl.ioctl(fd,S_CTRL,data,True)

# Limit standard writes to standard camera properties actually requested by the bridge.
allowed_controls={0x00980900,0x00980901,0x00980902,0x00980903,0x0098090c,
                  0x00980910,0x00980913,0x0098091a,0x0098091b,0x0098091c,0x009a0901,0x009a0902}
class Handler(socketserver.BaseRequestHandler):
    def read(self,n):
        out=b''
        while len(out)<n:
            block=self.request.recv(n-len(out))
            if not block: raise EOFError
            out+=block
        return out
    def handle(self):
        self.request.settimeout(4)
        try:
            if self.read(64) != token.ljust(64,b'\0'): return
            op,ep,selector,n=struct.unpack('<4I',self.read(16))
            if ep>1 or n>1024: return
            payload=self.read(n)
            out=b''; error=0; unit=None
            try:
                with locks[ep]:
                    fd=state[ep]['fd']
                    if op in (1,2,3):
                        unit=selector>>8 or 4; selector&=0xff
                        length=int.from_bytes(xu(fd,unit,selector,0x85,2),'little')
                        if not 0<length<=1024: raise OSError(errno.EOVERFLOW,'XU length')
                        if op==1: out=struct.pack('<I',length)
                        elif op==2: out=xu(fd,unit,selector,0x81,length)
                        else:
                            if n != length: raise OSError(errno.EINVAL,'XU length mismatch')
                            # Unmodified SDK commands only; no firmware/update API is invoked by our probe.
                            xu(fd,unit,selector,1,length,payload)
                    elif op==10:
                        b=bytearray(68); struct.pack_into('<I',b,0,selector)
                        fcntl.ioctl(fd,QUERYCTRL,b,True); out=bytes(b)
                    elif op==11: out=struct.pack('<i',ctrl_get(fd,selector))
                    elif op==12:
                        if selector not in allowed_controls or n!=4: raise OSError(errno.EINVAL,'control bounds')
                        if selector not in state[ep]['saved']: state[ep]['saved'][selector]=ctrl_get(fd,selector)
                        ctrl_set(fd,selector,struct.unpack('<i',payload)[0])
                    else: raise OSError(errno.ENOTSUP,'operation')
            except OSError as e: error=e.errno
            declared=bool(state[ep]['declared'].get(unit,0)>>(selector-1)&1) if unit and selector else None
            print(json.dumps({'op':op,'endpoint':ep,'unit':unit,'selector':selector,'declared':declared,'request_length':n,
                              'request_header':payload[:24].hex() if op==3 else None,
                              'response_length':len(out),'errno':error,'error':errno.errorcode.get(error)}),flush=True)
            self.request.sendall(struct.pack('<2I',error,len(out))+out)
        except (OSError,EOFError): return
class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=False
server=Server(('127.0.0.1',int(os.environ['PIKA_CONTROL_PORT'])),Handler)
# Wake serve_forever from a different thread; preserve cleanup on SIGTERM.
def stop(signum,frame): threading.Thread(target=server.shutdown,daemon=True).start()
signal.signal(signal.SIGTERM,stop)
signal.signal(signal.SIGINT,stop)
print(f'READY scoped UVC control helper for scanner 2bc5:{expected_pid}, extension units {sorted(units)}',flush=True)
try: server.serve_forever(poll_interval=.1)
finally:
    server.server_close()
    restore_failed=False
    for ep,item in enumerate(state):
        # V4L2 rejects manual exposure writes while auto exposure is active.
        # Restore saved exposure under MANUAL, then restore saved auto mode last.
        if 0x009a0902 in item['saved'] and 0x009a0901 in item['saved']:
            try: ctrl_set(item['fd'],0x009a0901,1)
            except OSError as e:
                restore_failed=True
                print(f'RESTORE preparation failed endpoint={ep}: {e}',flush=True)
        for key,value in sorted(item['saved'].items(), key=lambda pair: pair[0]==0x009a0901):
            try: ctrl_set(item['fd'],key,value); print(f'RESTORED endpoint={ep} control={key:x} value={value}',flush=True)
            except OSError as e:
                restore_failed=True
                print(f'RESTORE FAILED endpoint={ep} control={key:x}: {e}',flush=True)
        os.close(item['fd'])
    print('CLOSED control helper',flush=True)
    if restore_failed:raise SystemExit(3)
