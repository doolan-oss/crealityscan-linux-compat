"""Read-only report of connected Creality/Orbbec scanners, to paste into an issue.
Lists USB identity, interface types, camera formats and UVC extension units.
Serial numbers are never printed. Nothing is written to the device."""
import fcntl
import os
from pathlib import Path
import re
import struct

ORBBEC_VID = '2bc5'
NAMES = re.compile(r'creality|orbbec|pika|raptor|otter|ferret|sermoon|lizard|cr-scan', re.I)
CLASSES = {'01': 'audio', '02': 'communications', '03': 'HID', '08': 'mass storage', '0a': 'CDC data',
           '0e': 'video (UVC)', 'e0': 'wireless', 'ef': 'misc', 'fe': 'application', 'ff': 'vendor-specific'}
VIDIOC_QUERYCAP, VIDIOC_ENUM_FMT = 0x80685600, 0xC0405602
VIDIOC_ENUM_FRAMESIZES, VIDIOC_ENUM_FRAMEINTERVALS = 0xC02C564A, 0xC034564B
CAPTURE, META_CAPTURE = 1, 13


def read(path, default=''):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def scanners(root=Path('/sys/bus/usb/devices')):
    """USB devices made by Orbbec (Creality's scanner supplier) or named like a scanner."""
    found = []
    for dev in sorted(root.glob('*')):
        if ':' in dev.name or not (dev/'idVendor').exists():
            continue
        label = read(dev/'manufacturer') + ' ' + read(dev/'product')
        if read(dev/'idVendor') == ORBBEC_VID or NAMES.search(label):
            found.append(dev)
    return found


def extension_units(raw):
    """GUIDs of UVC extension units in the configuration descriptors."""
    guids, pos = [], 0
    while pos + 2 <= len(raw) and raw[pos] >= 2:
        size = raw[pos]
        if raw[pos+1] == 0x24 and size >= 20 and raw[pos+2] == 0x06:  # CS_INTERFACE, VC_EXTENSION_UNIT
            guids.append(f'unit {raw[pos+3]}: {raw[pos+4:pos+20].hex()}')
        pos += size
    return guids


def ioctl(fd, request, data):
    buf = bytearray(data)
    fcntl.ioctl(fd, request, buf)
    return bytes(buf)


def formats(node):
    """Capture formats with frame sizes and rates, without starting a stream."""
    lines = []
    fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        caps = struct.unpack_from('<I', ioctl(fd, VIDIOC_QUERYCAP, bytes(104)), 88)[0]
        kind = META_CAPTURE if caps & 0x00800000 and not caps & 1 else CAPTURE
        for i in range(32):
            try:
                desc = ioctl(fd, VIDIOC_ENUM_FMT, struct.pack('<II', i, kind) + bytes(56))
            except OSError:
                break
            fourcc = desc[44:48].decode('ascii', 'replace')
            name = desc[12:44].split(b'\0')[0].decode('ascii', 'replace')
            sizes = []
            for j in range(32):
                try:
                    size = ioctl(fd, VIDIOC_ENUM_FRAMESIZES, struct.pack('<II', j, struct.unpack_from('<I', desc, 44)[0]) + bytes(36))
                except OSError:
                    break
                if struct.unpack_from('<I', size, 8)[0] != 1:  # not discrete
                    sizes.append('stepwise'); break
                w, h = struct.unpack_from('<II', size, 12)
                rates = []
                for k in range(16):
                    try:
                        ival = ioctl(fd, VIDIOC_ENUM_FRAMEINTERVALS, struct.pack('<IIIII', k, struct.unpack_from('<I', desc, 44)[0], w, h, 0) + bytes(32))
                    except OSError:
                        break
                    num, den = struct.unpack_from('<II', ival, 20)
                    if struct.unpack_from('<I', ival, 16)[0] == 1 and num:
                        rates.append(f'{den/num:g}')
                sizes.append(f'{w}x{h}' + (f'@{"/".join(rates)}' if rates else ''))
            lines.append(f'{"metadata" if kind == META_CAPTURE else "capture"} {fourcc} ({name}): {", ".join(sizes) or "-"}')
    finally:
        os.close(fd)
    return lines


def report(root=Path('/sys/bus/usb/devices'), v4l=Path('/sys/class/video4linux'), hid=Path('/sys/class/hidraw')):
    out = []
    devices = scanners(root)
    if not devices:
        return 'No Creality or Orbbec USB scanner found. Connect it by USB and run this again.'
    for dev in devices:
        real = dev.resolve()
        out.append(f'USB {read(dev/"idVendor")}:{read(dev/"idProduct")}  {read(dev/"manufacturer")} {read(dev/"product")}'
                   f'  (revision {read(dev/"bcdDevice")}, {read(dev/"speed")} Mbit/s, serial number not shown)')
        for intf in sorted(dev.glob(f'{dev.name}:*')):
            cls = read(intf/'bInterfaceClass')
            driver = os.path.basename(os.readlink(intf/'driver')) if (intf/'driver').exists() else 'no driver'
            out.append(f'  interface {read(intf/"bInterfaceNumber")}: {CLASSES.get(cls, cls)} '
                       f'(class {cls}/{read(intf/"bInterfaceSubClass")}/{read(intf/"bInterfaceProtocol")}), {driver}')
        try:
            units = extension_units((dev/'descriptors').read_bytes())
        except OSError:
            units = []
        out += [f'  UVC extension {u}' for u in units]
        for entry in sorted(v4l.glob('video*'), key=lambda p: int(p.name[5:] or 0)):
            if real not in entry.resolve().parents:
                continue
            node = '/dev/' + entry.name
            try:
                lines = formats(node)
            except OSError as e:
                lines = [f'cannot read formats: {e.strerror}']
            out.append(f'  {node} "{read(entry/"name")}" index {read(entry/"index")}')
            out += [f'    {line}' for line in lines]
        nodes = [p.name for p in sorted(hid.glob('hidraw*')) if real in p.resolve().parents]
        if nodes:
            out.append('  HID: ' + ', '.join('/dev/' + n for n in nodes))
    return '\n'.join(out)


def other_scanners(root=Path('/sys/bus/usb/devices')):
    """Connected Orbbec-made devices that are not the Pika (2bc5:0c0b)."""
    return [f'{read(d/"product") or "unknown scanner"} (USB {read(d/"idVendor")}:{read(d/"idProduct")})'
            for d in scanners(root) if read(d/'idVendor') == ORBBEC_VID and read(d/'idProduct') != '0c0b']


if __name__ == '__main__':
    print(report())
