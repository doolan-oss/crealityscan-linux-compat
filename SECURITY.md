# Security boundaries

This is experimental compatibility software for a separately supplied Windows
application. The source checkout, local configuration, compiler/toolchain or pinned prebuilt
helper release, desktop compositor and X server, optional xwayland-satellite, Wine, kernel and
graphics drivers are trusted host components. It is
not a VM and does not defend against a malicious host process running as your
Linux user, kernel/driver vulnerabilities, or malicious scanner firmware.

## Application filesystem and display

The launcher starts with an empty Bubblewrap filesystem. Read-only inputs are
`/usr`, compatibility library links, selected public runtime files under `/etc`,
the pinned runner, and the required source/build directories. GPU launches also
expose `/sys`, `/opt/rocm` when present, and the graphics device nodes. The installer
file is exposed only for installation. Other host-home files, host temporary
files, desktop credentials and the host trust store are not mounted. Z: therefore
addresses this restricted filesystem, not the host root.

Only the selected `data_dir` and the exports folder are persistent and writable.
HOME is private to its prefix. Installed executable files are overmounted read-only after installation.
Temporary `/tmp`, `/run` and `/dev` are private; USB nodes are explicit. `/sys`
contains hardware information, so this is not hardware-identity anonymization.

The exports folder (`exports_dir`, default `Documents/CrealityScan` in your home)
is mounted at a fixed sandbox path and appears in the app as its Windows
**Documents** folder; its `Projects` subfolder is the app's project store. The
app can create, change and delete anything in that folder, so keep only scans and
exports there and do not run programs saved into it. The host never executes or
parses its contents. At launch the host moves any files the prefix's Documents
or project folders already hold into it by rename only. It never copies or
overwrites files, and leaves both folders unchanged if a name is already taken
or they are on different filesystems.

The display is chosen by `display` in the local config:

- `"desktop"` (default): the app's windows are ordinary windows on your desktop's
  own X server (XWayland on a Wayland session, or Xorg). Only that server's socket
  and Xauthority cookie are mounted; never the Wayland socket or the rest of
  `/tmp/.X11-unix`. X11 does not isolate clients from each other: the app can
  read and inject input and window contents of **other X11 windows** on that
  server and use the clipboard. On a Wayland session, native Wayland apps (most
  of the desktop, browsers, terminals) are outside its reach; on an Xorg session
  every window is exposed.
- `"isolated"`: each run starts a private rootless XWayland server with
  xwayland-satellite, whose windows still appear as normal desktop windows. Only
  that server's socket is mounted, so other X11 apps are not reachable. The
  satellite process runs outside the sandbox with Wayland access and, as of
  0.8.3, bridges the clipboard and primary selection while the app has focus.

There is no automatic fallback between modes; a missing display or
xwayland-satellite fails the launch.

USB and diagnostics use a private network namespace, also separating abstract
Unix sockets. Wi-Fi is refused by default. Enabling `allow_host_network: true`
in the trusted local config is an explicit opt-in to a weaker boundary.
**Wi-Fi shares the host network**, including access to
host network services and abstract Unix sockets, including the abstract
sockets of X servers. In isolated display mode, the desktop X server's cookie is
still withheld, but permissive host X-server access rules would let the app reach
it in Wi-Fi mode. Do not treat Wi-Fi mode as equivalent to USB security
isolation. A separate network broker would require additional implementation and
scanner validation. Nothing here authenticates the vendor SDK's Wi-Fi protocol.

## Integrity

The entire runner file/link inventory is hashed against a tree fingerprint
derived from the SHA-256-verified upstream archive. The fingerprint covers both
architectures, support libraries and build headers; additions/removals also fail.
DXVK and installer hashes remain separately pinned. System libraries and the
compiler are maintained through the host package manager, not this project.

`setup` and `fetch` download the runner, DXVK and prebuilt helpers only from URLs
pinned in `config/versions.lock.json`, check the pinned SHA-256 before keeping or
unpacking them, and refuse archive paths or links that leave the target folder.
Prebuilt helper files must also match the manifest inside their archive. Using a
prebuilt release means trusting this repository's GitHub Actions build:
`gh attestation verify <archive> --repo doolan-oss/crealityscan-linux-compat`
checks its build provenance, and `build` produces the helpers from source instead.

Fresh installation creates a host-side baseline under ignored `.local-trust/`,
keyed by the absolute data directory. That directory is never mounted into Wine.
The session lock is also host-side, so the app cannot replace it to permit a
second session. Host log writes, ownership-marker reads and post-install copies
traverse directories without following links. Log/status outputs are exclusive;
intentional DLL replacement checks for a regular, singly linked file before
truncation. App-created links cannot redirect those host operations elsewhere.
Every `.exe`, `.dll`, `.so`, `.drv` and `.ocx` under drive_c is checked against the
baseline before launch (the Documents link to the sandbox-only exports mount is
the only prefix directory link allowed to point outside the prefix), including pikacam.dll, diagnostics and both SDK copies.
Missing, changed or additional executable files fail verification. The baseline
also records the trusted helper build. Empty baselines are rejected.

The old writable `data_dir/installation.json` is not a trust source. Old prefixes
are not automatically adopted or upgraded: use a **new data directory** and fresh
installation. Do not regenerate hashes to bless a potentially modified prefix.
Keep `.local-trust/` with this source checkout; moving data changes its identity.

This is executable-integrity protection, not authentication of all mutable Wine
state. Registry settings, projects, shaders/assets and app settings are not a
complete trusted-state snapshot. After suspected compromise, preserve necessary
projects and install into a new prefix; do not rely on a successful DLL check to
declare that entire prefix safe.

## Recordings and privacy

Offline recording readers open each path component relative to a directory
descriptor with `O_NOFOLLOW`; only singly linked regular files are accepted.
Outputs use exclusive creation and never replace existing files. Symlinks,
hard-linked inputs, FIFOs and symlinked directory ancestors are refused. Repeated
analysis requires a new output location or explicit removal of old derived files
by the user; source recordings are not silently overwritten.

Bounds: 16 MiB per JSONL index, 8 KiB per line, 20,000 rows per index and replay
events, 16 GiB per payload file, 8 MiB per image, 64 KiB per metadata buffer,
16 MiB aggregate metadata per stream, 120 seconds per recording and a five-second
timestamp gap. Pairing density is bounded. Paced replay rejects runs over one
hour or individual scheduled gaps over five seconds; waits are at most 0.1 s
each. Loops are limited to 100. These tools intentionally target short captures,
not arbitrary-size recordings or unattended public ingestion services.

The USB helper no longer writes unsolicited initial-frame debug dumps. Explicit
native recording still saves camera imagery. Application logs can contain
personal paths or scanner credentials; review before sharing. These changes do
not delete older debug dumps, recordings or logs from any existing installation.

See [validation](docs/VALIDATION.md) for the exact tested boundary. Functional
scanning success and source-provenance checks are not security certification.
