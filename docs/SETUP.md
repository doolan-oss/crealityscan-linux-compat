# Setup

## Quick setup

1. Install the runtime packages (no compilers needed):
   - Arch/CachyOS: `sudo pacman -S --needed bubblewrap python psmisc procps-ng`
   - Ubuntu 24.04: `sudo apt install bubblewrap python3 psmisc procps`

   Your GPU also needs a working Vulkan driver and an OpenCL driver. The tested
   combination is an AMD RX 6800 XT with ROCm OpenCL (`rocm-opencl-runtime` on
   Arch); other GPUs and OpenCL drivers are untested (see LIMITATIONS.md).
2. Download **CrealityScan 4.3.2 for Windows** (`CrealityScan_win_4.3.2.exe`)
   from Creality into your Downloads folder.
3. From this repository, run:

   ```sh
   python3 scripts/creality.py setup
   ```

Setup downloads the pinned Wine runner and DXVK into
`~/.local/share/crealityscan-linux/runtime`, checking each archive's SHA-256
before unpacking it. It then:

- finds the installer by checksum
- detects your GPU (the discrete one, if you also have integrated graphics)
- writes `config.local.json`
- installs CrealityScan into `~/.local/share/crealityscan-linux/data`
- runs the diagnostics
- adds **CrealityScan** to your app menu

If no scanner USB rule is installed, it prints the one `sudo` command needed.
Rerunning setup reuses finished steps. Options: `--installer PATH`, `--gpu-name NAME`.

Helper binaries come from a pinned prebuilt release when one is pinned in
`config/versions.lock.json`. Each release is built by this repository's GitHub
Actions workflow (see THIRD_PARTY_NOTICES.md). Until a release is pinned,
setup builds them from source, which needs the build packages below.

## Manual setup and building from source

The rest of this guide is the step-by-step recipe that `setup` automates, for
custom locations or building from source. It pins the tested 4.3.2 installer,
Wine runner and DXVK release in `config/versions.lock.json` and rejects different
hashes rather than applying version-specific shims to untested binaries.
This is functional reproducibility from pinned inputs, not a claim of
bit-identical compiler output across toolchains or support for every GPU or
distribution.

Building from source also needs GCC, Clang, LLD (`lld-link`), LLVM
(`llvm-dlltool`), Linux UAPI headers, libyuv and OpenCL headers:

- Arch/CachyOS: `gcc clang lld llvm libyuv opencl-headers`
- Ubuntu 24.04: `gcc g++ clang lld llvm libyuv-dev libjpeg-turbo8-dev opencl-c-headers`

A graphical desktop session with X11 support is required (Wayland with XWayland,
or Xorg). The optional isolated display also needs
[xwayland-satellite](https://github.com/Supreeeme/xwayland-satellite) and
XWayland 23.1 or newer. Ubuntu does not package xwayland-satellite (checked
18 October 2026), so use the default desktop display there. `clinfo` and
`vulkan-tools` help diagnose GPU problems. On Arch, avoid `pacman -Sy` followed
by selective installs. Apart from the menu entry, these scripts install no
system packages, drivers, udev rules or firewall rules.

## Obtain external inputs

1. Obtain **CrealityScan_win_4.3.2.exe** from Creality; expected SHA-256 is in the
   lockfile. Keep the installer outside the repo. It contains the required x64
   app/SDK; no Windows display driver is installed by this integration.
2. The standalone **Kron4ek Proton Experimental 11.0 amd64** Wine distribution and
   the official **DXVK 3.1.1** release. `python3 scripts/creality.py fetch`
   downloads both (pinned URLs and SHA-256 in the lockfile) and prints their
   paths for `configure`. `runner` is the directory containing `bin/wine`,
   `include/wine` and `lib/wine`; `dxvk_dir` is the release's `x64` folder.
   Every launch verifies the complete runner file/link inventory against
   `runner_tree_sha256`; extra files or modified runner libraries are refused.
   Other DXVK releases are not silently substituted.

The supplied Wine, Wine headers, DXVK, system libraries and Creality application
retain their own licenses. No external binary is committed here.

## Configure (fish and Bash compatible)

From the repository directory, substitute real absolute paths:

```sh
python3 scripts/creality.py configure --runner '/absolute/path/to/wine-proton-exp-11.0-amd64' --installer '/absolute/path/to/CrealityScan_win_4.3.2.exe' --dxvk-dir '/absolute/path/to/dxvk/x86_64-windows' --data-dir '/absolute/path/to/NEW-crealityscan-data'
```

This exclusively creates ignored `config.local.json`; it refuses overwrite.
Edit that JSON before continuing. Paths with spaces are supported. `data_dir`
must be new/empty and must not point to an existing working prefix or project.
The setup creates `prefix/`, logs and an ownership marker beneath it. A separate
host-only installation baseline and session lock are stored in
`~/.local/share/crealityscan-linux/trust/`, so re-cloning or moving this checkout
keeps them. That store is not exposed to Wine. Installs made before it existed
use the checkout's ignored `.local-trust/`, which is still read.
A baseline from an older writable `installation.json` is not accepted; choose a
new data directory and install afresh. Existing prefixes are preserved.

`display` chooses where the app's windows appear; both give normal desktop windows:

- `"desktop"` (default): your desktop's own X server. Works on KDE, GNOME and
  Xorg without extra packages.
- `"isolated"`: a private XWayland server per run via `xwayland-satellite`,
  keeping the app away from your other X11 apps. Needs a Wayland session.

`exports_dir` is the one ordinary folder the app may write: its exports and its
projects (in `Projects`). `configure` sets it to
`CrealityScan` inside your Documents folder; `null` means the same default. It
must be a dedicated folder, not your home directory or a folder containing the
source, runner or data directory. SECURITY.md describes both settings' boundaries.

`gpu_name` is a substring of the intended OpenCL device name/AMD board name and
OpenGL renderer, for example `RX 6800 XT` on the tested hardware. Set only needed
entries in `environment` using values measured on your machine:

- `OCL_ICD_VENDORS`: an existing host ICD file/directory, if selecting one ICD.
- `ROCR_VISIBLE_DEVICES`: your selected ROCm device UUID, if multiple GPUs exist.
- `DRI_PRIME`: your Mesa PCI/device selector, if needed.
- `DXVK_FILTER_DEVICE_NAME`: your intended Vulkan device name substring.
- `RUSTICL_ENABLE`: `radeonsi` only if deliberately testing Rusticl.
- `HSA_ENABLE_SDMA`: defaults to 0 for the tested ROCm workaround; override to 1
  only as an explicit experiment. This affects this app process, not the desktop.

No GPU UUID, PCI address, scanner serial or Wi-Fi adapter identity is supplied by
our public example. Blank environment retains driver defaults. The RX 6800 XT
allocation fix remains explicitly GPU guarded; configurability does not prove
other GPUs/ICDs work. `blue_laser_fix` and `device_memory_fix` are opt-in booleans
in the local config, enabled by the tested recipe. Their prefix guard is provided
by the launcher; no source recompilation is needed for a different checkout path.

## Build and install

```sh
python3 scripts/creality.py doctor
python3 scripts/creality.py build
python3 -m unittest discover -s tests -v
python3 scripts/creality.py install
```

Doctor verifies pinned inputs and commands. Build compiles only our source;
missing development libraries cause a compiler error without package changes.
Install runs the user-supplied installer silently in a new 64-bit prefix inside
Bubblewrap. Only the new data directory is writable; host network, scanner and
GPU devices are hidden during installation. The desktop display is available.
Wine's optional Mono/HTML bootstrap downloads are disabled for installation;
the tested Unity IL2CPP app does not require Wine Mono for this workflow.

After checking the original SDK hash, install preserves it as
`OrbbecSDK-stock.dll`, deploys the forwarding shim/Media Foundation bridge,
copies the runner's original `mf.dll` as `mfstock.dll`, and adds the matching
DXVK files locally. It also installs our diagnostic executables in this prefix.
The original runner and other prefixes are never edited.

Rerunning install on a completed installation only checks integrity. A failed or
interrupted install is preserved and refused on retry: inspect its logs and use
a **different new data_dir**. Never restore an old prefix over later projects.
Building changed code after installation also requires a new data directory for
validation; no automatic upgrade overwrites an existing user's application.

## Validate without a scanner

```sh
python3 scripts/creality.py diagnose
python3 scripts/creality.py smoke
```

Diagnose checks a compiled 256-element Windows OpenCL kernel result on the named
GPU, an OpenGL rendered pixel, and a synthetic Media Foundation source. Synthetic
identity is clearly labelled and is not scanner detection. Smoke starts the
installed app for 35 seconds, checks the Unity log for Direct3D/HomeState, then
terminates only this sandbox's Wine session. A successful smoke test establishes
startup, not responsiveness or scanning. These commands expose no scanner and
have no network access. Their temporary windows may appear on your desktop.
Unity pauses startup while its window is in the background, so smoke can report
NOT CONFIRMED if the window opens without focus; click the window and rerun.

## Launch and normal use

```sh
python3 scripts/creality.py launch --mode usb
python3 scripts/creality.py launch --mode wifi
```

Use one command at a time. USB mode discovers the actual Pika endpoints and
serial, verifies access/ownership, and starts private helper processes. Its
network namespace is isolated, so it cannot silently fall back to Wi-Fi.
See [USB.md](USB.md) for permissions and cross-checkout locking.
Wi-Fi mode shares the host network and exposes no scanner USB nodes. Connect
your scanner network through your normal desktop network tools first; no adapter,
SSID, routing or firewall changes are automated. SDK-provided network discovery
is used; we do not provide a native Wi-Fi protocol implementation.

**Saving exports:** in the app's save dialog, choose **Documents**. That folder
is your exports folder on Linux (`Documents/CrealityScan` by default), and files
appear there immediately. The dialog may first open in the app's install folder
(`C:\Program Files\CrealityScan`); files saved there stay inside the prefix.
To import a model, copy it into the exports folder first. The folder window the
app opens after export is a normal desktop window you can close.

**Projects** are stored in `Projects` inside the same folder, although the app
still shows its usual project paths. On the first launch with this version, the
launcher moves projects already in the prefix there (an instant rename on the
same disk; nothing is copied or deleted) and prints what it moved. Back up that
folder like any other documents. Close the app before moving or renaming
projects there.

Logs and app settings remain under data_dir. Some application logs can contain
scanner network credentials or personal paths; do not publish them unreviewed.
Close the app normally before unplugging or switching launchers. Reliability
limits and hardware acceptance still needed are in LIMITATIONS.md.

To undo, close the app and archive/remove only this newly owned data directory
and source/build folder as desired. Projects and exports are in the exports
folder, outside data_dir, which these scripts never remove. There are
no installed services, changed graphics drivers or shared Proton files to undo.

Inside the sandbox only the required scripts, USB source and build folders are
mounted read-only at
`/run/creality-source`. This avoids Linux's whitespace splitting of LD_PRELOAD
when the checkout path contains spaces. Before running Wine, the wrapper verifies
that each requested x64 helper is already loaded; missing helpers fail the run
instead of silently removing the fixes. This mount alias exists only inside the
private namespace and creates no host `/run` directory.


## Hardened runtime checks

See [SECURITY.md](../SECURITY.md) for the exact mount allowlist and residual risks.
The launcher no longer exposes host home directories. HOME belongs to the new
prefix. The exports folder is the only other writable location.
A nonstandard GPU ICD outside `/etc/OpenCL`, `/usr` or `/opt/rocm` needs a reviewed
mount change; do not restore a whole-host mount to make it visible.

Launches need a local desktop display (`DISPLAY=:N`); the isolated display also
needs `xwayland-satellite` on PATH and a Wayland session. A missing display fails
instead of falling back to the other mode. Wi-Fi retains host networking and has a
weaker boundary than USB. It is refused unless the local config explicitly sets
`"allow_host_network": true` after reviewing SECURITY.md. The default is false.
No network/desktop service settings are changed.

Removal: remove only the newly created data directory and its
`<data-directory-hash>.json` baseline in `~/.local/share/crealityscan-linux/trust/`
(or the checkout's `.local-trust/` for older installs). A prefix without its
baseline is never adopted: `install` refuses it and `setup` moves it aside.
