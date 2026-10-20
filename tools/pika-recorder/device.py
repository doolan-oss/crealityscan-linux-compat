"""Native Pika discovery and bounded Orbbec integer-property transactions.
No SDK imports. Protocol framing reference recorded in README.md.
"""
import ctypes as C
import os
from pathlib import Path
import struct
import time

class Xu(C.Structure):
    _fields_ = [('unit', C.c_ubyte), ('selector', C.c_ubyte), ('query', C.c_ubyte),
                ('size', C.c_ushort), ('data', C.c_void_p)]


def discover():
    devices = {}
    for entry in Path('/sys/class/video4linux').glob('video*'):
        interface = (entry/'device').resolve()
        while interface != interface.parent and not (interface/'bInterfaceNumber').exists():
            interface = interface.parent
        parent = interface.parent
        try:
            if (parent/'idVendor').read_text().strip() != '2bc5' or (parent/'idProduct').read_text().strip() != '0c0b':
                continue
            serial = (parent/'serial').read_text().strip()
            if bytes.fromhex('a15157a5c5f35e4a8d5a6854b8fa2716') not in (parent/'descriptors').read_bytes():
                raise RuntimeError('Pika XU descriptor differs from verified hardware')
            d = devices.setdefault(str(parent), {'serial': serial, 'usb_path': str(parent), 'nodes': {}})
            key = f"{int((interface/'bInterfaceNumber').read_text(),16)}:{int((entry/'index').read_text())}"
            if key in d['nodes']: raise RuntimeError('Duplicate Pika endpoint')
            d['nodes'][key] = '/dev/'+entry.name
        except FileNotFoundError:
            continue
    return list(devices.values())


def parse_response(raw, opcode, request_id):
    if len(raw) < 10: raise ValueError('Truncated response')
    magic, words, op, rid, error = struct.unpack_from('<5H', raw)
    if magic != 0x4252 or op != opcode or rid != request_id:
        raise ValueError(f'Unmatched response: {raw.hex()}')
    end = 8 + 2*words
    if words < 1 or end > len(raw): raise ValueError('Invalid response length')
    if error: raise RuntimeError(f'Device rejected request: 0x{error:04x}, {raw[10:end]!r}')
    return raw[10:end]


class Control:
    def __init__(self, node, log):
        self.fd = os.open(node, os.O_RDWR|os.O_NONBLOCK|os.O_CLOEXEC|os.O_NOFOLLOW)
        self.libc = C.CDLL(None, use_errno=True)
        self.log = log
        self.request_id = 0
        self.saved = {}
        try:
            if struct.unpack('<H', self.xu(0x85, 2))[0] != 64:
                raise RuntimeError('Unexpected XU selector 2 length')
        except BaseException:
            os.close(self.fd)
            raise

    def xu(self, query, length, payload=b'', *, selector=2):
        buf = C.create_string_buffer(length)
        if payload: C.memmove(buf, payload, len(payload))
        arg = Xu(4, selector, query, length, C.addressof(buf))
        assert C.sizeof(arg) == 16
        if self.libc.ioctl(self.fd, 0xC0107521, C.byref(arg)) < 0:
            e = C.get_errno(); raise OSError(e, os.strerror(e))
        return buf.raw

    def transact(self, opcode, prop, value=None):
        self.request_id = (self.request_id+1)&0xffff
        payload = struct.pack('<I', prop)
        if value is not None: payload += struct.pack('<i', value)
        request = struct.pack('<4H', 0x4d47, len(payload)//2, opcode, self.request_id)+payload
        self.xu(1, 64, request.ljust(64, b'\0'))
        time.sleep(0.01)
        response = self.xu(0x81, 64)
        self.log({'opcode':opcode, 'property':prop, 'value':value, 'request':request.hex(), 'response':response.hex()})
        return parse_response(response, opcode, self.request_id)

    def get(self, prop):
        data = self.transact(1, prop)
        if len(data) != 20: raise ValueError(f'Unexpected property response size {len(data)}')
        return dict(zip(('current','max','min','default','step'), struct.unpack('<5i',data)))

    def set(self, prop, value, *, allow_laser_test=False, allow_illumination_test=False):
        from illumination import allowed
        if allow_illumination_test and allowed(prop,value):
            pass
        else:
            if prop not in (3, 152, 153, 2026): raise ValueError('Property not allowlisted')
            if prop in (3, 152, 153) and value != 0:
                if not (prop == 3 and value == 1 and allow_laser_test):
                    raise ValueError('Emitters require an explicit bounded test')
            if prop == 2026 and not 10 <= value <= 2500: raise ValueError('Exposure exceeds recorder limit')
        old = self.get(prop)
        if not old['min'] <= value <= old['max'] or (old['step'] > 0 and (value-old['min']) % old['step']):
            raise ValueError(f'Outside reported property range: {old}')
        if old['current'] == value: return
        self.saved.setdefault(prop, old['current'])
        self.transact(2,prop,value)
        if self.get(prop)['current'] != value: raise RuntimeError('Property readback mismatch')

    def close(self):
        errors=[]
        for prop,value in reversed(list(self.saved.items())):
            try:
                if self.get(prop)['current'] == value:continue
                self.transact(2,prop,value)
                if self.get(prop)['current'] != value: raise RuntimeError('Restore readback mismatch')
            except Exception as e: errors.append(f'{prop}: {e}')
        os.close(self.fd)
        if errors: raise RuntimeError('Control restore failed: '+ '; '.join(errors))
