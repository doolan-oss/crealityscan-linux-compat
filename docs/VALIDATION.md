# Release workflow validation — 18 October 2026

**The original full-workflow scan results below predate security hardening.**
The latest security changes have their own fresh-prefix results at the end of
this document, including a subsequent live USB preview check. Do not treat the
earlier 110 FPS or scan/export results as validation of the hardened setup.

The public source was built and installed into a **fresh** prefix, not a copy of
an existing working CrealityScan installation. The source folder and test data
are separate from the existing scanner setups. Tests used the checked installer,
standalone runner and matching DXVK inputs from versions.lock.json.

| Acceptance check | Result |
|---|---|
| External dependency hashes | Passed |
| Compile bridge, helpers, OpenCL shims and Windows probes from source | Passed, warnings treated as errors |
| Setup and rewrite tests | 10 passed, including 14 rewrite scenarios and the nested 22-test native suite |
| Fresh silent 4.3.2 installation and SDK/bridge deployment | Passed |
| Paths containing spaces | Passed in source, data and prefix, including a second clean install and diagnostics |
| Completed-install rerun | Passed: integrity verification only, no prefix reset |
| Active-session lock | Passed: concurrent install refused while smoke app ran |
| Windows x64 OpenCL | Passed: RX 6800 XT/gfx1030, compiler/images, 256 checked kernel results |
| Windows OpenGL rendering | Passed: Radeon renderer and checked rendered pixel |
| Synthetic Media Foundation pipeline | Passed: synchronous/asynchronous delivery, frame contents/timestamps, shutdown |
| Wrong-prefix bridge guard | Passed: no synthetic camera exposed; expected probe refusal |
| Real installed app startup | Passed: HomeState, Direct3D11, Radeon renderer |
| Real USB scanner connection and preview | Passed in a subsequent live test: Pika, Blue Laser with markers; user reported approximately 110 FPS |
| Fresh-prefix point-cloud acquisition | Passed: user completed a short marked blue-laser scan and confirmed the resulting point cloud |
| Mesh generation and STL export | Passed: user confirmation and app logs; exported binary STL contains 4,196,426 triangles with valid length and finite geometry |
| Reopen exported STL | Passed: user opened the exported STL in CrealityScan and confirmed correct display |
| Extended stability, repeated reconnects, other scan modes in this fresh prefix | Not tested |
| Wi-Fi workflow in fresh packaged setup | Not tested; installation/diagnostics were network-isolated |

The app smoke test runs for 35 seconds and exits via its own timeout (code 124 is
expected if startup checks pass). It closes only its private Wine session. It is
not a GUI interaction test or proof of scanner compatibility. DXVK and Unity
logs identified the Radeon; native rendering and OpenCL checks are separate.

An initial fresh-prefix attempt exposed Wine's optional Mono download prompt.
It was stopped without downloading Mono. The final installer environment disables
Mono/HTML bootstrap downloads and the next clean installation succeeded. The
aborted prefix was preserved separately, not recycled or used as successful proof.
The logs can contain harmless 32-bit-bootstrap warnings about the 64-bit preload;
the x64 probe results above establish the intended compute/rendering path.

Test environment: CachyOS x86-64, Python 3.13.9 (setup/tests) and 3.14.8 (sandbox helpers), GCC 16.2.1, Clang/LLD/LLVM 23.1.3,
libyuv r2921, OpenCL headers 2026.05.29, ocl-icd 2.3.5, Bubblewrap 0.13.1,
Mesa 26.2.4, ROCm ICD, Radeon RX 6800 XT. This is not validation of every supported
compiler, distribution, GPU or OpenCL implementation.

Raw test logs, configs and installation directories are kept outside the public
repo. They are intentionally not published: installed apps and logs can contain
personal data or credentials. The source publication check examines the staged
Git file set; it is a bounded packaging check, not a universal secret scanner.

A second clean prefix was installed from a relocated source checkout whose path
also contains spaces. The source built successfully there and installation exited
0. The runtime uses a fixed private source mount for preload paths; a mandatory
RTLD_NOLOAD check confirms the requested helpers are loaded into an x64 process.
Windows OpenCL, OpenGL and synthetic Media Foundation diagnostics passed again
in this relocated setup. Its final 35-second app smoke test also passed with
HomeState and Radeon Direct3D rendering, followed by the expected timeout exit.

Preservation checks matched all 70 recorded working-setup file hashes and all
49 original source-file hashes. No system packages, drivers, network settings or
working scanner configurations were changed for this packaging task.

To repeat the offline checks from the repository root:

```sh
python3 -m unittest discover -s tests -v
```

Before publication, stage the intended source files, then run:

```sh
git diff --cached --check
python3 scripts/check_public.py
```

## Completed live USB acceptance

The subsequent hardware test uses the same separate fresh prefix and packaged
source checkout. The app process has the V4L2 backend and both OpenCL helpers
loaded. Its private network namespace prevents a Wi-Fi fallback. Real USB frames
are arriving, and the user confirmed Blue Laser with markers live preview at
approximately 110 FPS. This is a reported preview rate, not an acquisition
benchmark. The user then completed a short scan and confirmed a resulting point
cloud. Mesh generation and STL export subsequently passed. The exported binary
STL is 209,821,384 bytes, contains 4,196,426 triangles, has the exact expected
record length and finite vertex/normal values. These checks establish file
structure, not dimensional accuracy or watertightness. The user then opened the
exported STL in CrealityScan and confirmed that it displayed correctly.

This completes the short USB Blue Laser with markers workflow: connection,
preview, acquisition, point cloud, mesh generation, STL export and reopening.
No runtime changes were needed during this hardware acceptance test. The scan,
export, private configuration and raw logs remain outside the public source tree.
Long-duration stability, reconnect recovery, marker-free blue laser, infrared and
Wi-Fi remain untested in this packaged prefix; historical results from other
prefixes are described separately in [LIMITATIONS.md](LIMITATIONS.md).

## Provenance cleanup regression checks

The source-matching expression was replaced after the full USB acceptance above.
The audited matcher retains the same complete-program fingerprint and replaces
only a standard OpenCL function token at its measured offset. The helper's
executable code is unchanged. See [PROVENANCE.md](PROVENANCE.md).

- Passed: 14 synthetic rewrite/pass-through cases across three new test methods;
  10 top-level tests total, including the 22-test native suite.
- Passed: private comparison against the actual captured program. Old and new
  executable program text is byte-for-byte identical. Only two compile-time
  layout assertions were removed; their vendor identifiers are no longer stored.
- Passed: the actual program compiles on RX 6800 XT/gfx1030 through the revised
  production matcher. Private program text is excluded from the repo.
- Passed: another build from source and clean installation in a new isolated
  prefix, followed by Windows GPU OpenCL, rendered pixel and synthetic camera
  diagnostics through the actual launcher.
- Passed: the unchanged atomic helper compiled and executed through Windows
  OpenCL in the audited prefix; all 256 return-value and adjacent-field
  preservation checks were correct.
- Passed: revised-build USB Blue Laser with markers preview and short point-cloud
  acquisition, confirmed by the user without errors. Logs confirm USB mode, the
  revised matcher being applied and scan completion. FPS was not separately
  reported for this rerun. Meshing/export/reopening passed on the prior packaged
  build and were not repeated after this matcher-only cleanup.

The earlier working prefixes and the full-workflow acceptance prefix were not
modified to apply this cleanup.

## Security hardening regression checks

Changes address the seven findings in a security review of the first public
version: replace
the whole-host mount, protect installation baselines and executable files,
refuse symlink/hard-link recording paths and output replacement, isolate the
display, verify the complete runner, remove raw debug-frame retention, and bound
offline input sizes/pairing/replay timing. Wi-Fi host networking is now refused
unless explicitly enabled; its weaker boundary is documented in SECURITY.md.

Passed on the same RX 6800 XT/CachyOS machine, using only a new disposable state:

- 23 top-level tests, including attack regressions and the existing nested
  22-test native suite. Regressions cover manifest tampering and missing/added
  executable files, unpinned runner changes, symlink/hard-link/FIFO rejection,
  directory replacement during output opening, pairing density, sparse replay
  timestamps, input limits and default refusal of shared display/network access.
  Host-side log/deployment symlinks and hard links are rejected before damage;
  replacing the app-visible session-lock filename cannot bypass the host lock.
- Native code rebuilt with warnings treated as errors. Python sources parse
  with Python 3.11 syntax rules. Public worktree inventory and whitespace checks
  pass; configs, trust metadata, prefixes, test logs and recordings are excluded.
- Actual Bubblewrap canary test: host secret/trust paths are absent, state is
  writable, executable mounts refuse write access, and network/devices are
  private. This uses dummy files, not personal secrets or scanner hardware.
- Fresh silent installation of pinned CrealityScan 4.3.2, then completed-install
  rerun verifying the protected baseline without recreating the prefix.
- Windows GPU OpenCL: RX 6800 XT, all 256 kernel results correct.
- Windows OpenGL: Radeon renderer and checked rendered pixel, through private
  Gamescope 3.16.31/XWayland on Wayland.
- Synthetic synchronous/asynchronous Media Foundation frames and cleanup.
- Real application startup: HomeState and Radeon Direct3D11; expected bounded
  timeout exit 124. Not a sustained GUI interaction or live scanning test.
- Read-only replay of the existing marker-laser turntable capture: 4,670 events
  over 19.99695 seconds; payload checksums match. Original recordings unchanged.
  Binary replay through the minimal device-free sandbox also preserved every
  image and metadata hash. A paced 239-event tail took 0.99644 seconds against
  0.995783 seconds of recorded timing.
- Preservation hashes still match all 70 recorded working-setup files and all
  49 original source files.

Gamescope can return zero after a child failure. The launcher now obtains the
actual child status through a host-only result file; a failed or missing result
cannot silently pass diagnostics. Diagnostics and smoke passed again after that
correction.

### Live USB preview after hardening

Passed: the user confirmed Blue Laser with markers preview in the separate fresh
hardened prefix, reporting approximately **95 FPS**. The app identifies the
Radeon renderer, the USB frame/control helpers are active, and the blue-laser
OpenCL compatibility rewrite is applied. Inspection of the live app process
confirmed separate network/mount namespaces and a read-only application
executable mount. No isolation settings were relaxed for this test.

The reported rate is about 14% below the earlier approximately 110 FPS observation.
This is not a controlled performance comparison: equivalent scene, settings and
system load have not been established. Gamescope is configured for 120 Hz, not
95 Hz. The app log contains frameset-queue overflow/drop warnings during preview;
these show backpressure but do not establish its cause or the sustained drop rate.
Whether the private compositor contributes to the difference remains untested.
No runtime settings or working setups were changed in response to this report.

Subsequent live test: app logs record fusion and STL export completion. The user
reported saving the model, and the resulting binary STL contains 2,200,703
triangles with the exact expected file length (110,035,234 bytes). These checks
confirm a generated/exported mesh, not dimensional accuracy or watertightness.

Usability issue found: after export the app starts `explorer.exe /select` to show
the output folder. In the private Gamescope display this browser appeared without
an accessible close control and obscured the app. A normal `WM_DELETE_WINDOW`
request, targeted after matching the browser's namespace PID, closed only that
browser and restored the app as the active window. CrealityScan remained running
and the export was preserved. The subsequent automatic-dismissal fix and its
scanner-free validation are described below. Do not terminate Gamescope or the
Wine session to dismiss the folder browser.

Not yet confirmed after hardening: exported-model reopening, reconnects,
performance under an active scan, other desktop compositors, or Wi-Fi opt-in mode.
Earlier working launchers, prefixes and scanner settings were not modified.

Repeat the hardware-free security checks after building, with your local config:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check_sandbox.py --config config.local.json
python3 scripts/check_public.py --worktree
git diff --check
```

`check_sandbox.py` needs permission to create normal Bubblewrap namespaces. It
creates and removes a temporary dummy state; it does not launch Wine or expose
the scanner, desktop or network. Repeat fresh installation/diagnostics/smoke using
SETUP.md and a new data directory. No automated test upgrades an old prefix.

### Post-export folder workaround (scanner-free)

The launcher now starts an event-driven helper inside the private sandbox before
Wine. It matches the window's PID to `explorer.exe /select, ...` and sends a
normal close request. It preserves the exported file, ordinary Explorer windows,
save/import dialogs and the application. No new registry setting, DLL, runner
change, desktop service, or host-display access is required.

Passed with the pinned Wine runner and Gamescope in a new disposable prefix:

- Baseline reproduction: the expected close-button location hit the browser's
  client area; clicking did not close it. The dummy underlying application lived.
- Final implementation: two successive `/select` browsers exited normally;
  the dummy application remained open after each. An ordinary Explorer folder
  remained open for the negative control and was closed by the test's cleanup.
- The dummy export's hash was unchanged. The guard logged exactly two dismissals
  and shut down cleanly with the test session.
- Unit coverage rejects desktop/ordinary Explorer invocations, mismatched
  executable identities, empty selections, missing processes, oversized command
  lines and direct invocation without the private sandbox environment.
- The complete 25-test top-level suite passed (including the nested 22-test
  native suite); public source inventory and whitespace checks passed.

Live CrealityScan export/reopening after this workaround was never tested. The
helper and its checker were removed with Gamescope (below).

## Desktop display and exports folder — 20 October 2026

Gamescope and the post-export folder helper were removed. Windows now appear on
the desktop's own X server by default, or on a private xwayland-satellite server
with `"display": "isolated"`. The app's Windows Documents folder is a host
exports folder. Earlier sections describe the Gamescope configuration.

Passed on the same RX 6800 XT/CachyOS/KDE Plasma Wayland machine, using a new
disposable data directory and exports folder:

- 34 top-level tests, including the nested native suite. New tests cover
  desktop socket/cookie selection, refusal of missing or remote displays,
  isolated-server readiness, failure and shutdown with a stand-in satellite,
  exports-folder placement rules, and the Documents link. The link replaces only
  empty Wine placeholder folders and keeps any file or link, and the integrity
  check accepts only that link.
- Bubblewrap canary check, public worktree inventory and whitespace checks.
- Fresh silent installation of pinned CrealityScan 4.3.2 on the desktop display.
- Diagnose on both displays: Windows OpenCL kernel, rendered OpenGL pixel and
  synthetic Media Foundation source. Isolated mode used xwayland-satellite 0.8.3
  from the signature-checked CachyOS package. It reported ready on a new display
  number and had exited, with its socket removed, after each run.
- Real application startup (smoke) on the desktop display: HomeState and Radeon
  Direct3D11 at 1660×960. The window was the active X11 window for the whole run.
  Two earlier runs, whose focus was not recorded, stalled during startup.
- A Windows command writing `C:\users\steamuser\Documents\…` created the file in
  the host exports folder. App startup wrote nothing there.
- Project folder: a dummy project in the prefix was moved into `Projects` in the
  exports folder at launch and the prefix's project folder became a link to it.
  Tests cover a refused name clash, rollback after a failed move, and refusal to
  follow an unexpected link in the profile. The app's own use of the linked
  project folder (new scans, reopening, project list) is not yet tested.

Not passed: smoke in isolated mode stalled at the same startup stage, with
xwayland-satellite logging that it could not focus the new window. Unity
pauses its startup while unfocused. This was observed with launches from a
background process, not from a desktop launcher.

Passed afterwards (user, existing hardened prefix with Proton 11.0 DXVK, desktop
display): a live USB scan with the export saved through the app's Documents folder
(a 1.4 GB fused STL in `~/Documents/CrealityScan`). On the next launch both
existing projects (576 MB and 2.6 GB) were moved to `Projects` in that folder,
and the app listed both.

Not tested: performance compared with Gamescope, window controls by hand, launch
from a desktop menu entry, GNOME/Ubuntu, Xorg sessions or fractional scaling.

## One-command setup, DXVK 3.1.1 and prebuilt helpers — 20 October 2026

Passed on the same machine:

- DXVK 3.1.1, the official release (archive SHA-256 matched GitHub's published
  digest): fresh install, diagnose, and app startup to HomeState on Direct3D 11
  (DXVK 3.1.1 on RADV).
- The pinned Wine runner, downloaded and unpacked by `fetch`, reproduced
  `runner_tree_sha256` exactly.
- `setup` end to end with a throwaway home, Downloads and Documents. It found the
  installer by checksum, detected the RX 6800 XT, then downloaded, configured,
  installed, passed diagnose and wrote the menu entry. The first attempt picked
  the integrated GPU; detection now prefers the discrete GPU and uses the
  system Python's libraries.
- 40 unit tests, including: the checksum is checked before an archive is kept
  or unpacked; archives with `..` paths, absolute paths, external links or a
  wrong layout are refused; prebuilt helper archives with unexpected files or a
  manifest mismatch are refused; setup error messages; menu-entry quoting.

- Helpers built by CI on Ubuntu 24.04, installed by `setup` on CachyOS through
  a local stand-in for the release pin: install and diagnose passed, and the
  native helpers load with only the standard C/C++ runtime.
- Live USB scanning on that install (DXVK 3.1.1 with the CI-built helpers,
  desktop display): the user reported that all scan modes they tried worked
  well. No FPS figure was recorded.

- Release `helpers-v1`: the archive's SHA-256 matches its published checksum,
  and `gh attestation verify` confirms it was built by this repository's
  `helpers.yml` workflow from the tagged commit.
- A fresh clone with `helpers-v1` pinned: `python3 scripts/creality.py setup` in a
  throwaway home downloaded the runner, DXVK and the release helpers, then
  installed, passed diagnose and wrote the menu entry in 72 seconds, with no
  compiler.

Not yet done: any Ubuntu machine test.
