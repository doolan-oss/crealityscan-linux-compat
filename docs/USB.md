# USB access and isolation

The Pika is identified by USB VID:PID 2bc5:0c0b and its measured extension-unit
GUID. Capture and metadata nodes come from sysfs, not fixed `/dev/videoN` names.
For multiple scanners, set `scanner_serial` in ignored local configuration.

## Scanner models

`scripts/models.py` describes each model the bridge can present to the SDK: USB
product ID, extension units, and the camera stream modes it offers (the RGB
camera's MJPEG modes are also offered as NV12 and RGB24, decoded natively). The
launcher passes the connected model's profile to the bridge and helpers in the
environment (format in `src/usb-bridge/scanner-profile.h`), so a profile can
change without rebuilding the helpers. The Pika profile reproduces the values
the bridge used before profiles existed.

| Model | USB ID | Status |
|---|---|---|
| Creality Pika | 2bc5:0c0b | Supported |
| Creality Sermoon S1 | 2bc5:0c06 | Experimental, untested; off by default |

The Sermoon S1 profile comes from a user's `survey` report: the same interface
layout and unit-4 extension unit as the Pika, an extra unit 6 (which the SDK is
not known to use; requests for it are forwarded and logged), and different
camera modes (greyscale up to 1600x1200 at 90 fps, colour up to 1920x1200). To
try it:

```sh
python3 scripts/creality.py experimental sermoon-s1
```

then start CrealityScan as usual. Each USB launch writes `scanner.txt` (model,
profile and camera formats, no serial) beside `wine.log`, `frames.log` (stream
requests) and `controls.log` (extension-unit traffic). `python3 scripts/creality.py logs`
bundles those and the app's own logs, including the SDK's `ScannerStreamSDK.log`
(which stream modes the SDK wants), into one zip file to attach to a report.
`python3 scripts/creality.py experimental sermoon-s1 --off` turns it off again. The
launcher also finds the device's HID nodes and forwards measured descriptors.

Check Linux access first: V4L2 image/metadata and HID nodes must be readable and
writable by your logged-in desktop user. Native `uvcvideo` normally supplies the
video nodes; a Windows USB driver inside Wine does not provide Linux access.
If HID/USB access is missing, these narrowly scoped udev rules can be installed
by an administrator after checking local policy:

```text
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="2bc5", ATTR{idProduct}=="0c0b", TAG+="uaccess"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="2bc5", ATTRS{idProduct}=="0c0b", TAG+="uaccess"
```

`config/70-creality-pika.rules` contains these lines and the same two for the
Sermoon S1 (`0c06`). Desktop sessions usually get camera access automatically,
but not HID access, which is why the rule is needed. Setup and each USB launch
check that you can open the connected scanner's camera and HID nodes. If you
can't, they name the blocked nodes and give the command that installs the rule;
if the rule is already installed, they say to unplug and replug the scanner first.

Reload rules and reconnect the scanner for the active seat ACL to apply. This
project does not automatically write `/etc`, add broad world-writable permissions
or install camera/kernel drivers. Diagnose access separately from camera support.

USB launch creates private PID/network/tmp namespaces. Only this scanner's
verified camera/metadata/HID nodes plus the selected graphics devices are exposed.
The private helper endpoints use a per-launch random token. Synthetic diagnostics
expose none of those hardware nodes and use a clearly synthetic identity.

An app/session lock protects this installation. A scanner lock plus process/node
ownership checks prevents ordinary conflicting use. To coordinate with an older
checkout, set `scanner_lock_root` to its existing workspace; both will use
`.creality-usb-bridge-test.lock`. Otherwise the public launcher's scanner lock is
local to data_dir. Do not run multiple scanner tools concurrently; uncooperative
external applications can race an ownership check.

Wi-Fi mode exposes no scanner USB nodes but shares host network. It does not
configure a Wi-Fi adapter, SSID, password, route or firewall. Resolve discovery
failures from current routing/log evidence rather than applying another user's
interface-specific firewall recipe.
