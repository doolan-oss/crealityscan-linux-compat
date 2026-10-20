# Third-party reference notices

These notices accompany the public API/protocol reference material identified in
[PROVENANCE.md](docs/PROVENANCE.md). They do not license CrealityScan, its bundled
SDK binaries, or proprietary Orbbec extension libraries. No such binaries or full
upstream header/implementation collections are distributed here.

## Orbbec public source references (MIT)

Protocol framing, public property/API definitions and Windows device enumeration
behaviour were checked against Orbbec public sources. The following notice is
retained for those references/adapted interface declarations. The source repository
has separate terms for its proprietary extensions; the MIT grant below does not
cover them.

Source: https://github.com/orbbec/OrbbecSDK_v2/blob/85e94c4ee4032817df2e33228dbd7f51517d3d4e/LICENSE.txt

```text
Copyright (c) 2024-2026 Orbbec Inc

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## MinGW-w64 ABI references

Reduced, renamed Windows ABI declarations in `control-interfaces.h` and USB layout
handling were checked against MinGW-w64 headers. They are project adaptations,
not verbatim header distributions. The reference headers include public-domain
sections; the general project notice and public-domain disclaimer are retained
below rather than assuming one status for every referenced declaration.

Sources: https://github.com/mingw-w64/mingw-w64/blob/master/COPYING
and https://github.com/mingw-w64/mingw-w64/blob/master/DISCLAIMER.PD

```text
With exception of certain parts that are prominently marked as being
in the Public Domain, BSD, or LGPL this Software is provided under the
Zope Public License (ZPL) Version 2.1.

Copyright (c) 2009 - 2013 by the mingw-w64 project

See the AUTHORS file for the list of contributors to the mingw-w64 project.

This license has been certified as open source. It has also been designated
as GPL compatible by the Free Software Foundation (FSF).

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

   1. Redistributions in source code must retain the accompanying copyright
      notice, this list of conditions, and the following disclaimer.
   2. Redistributions in binary form must reproduce the accompanying
      copyright notice, this list of conditions, and the following disclaimer
      in the documentation and/or other materials provided with the
      distribution.
   3. Names of the copyright holders must not be used to endorse or promote
      products derived from this software without prior written permission
      from the copyright holders.
   4. The right to distribute this software or to use it for any purpose does
      not give you the right to use Servicemarks (sm) or Trademarks (tm) of
      the copyright holders.  Use of them is covered by separate agreement
      with the copyright holders.
   5. If any files are modified, you must cause the modified files to carry
      prominent notices stating that you changed the files and the date of
      any change.

Disclaimer

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS ``AS IS'' AND ANY EXPRESSED
OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO
EVENT SHALL THE COPYRIGHT HOLDERS BE LIABLE FOR ANY DIRECT, INDIRECT,
INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

```text
/**
 * DISCLAIMER
 * This file has no copyright assigned and is placed in the Public Domain.
 * This file is part of the mingw-w64 runtime package.
 *
 * The mingw-w64 runtime package and its code is distributed in the hope that it
 * will be useful but WITHOUT ANY WARRANTY.  ALL WARRANTIES, EXPRESSED OR
 * IMPLIED ARE HEREBY DISCLAIMED.  This includes but is not limited to
 * warranties of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 */
```

## Wine, OpenCL and libyuv build/runtime dependencies

The generated attribute delegates implement public Media Foundation method
signatures and forward calls to Wine; they do not copy Wine method bodies.
Platform declarations are compiled against the user's external Wine headers.
Wine's own code, headers, import libraries and license notices stay in that
external distribution (https://gitlab.winehq.org/wine/wine/-/blob/master/COPYING.LIB).
The system OpenCL headers/loader, libyuv and DXVK also remain external dependencies
with their own terms. This source publication does not distribute their binaries
or purport to relicense them.

## Prebuilt helper releases

`helpers-v*` releases contain helpers compiled from this repository by its GitHub
Actions workflow on Ubuntu 24.04. Each archive includes a `licenses/` folder with
the notices below.

- The Windows DLLs and diagnostic programs contain this project's code and import
  stubs. From Wine's static libraries they contain only the interface-ID tables
  `uuid.o`, `mfuuid.o` and `strmiids.o` (LGPL-2.1-or-later); link maps show no
  other Wine objects. Wine's LGPL text is included. The complete source and
  build script for relinking are this repository at the release's tagged commit
  (`python3 scripts/creality.py build`).
- `sdk-frame-helper` statically links libyuv (BSD-3-Clause) and libjpeg-turbo
  (IJG, BSD-3-Clause and zlib licenses). Ubuntu's copyright files for both are
  included.
- The OpenCL preload libraries and `v4l2-helper` link only the C library.

DXVK, Wine and CrealityScan are not part of these archives.
