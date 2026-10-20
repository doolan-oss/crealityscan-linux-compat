# Desktop-style display evaluation — 18 October 2026

Status (20 October 2026): Gamescope has been removed. Usability now takes
priority, so the default is the desktop's own X server. xwayland-satellite is the
opt-in `"display": "isolated"` mode; see SECURITY.md for the trade-off and
VALIDATION.md for current results. The evaluation below is kept as the record
of 18 October; no CrealityScan instance or scanner was used in it.

## Why investigate a replacement?

The current Gamescope launcher renders at a fixed 1280×800. Maximizing its outer
window scales that image instead of increasing application resolution, and its
aspect ratio is a poor fit for ultrawide displays. Gamescope's window management
also left the automatic Wine export-folder browser without usable close controls.
Increasing resolution addresses sharpness but not normal multi-window behavior.

The candidate is [xwayland-satellite](https://github.com/Supreeeme/xwayland-satellite):
a separate rootless XWayland server whose windows become individual Wayland
desktop windows. Wine would receive only this private X socket, preserving the
separation from the host desktop's shared X server. The trusted display bridge,
not Wine, connects to the host Wayland compositor.

## Local evidence

Version 0.8.3 was extracted locally from a signed CachyOS package; its signature
was checked against the installed distribution keyring. All runtime dependencies
were already installed. No package or desktop service was installed or enabled.
This binary is a local experiment, **not an Ubuntu distribution artifact**.

Using the pinned Wine runner and a new disposable filesystem sandbox:

- Passed: synthetic Windows application opened at 1800×1000 and resized to
  2000×1100. The desktop exposed a 2560×1440 screen, not a fixed 1280×800 canvas.
- Passed: separate Explorer windows were classified as normal top-level windows
  with border/title/menu/minimize/maximize decoration requests. Two normal
  close-message cycles preserved the underlying dummy application. This checks
  normal window closure, not a physical click on every desktop control.
- Passed: standalone Windows OpenGL diagnostic used RX 6800 XT and verified the
  rendered pixel. This does not establish DXVK/Unity behavior or scanning FPS.
- The Gamescope-specific export-browser auto-dismissal helper was disabled only
  in this disposable test, so it could not conceal a browser-window failure.

The test used KDE/KWin Wayland on CachyOS. No GNOME, Ubuntu, live scanning,
fractional-scale, clipboard-isolation, or long-running stability pass is claimed.
Raw evidence and downloaded binaries remain outside the public source tree.

## Local adoption and secondary Ubuntu portability

The primary target is the local CachyOS/KDE machine. Ubuntu/GNOME compatibility
is a secondary, nice-to-have goal and does not block adopting a locally validated
backend. Keep configuration portable where practical and state the tested scope
clearly; do not claim Ubuntu support from a CachyOS-only test. A query to the
[official Ubuntu archive API](https://api.launchpad.net/1.0/ubuntu/+archive/primary?ws.op=getPublishedBinaries&binary_name=xwayland-satellite&exact_match=true&status=Published)
returned zero published `xwayland-satellite` binaries on this date. Do not document
`apt install xwayland-satellite` as a working installation path without rechecking.

Upstream requires XWayland >=23.1, xcb and xcb-util-cursor; its
[0.8.3 build manifest](https://github.com/Supreeeme/xwayland-satellite/blob/v0.8.3/Cargo.toml)
declares Rust >=1.85. A portable route needs a pinned upstream source revision,
verified download, locked Cargo dependencies and a toolchain/build environment
tested against the oldest supported Ubuntu release. A binary built on CachyOS
must not be assumed compatible with Ubuntu's glibc or CPU baseline. Any bundled
component must retain its own license and provenance, separate from this repo's
MIT source. No unreviewed PPA or graphics-stack replacement should be required.

Before making this a supported backend:

1. Review and constrain clipboard/primary-selection forwarding. The current
   upstream implementation bridges these selections; a private X socket alone
   does not guarantee the previous clipboard boundary. Keep this explicit rather
   than silently loosening isolation for desktop integration.
2. Implement per-session startup/readiness/cleanup, private socket selection and
   authentication, with no fallback to the host X display.
3. Check resize/maximize, close controls, modal/save dialogs, monitor movement
   and accelerated rendering on the local KDE desktop in the scanner-free
   harness; check scaling modes as needed for local use.
4. Then test CrealityScan and live USB locally in a separate prefix, including
   performance and export/reopening. Preserve Gamescope as an explicit tested
   alternative until that acceptance is complete.
5. As a separate portability follow-up, verify Ubuntu build/runtime dependencies,
   GNOME decorations and scaling. This is not a prerequisite for local adoption.

This evaluation establishes a plausible desktop-window replacement, not a
finished Ubuntu-compatible launcher or an explanation for the earlier FPS drop.
