"""Scanner models the USB bridge can present to CrealityScan's SDK.

The launcher passes the connected model's profile to the bridge and helpers in
the environment (format in src/usb-bridge/scanner-profile.h). The Pika profile
reproduces the values the bridge used before profiles existed. Experimental
models are used only when the config lists them in experimental_scanners.
"""
from dataclasses import dataclass

PIKA_XU_GUID = 'a15157a5c5f35e4a8d5a6854b8fa2716'
# Orbbec's "ORBB" extension units on the CR-Scan Otter; the SDK never names them.
ORBB_1_GUID, ORBB_2_GUID = '4f524242000000000000000000000001', '4f524242000000000000000000000002'


@dataclass(frozen=True)
class Model:
    key: str            # name used in the config and on the command line
    name: str           # product name, also the Windows device description
    short: str          # in the SDK-visible extension unit names
    pid: str            # USB product ID; the vendor is always 2bc5
    units: tuple        # (unit, GUID) of each UVC extension unit the bridge exposes
    modes: tuple        # per camera endpoint (IR, RGB, ...): (fourcc, width, height, rates);
                        # endpoint n is the camera whose VideoControl interface is 2n
    experimental: bool = False
    note: str = ''
    # Give each camera its own extension units in its own descriptor order, as
    # Windows does; otherwise every camera gets camera 0's order (Pika, S1).
    units_per_camera: bool = False
    # Refuse frames that arrive without UVC metadata (timestamps for sync).
    needs_metadata: bool = True


def decoded(modes):
    """The RGB camera's MJPEG modes again as NV12 and BGR3, which the frame
    helper decodes natively so the camera's UVC metadata stays attached."""
    mjpg = [m for m in modes if m[0] == 'MJPG']
    return (*modes, *(('NV12',) + m[1:] for m in mjpg), *(('BGR3',) + m[1:] for m in mjpg))


PIKA_IR = (120, 110, 100, 90, 80, 70, 60, 50, 40, 30, 20, 15, 10)
PIKA_RGB = (60, 50, 40, 30, 20, 15, 10, 5)
OTTER_RATES = (30, 20, 15, 10, 5)
# The Otter's depth and IR cameras list the same formats (issue #10), in this order.
OTTER_MONO = (*(('Y10 ', w, h, OTTER_RATES) for w, h in ((320, 200), (640, 400), (1280, 800))),
              *(('GREY', w, h, OTTER_RATES) for w, h in ((320, 200), (640, 400), (1280, 800), (800, 600))),
              *(('MJPG', w, h, OTTER_RATES) for w, h in ((320, 200), (640, 400), (1280, 800))))
OTTER_COLOUR_SIZES = ((320, 240), (640, 480), (1280, 720), (1280, 960), (1920, 1080), (640, 360), (1280, 800))

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
    # From the survey in issue #10: three cameras (depth "De", IR, colour "RG"), Y10
    # formats and two extra Orbbec units. The SDK groups 06da with the Otter Lite
    # (0c04) in its AvatarDevice class and talks to it over the unit-4 protocol.
    Model('otter', 'Creality CR-Scan Otter', 'CR-Scan Otter', '06da',
          ((4, PIKA_XU_GUID), (8, ORBB_1_GUID), (12, ORBB_2_GUID)), (
              OTTER_MONO, OTTER_MONO,
              decoded((*(('YUYV', w, h, OTTER_RATES) for w, h in OTTER_COLOUR_SIZES),
                       *(('MJPG', w, h, OTTER_RATES) for w, h in OTTER_COLOUR_SIZES)))),
          experimental=True, note='untested: no Otter owner has reported a scan yet',
          units_per_camera=True, needs_metadata=False),
)}
BY_PID = {m.pid: m for m in MODELS.values()}


def encode_modes(modes):
    return ';'.join(f'{fourcc}:{w}x{h}:{",".join(map(str, rates))}' for fourcc, w, h, rates in modes)


def camera_units(raw):
    """Extension units of each camera, from the raw USB descriptors: a list, in
    descriptor order, of (VideoControl interface number, [(unit, GUID hex,
    selector mask), ...]). Bit n of the mask is set when the unit lists control
    (selector) n+1; uvcvideo only lets those controls through."""
    cameras, current, pos = [], None, 0
    while pos + 2 <= len(raw) and raw[pos] >= 2:
        size, kind = raw[pos], raw[pos+1]
        if kind == 4 and size >= 9:  # interface: VideoControl is class 0e, subclass 01
            current = (raw[pos+2], []) if raw[pos+5] == 0x0e and raw[pos+6] == 1 else None
            if current:
                cameras.append(current)
        elif kind == 0x24 and size >= 24 and raw[pos+2] == 0x06 and current:  # VC_EXTENSION_UNIT
            pins = raw[pos+21]
            mask = 0
            if pos + 23 + pins <= len(raw):
                control_size = raw[pos+22+pins]
                mask = int.from_bytes(raw[pos+23+pins:pos+23+pins+control_size], 'little')
            current[1].append((raw[pos+3], raw[pos+4:pos+20].hex(), mask))
        pos += size
    return cameras


def selectors(mask):
    return ','.join(str(i+1) for i in range(mask.bit_length()) if mask >> i & 1) or 'no controls'


def unit_report(model, cameras):
    """One line per camera listing its extension units, then a line per
    difference from what the model expects (missing unit, other GUID, no controls).
    Models whose cameras each have their own units only need each unit somewhere."""
    lines, problems = [], [] if cameras else ['no camera control interfaces found']
    for index, (interface, units) in enumerate(cameras):
        lines.append(f'camera {index} (interface {interface}): ' +
                     ('; '.join(f'unit {u} {g} selectors {selectors(m)}' for u, g, m in units) or 'no extension units'))
    if model.units_per_camera:
        for unit, guid in model.units:
            seen = [(index, g, m) for index, (_, units) in enumerate(cameras) for u, g, m in units if u == unit]
            if not seen:
                problems.append(f'extension unit {unit} is on no camera')
            for index, g, m in seen:
                if g != guid:
                    problems.append(f'camera {index}: extension unit {unit} differs from the known hardware')
                elif not m:
                    problems.append(f'camera {index}: extension unit {unit} reports no controls')
        return lines, problems
    for index, (interface, units) in enumerate(cameras):
        for unit, guid in model.units:
            found = [m for u, g, m in units if u == unit and g == guid]
            if not found:
                problems.append(f'camera {index}: extension unit {unit} differs from the known hardware')
            elif not found[0]:
                problems.append(f'camera {index}: extension unit {unit} reports no controls')
    return lines, problems


def environment(model, descriptors):
    """Bridge and helper settings for this model; descriptors are the device's
    raw USB descriptors, which give each camera's extension units and selectors.
    Supported models must match exactly. For experimental ones, differences are
    left to unit_report() to record, so a first test run still yields logs."""
    cameras = camera_units(descriptors)
    problems = unit_report(model, cameras)[1]
    if problems and not model.experimental:
        raise RuntimeError(f'{model.name}: {problems[0]}')
    # The SDK picks an extension unit by its topology node index, which on Windows
    # follows the device's descriptor order (the S1 lists unit 6 before unit 4).
    listed = [u for u, g, m in (cameras[0][1] if cameras else [])]
    known = dict(model.units)
    order = [u for u in dict.fromkeys(listed) if u in known] + [u for u in known if u not in listed]
    xu = []
    for unit in order:
        guid = known[unit]
        masks = [m for _, units in cameras for u, g, m in units if (u, g) == (unit, guid)]
        if masks:
            # The bridge takes one mask per unit: allow what any camera lists. If none
            # lists a control, pass every selector on so the kernel's answer is logged.
            mask = 0
            for m in masks:
                mask |= m
            xu.append(f'{unit}:{guid}:{mask or 0xffffffff:x}')
    e = {'PIKA_USB_PID': model.pid, 'PIKA_USB_PRODUCT': model.name, 'PIKA_MODEL_NAME': model.short,
         **{f'PIKA_MODES_{n}': encode_modes(modes) for n, modes in enumerate(model.modes)},
         'PIKA_XU': ';'.join(xu)}
    # Only what differs from the bridge's defaults, so two-camera models stay as they were.
    if len(model.modes) != 2:
        e['PIKA_CAMERAS'] = str(len(model.modes))
    if model.units_per_camera:
        # The SDK sends its vendor commands to a camera's last vendor-specific
        # node; on Windows nodes follow that camera's own descriptors.
        by_interface = dict(cameras)
        for n in range(len(model.modes)):
            own = [(u, g, m) for u, g, m in by_interface.get(2*n, []) if (u, g) in model.units]
            e[f'PIKA_XU_{n}'] = ';'.join(f'{u}:{g}:{m or 0xffffffff:x}' for u, g, m in own) or 'none'
    if not model.needs_metadata:
        e['PIKA_METADATA_REQUIRED'] = '0'
    return e


def camera_keys(model):
    """sysfs keys ("interface:index") of each camera's capture and metadata nodes."""
    return [f'{2*n}:{index}' for n in range(len(model.modes)) for index in (0, 1)]
