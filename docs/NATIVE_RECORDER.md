# Optional native recorder and replay

These tools run without Wine, vendor DLLs or GPU processing. They are independent
of the Windows app setup and do not reconstruct 3D or contain scanner calibration.

```sh
./tools/pika-recorder/build.sh
./record-pika.sh --list
./record-pika.sh --scan-mode marker-laser --seconds 20
./replay-pika.sh '/absolute/path/to/new-recording' --pack
./replay-pika.sh '/absolute/path/to/new-recording' --start 1
```

Build compiles the libc-only V4L2 helper and runs 22 offline tests. List reads
sysfs without opening hardware. For live capture first close other scanner apps,
confirm exclusive access, and position a marked object. Marker mode selects
120fps GREY, blue laser and blue marker illumination, no colour stream or white
LEDs. Duration is bounded to 30s; exposure 2026 defaults to 1000. Power/current is
not increased. RAM-backed `/tmp` staging is checked before capture; files are
copied/checksummed to persistent storage after controls restore. A failed copy
keeps its private staging files and prints their path; recover before reboot.

For verified mixed laser/speckle scheduling use `--sync-mode mixed --seconds 3`:
90fps GREY+30fps MJPEG, mode192=4 then gates3+152. Each camera cycles C3/C4/C8;
C3 lines, C8 speckles, C4 dark with fill off. Phase tags are scheduled slots,
not universal optical labels. In mode6, speckles instead carry C4. Short
illumination tests retain their 3-second limit. Only tested named controls are
exposed. Do not brute-force firmware/calibration/current settings.

For a shared scanner with another checkout, set PIKA_LOCK_ROOT to the same
existing lock directory used there, using `env PIKA_LOCK_ROOT='/absolute/path'
before the recorder command. The controller also checks running app and device
ownership, and never kills another process. Standalone recorder output defaults
to ignored `recordings/` in this checkout. Existing directories are refused.

Recordings contain raw GREY/MJPEG payloads, index offsets, V4L2 timestamps,
sequence/error flags and original Linux UVCH metadata. UVC header byte 6 selects
A2=SDK left/A3=SDK right; byte 7 is the phase; bytes 2..5 are raw uint32 device PTS.
A Linux UVCH record adds a 10-byte host prefix. Pair only matching same-endpoint
image/metadata sequences; never pair RGB/IR sequence numbers. `demux.py` separates
camera/phase and reports conservative unique same-phase stereo candidates.

Replay packs relative-path indexes and SHA-256 checks without copying images.
Default replay paces files and prints a summary, not a GUI. `--speed 0` runs
unpaced; `--start`, `--loops` control seeking/repetition. Host monotonic capture
timestamps drive replay; device PTS and startup discontinuities are preserved.

Python API (add tools/pika-recorder to your module path):

```python
from replay import Recording
for event, pixels, metadata in Recording('/path/to/recording').frames(speed=1):
    consume(event, pixels, metadata)
```

`--packet-stream` emits binary stdout for another app: 8-byte `PKRPv1\r\n` magic,
then repeated three LE uint32 lengths (JSON/image/metadata), JSON UTF-8 header,
original image bytes, original UVCH bytes. `read_packets()` validates framing.
Do not send binary output to a terminal. This is a custom app frame source, not
USB-device emulation or a CrealityScan replay plugin. No real recordings are
included in this public repository.


Untrusted recordings are subject to the file, event, duration and replay limits
listed in [SECURITY.md](../SECURITY.md). Symlinks (including directory ancestors),
hard-linked files and nonregular files are refused. Derived outputs are created
exclusively; analysis never truncates an existing output. Use a fresh directory
for demux output. To repeat analysis in the recording directory, explicitly
remove only previously derived summaries/samples first, preserving originals.
