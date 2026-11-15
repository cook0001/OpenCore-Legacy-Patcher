import copy
import importlib
import plistlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


class _Dummy:
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, _name):
        return self

    def __or__(self, _other):
        return 0

    def __ror__(self, _other):
        return 0


def _install_macos_stubs() -> None:
    dummy = _Dummy()
    needed = [
        "objc", "CoreFoundation", "Foundation", "PyObjCTools", "PyObjCTools.Conversion",
        "Cocoa", "py_sip_xnu", "applescript", "markdown2", "wx", "wx.html2",
    ]
    for name in needed:
        if name in sys.modules:
            continue
        try:
            importlib.import_module(name)
            continue
        except ImportError:
            pass
        mod = types.ModuleType(name)
        mod.__path__ = []
        mod.__getattr__ = lambda _attr, d=dummy: d
        sys.modules[name] = mod
        if "." in name:
            parent, _, child = name.rpartition(".")
            setattr(sys.modules[parent], child, mod)

    objc_mod = sys.modules["objc"]
    if isinstance(objc_mod, types.ModuleType):
        objc_mod.lookUpClass = lambda name: type(name, (), {})
        objc_mod.super = super
        objc_mod.python_method = lambda func: func
        objc_mod.loadBundleFunctions = lambda *args, **kwargs: None
        objc_mod.loadBundleVariables = lambda _b, ns, vars_list, *a, **k: [ns.setdefault(v, 0) for v, _ in vars_list]
    if hasattr(sys.modules["CoreFoundation"], "__getattr__"):
        sys.modules["CoreFoundation"].kCFAllocatorDefault = None
        sys.modules["CoreFoundation"].CFRelease = lambda *_args: None
    if hasattr(sys.modules["Foundation"], "__getattr__"):
        sys.modules["Foundation"].NSBundle = type("NSBundle", (), {"bundleWithIdentifier_": staticmethod(lambda *_a: None)})
    if hasattr(sys.modules["wx"], "__getattr__"):
        for cls_name in ("Frame", "Dialog", "Panel"):
            setattr(sys.modules["wx"], cls_name, type(cls_name, (), {}))


_install_macos_stubs()

from opencore_legacy_patcher import constants  # noqa: E402
from opencore_legacy_patcher.datasets import example_data, model_array, os_data  # noqa: E402
from opencore_legacy_patcher.detections import device_probe  # noqa: E402
from opencore_legacy_patcher.efi_builder import build  # noqa: E402
from opencore_legacy_patcher.support import defaults, global_settings, macos_installer_handler, utilities, validation  # noqa: E402
from opencore_legacy_patcher.sys_patch.patchsets import DynamicPatchset, HardwarePatchsetDetection, HardwarePatchsetSettings, PatchType  # noqa: E402
from opencore_legacy_patcher.wx_gui import gui_macos_installer_flash, gui_support  # noqa: E402


class _TempConstants(constants.Constants):
    def __init__(self, temp_build_dir: Path) -> None:
        super().__init__()
        self._temp_build_dir = temp_build_dir
        self.vault = False
        self.validate = True

    @property
    def build_path(self) -> Path:
        return self._temp_build_dir


def _enabled_kexts(config: dict) -> set:
    return {entry["BundlePath"] for entry in config["Kernel"]["Add"] if entry.get("Enabled")}


class TestMacPro61(unittest.TestCase):

    def setUp(self) -> None:
        super().setUp()
        self._settings_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._settings_dir.cleanup)
        settings_root = self._settings_dir.name

        def _temp_settings_init(settings_self) -> None:
            settings_self.file_name = ".com.dortania.opencore-legacy-patcher.plist"
            settings_self.global_settings_folder = settings_root
            settings_self.global_settings_plist = f"{settings_root}/{settings_self.file_name}"
            settings_self._generate_settings_file()

        for patcher in [
            mock.patch.object(global_settings.GlobalEnviromentSettings, "__init__", _temp_settings_init),
            mock.patch.object(utilities, "get_nvram", return_value=None),
            mock.patch.object(utilities, "get_rom", return_value=None),
            mock.patch.object(utilities, "check_recovery", return_value=False),
            mock.patch.object(utilities, "check_cli_args", return_value=None),
            mock.patch.object(utilities, "check_kext_loaded", return_value=True),
        ]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _constants_for(self, computer=None, custom_model: str = "") -> _TempConstants:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        c = _TempConstants(Path(tmp.name) / "Build-Folder")
        c.custom_model = custom_model
        if computer is not None:
            c.computer = copy.deepcopy(computer)
            defaults.GenerateDefaults(c.computer.real_model, True, c)
        elif custom_model:
            defaults.GenerateDefaults(custom_model, False, c)
        return c

    def _build_efi(self, model: str, computer=None, custom_model: str = "", **overrides):
        c = self._constants_for(computer=computer, custom_model=custom_model)
        for key, value in overrides.items():
            setattr(c, key, value)
        efi = build.BuildOpenCore(model, c)
        return c, efi, _enabled_kexts(efi.config)

    def test_dgpu_probe_fallbacks(self) -> None:
        d500_1, d500_2 = example_data.MacPro.MacPro61_Stock.gpus
        pxs1 = example_data.MacPro.MacPro41_Upgrade.gpus[0]
        igpu = example_data.Macmini.Macmini61_Stock.gpus[0]

        with mock.patch.object(device_probe.ioreg, "kIOMasterPortDefault", 0, create=True), \
             mock.patch.object(device_probe.ioreg, "IOServiceNameMatching", side_effect=lambda name: name, create=True), \
             mock.patch.object(device_probe.ioreg, "IOServiceGetMatchingServices", return_value=(0, []), create=True), \
             mock.patch.object(device_probe.ioreg, "ioiterator_to_list", side_effect=lambda *_a: iter([])):
            mp = device_probe.Computer(gpus=[copy.deepcopy(d500_2), copy.deepcopy(d500_1)])
            mp.dgpu_probe()
            self.assertEqual(mp.dgpu.name, "ATY,KaniParent")
            self.assertIn("GFX1", mp.dgpu.acpi_path)

            swapped_1 = copy.deepcopy(d500_1)
            swapped_1.name = "ATY,KaniSParent"
            swapped_2 = copy.deepcopy(d500_2)
            swapped_2.name = "ATY,KaniParent"
            mp_renamed = device_probe.Computer(gpus=[swapped_2, swapped_1])
            mp_renamed.dgpu_probe()
            self.assertIn("GFX1", mp_renamed.dgpu.acpi_path)
            self.assertEqual(mp_renamed.dgpu.pci_path, d500_1.pci_path)

            mp41 = device_probe.Computer(gpus=[copy.deepcopy(pxs1)])
            mp41.dgpu_probe()
            self.assertEqual(mp41.dgpu.name, "PXS1")

            igpu_mac = device_probe.Computer(gpus=[copy.deepcopy(igpu)], igpu=copy.deepcopy(igpu))
            igpu_mac.dgpu_probe()
            self.assertIsNone(igpu_mac.dgpu)

    def test_macpro61_defaults(self) -> None:
        self.assertIn("MacPro6,1", model_array.MacPro)
        c = self._constants_for(computer=example_data.MacPro.MacPro61_Stock)
        self.assertEqual(c.serial_settings, "None")
        self.assertTrue(c.allow_nvme_fixing)
        self.assertFalse(c.sip_status)
        self.assertFalse(c.secure_status)
        self.assertTrue(c.force_vmm)
        self.assertFalse(c.fu_status)

    def test_macpro61_stock_efi_build(self) -> None:
        _, efi, kexts = self._build_efi("MacPro6,1", computer=example_data.MacPro.MacPro61_Stock)
        for kext in ["IOS3XeFamily.kext", "WhateverGreen.kext", "RestrictEvents.kext", "CryptexFixup.kext", "USB-Map-Tahoe.kext", "AirPortBrcmNIC-Tahoe.kext", "AppleIntelCPUPowerManagement.kext", "AppleIntelCPUPowerManagementClient.kext"]:
            self.assertIn(kext, kexts)
        for kext in ["AGPM-Override.kext", "NVMeFix.kext", "AppleALC.kext", "AGDP-Override.kext"]:
            self.assertNotIn(kext, kexts)

        dev_props = efi.config["DeviceProperties"]["Add"]
        expected_gpu = {"shikigva": 128, "unfairgva": 1, "rebuild-device-tree": 1, "agdpmod": "pikera", "enable-gva-support": 1}
        self.assertEqual(dev_props["PciRoot(0x0)/Pci(0x2,0x0)/Pci(0x0,0x0)"], expected_gpu)
        self.assertEqual(dev_props["PciRoot(0x0)/Pci(0x3,0x0)/Pci(0x0,0x0)"], expected_gpu)
        self.assertEqual(dev_props["PciRoot(0x0)/Pci(0x1C,0x4)/Pci(0x0,0x0)"], {"built-in": 1})

        pci_patch = next(p for p in efi.config["Kernel"]["Patch"] if p["Comment"] == "Fix PCI bus enumeration (Sonoma)")
        self.assertTrue(pci_patch["Enabled"])
        self.assertEqual((pci_patch["MinKernel"], pci_patch["MaxKernel"]), ("23.0.0", ""))

        nvram_re = efi.config["NVRAM"]["Add"]["4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102"]
        self.assertEqual(nvram_re["revblock"], "pci")
        self.assertIn("sbvmm", nvram_re["revpatch"].split(","))
        self.assertIn("f16c", nvram_re["revpatch"].split(","))
        self.assertNotIn("pci", nvram_re["revpatch"].split(","))

    def test_macpro61_apple_ahci_s1x_efi_build(self) -> None:
        comp = copy.deepcopy(example_data.MacPro.MacPro61_Stock)
        comp.storage = [
            device_probe.SATAController(
                vendor_id=0x144D,
                device_id=0x1600,
                class_code=0x010601,
                name="SSD0",
                model="APPLE SSD SM1024F",
                acpi_path="IOService:/AppleACPIPlatformExpert/PCI0@0/AppleACPIPCI/RP05@1C,4/IOPP/SSD0@0",
                pci_path="PciRoot(0x0)/Pci(0x1C,0x4)/Pci(0x0,0x0)",
            )
        ]
        _, efi, kexts = self._build_efi("MacPro6,1", computer=comp)
        self.assertNotIn("NVMeFix.kext", kexts)
        self.assertNotIn("IOS3XeFamily.kext", kexts)
        self.assertEqual(efi.config["DeviceProperties"]["Add"]["PciRoot(0x0)/Pci(0x1C,0x4)/Pci(0x0,0x0)"], {"built-in": 1})

    def test_macpro61_samsung_nvme_upgrade_efi_build(self) -> None:
        _, efi, kexts = self._build_efi("MacPro6,1", computer=example_data.MacPro.MacPro61_NVMe_Upgrade)
        self.assertIn("NVMeFix.kext", kexts)
        self.assertNotIn("IOS3XeFamily.kext", kexts)
        self.assertNotIn("AppleALC.kext", kexts)

        dev_props = efi.config["DeviceProperties"]["Add"]
        self.assertEqual(dev_props["PciRoot(0x0)/Pci(0x1C,0x4)/Pci(0x0,0x0)"], {"built-in": 1, "pci-aspm-default": 2})
        self.assertEqual(dev_props["PciRoot(0x0)/Pci(0x1C,0x4)"], {"pci-aspm-default": 2})

    def test_macpro61_nvme_edge_cases(self) -> None:
        comp_no_path = copy.deepcopy(example_data.MacPro.MacPro61_NVMe_Upgrade)
        comp_no_path.storage[0].aspm = None
        comp_no_path.storage[0].pci_path = None
        _, efi, kexts = self._build_efi("MacPro6,1", computer=comp_no_path)
        self.assertIn("NVMeFix.kext", kexts)
        self.assertIn("Innie.kext", kexts)
        self.assertIn("-nvmefaspm", efi.config["NVRAM"]["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"].split())

        comp_none_aspm = copy.deepcopy(example_data.MacPro.MacPro61_NVMe_Upgrade)
        comp_none_aspm.storage[0].aspm = None
        _, efi2, _ = self._build_efi("MacPro6,1", computer=comp_none_aspm)
        self.assertEqual(efi2.config["DeviceProperties"]["Add"]["PciRoot(0x0)/Pci(0x1C,0x4)/Pci(0x0,0x0)"], {"built-in": 1, "pci-aspm-default": 2})

    def test_macpro61_smbios_spoof_macpro71(self) -> None:
        c, efi, kexts = self._build_efi(
            "MacPro6,1",
            computer=example_data.MacPro.MacPro61_NVMe_Upgrade,
            serial_settings="Minimal",
            hardware_spoof=True,
        )
        self.assertIn("AGPM-Override.kext", kexts)
        self.assertNotIn("AGDP-Override.kext", kexts)
        self.assertEqual(efi.config["PlatformInfo"]["DataHub"]["BoardProduct"], "Mac-27AD2F918AE68F61")

        nvram_re = efi.config["NVRAM"]["Add"]["4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102"]
        self.assertEqual(nvram_re["revblock"], "pci")
        self.assertIn("pci", nvram_re["revpatch"].split(","))
        self.assertIn("f16c", nvram_re["revpatch"].split(","))

        with c.plist_path.open("rb") as f:
            self.assertEqual(plistlib.load(f)["PlatformInfo"]["DataHub"]["BoardProduct"], "Mac-27AD2F918AE68F61")
        with (c.agpm_contents_folder / "Info.plist").open("rb") as f:
            machines = plistlib.load(f)["IOKitPersonalities"]["AGPM"]["Machines"]
        self.assertIn("GFX1", machines["Mac-27AD2F918AE68F61"])
        self.assertIn("GFX2", machines["Mac-27AD2F918AE68F61"])
        self.assertNotIn("MacPro6,1", machines)

    def test_macpro61_egpu_and_missing_acpi_paths(self) -> None:
        comp = copy.deepcopy(example_data.MacPro.MacPro61_Stock)
        comp.gpus.append(
            device_probe.AMD(
                vendor_id=0x1002, device_id=0x731F, class_code=0x030000,
                name="display", model="AMD Radeon RX 5700 XT",
                acpi_path=None, pci_path="PciRoot(0x0)/Pci(0x5,0x0)/Pci(0x0,0x0)",
            )
        )
        _, efi, _ = self._build_efi("MacPro6,1", computer=comp)
        args = efi.config["NVRAM"]["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"].split()
        for expected in ["shikigva=128", "unfairgva=1", "agdpmod=pikera", "radgva=1", "-wegtree"]:
            self.assertEqual(args.count(expected), 1)

    def test_macpro61_custom_model_offline_build(self) -> None:
        _, efi, kexts = self._build_efi("MacPro6,1", custom_model="MacPro6,1")
        self.assertIn("WhateverGreen.kext", kexts)
        self.assertIn("IOS3XeFamily.kext", kexts)
        self.assertIn("RestrictEvents.kext", kexts)
        self.assertNotIn("AppleALC.kext", kexts)

        args = efi.config["NVRAM"]["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"].split()
        for expected in ["shikigva=128", "unfairgva=1", "-wegtree", "agdpmod=pikera", "radgva=1"]:
            self.assertEqual(args.count(expected), 1)

    def test_regression_models_and_all_macpro_dumps(self) -> None:
        _, _, mbp_kexts = self._build_efi("MacBookPro13,3", computer=example_data.MacBookPro.MacBookPro133_Stock)
        self.assertNotIn("NVMeFix.kext", mbp_kexts)

        for name in dir(example_data.MacPro):
            dump = getattr(example_data.MacPro, name)
            if not isinstance(dump, device_probe.Computer):
                continue
            _, _, kexts = self._build_efi(dump.real_model, computer=dump)
            if dump.real_model != "MacPro6,1":
                self.assertIn("AppleALC.kext", kexts, f"AppleALC missing for {dump.real_model}")
            else:
                self.assertNotIn("AppleALC.kext", kexts)

    def test_root_patchsets_sonoma_sequoia_tahoe(self) -> None:
        with mock.patch.object(HardwarePatchsetDetection, "_validation_check_missing_network_connection", return_value=False), \
             mock.patch.object(HardwarePatchsetDetection, "_validation_check_filevault_is_enabled", return_value=False), \
             mock.patch.object(HardwarePatchsetDetection, "_validation_check_system_integrity_protection_enabled", return_value=False), \
             mock.patch.object(HardwarePatchsetDetection, "_validation_check_secure_boot_model_enabled", return_value=False), \
             mock.patch.object(HardwarePatchsetDetection, "_validation_check_amfi_enabled", return_value=False), \
             mock.patch.object(HardwarePatchsetDetection, "_validation_check_unsupported_host_os", return_value=False), \
             mock.patch.object(HardwarePatchsetDetection, "_is_cached_metallib_support_pkg_present", return_value=True), \
             mock.patch.object(HardwarePatchsetDetection, "_is_cached_kernel_debug_kit_present", return_value=True):
            for xnu_major, expect_audio in [(23, False), (24, False), (25, True)]:
                c = self._constants_for(computer=example_data.MacPro.MacPro61_Stock)
                detector = HardwarePatchsetDetection(c, xnu_major=xnu_major, xnu_minor=0, validation=False)
                self.assertIn("Graphics: AMD Legacy GCN", detector.device_properties)
                self.assertIn("Networking: Modern Wireless", detector.device_properties)
                self.assertNotIn("Miscellaneous: Legacy GMUX", detector.device_properties)
                if expect_audio:
                    self.assertIn("Miscellaneous: Modern Audio", detector.device_properties)
                else:
                    self.assertNotIn("Miscellaneous: Modern Audio", detector.device_properties)

            comp = copy.deepcopy(example_data.MacPro.MacPro61_Stock)
            comp.gpus.append(
                device_probe.AMD(
                    vendor_id=0x1002, device_id=0x731F, class_code=0x030000,
                    name="display", model="AMD Radeon RX 5700 XT",
                    pci_path="PciRoot(0x0)/Pci(0x5,0x0)/Pci(0x0,0x0)",
                )
            )
            c = self._constants_for(computer=comp)
            detector = HardwarePatchsetDetection(c, xnu_major=24, xnu_minor=0, validation=False)
            self.assertIn("Graphics: AMD Legacy GCN", detector.device_properties)
            self.assertIn("Graphics: AMD Navi", detector.device_properties)

            ps = HardwarePatchsetDetection(c, xnu_major=os_data.os_data.tahoe.value, xnu_minor=0, validation=True).patches
            for block in ps.values():
                for install_type in block:
                    self.assertIn(install_type, PatchType)
                for it in [PatchType.OVERWRITE_SYSTEM_VOLUME, PatchType.OVERWRITE_DATA_VOLUME, PatchType.MERGE_SYSTEM_VOLUME, PatchType.MERGE_DATA_VOLUME]:
                    for files in block.get(it, {}).values():
                        for fname, ver in files.items():
                            if isinstance(ver, DynamicPatchset):
                                continue
                            if it in [PatchType.OVERWRITE_SYSTEM_VOLUME, PatchType.OVERWRITE_DATA_VOLUME]:
                                self.assertFalse(fname.endswith(".framework"))
                            elif fname not in ["MechanismPlugins", "ModulePlugins"]:
                                self.assertTrue(fname.endswith(".framework"))

            gcn_tahoe = ps["AMD Legacy GCN"][PatchType.OVERWRITE_SYSTEM_VOLUME]["/System/Library/Extensions"]
            self.assertEqual(gcn_tahoe["AMDRadeonVADriver.bundle"], "12.5")
            self.assertEqual(gcn_tahoe["AMDRadeonVADriver2.bundle"], "12.5-25")

            ps_sequoia = HardwarePatchsetDetection(c, xnu_major=os_data.os_data.sequoia.value, xnu_minor=0, validation=False).patches
            gcn_sequoia = ps_sequoia["AMD Legacy GCN"][PatchType.OVERWRITE_SYSTEM_VOLUME]["/System/Library/Extensions"]
            self.assertEqual(gcn_sequoia["AMDRadeonVADriver.bundle"], "12.5")
            self.assertEqual(gcn_sequoia["AMDRadeonVADriver2.bundle"], "12.5")

            polaris_comp = copy.deepcopy(example_data.MacPro.MacPro61_Stock)
            polaris_comp.gpus.append(
                device_probe.AMD(
                    vendor_id=0x1002, device_id=0x67DF, class_code=0x030000,
                    name="display", model="AMD Radeon RX 580",
                    pci_path="PciRoot(0x0)/Pci(0x5,0x0)/Pci(0x0,0x0)",
                )
            )
            c_polaris = self._constants_for(computer=polaris_comp)
            ps_polaris_sequoia = HardwarePatchsetDetection(c_polaris, xnu_major=os_data.os_data.sequoia.value, xnu_minor=0, validation=False).patches
            ps_polaris_tahoe = HardwarePatchsetDetection(c_polaris, xnu_major=os_data.os_data.tahoe.value, xnu_minor=0, validation=False).patches
            self.assertEqual(
                ps_polaris_sequoia["AMD Polaris"][PatchType.OVERWRITE_SYSTEM_VOLUME]["/System/Library/Extensions"]["AMDRadeonVADriver2.bundle"],
                "12.5",
            )
            self.assertEqual(
                ps_polaris_tahoe["AMD Polaris"][PatchType.OVERWRITE_SYSTEM_VOLUME]["/System/Library/Extensions"]["AMDRadeonVADriver2.bundle"],
                "12.5-25",
            )

            seen_os = set()
            v = object.__new__(validation.PatcherValidation)
            v.constants = c
            v.verify_unused_files = False
            v.active_patchset_files = []
            with mock.patch.object(validation.Path, "exists", return_value=True), \
                 mock.patch.object(validation.subprocess, "run", return_value=mock.Mock(returncode=0)), \
                 mock.patch.object(validation.sys_patch_helpers.SysPatchHelpers, "snb_board_id_patch"), \
                 mock.patch.object(v, "_unmount_dmg"), \
                 mock.patch.object(v, "_validate_root_patch_files", side_effect=lambda os_ver, _minor: seen_os.add(os_ver)):
                v._validate_sys_patch()
            self.assertIn(os_data.os_data.tahoe, seen_os)

    def test_macpro61_live_opencore_usb_installer_build(self) -> None:
        comp = copy.deepcopy(example_data.MacPro.MacPro61_NVMe_Upgrade)
        comp.reported_model = "MacPro7,1"
        comp.reported_board_id = "Mac-27AD2F918AE68F61"
        comp.build_model = "MacPro6,1"
        comp.oclp_version = constants.Constants().patcher_version
        comp.opencore_version = "REL-106-2025-07-01"
        comp.opencore_path = (
            "PciRoot(0x0)/Pci(0x1C,0x4)/Pci(0x0,0x0)/NVMe(0x1,00-1B-44-8B-44-8B-00-01)"
            r"/HD(1,GPT,11111111-2222-3333-4444-555555555555,0x28,0x64000)/\EFI\BOOT\BOOTx64.EFI"
        )
        comp.gpus[0].name = "GFX0"
        comp.gpus[0].acpi_path = "IOACPIPlane:/_SB/PCI0@0/GFXA@20000/GFX0@0"
        comp.gpus[1].name = "GFX1"
        comp.gpus[1].acpi_path = "IOACPIPlane:/_SB/PCI0@0/GFXB@30000/GFX1@0"

        self.assertEqual(
            utilities.clean_device_path(comp.opencore_path),
            "11111111-2222-3333-4444-555555555555",
        )

        # Post-OpenCore boot with WhateverGreen -wegtree active exposes GFX0 directly
        probe_comp = copy.deepcopy(comp)
        probe_comp.dgpu = None
        sentinel_gfx0 = object()
        fake_pcidev = mock.Mock()
        fake_pcidev.vendor_detect.return_value = device_probe.AMD
        with mock.patch.object(device_probe.ioreg, "kIOMasterPortDefault", 0, create=True), \
             mock.patch.object(device_probe.ioreg, "IOServiceNameMatching", side_effect=lambda name: name, create=True), \
             mock.patch.object(device_probe.ioreg, "IOServiceGetMatchingServices", return_value=(0, [sentinel_gfx0]), create=True), \
             mock.patch.object(device_probe.ioreg, "IOObjectRelease"), \
             mock.patch.object(device_probe.ioreg, "ioiterator_to_list", side_effect=lambda it: iter(it)), \
             mock.patch.object(device_probe.PCIDevice, "from_ioregistry", return_value=fake_pcidev), \
             mock.patch.object(device_probe.AMD, "from_ioregistry", return_value=copy.deepcopy(comp.gpus[0])):
            probe_comp.dgpu_probe()
        self.assertEqual(probe_comp.dgpu.name, "GFX0")
        self.assertEqual(probe_comp.dgpu.pci_path, comp.gpus[0].pci_path)

        c, efi, kexts = self._build_efi(
            comp.real_model,
            computer=comp,
            custom_model=None,
            wxpython_variant=True,
            detected_os=os_data.os_data.monterey.value,
        )
        self.assertTrue(gui_support.CheckProperties(c).host_can_build())
        self.assertIn("AutoPkgInstaller.kext", kexts)
        self.assertIn("WhateverGreen.kext", kexts)
        self.assertIn("NVMeFix.kext", kexts)
        self.assertIn("USB-Map.kext", kexts)
        self.assertIn("USB-Map-Tahoe.kext", kexts)
        self.assertNotIn("AppleALC.kext", kexts)

        dp = efi.config["DeviceProperties"]["Add"]
        for gpu in comp.gpus:
            self.assertEqual(dp[gpu.pci_path]["shikigva"], 128)
            self.assertEqual(dp[gpu.pci_path]["rebuild-device-tree"], 1)
            self.assertEqual(dp[gpu.pci_path]["agdpmod"], "pikera")
        nvme_path = comp.storage[0].pci_path
        self.assertEqual(dp[nvme_path]["built-in"], 1)
        self.assertEqual(dp[nvme_path]["pci-aspm-default"], 2)
        self.assertEqual(dp[nvme_path.rpartition("/")[0]]["pci-aspm-default"], 2)
        self.assertEqual(efi.config["#Revision"]["Build-Type"], "OpenCore Built on Target Machine")
        self.assertEqual(efi.config["#Revision"]["Original-Model"], "MacPro6,1")
        self.assertEqual(efi.config["NVRAM"]["Add"]["4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102"]["OCLP-Model"], "MacPro6,1")

        with mock.patch.object(HardwarePatchsetDetection, "_validation_check_missing_network_connection", return_value=False), \
             mock.patch.object(HardwarePatchsetDetection, "_validation_check_filevault_is_enabled", return_value=False), \
             mock.patch.object(HardwarePatchsetDetection, "_validation_check_system_integrity_protection_enabled", return_value=False), \
             mock.patch.object(HardwarePatchsetDetection, "_validation_check_secure_boot_model_enabled", return_value=False), \
             mock.patch.object(HardwarePatchsetDetection, "_validation_check_amfi_enabled", return_value=False), \
             mock.patch.object(HardwarePatchsetDetection, "_validation_check_unsupported_host_os", return_value=False), \
             mock.patch.object(HardwarePatchsetDetection, "_is_cached_metallib_support_pkg_present", return_value=False), \
             mock.patch.object(HardwarePatchsetDetection, "_is_cached_kernel_debug_kit_present", return_value=False):
            detector = HardwarePatchsetDetection(c, xnu_major=os_data.os_data.tahoe.value, xnu_minor=0, validation=False)
        self.assertIn("Graphics: AMD Legacy GCN", detector.device_properties)
        self.assertIn("Networking: Modern Wireless", detector.device_properties)
        self.assertIn("Miscellaneous: Modern Audio", detector.device_properties)
        self.assertTrue(detector.device_properties[HardwarePatchsetSettings.KERNEL_DEBUG_KIT_REQUIRED])
        self.assertTrue(detector.device_properties[HardwarePatchsetSettings.KERNEL_DEBUG_KIT_MISSING])
        self.assertFalse(detector.device_properties[HardwarePatchsetSettings.METALLIB_SUPPORT_PKG_REQUIRED])
        self.assertFalse(detector.device_properties[HardwarePatchsetSettings.METALLIB_SUPPORT_PKG_MISSING])

    def test_usb_installer_kdk_chainload_low_space_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            usb_packages = tmp_path / "usb" / "Library" / "Packages"
            usb_packages.mkdir(parents=True)
            local_kdk_dmg = tmp_path / "payloads" / "KDK.dmg"
            local_kdk_dmg.parent.mkdir(parents=True)

            c = self._constants_for(computer=example_data.MacPro.MacPro61_Stock, custom_model=None)
            frame = gui_macos_installer_flash.macOSInstallerFlashFrame.__new__(gui_macos_installer_flash.macOSInstallerFlashFrame)
            frame.constants = mock.Mock(wraps=c)
            frame.constants.kdk_download_path = local_kdk_dmg

            kdk_obj = mock.Mock()
            kdk_obj.success = True
            kdk_obj.error_msg = ""
            kdk_obj.kdk_url_expected_size = 1000

            requested_paths = []

            def _retrieve_download(override_path=""):
                requested_paths.append(Path(override_path))
                dl = mock.Mock()
                dl.download_complete = True
                dl.download.side_effect = lambda spawn_thread=False: Path(override_path).write_bytes(b"kdk")
                return dl

            kdk_obj.retrieve_download.side_effect = _retrieve_download

            def _fake_subprocess_run(cmd, **_kwargs):
                if cmd[:2] == ["/usr/bin/hdiutil", "attach"]:
                    Path(cmd[cmd.index("-mountpoint") + 1], "KernelDebugKit.pkg").write_bytes(b"pkg")
                elif cmd[:2] != ["/usr/bin/hdiutil", "detach"]:
                    Path(cmd[-1]).write_bytes(Path(cmd[-2]).read_bytes())
                return mock.Mock(returncode=0, stdout=b"", stderr=b"")

            with mock.patch.object(gui_macos_installer_flash.kdk_handler, "KernelDebugKitObject", return_value=kdk_obj), \
                 mock.patch.object(gui_macos_installer_flash.utilities, "get_free_space", return_value=1500), \
                 mock.patch.object(gui_macos_installer_flash, "generate_copy_arguments", side_effect=lambda src, dst: ["/bin/cp", str(src), str(dst)]), \
                 mock.patch.object(gui_macos_installer_flash.subprocess, "run", side_effect=_fake_subprocess_run):
                frame._kdk_chainload("25A123", "26.0", str(usb_packages))

            self.assertEqual(requested_paths, [local_kdk_dmg])
            self.assertFalse(local_kdk_dmg.exists())
            self.assertFalse((usb_packages / "KDK.dmg").exists())
            self.assertEqual((usb_packages / "KDK.pkg").read_bytes(), b"pkg")

            # Missing DownloadObject must return without calling .download()
            kdk_obj.retrieve_download.side_effect = None
            kdk_obj.retrieve_download.return_value = None
            with mock.patch.object(gui_macos_installer_flash.kdk_handler, "KernelDebugKitObject", return_value=kdk_obj), \
                 mock.patch.object(gui_macos_installer_flash.utilities, "get_free_space", return_value=5000):
                frame._kdk_chainload("25A123", "26.0", str(usb_packages))

            # Non-CoW installer size check must measure installer_path contents rather than empty ia_tmp
            installer_app = tmp_path / "Install macOS Tahoe.app"
            shared_support = installer_app / "Contents" / "SharedSupport"
            shared_support.mkdir(parents=True)
            (shared_support / "SharedSupport.dmg").write_bytes(b"x" * 4096)
            with mock.patch.object(macos_installer_handler, "can_copy_on_write", return_value=False), \
                 mock.patch.object(macos_installer_handler.utilities, "get_free_space", return_value=1024):
                self.assertFalse(
                    macos_installer_handler.InstallerCreation().generate_installer_creation_script(
                        str(tmp_path), str(installer_app), "/dev/disk9"
                    )
                )


if __name__ == "__main__":
    unittest.main()
