"""Offline fail-closed firmware/hardware profile pairing before any JTAG action."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


LEGACY_BIT_SHA = "ebe2f73d9fd2d605629cb751a734b0da2db1341e9c1e7d21a415979a0a65f3eb"
PS_INIT_SHA = "05ff63c18d43e9d8b6b117ab9e5463d76b8235266daec17327d23e09fecc788b"
PROFILES = {(128, 96): "pynq_uart_image_v1", (256, 192): "pynq_uart_image_256x192_v1"}
REQUIRED = {"image_system.bit", "image_system.hwh", "ps7_init.tcl", "image_system.xsa"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def geometry(record, legacy=False):
    width = record.get("image_width", 128 if legacy else None)
    height = record.get("image_height", 96 if legacy else None)
    if type(width) is not int or type(height) is not int or (width, height) not in PROFILES:
        raise ValueError("Only the explicit 128x96 and 256x192 profiles are supported")
    return width, height


def validate_pair(firmware_directory, hardware_directory, legacy_pinned=False):
    firmware_directory, hardware_directory = map(Path, (firmware_directory, hardware_directory))
    firmware = json.loads((firmware_directory / "manifest.json").read_text(encoding="utf-8-sig"))
    width, height = geometry(firmware, legacy=True)
    expected_info = PROFILES[width, height]
    if firmware.get("firmware_info", expected_info) != expected_info:
        raise ValueError("Firmware manifest identity differs from its resolution profile")
    elf = firmware_directory / "uart_image.elf"
    elf_sha = digest(elf)
    if elf_sha != str(firmware.get("elf_sha256", "")).lower():
        raise ValueError("Firmware ELF manifest hash mismatch")
    if expected_info.encode("ascii") + b"\0" not in elf.read_bytes():
        raise ValueError("Firmware ELF does not contain its expected profile identity")
    artifacts = {}
    if legacy_pinned:
        if (width, height) != (128, 96):
            raise ValueError("Nondefault firmware requires an explicit matching hardware directory")
        bit = hardware_directory / "image_system.bit"
        if digest(bit) != LEGACY_BIT_SHA:
            raise ValueError("Verified legacy bitstream changed")
        for name in REQUIRED:
            path = hardware_directory / name
            artifacts[name] = {"sha256": digest(path), "bytes": path.stat().st_size}
        manifest_sha = None
    else:
        manifest_path = hardware_directory / "build_manifest.json"
        hardware = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if (geometry(hardware) != (width, height)
                or hardware.get("part") != "xc7z020clg400-1"
                or hardware.get("fabric_clock_hz") != 50000000
                or hardware.get("implementation_passed") is not True):
            raise ValueError("Implemented hardware geometry/part/clock does not match firmware")
        declared = hardware.get("artifacts")
        if not isinstance(declared, dict) or not REQUIRED.issubset(declared):
            raise ValueError("Hardware artifact manifest is incomplete")
        for name, entry in declared.items():
            if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", name)
                    or not isinstance(entry, dict) or type(entry.get("bytes")) is not int
                    or entry["bytes"] <= 0 or not isinstance(entry.get("sha256"), str)
                    or not re.fullmatch(r"[0-9a-fA-F]{64}", entry["sha256"])):
                raise ValueError("Invalid hardware artifact record")
            path = hardware_directory / name
            actual = {"sha256": digest(path), "bytes": path.stat().st_size}
            if actual != {"sha256": entry["sha256"].lower(), "bytes": entry["bytes"]}:
                raise ValueError("Hardware artifact hash/length mismatch: " + name)
            artifacts[name] = actual
        manifest_sha = digest(manifest_path)
    if artifacts["ps7_init.tcl"]["sha256"] != PS_INIT_SHA:
        raise ValueError("Matching pinned PS initialization changed")
    root = ET.parse(hardware_directory / "image_system.hwh").getroot()
    modules = root.findall(".//MODULE[@INSTANCE='image_axis_core_0']")
    if len(modules) != 1 or modules[0].get("MODTYPE") != "image_axis_core":
        raise ValueError("Expected one image_axis_core_0 in generated HWH")
    params = {p.get("NAME"): p.get("VALUE") for p in modules[0].findall("./PARAMETERS/PARAMETER")}
    if (params.get("IMAGE_WIDTH"), params.get("IMAGE_HEIGHT")) != (str(width), str(height)):
        raise ValueError("HWH image core dimensions do not match firmware")
    return {"pair_validated": True, "hardware_access": False,
            "validation_mode": "legacy_pinned" if legacy_pinned else "manifest_bound",
            "image_width": width, "image_height": height, "firmware_info": expected_info,
            "firmware_elf_sha256": elf_sha, "hardware_manifest_sha256": manifest_sha,
            "artifacts": artifacts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("firmware_directory", type=Path)
    parser.add_argument("hardware_directory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--legacy-pinned", action="store_true")
    args = parser.parse_args()
    result = validate_pair(args.firmware_directory, args.hardware_directory, args.legacy_pinned)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    print("UART_BUILD_PAIR_OK profile=%dx%d mode=%s" %
          (result["image_width"], result["image_height"], result["validation_mode"]))


if __name__ == "__main__":
    main()
