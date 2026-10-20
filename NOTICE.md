# Provenance and external software

The MIT license applies to this project's original compatibility helpers,
recorder/replay implementation, tooling and documentation. It does not relicense
CrealityScan, its SDK/DLLs, Wine, DXVK, drivers or referenced source material.
CrealityScan and Pika names identify compatible products; this is an unofficial
community project, not affiliated with, endorsed by, or supported by Creality.

The source snapshot intentionally excludes inspected third-party source trees,
SDK headers, Microsoft/Wine copied header collections, captured proprietary
OpenCL programs, disassemblies and binaries. Platform declarations compile against
user-supplied Wine headers. Export-forwarding lists describe the pinned API;
original SDK function implementations remain in the user's separately installed
DLL. OpenCL generated headers contain our replacement helper and numerical source
fingerprints and a token offset, not captured vendor kernel bodies. The matcher
contains only the standard OpenCL builtin name; vendor argument expressions and
field/type names have been removed.

Protocol framing was checked against public Orbbec SDK sources (MIT), while
Pika-specific semantics were established with local device observations:
https://github.com/orbbec/OrbbecSDK_v2/blob/85e94c4ee4032817df2e33228dbd7f51517d3d4e/src/device/protocol/Protocol.hpp

Wine API/override behaviour reference:
https://github.com/wine-mirror/wine

Standalone runner provider and its source/build information:
https://github.com/Kron4ek/Wine-Builds

DXVK source and licensing:
https://github.com/doitsujin/dxvk

See [PROVENANCE.md](docs/PROVENANCE.md) for the remaining derived interface and
protocol material, the audit scope and publication-history handling. Attribution
and reference notices are retained in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
This is not a clean-room or blanket IP-clearance claim.

No third-party software is downloaded during build. Runtime dependencies stay
outside the source repository and keep their accompanying notices/licenses.
