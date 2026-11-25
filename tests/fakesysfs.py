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


# Device and configuration descriptors of the Sermoon S1, verbatim from its
# survey in issue #7 (no strings, so no serial number). Each camera lists unit 6
# before unit 4; only the IR camera's unit 4 lists controls (1-3).
S1_DESCRIPTORS = bytes.fromhex('''
    12011003ef020109c52b060c1904010203010902ec02050104c000080b00020e03000509040000000e0100050d240100016900006cdc02010112240201010200
    00000000000000030a00000b240503010040020002001b240606d09ee4237811314fae52d2fb8a8d3b480e0103020000001b240604a15157a5c5f35e4a8d5a68
    54b8fa27160601060207000009240307010100040009040100010e0200060e240101c90081000700000001001b240401035938202000001000800000aa00389b
    710801000000002e24050100000520030000e20400004c1d00401f00151605000515160500801a060020a107002a2c0a0040420f002e240502000005c0030000
    dc050000282300802500151605000515160500801a060020a107002a2c0a0040420f003e240503004006b00400c027090080ee3600983a0007b201000907b201
    0048e80100092e02000a8b0200400d030090d00300151605002a2c0a0040420f0006240d0101040705810200040006300d000000080b02020e03000809040200
    000e0100080d240100016900006cdc0201031224020101020000000000000000030a20000b240503010040025b16001b240606d09ee4237811314fae52d2fb8a
    8d3b480e0103020000001b240604a15157a5c5f35e4a8d5a6854b8fa27160601060200000009240307010100040009040300010e0200090f240102db00820007
    0000000100041b240401025955593200001000800000aa00389b711001000000002624050100800738040040e3090080533b00483f002a2c0a00032a2c0a0040
    420f0080841e0026240502008007b0040080fc0a0000eb41005046002a2c0a00032a2c0a0040420f0080841e000b240602020001000000002a24070100800738
    040040e3090080533b00483f001516050004151605002a2c0a0040420f0080841e002a240702008007b0040080fc0a0000eb4100504600151605000415160500
    2a2c0a0040420f0080841e0006240d0101040705820200040006300d00000009040400010300000b09210101000122210007058303f8000406300000f800
'''.replace('\n', '').replace(' ', ''))


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
            units=((6, S1_UNIT6_GUID, 0x1f), (4, PIKA_GUID, 0x07)), serial='S1SERIAL42', first_node=2, rgb_units=None,
            raw=None):
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
    (dev/'descriptors').write_bytes(raw if raw is not None else descriptors(pid, units, rgb_units))
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
