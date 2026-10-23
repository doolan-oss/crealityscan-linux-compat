"""A fake sysfs tree for a connected scanner, shaped like the real Pika and,
from the survey in issue #7, the Sermoon S1."""
from pathlib import Path

PIKA_GUID = bytes.fromhex('a15157a5c5f35e4a8d5a6854b8fa2716')
S1_UNIT6_GUID = bytes.fromhex('d09ee4237811314fae52d2fb8a8d3b48')

# Camera nodes and formats of the Sermoon S1, verbatim from the survey in issue #7.
S1_SURVEY = """
  /dev/video2 "Creality Sermoon S1: Creality S" index 0
    capture GREY (8-bit Greyscale): 1280x800@30/25/20/15/10, 1280x960@30/25/20/15/10, 1600x1200@90/80/70/60/50/40/30/15/10
  /dev/video3 "Creality Sermoon S1: Creality S" index 1
    metadata UVCH (UVC Payload Header Metadata): -
  /dev/video4 "Creality Sermoon S1: Creality S" index 0
    capture YUYV (YUYV 4:2:2): 1920x1080@15/10/5, 1920x1200@15/10/5
    capture MJPG (Motion-JPEG): 1920x1080@30/15/10/5, 1920x1200@30/15/10/5
  /dev/video5 "Creality Sermoon S1: Creality S" index 1
    metadata UVCH (UVC Payload Header Metadata): -
"""


def formats_from_survey(text):
    """{node: survey.enumerate_formats(node)} rebuilt from survey report lines."""
    found, node = {}, None
    for line in text.strip().splitlines():
        line = line.strip()
        if line.startswith('/dev/'):
            node = line.split()[0]; found[node] = []
            continue
        kind, fourcc, rest = line.split(' ', 2)
        name, sizes = rest[1:].split('): ')
        found[node].append((kind, fourcc, name, [] if sizes == '-' else [
            (int(size.split('x')[0]), int(size.split('x')[1].split('@')[0]), [float(r) for r in size.split('@')[1].split('/')])
            for size in sizes.split(', ')]))
    return found


def xu(unit, guid, controls):
    """VC_EXTENSION_UNIT descriptor with one input pin and a one-byte control bitmap."""
    return bytes([26, 0x24, 0x06, unit]) + guid + bytes([bin(controls).count('1'), 1, 1, 1, controls, 0])


def descriptors(pid, units, rgb_units=None):
    """Device and configuration descriptors; units are each camera's extension
    units (unit, GUID, control bitmap), or the IR camera's when rgb_units is given."""
    device = bytes([18, 1, 0x20, 0x03, 0xef, 2, 1, 9, 0xc5, 0x2b, pid & 0xff, pid >> 8, 0x19, 0x04, 1, 2, 3, 1])
    body = b''
    for number, cls, sub, name in ((0, 0x0e, 1, 4), (1, 0x0e, 2, 5), (2, 0x0e, 1, 6), (3, 0x0e, 2, 5), (4, 3, 0, 7)):
        body += bytes([9, 4, number, 0, 0, cls, sub, 0, name])
        if sub == 1 and cls == 0x0e:
            body += b''.join(xu(*u) for u in (rgb_units if number and rgb_units is not None else units))
    config = bytes([9, 2, (9 + len(body)) & 0xff, (9 + len(body)) >> 8, 5, 1, 0, 0x80, 250])
    return device + config + body


def scanner(root, pid=0x0c06, product='Creality Sermoon S1', names=('Creality Sermoon S1 Depth Camera', 'Creality Sermoon S1 RGB Camera'),
            units=((6, S1_UNIT6_GUID, 0x1f), (4, PIKA_GUID, 0x07)), serial='S1SERIAL42', first_node=2, rgb_units=None):
    """Creates devices/, class/video4linux and class/hidraw under root; returns
    {'usb': device dir, 'nodes': {key: /dev path}}."""
    hub = root/'devices/usb4'
    dev = hub/'4-2'
    dev.mkdir(parents=True)
    (hub/'maxchild').write_text('4\n')
    for key, value in (('idVendor', '2bc5'), ('idProduct', f'{pid:04x}'), ('serial', serial), ('manufacturer', 'Creality'),
                       ('product', product), ('configuration', 'Default'), ('bcdDevice', '0419'), ('devnum', '7'),
                       ('speed', '5000')):
        (dev/key).write_text(value + '\n')
    (dev/'descriptors').write_bytes(descriptors(pid, units, rgb_units))
    strings = {0: names[0], 1: 'Video Streaming', 2: names[1], 3: 'Video Streaming', 4: 'HID Interface'}
    for number, label in strings.items():
        intf = dev/f'4-2:1.{number}'
        intf.mkdir()
        for key, value in (('bInterfaceNumber', f'{number:02x}'), ('bInterfaceClass', '03' if number == 4 else '0e'),
                           ('bInterfaceSubClass', '01' if number in (0, 2) else '00' if number == 4 else '02'),
                           ('bInterfaceProtocol', '00'), ('interface', label)):
            (intf/key).write_text(value + '\n')
    v4l = root/'class/video4linux'
    v4l.mkdir(parents=True)
    nodes = {}
    for offset, (number, index) in enumerate(((0, 0), (0, 1), (2, 0), (2, 1))):
        entry = v4l/f'video{first_node + offset}'
        entry.mkdir()
        (entry/'index').write_text(f'{index}\n')
        (entry/'name').write_text(f'{product}: Creality S\n')
        (entry/'device').symlink_to(dev/f'4-2:1.{number}')
        nodes[f'{number}:{index}'] = f'/dev/{entry.name}'
    hid = dev/'4-2:1.4/0003:2BC5:0C06.0001'
    hid.mkdir()
    (root/'class/hidraw/hidraw10').mkdir(parents=True)
    (root/'class/hidraw/hidraw10/device').symlink_to(hid)
    return {'usb': dev, 'nodes': nodes}


def pika(root):
    return scanner(root, 0x0c0b, 'Creality Pika', ('Creality Pika Depth Camera', 'Creality Pika RGB Camera'),
                   ((4, PIKA_GUID, 0x07),), 'AB12CD34EF', 0)
