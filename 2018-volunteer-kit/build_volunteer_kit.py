#!/usr/bin/env python3
"""Generate external-USB diagnostic OpenCore EFI bundles for 2018 T2 Macs."""

import argparse
import plistlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from opencore_legacy_patcher import constants
from opencore_legacy_patcher.efi_builder import build


TARGET_MODELS = [
    "MacBookAir8,1",
    "MacBookPro15,1",
    "MacBookPro15,2",
    "Macmini8,1",
]


def _copy_if_present(src: Path, dst: Path) -> None:
    if src.is_file():
        shutil.copy2(src, dst)


def _package_zip(source_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(source_dir.rglob("*")):
            if file_path.is_dir():
                continue
            arcname = str(file_path.relative_to(source_dir))
            info = zipfile.ZipInfo.from_file(file_path, arcname=arcname)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = file_path.stat().st_mode & 0xFFFF
            info.external_attr = mode << 16
            archive.writestr(info, file_path.read_bytes())


def build_diagnostic_efis(out_dir: Path, models: list[str]) -> None:
    kit_dir = Path(__file__).resolve().parent
    collector = kit_dir / "collect_2018_mac_diagnostics.command"
    readme = kit_dir / "README.md"

    out_dir.mkdir(parents=True, exist_ok=True)

    # Always publish the zero-risk native collector kit separately.
    with tempfile.TemporaryDirectory() as native_tmp:
        native_root = Path(native_tmp) / "2018-Native-Capture-Kit"
        native_root.mkdir()
        _copy_if_present(collector, native_root / collector.name)
        _copy_if_present(readme, native_root / readme.name)
        _package_zip(native_root.parent, out_dir / "2018-Native-Capture-Kit.zip")

    cleanup_constants = constants.Constants()
    try:
        for model in models:
            c = constants.Constants()
            c.validate = True
            c.custom_model = model
            c.verbose_debug = True
            c.opencore_debug = True
            c.kext_debug = True
            c.kext_variant = "DEBUG"
            c.secure_status = False
            c.sip_status = True
            c.serial_settings = "None"

            build.BuildOpenCore(model, c)
            config_plist = c.opencore_release_folder / "EFI/OC/config.plist"
            result = subprocess.run(
                [c.ocvalidate_path, str(config_plist)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"ocvalidate failed for {model}:\n{result.stdout}")

            cfg = plistlib.load(config_plist.open("rb"))
            if cfg["Misc"]["Debug"]["Target"] != 0x43:
                raise RuntimeError(f"Unexpected OpenCore Debug Target for {model}: {cfg['Misc']['Debug']['Target']}")

            with tempfile.TemporaryDirectory() as stage_tmp:
                bundle_root = Path(stage_tmp) / f"{model}-Diag-EFI"
                bundle_root.mkdir()
                shutil.copytree(c.opencore_release_folder / "EFI", bundle_root / "EFI")
                _copy_if_present(collector, bundle_root / collector.name)
                _copy_if_present(readme, bundle_root / readme.name)
                _package_zip(bundle_root.parent, out_dir / f"{model}-Diag-EFI.zip")
            print(f"Built & validated: {out_dir / f'{model}-Diag-EFI.zip'}")
    finally:
        shutil.rmtree(cleanup_constants.build_path, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "dist",
        help="Output directory for volunteer ZIP archives",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=TARGET_MODELS,
        help="2018 SMBIOS identifiers to package",
    )
    args = parser.parse_args()
    build_diagnostic_efis(args.out, args.models)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
