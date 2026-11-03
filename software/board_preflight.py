"""Read-only deployment checks; never load an Overlay, open a camera or write MMIO."""
import argparse
import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import struct
import sys
import xml.etree.ElementTree as ET


def inspect_board(bundle_root):
    """Return readiness hints, not proof that DMA or camera processing works.

    Only standard-library code is needed to report a missing board environment.
    Imported dependencies are inspected but no project driver is instantiated.
    """
    root = Path(bundle_root).resolve()
    checks = []

    def add(name, passed, detail, required_for):
        checks.append(dict(name=name, passed=bool(passed), detail=str(detail),
                           required_for=list(required_for)))

    all_stages = ("synthetic", "camera", "notebook")
    system, machine = platform.system(), platform.machine()
    add("linux_arm32", system == "Linux" and machine.lower().startswith("armv7")
        and struct.calcsize("P") == 4,
        "%s / %s / %d-bit Python; this bundle targets PYNQ-Z2 Zynq-7000" %
        (system, machine, struct.calcsize("P") * 8), all_stages)
    add("python_version", sys.version_info >= (3, 8), platform.python_version(), all_stages)
    declared_board = os.environ.get("BOARD", "")
    board_key = "".join(c.lower() for c in declared_board if c.isalnum())
    add("declared_board", not board_key or board_key == "pynqz2",
        declared_board or "BOARD not set; physically confirm PYNQ-Z2", all_stages)
    model = None
    for filename in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        try:
            model = Path(filename).read_bytes().rstrip(b"\0").decode("utf-8", "replace")
            break
        except OSError:
            pass

    modules = {}
    for name, stages in (("pynq", all_stages), ("numpy", all_stages),
                         ("PIL", all_stages), ("cv2", ("camera", "notebook")),
                         ("ipywidgets", ("notebook",)), ("IPython", ("notebook",))):
        try:
            module = importlib.import_module(name)
            version = str(getattr(module, "__version__", "unknown"))
            modules[name] = version
            add("import_" + name, True, version, stages)
            if name == "pynq":
                add("pynq_version", version == "2.7" or version.startswith("2.7."),
                    version + "; this driver was prepared against PYNQ 2.7", all_stages)
                add("pynq_api", hasattr(module, "Overlay") and hasattr(module, "allocate"),
                    "Overlay and allocate must both be available", all_stages)
        except Exception as error:
            modules[name] = None
            add("import_" + name, False, "%s: %s" % (type(error).__name__, error), stages)

    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
        if manifest.get("schema_version") != 1:
            raise ValueError("Unsupported deployment manifest schema")
        files = manifest["files"]
        required = ("image_system.bit", "image_system.hwh", "software/image_accelerator.py",
                    "software/image_reference.py", "software/image_demo.py",
                    "software/live_notebook.py", "software/board_preflight.py")
        if not isinstance(files, dict) or not all(name in files for name in required):
            raise ValueError("Deployment manifest is missing a required payload")
        for name, record in files.items():
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
                raise ValueError("Invalid payload path: " + name)
            filename = root.joinpath(*relative.parts).resolve()
            # Reject links escaping the deployed folder as well as traversal paths.
            filename.relative_to(root)
            data = filename.read_bytes()
            if len(data) != record["size_bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError("Payload hash/size mismatch: " + name)
        add("bundle_integrity", True, "%d payload files match manifest" % len(files), all_stages)
    except Exception as error:
        add("bundle_integrity", False, "%s: %s" % (type(error).__name__, error), all_stages)

    try:
        hardware = ET.parse(str(root / "image_system.hwh")).getroot()

        def parameters(instance):
            module = hardware.find(".//MODULE[@INSTANCE='%s']" % instance)
            if module is None:
                raise ValueError("Missing HWH module: " + instance)
            return {node.get("NAME"): node.get("VALUE") for node in module.findall(".//PARAMETER")}

        core = parameters("image_axis_core_0")
        reset = parameters("rst_fclk0")
        if core.get("IMAGE_WIDTH") != "128" or core.get("IMAGE_HEIGHT") != "96":
            raise ValueError("HWH must describe 128x96 input")
        if reset.get("C_EXT_RESET_HIGH") != "0" or reset.get("C_AUX_RESET_HIGH") != "1":
            raise ValueError("HWH reset polarity differs from the verified build")
        ranges = hardware.findall(".//MEMRANGE")
        for instance, address in (("axi_dma_0", 0x40400000), ("axi_gpio_0", 0x41200000)):
            matches = [node for node in ranges if node.get("INSTANCE") == instance
                       and int(node.get("BASEVALUE", "-1"), 0) == address]
            if len(matches) != 1:
                raise ValueError("HWH address mismatch: " + instance)
        add("hwh_contract", True, "128x96; DMA 0x40400000; GPIO 0x41200000; EXT=0/AUX=1", all_stages)
    except Exception as error:
        add("hwh_contract", False, "%s: %s" % (type(error).__name__, error), all_stages)

    videos = sorted(str(path) for path in Path("/dev").glob("video*")) if system == "Linux" else []
    add("video_device_present", bool(videos),
        ", ".join(videos) if videos else "No /dev/video* node found; connect the USB camera to board USB HOST",
        ("camera", "notebook"))

    def ready(stage):
        return all(item["passed"] for item in checks if stage in item["required_for"])

    return dict(schema_version=1,
                checked_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                hardware_test=False, camera_test=False, linux_application_test=False,
                environment=dict(system=system, machine=machine, python=platform.python_version(),
                                 declared_board=declared_board or None, device_tree_model=model,
                                 modules=modules, video_devices=videos),
                ready_for_synthetic=ready("synthetic"), ready_for_camera=ready("camera"),
                ready_for_notebook=ready("notebook"), checks=checks,
                note="Read-only prerequisite checks only. A video node does not prove capture works; "
                     "no Overlay, DMA, MMIO or camera capture was started.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, help="Optional NEW JSON evidence file; never overwrites")
    args = parser.parse_args()
    result = inspect_board(args.bundle_root)
    rendered = json.dumps(result, indent=2, ensure_ascii=True)
    if args.output is not None:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(rendered + "\n")
    print(rendered)
    return 0 if result["ready_for_synthetic"] else 1


if __name__ == "__main__":
    sys.exit(main())
