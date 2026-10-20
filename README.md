# CrealityScan on Linux — community Pika support

Run **CrealityScan 4.3.2** with a **Creality Pika** scanner on Linux. The app runs
in Wine inside a sandbox, opens as normal desktop windows, and saves your scans
to an ordinary `Documents/CrealityScan` folder. This is an unofficial,
experimental community project; you supply the CrealityScan installer yourself.

Tested on CachyOS with an AMD RX 6800 XT (ROCm OpenCL) on KDE Plasma. Other
distributions and GPUs may work but are untested; read
[LIMITATIONS.md](docs/LIMITATIONS.md) before relying on it.

## Install

1. Install the required packages:
   - Arch/CachyOS: `sudo pacman -S --needed git bubblewrap python psmisc procps-ng`
   - Ubuntu 24.04: `sudo apt install git bubblewrap python3 psmisc procps`

   Your GPU also needs a Vulkan driver and an OpenCL driver. On AMD, the tested
   OpenCL driver is ROCm (`rocm-opencl-runtime` on Arch/CachyOS).
2. Download **CrealityScan 4.3.2 for Windows** (`CrealityScan_win_4.3.2.exe`)
   from Creality into your Downloads folder.
3. Get this project and run setup:

   ```sh
   git clone https://github.com/doolan-oss/crealityscan-linux-compat.git
   cd crealityscan-linux-compat
   python3 scripts/creality.py setup
   ```

   Setup downloads the rest (Wine, DXVK and this project's prebuilt helpers,
   about 100 MB), checks every download against a pinned checksum, installs
   CrealityScan, runs a GPU check and adds **CrealityScan** to your app menu.
   Allow about 3 GB of disk space.
4. If setup prints a `sudo` command for scanner access, run it once, then
   unplug and replug the scanner.
5. Connect the scanner by USB and open **CrealityScan** from your app menu.

Keep the `crealityscan-linux-compat` folder: the menu entry runs from it.

## Using it

- **Saving:** in the app's save dialog choose **Documents**. That is
  `~/Documents/CrealityScan` on Linux; projects are kept in its `Projects` folder.
  To import a model, copy it into that folder first.
- **Startup:** if the window opens behind other windows, click it. The app pauses
  loading while it is in the background.
- **Problems:** if the app can't start you'll usually get a desktop notification; logs
  are in `~/.local/share/crealityscan-linux/data/logs`. Wi-Fi mode and other
  options are in [SETUP.md](docs/SETUP.md).

**Help test it:** this has only been tested on one computer. Whether it worked
or not, please file a
[hardware report](https://github.com/doolan-oss/crealityscan-linux-compat/issues/new?template=hardware-report.yml)
with your distribution and GPU.

To uninstall, delete `~/.local/share/crealityscan-linux`,
`~/.local/share/applications/crealityscan-linux.desktop` and the
`crealityscan-linux-compat` folder. Your scans in `~/Documents/CrealityScan` stay.

## About the Releases page

`helpers-v*` releases hold this project's prebuilt helper programs (the USB
camera bridge, OpenCL fixes and diagnostics). **You don't need to download
anything from Releases:** setup fetches and checks the right one automatically.
Their "Source code" archives are snapshots of the commit the helpers were built
from; install from the main branch as above.

## Status

Before security hardening, the packaged setup passed a fresh-install **USB Blue
Laser with markers** test: live preview (approximately 110 FPS reported),
point-cloud acquisition, mesh generation, STL export and reopening in
CrealityScan. With the current hardened launcher and desktop display, a live USB
scan, STL export to Documents and reopening of moved projects passed (Proton 11.0
DXVK). With the official DXVK 3.1.1 now pinned and the CI-built helpers, live USB
scanning worked in every mode the user tried, at about 80–90 FPS in Laser Lines
mode on the RX 6800 XT. Other scan modes, extended
stability and other hardware remain untested; see
[VALIDATION.md](docs/VALIDATION.md).

## For developers

The USB bridge supplies camera enumeration, device identity/control interfaces
and real Linux V4L2 image/metadata transport to the Windows SDK. Scoped OpenCL
helpers address observed blue-laser compiler and RX 6800 XT allocation issues.
No patched vendor binary, vendor kernel source, Wine distribution, driver,
installer, recording or user prefix is included. [SETUP.md](docs/SETUP.md) covers
the manual recipe and building the helpers from source.

```sh
python3 scripts/creality.py --help
```

Project layout:

- `src/usb-bridge/`: Windows Media Foundation shim and native transport helpers.
- `src/opencl/`: opt-in, prefix-scoped compatibility and allocation fixes.
- `src/probes/`: transparent Windows rendering/OpenCL correctness probes.
- `scripts/`: config, build, isolated installer and launcher.
- `config/`: public example and pinned dependency hashes; personal config stays local.
- `tools/pika-recorder/`: [native recorder/replay](docs/NATIVE_RECORDER.md), no Wine or vendor DLLs.
- `tests/`, `docs/`: offline checks, setup and measured limitations.

Build products go in ignored `build/`. Installed software goes in a
user-selected **new** data directory outside source; projects and exports go in
the exports folder. Normal launches never recreate
a prefix; setup refuses unowned or incompletely populated locations. Existing
Steam/Proton installations are read-only inputs, not modified. Dependencies and
installed executables are checked against a host-only baseline before launch.
See [SECURITY.md](SECURITY.md) for filesystem/display isolation, Wi-Fi exceptions
and recording-input limits. Earlier prefixes require a new installation; they
are never migrated or rebaselined automatically.

Original source is MIT-licensed; see [NOTICE.md](NOTICE.md), the
[provenance audit](docs/PROVENANCE.md) and [third-party notices](THIRD_PARTY_NOTICES.md). Do not include local configs, logs, prefixes or recordings in issues
or commits without reviewing their contents. No GitHub publication is automated.
