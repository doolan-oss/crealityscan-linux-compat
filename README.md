# CrealityScan on Linux — community Pika support

Wine compatibility helpers and a reproducible, isolated setup for
**CrealityScan 4.3.2 / Creality Pika**. Tested hardware: CachyOS x86-64, AMD RX 6800 XT,
ROCm OpenCL and XWayland. The app opens as normal desktop windows and saves exports to an
ordinary `Documents/CrealityScan` folder. This is an unofficial experimental integration; the
original vendor software is supplied separately by the user.

The USB bridge supplies camera enumeration, device identity/control interfaces
and real Linux V4L2 image/metadata transport to the Windows SDK. Scoped OpenCL
helpers address observed blue-laser compiler and RX 6800 XT allocation issues.
No patched vendor binary, vendor kernel source, Wine distribution, driver,
installer, recording or user prefix is included.

Quick start: install `bubblewrap`, Python 3 and `psmisc`, put
`CrealityScan_win_4.3.2.exe` from Creality in your Downloads folder, then run
`python3 scripts/creality.py setup`. It downloads and checks everything else,
installs, runs diagnostics and adds CrealityScan to your app menu.
**[SETUP.md](docs/SETUP.md)** has the details, the manual recipe and building
from source. See
[VALIDATION.md](docs/VALIDATION.md) for what this packaged workflow actually passed,
and [LIMITATIONS.md](docs/LIMITATIONS.md) before relying on it for scans.

Before security hardening, the packaged setup passed a fresh-install **USB Blue Laser with markers** test:
live preview (approximately 110 FPS reported), point-cloud acquisition, mesh
generation, STL export and reopening in CrealityScan. This validates one short
workflow on the hardware above; other scan modes and extended stability remain
untested in the packaged prefix. With the current hardened launcher and desktop
display, a live USB scan, STL export to Documents and reopening of moved projects
passed (Proton 11.0 DXVK). With the official DXVK 3.1.1 now pinned and the
CI-built helpers, live USB scanning worked in every mode the user tried.

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
