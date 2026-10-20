# USB access and isolation

The Pika is identified by USB VID:PID2bc5:0c0b and its measured extension-unit
GUID. Capture and metadata nodes come from sysfs, not fixed `/dev/videoN` names.
For multiple Pikas, set `scanner_serial` in ignored local configuration. The
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
