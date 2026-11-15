#!/usr/bin/env python3
"""Inspect a volunteer diagnostic zip/directory and extract USB maps, hardware probe data, and T2/OpenCore logs."""

import argparse
import plistlib
import re
import tempfile
import zipfile
from pathlib import Path


def _open_bundle(bundle_path: Path, tmp_dir: Path) -> Path:
    if bundle_path.is_file() and bundle_path.suffix == ".zip":
        with zipfile.ZipFile(bundle_path) as archive:
            archive.extractall(tmp_dir)
        subdirs = [p for p in tmp_dir.iterdir() if p.is_dir()]
        return subdirs[0] if len(subdirs) == 1 else tmp_dir
    return bundle_path


def _extract_usb_map(root: Path, model: str) -> dict | None:
    xhci_file = next(
        (
            root / rel
            for rel in ("ioreg/usb_xhci.plist", "ioreg/usb_xhci_all.plist", "ioreg/usb_hosts.plist")
            if (root / rel).is_file() and (root / rel).stat().st_size > 0
        ),
        None,
    )
    if xhci_file is None:
        return None

    tree = plistlib.loads(xhci_file.read_bytes())
    personalities: dict = {}

    def _walk_ports(node: dict, ports: dict, max_port: list[int]) -> None:
        cls = node.get("IOObjectClass", "")
        name = node.get("IORegistryEntryName", "")
        if "XHCIPort" in cls or (
            name.startswith(("HS", "SS", "SSP", "PRT", "USR"))
            and ("port" in node or "usb-port-number" in node)
        ):
            raw_port = node.get("port") or node.get("usb-port-number")
            conn = node.get("UsbConnector") if "UsbConnector" in node else node.get("usb-port-type")
            if isinstance(raw_port, bytes) and conn is not None:
                port_num = int.from_bytes(raw_port, "little")
                if isinstance(conn, bytes):
                    conn_int = int.from_bytes(conn, "little")
                else:
                    conn_int = int(conn)
                ports[name] = {
                    "UsbConnector": conn_int,
                    "port": port_num.to_bytes(4, "little"),
                }
                if port_num > max_port[0]:
                    max_port[0] = port_num
                return
        for child in node.get("IORegistryEntryChildren", []):
            _walk_ports(child, ports, max_port)

    def _find_controllers(nodes) -> None:
        if isinstance(nodes, list):
            for item in nodes:
                _find_controllers(item)
            return
        if not isinstance(nodes, dict):
            return
        children = nodes.get("IORegistryEntryChildren", [])
        name = nodes.get("IORegistryEntryName", "")
        cls = nodes.get("IOObjectClass", "")
        if cls == "IOPCIDevice" or "XHCI" in cls:
            ports: dict = {}
            max_port = [0]
            _walk_ports(nodes, ports, max_port)
            if ports:
                ctrl_name = name.split("@")[0] or "XHC1"
                key = f"{model}-{ctrl_name}"
                suffix = 2
                while key in personalities:
                    key = f"{model}-{ctrl_name}-{suffix}"
                    suffix += 1
                personalities[key] = {
                    "CFBundleIdentifier": "com.apple.driver.AppleUSBHostMergeProperties",
                    "IOClass": "AppleUSBHostMergeProperties",
                    "IONameMatch": ctrl_name,
                    "IOProviderClass": "AppleUSBXHCIPCI",
                    "IOProviderMergeProperties": {
                        "port-count": max_port[0].to_bytes(4, "little"),
                        "ports": ports,
                    },
                    "model": model,
                }
                return
        for child in children:
            _find_controllers(child)

    _find_controllers(tree)
    if not personalities:
        return None
    return {"IOKitPersonalities_x86_64": personalities}


def _summarize_pci(root: Path) -> list[str]:
    pci_file = root / "ioreg/pci_devices.plist"
    if not pci_file.is_file() or pci_file.stat().st_size == 0:
        return []
    tree = plistlib.loads(pci_file.read_bytes())
    lines: list[str] = []

    def _walk(nodes) -> None:
        if isinstance(nodes, list):
            for item in nodes:
                _walk(item)
            return
        if not isinstance(nodes, dict):
            return
        vid_raw = nodes.get("vendor-id")
        did_raw = nodes.get("device-id")
        cls_raw = nodes.get("class-code")
        if isinstance(vid_raw, bytes) and isinstance(did_raw, bytes) and isinstance(cls_raw, bytes):
            vid = int.from_bytes(vid_raw, "little")
            did = int.from_bytes(did_raw, "little")
            cls = int.from_bytes(cls_raw, "little")
            if cls >> 8 in (0x0300, 0x0380, 0x0401, 0x0403, 0x0280, 0x0200, 0x0108, 0x0C03, 0x1080):
                name = nodes.get("IORegistryEntryName", "?")
                acpi = nodes.get("acpi-path", "")
                lines.append(f"  {name:16s} 0x{vid:04x}:0x{did:04x} class=0x{cls:06x} acpi={acpi}")
        for child in nodes.get("IORegistryEntryChildren", []):
            _walk(child)

    _walk(tree)
    return lines


def _summarize_efis_and_logs(root: Path) -> None:
    efi_base = root / "efi_and_logs"
    if not efi_base.is_dir():
        return

    oc_logs = sorted(list(efi_base.glob("*opencore-*.txt")) + list(efi_base.glob("*Lilu_*.txt")))
    print(f"\n=== OpenCore / Lilu Logs ({len(oc_logs)}) ===")
    for log_path in oc_logs:
        text = log_path.read_text(errors="replace")
        lines = text.splitlines()
        interesting = [
            line for line in lines
            if re.search(r"(OC:|OCS:|OCB:|OCUI:|Err|Fail|Timeout|Panic|SMBIOS|SecureBoot|T2|Bridge)", line, re.I)
        ]
        print(f"- {log_path.name} ({len(lines)} lines); tail sample:")
        for line in (interesting[-12:] if interesting else lines[-12:]):
            print(f"    {line}")

    panics = sorted((efi_base / "panics").glob("*")) if (efi_base / "panics").is_dir() else []
    print(f"\n=== Panic / Bridge / SEP Reports ({len(panics)}) ===")
    for panic_path in panics:
        text = panic_path.read_text(errors="replace")
        match = re.search(r"panic\([^\n]+\):[^\n]+", text)
        print(f"- {panic_path.name}: {match.group(0) if match else 'see file'}")

    efis = sorted((efi_base / "efis").iterdir()) if (efi_base / "efis").is_dir() else []
    print(f"\n=== Captured EFIs ({len(efis)}) ===")
    for efi_dir in efis:
        cfg_path = efi_dir / "config.plist"
        if not cfg_path.is_file():
            continue
        cfg = plistlib.loads(cfg_path.read_bytes())
        boot_args = cfg.get("NVRAM", {}).get("Add", {}).get("7C436110-AB2A-4BBB-A880-FE41995C9F82", {}).get("boot-args", "")
        sbm = cfg.get("Misc", {}).get("Security", {}).get("SecureBootModel")
        kexts = [k.get("BundlePath") for k in cfg.get("Kernel", {}).get("Add", []) if k.get("Enabled")]
        blocks = [k.get("Identifier") for k in cfg.get("Kernel", {}).get("Block", []) if k.get("Enabled")]
        patches = [p.get("Comment") or p.get("Identifier") for p in cfg.get("Kernel", {}).get("Patch", []) if p.get("Enabled")]
        acpis = [a.get("Path") for a in cfg.get("ACPI", {}).get("Add", []) if a.get("Enabled")]
        print(f"- {efi_dir.name}:")
        print(f"    SecureBootModel: {sbm}")
        print(f"    boot-args:       {boot_args}")
        print(f"    ACPI->Add:       {acpis}")
        print(f"    Kernel->Block:   {blocks}")
        print(f"    Kernel->Patch:   {patches}")
        print(f"    Kernel->Add:     {kexts}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="Path to volunteer .zip or extracted directory")
    parser.add_argument("--usb-out", type=Path, help="Optional output path to write draft USBMaps/<Model>.plist")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        root = _open_bundle(args.bundle, Path(tmp))
        summary = (root / "summary.txt").read_text(errors="replace") if (root / "summary.txt").is_file() else ""
        model_match = re.search(r"^hw\.model:\s*(\S+)", summary, re.M)
        board_match = re.search(r'"board-id"\s*=\s*<"([^"]+)"', summary)
        model = model_match.group(1) if model_match else "UnknownModel"
        board = board_match.group(1) if board_match else "UnknownBoard"

        print(f"Model:    {model}")
        print(f"Board ID: {board}")

        pci_lines = _summarize_pci(root)
        print(f"\n=== Relevant PCI Devices ({len(pci_lines)}) ===")
        for line in pci_lines:
            print(line)

        usb_map = _extract_usb_map(root, model)
        if usb_map:
            personalities = usb_map["IOKitPersonalities_x86_64"]
            print(f"\n=== Extracted USB Map ({len(personalities)} controller(s)) ===")
            for key, body in personalities.items():
                ports = body["IOProviderMergeProperties"]["ports"]
                port_desc = [
                    f"{p_name}=#{int.from_bytes(pv['port'], 'little')}(conn={pv['UsbConnector']})"
                    for p_name, pv in sorted(ports.items(), key=lambda kv: int.from_bytes(kv[1]["port"], "little"))
                ]
                print(f"- {key}: {', '.join(port_desc)}")
            if args.usb_out:
                args.usb_out.parent.mkdir(parents=True, exist_ok=True)
                with args.usb_out.open("wb") as file:
                    plistlib.dump(usb_map, file, sort_keys=False)
                print(f"Saved draft USB map plist to: {args.usb_out}")
        else:
            print("\n=== Extracted USB Map: none found in ioreg/usb_xhci.plist ===")

        _summarize_efis_and_logs(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
