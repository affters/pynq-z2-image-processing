# Third-party notices

The project MIT license applies to original project contributions. It does not
relicense the material and dependencies identified below.

## Xilinx PYNQ PYNQ-Z2 PS7 preset

The `apply_pynq_z2_ps7_preset` procedure in
`scripts/build_image_system.tcl` reproduces the 858-entry PS7 configuration
property list from the following upstream generated hardware-design script:

- Project: Xilinx/PYNQ.
- Version: `v2.7.0` (the release using Vivado 2020.2).
- File: `boards/Pynq-Z2/petalinux_bsp/hardware_project/pynqz2.tcl`.
- [Upstream file](https://github.com/Xilinx/PYNQ/blob/v2.7.0/boards/Pynq-Z2/petalinux_bsp/hardware_project/pynqz2.tcl).
- [Raw upstream file](https://raw.githubusercontent.com/Xilinx/PYNQ/v2.7.0/boards/Pynq-Z2/petalinux_bsp/hardware_project/pynqz2.tcl).
- Git blob SHA-1: `dd415eac9a19aeb5ec9341718c47a68f76204544`.
- Original file SHA-256: `0c193c72fcf504ce432d4866870b08d06e8dd88410125fe7b23aae8ee256147c`.
- Original file size: 47,476 bytes.

The upstream file header identifies it as a generated script based on the
`pynqz2` design; it does not state a separate file-specific license. The
repository's `LICENSE` at the same tag is the BSD 3-Clause License, with the
copyright notice reproduced below.

The project extracts that PS7 property list into a procedure accepting a cell
handle. The surrounding system-integration code and the later PL-facing bus
and 50 MHz FCLK0 overrides are project additions. The PYNQ-Z2 DDR/MIO preset
values are retained. This extraction and integration do not change the license
of the copied upstream material.

License provenance:

- [Upstream LICENSE at v2.7.0](https://github.com/Xilinx/PYNQ/blob/v2.7.0/LICENSE).
- [Raw upstream LICENSE](https://raw.githubusercontent.com/Xilinx/PYNQ/v2.7.0/LICENSE).
- License Git blob SHA-1: `d38369517fa51a9d15c0d68291c2e35d3e5656f7`.
- Verified against the upstream license and script header on 2026-10-29.

The following text is reproduced in full from that upstream license:

```text
BSD 3-Clause License

Copyright (c) 2018, Xilinx
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## AMD/Xilinx development tools and IP

Vivado 2020.2, XSim, XSDB, hardware-server utilities, and the AMD/Xilinx IP used
to build this project are external development dependencies. Relevant IP
includes Processing System 7, AXI DMA, AXI GPIO, AXI Interconnect, Processor
System Reset, and Constant. Their tool/IP installations are not supplied as
project-authored MIT source code.

Generated vendor components, initialization/support files, and implemented
hardware artifacts can incorporate AMD/Xilinx material. The project MIT
license does not replace applicable vendor terms or notices for that material.
Keep the original vendor notices accompanying generated files and use the
relevant tool/IP terms for any redistribution; this notice does not grant
additional rights to redistribute a tool installation or vendor IP sources.

The PYNQ runtime, Python packages, and other independently installed software
retain their own licenses. A reference to or use of an external dependency
does not relicense that dependency under the project's MIT license.

No endorsement by Xilinx, AMD, or the PYNQ project is claimed.
