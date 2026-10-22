"""Scanner models the USB bridge can present to CrealityScan's SDK.

The launcher passes the connected model's profile to the bridge and helpers in
the environment (format in src/usb-bridge/scanner-profile.h). The Pika profile
reproduces the values the bridge used before profiles existed. Experimental
models are used only when the config lists them in experimental_scanners.
"""
from dataclasses import dataclass

PIKA_XU_GUID = 'a15157a5c5f35e4a8d5a6854b8fa2716'


@dataclass(frozen=True)
class Model:
    key: str            # name used in the config and on the command line
    name: str           # product name, also the Windows device description
    short: str          # in the SDK-visible extension unit names
    pid: str            # USB product ID; the vendor is always 2bc5
    units: tuple        # (unit, GUID) of each UVC extension unit, in the order the SDK sees them
    modes: tuple        # per camera endpoint (IR, RGB): (fourcc, width, height, rates)
    experimental: bool = False
    note: str = ''


def decoded(modes):
    """The RGB camera's MJPEG modes again as NV12 and BGR3, which the frame
    helper decodes natively so the camera's UVC metadata stays attached."""
    mjpg = [m for m in modes if m[0] == 'MJPG']
    return (*modes, *(('NV12',) + m[1:] for m in mjpg), *(('BGR3',) + m[1:] for m in mjpg))


PIKA_IR = (120, 110, 100, 90, 80, 70, 60, 50, 40, 30, 20, 15, 10)
PIKA_RGB = (60, 50, 40, 30, 20, 15, 10, 5)

MODELS = {m.key: m for m in (
    Model('pika', 'Creality Pika', 'Pika', '0c0b', ((4, PIKA_XU_GUID),), (
        (('GREY', 1280, 960, PIKA_IR), ('MJPG', 1280, 960, PIKA_IR)),
        decoded((('YUYV', 1280, 960, PIKA_RGB), ('MJPG', 1280, 960, PIKA_RGB))))),
    # From the survey in issue #7. Same interface layout and unit-4 protocol as
    # the Pika; the SDK has a dedicated SermoonS1Device class for this ID.
    Model('sermoon-s1', 'Creality Sermoon S1', 'Sermoon S1', '0c06',
          ((4, PIKA_XU_GUID), (6, 'd09ee4237811314fae52d2fb8a8d3b48')), (
              (('GREY', 1280, 800, (30, 25, 20, 15, 10)), ('GREY', 1280, 960, (30, 25, 20, 15, 10)),
               ('GREY', 1600, 1200, (90, 80, 70, 60, 50, 40, 30, 15, 10))),
              decoded((('YUYV', 1920, 1080, (15, 10, 5)), ('YUYV', 1920, 1200, (15, 10, 5)),
                       ('MJPG', 1920, 1080, (30, 15, 10, 5)), ('MJPG', 1920, 1200, (30, 15, 10, 5))))),
          experimental=True, note='untested: no S1 owner has reported a scan yet'),
)}
BY_PID = {m.pid: m for m in MODELS.values()}


def encode_modes(modes):
    return ';'.join(f'{fourcc}:{w}x{h}:{",".join(map(str, rates))}' for fourcc, w, h, rates in modes)


def extension_units(raw):
    """{unit: (GUID hex, selector bitmask)} from UVC extension unit descriptors.
    Bit n of the mask is set when the unit reports control (selector) n+1."""
    units, pos = {}, 0
    while pos + 2 <= len(raw) and raw[pos] >= 2:
        size = raw[pos]
        if raw[pos+1] == 0x24 and size >= 24 and raw[pos+2] == 0x06:  # CS_INTERFACE, VC_EXTENSION_UNIT
            pins = raw[pos+21]
            if pos + 23 + pins <= len(raw):
                control_size = raw[pos+22+pins]
                bitmap = raw[pos+23+pins:pos+23+pins+control_size]
                units[raw[pos+3]] = (raw[pos+4:pos+20].hex(), int.from_bytes(bitmap, 'little'))
        pos += size
    return units


def environment(model, descriptors):
    """Bridge and helper settings for this model; descriptors are the device's
    raw USB descriptors, which give each extension unit's selectors."""
    found = extension_units(descriptors)
    xu = []
    for unit, guid in model.units:
        if found.get(unit, (None,))[0] != guid:
            raise RuntimeError(f'{model.name}: extension unit {unit} differs from the known hardware')
        if not found[unit][1]:
            raise RuntimeError(f'{model.name}: extension unit {unit} reports no controls')
        xu.append(f'{unit}:{guid}:{found[unit][1]:x}')
    return {'PIKA_USB_PID': model.pid, 'PIKA_USB_PRODUCT': model.name, 'PIKA_MODEL_NAME': model.short,
            'PIKA_MODES_0': encode_modes(model.modes[0]), 'PIKA_MODES_1': encode_modes(model.modes[1]),
            'PIKA_XU': ';'.join(xu)}
