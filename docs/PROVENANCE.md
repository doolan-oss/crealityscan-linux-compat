# Source provenance audit — 18 October 2026

This is a technical inventory of the source publication, not a legal opinion,
patent search, EULA determination or clean-room certification. Development used
public API references, local device observations and inspection of the installed
vendor software. MIT applies to this project's original work; it does not grant
rights to the external vendor software or third-party material.

## Material retained

| Material | Files | Origin and disposition |
|---|---|---|
| SDK export names and ordinals | `src/usb-bridge/sdk-proxy.def` | Mechanically extracted from the pinned user-provided DLL's PE export table. Names/ordinals forward calls to the original DLL; no SDK function bodies are reproduced. Retained for binary compatibility. |
| Public SDK function signatures and enum values | `sdk-connect-probe.c`, `sdk-stream-probe.inc` | Reduced dynamic-call declarations checked against public Orbbec APIs. No full SDK headers or implementations are included. Orbbec source notice retained in THIRD_PARTY_NOTICES.md. |
| Windows COM/USB ABI signatures, GUIDs, layouts and API export lists | `control-interfaces.h`, `device-tree.inc`, attribute delegate headers, `.def` files and probes | Public interface information checked against Wine, MinGW-w64 and Windows API references. Delegation and bridge implementations are project code. Reduced/renamed declarations are adaptations; MinGW reference notices are retained. Full upstream headers/reference collections remain excluded. |
| USB identity, control protocol, camera/illumination metadata | Bridge transport/control code; `tools/pika-recorder/{device,demux,illumination}.py` | VID/PID, extension-unit GUID, packet layouts, property numbers and phase mappings are interoperability observations, with public Orbbec protocol framing used as a reference. The Sermoon S1 profile (`scripts/models.py`) comes from a user's published `survey` report; inspecting the installed SDK confirmed it maps that product ID to its own device class and addresses only the unit-4 extension GUID. No firmware, calibration blob, trace dump or device-specific serial is included. Not a claim that all protocol details were discovered independently. |
| Version/program fingerprints and patch position | `config/versions.lock.json`, `src/opencl/usb-opencl-generated.h` | Measured hashes, byte length and one offset; these do not contain the captured program. They restrict the fix to the tested inputs. The FNV guard is a version check, not cryptographic authentication. |
| OpenCL replacement helper and allocator interposer | `src/opencl/` | Project-written implementations. The atomic helper uses standard OpenCL operations. The vendor program is obtained only from the application's runtime call and is never bundled here. |
| Product names and dependency links | Documentation, diagnostics and compatibility identifiers | Used to identify the supported software/hardware. No vendor artwork or logo is included; no affiliation or endorsement is claimed. |
| Scripts, tests and recorder/replay logic | `scripts/`, `tests/`, native tools | Project implementations. Test frames/programs are synthetic; private recordings, proprietary kernels, disassemblies and engineering logs are excluded. |

The filenames abbreviated above are under `src/usb-bridge/` unless otherwise
specified. Build inputs such as Wine headers/import libraries, libyuv, the OpenCL
loader, DXVK and CrealityScan remain external and keep their own licenses.

## Copied expression removed

The former OpenCL matcher embedded a short vendor call expression, repeated its
argument identifiers in the replacement, and emitted layout assertions referring
to vendor type/field names. Those literals have been removed. The replacement now:

1. Requires application opt-in and the exact prefix guard.
2. Concatenates the caller's program and checks its measured length/fingerprint.
3. Checks the standard OpenCL builtin name `atomic_xchg` at one measured offset.
4. Replaces only that function name with the project helper name, preserving all
   original arguments and other program bytes supplied by the caller.
5. Passes mismatches and invalid/oversized input through to the original loader.

No vendor-specific variable/type/field/kernel name is needed in this fix's
source. The exact-program fingerprint pins the layout previously validated for
the 16-bit exchange; the unchanged helper preserves the other half of its aligned
32-bit word. This is deliberately version-specific, not a generic kernel parser.

The public regression suite uses an original synthetic program and a fake OpenCL
loader to check rewriting, split strings, implicit/explicit lengths, trailing
NULs, disabled/mismatched guards, changed programs and malformed input. Private
validation additionally compares the old and new output for the actual locally
captured program. Those private programs and comparison artifacts are not part
of this source distribution. See [VALIDATION.md](VALIDATION.md) for runtime results.

## Audit scope and publication history

The reviewed source set contains no installer, vendor DLL, firmware, full vendor
OpenCL kernel, disassembly, SDK header collection, recording, project, prefix or
binary asset. A token-overlap check against the retained local reference sources
found no contiguous 30-token matches after removing comments. That bounded check
helps identify copied implementation blocks; it cannot prove independent
provenance, absence of shorter copied material, or freedom from legal claims.

Third-party references and their notices are documented in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). Orbbec's public source license
must not be confused with the separate proprietary extension-library terms.
Likewise, reference notices do not authorize redistribution of the installed
CrealityScan SDK binaries. Users obtain those separately under their own terms.

The publication is a clean source snapshot on top of the destination repository's
existing MIT-license commit. The local development commit containing the former
expression is not an ancestor and is not pushed, including through tags or other
refs. Private test material stays in the development workspace outside this repo.
