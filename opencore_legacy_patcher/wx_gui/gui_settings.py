"""
gui_settings.py: Declarative, scrollable Settings Panel for OpenCore Legacy Patcher
"""

import wx
import wx.adv
import pprint
import logging
import py_sip_xnu
import subprocess

from pathlib import Path

from .. import constants
from ..sys_patch import sys_patch
from ..wx_gui import gui_support, gui_strings
from ..support import (
    global_settings,
    defaults,
    generate_smbios,
    network_handler,
)
from ..datasets import (
    model_array,
    sip_data,
    smbios_data,
    os_data,
    cpu_data,
)


class SettingsPanel(wx.Panel):
    """
    Category-based scrollable Settings Panel routed inside the single main window
    """

    _APP_ONLY_SETTINGS = frozenset({
        "IgnoreAppUpdates",
        "DisableCrashAndAnalyticsReporting",
        "ShouldNukeKDKs",
        "MacBookPro_TeraScale_2_Accel",
    })

    _RESETTABLE_CONSTANTS = (
        "allow_oc_everywhere", "ignore_updates", "should_nuke_kdks", "custom_model",
        "opencore_debug", "boot_efi", "showpicker", "nvram_write", "oc_timeout",
        "kext_debug", "kext_variant", "verbose_debug", "serial_settings",
        "override_smbios", "allow_native_spoofs", "custom_serial_number",
        "custom_board_serial_number", "fu_status", "fu_arguments", "sip_status",
        "secure_status", "vault", "disable_cs_lv", "disable_amfi",
        "firewire_boot", "nvme_boot", "xhci_boot", "allow_ts2_accel",
        "drm_support", "force_nv_web", "force_output_support", "amd_gop_injection",
        "nvidia_kepler_gop_injection", "metal_build", "imac_vendor", "imac_model",
        "disallow_cpufriend", "enable_wake_on_wlan", "disable_tb", "dGPU_switch",
        "force_surplus", "force_latest_psp", "disable_fw_throttle",
        "software_demux", "force_vmm", "disable_connectdrivers", "set_vmm_cpuid",
        "disable_mediaanalysisd", "set_alc_usage", "allow_3rd_party_drives",
        "allow_nvme_fixing", "apfs_trim_timeout", "custom_sip_value",
    )

    def __init__(self, parent: wx.Window, app, global_constants: constants.Constants, oc_settings_changed: bool = False) -> None:
        super().__init__(parent)
        logging.info("Initializing Settings Panel")
        self.app = app
        self.constants = global_constants
        self.oc_settings_changed = oc_settings_changed
        self.hyperlink_colour = wx.Colour(25, 179, 231)

        self.categories: list[str] = []
        self.category_pages: dict[str, wx.ScrolledWindow] = {}
        self.settings: dict = {}

        self._build_ui()

    def _build_ui(self) -> None:
        outer = wx.BoxSizer(wx.VERTICAL)
        self.header = gui_support.PageHeader(
            self,
            gui_strings.SETTINGS["title"],
            back_label=gui_strings.NAV["return_main"],
            on_back=self.on_return,
        )
        outer.Add(self.header, 0, wx.EXPAND)

        # Target Model bar
        model_bar = wx.BoxSizer(wx.HORIZONTAL)
        model_lbl = wx.StaticText(self, label=f"{gui_strings.SETTINGS['target_model']}:")
        model_lbl.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_BOLD))
        model_bar.Add(model_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        self.model_choice = wx.Choice(self, choices=model_array.SupportedSMBIOS + ["Host Model"], size=(160, -1))
        self.model_choice.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        selection = self.constants.custom_model if self.constants.custom_model else "Host Model"
        self.model_choice.SetSelection(self.model_choice.FindString(selection))
        self.model_choice.Bind(wx.EVT_CHOICE, self.on_model_choice)
        model_bar.Add(self.model_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)

        model_desc = wx.StaticText(self, label=gui_strings.SETTINGS["target_model_desc"])
        model_desc.SetFont(gui_support.font_factory(11, wx.FONTWEIGHT_NORMAL))
        model_desc.SetForegroundColour(wx.Colour(128, 128, 128))
        model_bar.Add(model_desc, 1, wx.ALIGN_CENTER_VERTICAL)

        outer.Add(model_bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
        outer.AddSpacer(8)

        # Sidebar + right ScrolledWindow container
        split = wx.BoxSizer(wx.HORIZONTAL)
        self.sidebar = wx.ListBox(self, style=wx.LB_SINGLE, size=(155, -1))
        self.sidebar.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        self.sidebar.Bind(wx.EVT_LISTBOX, self._on_category_select)
        split.Add(self.sidebar, 0, wx.EXPAND | wx.RIGHT, 10)

        self.book = wx.Simplebook(self)
        split.Add(self.book, 1, wx.EXPAND)
        outer.Add(split, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 16)

        # Footer action bar
        footer = wx.BoxSizer(wx.HORIZONTAL)
        reset_btn = wx.Button(self, label=gui_strings.SETTINGS["reset_btn"], size=(135, 30))
        reset_btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        reset_btn.Bind(wx.EVT_BUTTON, self.on_reset_settings)
        footer.Add(reset_btn, 0, wx.RIGHT, 8)

        self.rebuild_button = wx.Button(self, label=gui_strings.SETTINGS["rebuild_btn"], size=(155, 30))
        self.rebuild_button.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        self.rebuild_button.Bind(wx.EVT_BUTTON, self.on_rebuild_opencore)
        self.rebuild_button.Enable(gui_support.CheckProperties(self.constants).host_can_build())
        footer.Add(self.rebuild_button, 0, wx.RIGHT, 8)

        return_btn = wx.Button(self, label=gui_strings.NAV["return_main"], size=(165, 30))
        return_btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        return_btn.Bind(wx.EVT_BUTTON, self.on_return)
        footer.Add(return_btn, 0)

        outer.Add(footer, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.TOP | wx.BOTTOM, 12)
        self.SetSizer(outer)
        self._reload_categories()

    def _reload_categories(self, preserve_category: str = None) -> None:
        self.settings = self._settings_schema()
        tabs = list(self.settings.keys())
        if not Path("~/.dortania_developer").expanduser().exists() and "Developer" in tabs:
            tabs.remove("Developer")

        self.book.DeleteAllPages()
        self.sidebar.Clear()
        self.category_pages.clear()
        self.categories = tabs

        for tab in tabs:
            self.sidebar.Append(tab)
            page = self._build_category_page(tab, self.settings[tab])
            self.category_pages[tab] = page
            self.book.AddPage(page, tab)

        idx = tabs.index(preserve_category) if preserve_category in tabs else 0
        self.sidebar.SetSelection(idx)
        self.book.SetSelection(idx)
        self.Layout()

    def _on_category_select(self, event: wx.Event) -> None:
        idx = self.sidebar.GetSelection()
        if idx != wx.NOT_FOUND:
            self.book.SetSelection(idx)

    def _build_category_page(self, category: str, entries: dict) -> wx.ScrolledWindow:
        page = wx.ScrolledWindow(self.book, style=wx.VSCROLL)
        page.SetScrollRate(0, 16)
        col = wx.BoxSizer(wx.VERTICAL)

        for label, info in entries.items():
            kind = info["type"]
            enabled = info.get("condition", True)

            if kind == "title":
                hdr = wx.StaticText(page, label=label)
                hdr.SetFont(gui_support.font_factory(15, wx.FONTWEIGHT_BOLD))
                col.Add(hdr, 0, wx.TOP | wx.BOTTOM, 6)
                col.Add(wx.StaticLine(page), 0, wx.EXPAND | wx.BOTTOM, 8)
                continue

            if kind == "custom":
                info["builder"](page, col)
                col.AddSpacer(8)
                continue

            if kind == "checkbox":
                cb = wx.CheckBox(page, label=label)
                cb.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_BOLD))
                cb.SetValue(bool(info.get("value", False)) if enabled else False)
                cb.Enable(enabled)
                cb.Bind(wx.EVT_CHECKBOX, lambda evt, cat=category, key=label: self._on_checkbox(evt, cat, key))
                col.Add(cb, 0, wx.BOTTOM, 2)

            elif kind == "spinctrl":
                row = wx.BoxSizer(wx.HORIZONTAL)
                spin = wx.SpinCtrl(page, value=str(info["value"]), min=info["min"], max=info["max"], size=(58, -1))
                spin.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_BOLD))
                spin.Bind(wx.EVT_TEXT, lambda evt, key=label, cat=category: self._on_spinctrl(evt, cat, key))
                row.Add(spin, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
                lbl = wx.StaticText(page, label=label)
                lbl.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_BOLD))
                row.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
                col.Add(row, 0, wx.BOTTOM, 2)

            elif kind == "choice":
                lbl = wx.StaticText(page, label=label)
                lbl.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_BOLD))
                col.Add(lbl, 0, wx.BOTTOM, 4)

                choice = wx.Choice(page, choices=info["choices"], size=(190, -1))
                choice.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
                sel = choice.FindString(info["value"])
                if sel != wx.NOT_FOUND:
                    choice.SetSelection(sel)
                choice.Enable(enabled)
                if "override_function" in info:
                    choice.Bind(wx.EVT_CHOICE, info["override_function"])
                else:
                    choice.Bind(wx.EVT_CHOICE, lambda evt, key=label, cat=category: self._on_choice(evt, cat, key))
                col.Add(choice, 0, wx.LEFT | wx.BOTTOM, 4)

            elif kind == "button":
                btn = wx.Button(page, label=label, size=(220, 30))
                btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
                btn.Bind(wx.EVT_BUTTON, info["function"])
                col.Add(btn, 0, wx.BOTTOM, 4)

            desc_lines = [line for line in info.get("description", []) if line]
            if desc_lines:
                desc = wx.StaticText(page, label=" ".join(desc_lines))
                desc.SetFont(gui_support.font_factory(11, wx.FONTWEIGHT_NORMAL))
                if not enabled:
                    desc.SetForegroundColour(wx.Colour(128, 128, 128))
                desc.Wrap(415)
                col.Add(desc, 0, wx.LEFT | wx.BOTTOM, 10)
            else:
                col.AddSpacer(6)

        page.SetSizer(col)
        page.FitInside()
        return page

    @staticmethod
    def _read_prop(key: str, default):
        val = global_settings.GlobalEnviromentSettings().read_property(key)
        return default if val is None else val

    def _fu_value_label(self) -> str:
        if self.constants.fu_status is False:
            return "Disabled"
        if self.constants.fu_arguments is None or self.constants.fu_arguments == "":
            return "Enabled"
        return "Partial"

    def _settings_schema(self) -> dict:
        models = [m for m in smbios_data.smbios_dictionary if "_" not in m and " " not in m and smbios_data.smbios_dictionary[m]["Board ID"] is not None]
        socketed_imac_models = ["iMac9,1", "iMac10,1", "iMac11,1", "iMac11,2", "iMac11,3", "iMac12,1", "iMac12,2"]
        socketed_gpu_models = socketed_imac_models + ["MacPro3,1", "MacPro4,1", "MacPro5,1", "Xserve2,1", "Xserve3,1"]
        target_model = self.constants.custom_model or self.constants.computer.real_model

        return {
            "App & Updates": {
                "General": {"type": "title"},
                "Allow native models": {
                    "type": "checkbox",
                    "value": self.constants.allow_oc_everywhere,
                    "variable": "allow_oc_everywhere",
                    "description": ["Allow OpenCore to be installed on natively supported Macs."],
                    "warning": (
                        "This option should only be used if your Mac natively supports the OSes you wish to run.\n\n"
                        "If running an unsupported OS, this option will break booting. Only toggle for enabling features on a native Mac.\n\n"
                        "Are you certain you want to continue?"
                    ),
                },
                "Ignore App Updates": {
                    "type": "checkbox",
                    "value": self._read_prop("IgnoreAppUpdates", self.constants.ignore_updates),
                    "variable": "IgnoreAppUpdates",
                    "constants_variable": "ignore_updates",
                    "description": ["Suppress automatic checks for OpenCore Legacy Patcher updates."],
                    "override_function": self._update_global_settings,
                },
                "Disable Reporting": {
                    "type": "checkbox",
                    "value": self._read_prop("DisableCrashAndAnalyticsReporting", False),
                    "variable": "DisableCrashAndAnalyticsReporting",
                    "description": ["Prevent sending crash and analytics reports to Dortania."],
                    "override_function": self._update_global_settings,
                },
                "Remove Unused KDKs": {
                    "type": "checkbox",
                    "value": self._read_prop("ShouldNukeKDKs", self.constants.should_nuke_kdks),
                    "variable": "ShouldNukeKDKs",
                    "constants_variable": "should_nuke_kdks",
                    "description": ["Remove unused Kernel Debug Kits during root patching."],
                    "override_function": self._update_global_settings,
                },
                "Statistics": {"type": "title"},
                "Populate Stats": {"type": "custom", "builder": self._build_app_stats},
            },
            "Boot & OpenCore": {
                "Boot Options": {"type": "title"},
                "Show OpenCore Boot Picker": {
                    "type": "checkbox",
                    "value": self.constants.showpicker,
                    "variable": "showpicker",
                    "description": ["When disabled, hold ESC in firmware to show the boot picker."],
                },
                "Boot Picker Timeout": {
                    "type": "spinctrl",
                    "value": self.constants.oc_timeout,
                    "variable": "oc_timeout",
                    "description": ["Seconds before selecting default entry (0 for no timeout)."],
                    "min": 0,
                    "max": 60,
                },
                "OpenCore Vaulting": {
                    "type": "checkbox",
                    "value": self.constants.vault,
                    "variable": "vault",
                    "description": ["Digitally sign OpenCore to prevent tampering or corruption."],
                },
                "FireWire Booting": {
                    "type": "checkbox",
                    "value": self.constants.firewire_boot,
                    "variable": "firewire_boot",
                    "description": ["Enable booting macOS from FireWire drives."],
                    "condition": not (generate_smbios.check_firewire(target_model) is False),
                },
                "XHCI Booting": {
                    "type": "checkbox",
                    "value": self.constants.xhci_boot,
                    "variable": "xhci_boot",
                    "description": ["Enable booting from add-in USB 3.0 expansion cards on older systems."],
                    "condition": not gui_support.CheckProperties(self.constants).host_has_cpu_gen(cpu_data.CPUGen.ivy_bridge),
                },
                "NVMe Booting": {
                    "type": "checkbox",
                    "value": self.constants.nvme_boot,
                    "variable": "nvme_boot",
                    "description": ["Enable booting from NVMe drives on systems without native firmware support."],
                    "condition": not gui_support.CheckProperties(self.constants).host_has_cpu_gen(cpu_data.CPUGen.ivy_bridge),
                },
                "Debug": {"type": "title"},
                "Verbose": {
                    "type": "checkbox",
                    "value": self.constants.verbose_debug,
                    "variable": "verbose_debug",
                    "description": ["Enable verbose kernel output during boot (-v)."],
                },
                "Kext Debugging": {
                    "type": "checkbox",
                    "value": self.constants.kext_debug,
                    "variable": "kext_debug",
                    "description": ["Use DEBUG kext variants and enable additional kernel logging."],
                },
                "OpenCore Debugging": {
                    "type": "checkbox",
                    "value": self.constants.opencore_debug,
                    "variable": "opencore_debug",
                    "description": ["Use DEBUG OpenCore binary and enable additional OpenCore logging."],
                },
            },
            "Hardware & SMBIOS": {
                "Model Spoofing": {"type": "title"},
                "SMBIOS Spoof Level": {
                    "type": "choice",
                    "choices": ["None", "Minimal", "Moderate", "Advanced"],
                    "value": self.constants.serial_settings,
                    "variable": "serial_settings",
                    "description": ["None: no spoofing; Minimal: Board ID; Moderate: Model; Advanced: Model + serial."],
                },
                "SMBIOS Spoof Model": {
                    "type": "choice",
                    "choices": models + ["Default"],
                    "value": self.constants.override_smbios,
                    "variable": "override_smbios",
                    "description": ["Set Mac model to spoof to."],
                },
                "Allow spoofing native Macs": {
                    "type": "checkbox",
                    "value": self.constants.allow_native_spoofs,
                    "variable": "allow_native_spoofs",
                    "description": ["Allow OpenCore to spoof natively supported Macs (e.g. Universal Control)."],
                },
                "Serial Spoofing": {"type": "title"},
                "Populate Serial Spoofing": {"type": "custom", "builder": self._build_serial_spoofing},
                "Hardware & Storage": {"type": "title"},
                "NVRAM WriteFlash": {
                    "type": "checkbox",
                    "value": self.constants.nvram_write,
                    "variable": "nvram_write",
                    "description": ["Allow OpenCore to write to hardware NVRAM."],
                },
                "Allow AppleALC Audio": {
                    "type": "checkbox",
                    "value": self.constants.set_alc_usage,
                    "variable": "set_alc_usage",
                    "description": ["Allow AppleALC to manage audio when applicable."],
                },
                "3rd Party NVMe PM": {
                    "type": "checkbox",
                    "value": self.constants.allow_nvme_fixing,
                    "variable": "allow_nvme_fixing",
                    "description": ["Enable non-stock NVMe power management in macOS."],
                },
                "3rd Party SATA PM": {
                    "type": "checkbox",
                    "value": self.constants.allow_3rd_party_drives,
                    "variable": "allow_3rd_party_drives",
                    "description": ["Enable non-stock SATA power management in macOS."],
                    "condition": not bool(self.constants.computer.third_party_sata_ssd is False and not self.constants.custom_model),
                },
                "APFS Trim": {
                    "type": "checkbox",
                    "value": self.constants.apfs_trim_timeout,
                    "variable": "apfs_trim_timeout",
                    "description": ["Recommended for most SSDs; disable if experiencing faulty SSD timeouts."],
                },
                "Wake on WLAN": {
                    "type": "checkbox",
                    "value": self.constants.enable_wake_on_wlan,
                    "variable": "enable_wake_on_wlan",
                    "description": ["Only applies to BCM943224, 331, 360 and 3602 chipsets."],
                },
                "Disable Thunderbolt": {
                    "type": "checkbox",
                    "value": self.constants.disable_tb,
                    "variable": "disable_tb",
                    "description": ["Workaround for MacBookPro11,x with faulty PCHs."],
                    "condition": target_model in ["MacBookPro11,1", "MacBookPro11,2", "MacBookPro11,3"],
                },
                "Windows GMUX": {
                    "type": "checkbox",
                    "value": self.constants.dGPU_switch,
                    "variable": "dGPU_switch",
                    "description": ["Expose iGPU in Windows on dual-GPU MacBooks."],
                },
                "Disable CPUFriend": {
                    "type": "checkbox",
                    "value": self.constants.disallow_cpufriend,
                    "variable": "disallow_cpufriend",
                    "description": ["Disable CPU power management helper for unsupported models."],
                },
                "TeraScale 2 Acceleration": {
                    "type": "checkbox",
                    "value": self._read_prop("MacBookPro_TeraScale_2_Accel", self.constants.allow_ts2_accel),
                    "variable": "MacBookPro_TeraScale_2_Accel",
                    "constants_variable": "allow_ts2_accel",
                    "description": ["Enable AMD TeraScale 2 GPU acceleration on MacBookPro8,2 / 8,3."],
                    "override_function": self._update_global_settings,
                    "condition": self.constants.computer.real_model in ["MacBookPro8,2", "MacBookPro8,3"],
                },
            },
            "Security": {
                "Kernel Security": {"type": "title"},
                "Disable Library Validation": {
                    "type": "checkbox",
                    "value": self.constants.disable_cs_lv,
                    "variable": "disable_cs_lv",
                    "description": ["Required for loading modified system files from root patching."],
                },
                "Disable AMFI": {
                    "type": "checkbox",
                    "value": self.constants.disable_amfi,
                    "variable": "disable_amfi",
                    "description": ["Extended bypass required for systems with deeper root patches."],
                },
                "Secure Boot Model": {
                    "type": "checkbox",
                    "value": self.constants.secure_status,
                    "variable": "secure_status",
                    "description": ["Set Apple Secure Boot Model Identifier (incompatible with Root Patching)."],
                },
                "System Integrity Protection": {"type": "title"},
                "Populate SIP": {"type": "custom", "builder": self._build_sip_controls},
            },
            "Advanced": {
                "Miscellaneous": {"type": "title"},
                "FeatureUnlock": {
                    "type": "choice",
                    "choices": ["Enabled", "Partial", "Disabled"],
                    "value": self._fu_value_label(),
                    "variable": "",
                    "description": ["Configure FeatureUnlock level (lower if experiencing memory instability)."],
                    "override_function": self.fu_selection_click,
                },
                "Hibernation Work-around": {
                    "type": "checkbox",
                    "value": self.constants.disable_connectdrivers,
                    "variable": "disable_connectdrivers",
                    "description": ["Load minimum EFI drivers to avoid sleep/hibernation issues (may affect external boot)."],
                },
                "Disable Firmware Throttling": {
                    "type": "checkbox",
                    "value": self.constants.disable_fw_throttle,
                    "variable": "disable_fw_throttle",
                    "description": ["Disable firmware throttling caused by missing battery/display sensors."],
                },
                "Software DeMUX": {
                    "type": "checkbox",
                    "value": self.constants.software_demux,
                    "variable": "software_demux",
                    "description": ["Software-based DeMUX for MacBookPro8,2 / 8,3 (requires gpu-power-prefs NVRAM arg)."],
                    "warning": (
                        "This setting requires 'gpu-power-prefs' NVRAM argument set to '1'.\n\n"
                        "Without it, the system will fail to boot.\n\n"
                        "nvram FA4CE28D-B62F-4C99-9CC3-6815686E30F9:gpu-power-prefs=%01%00%00%00"
                    ),
                    "condition": target_model in ["MacBookPro8,2", "MacBookPro8,3"],
                },
                "Disable mediaanalysisd service": {
                    "type": "checkbox",
                    "value": self.constants.disable_mediaanalysisd,
                    "variable": "disable_mediaanalysisd",
                    "description": ["Improves prolonged idle stability on 3802-GPU iCloud Photo hosts."],
                    "condition": gui_support.CheckProperties(self.constants).host_has_3802_gpu(),
                },
                "Graphics": {"type": "title"},
                "AMD GOP Injection": {
                    "type": "checkbox",
                    "value": self.constants.amd_gop_injection,
                    "variable": "amd_gop_injection",
                    "description": ["Inject AMD GOP for boot screen support on PC GPUs."],
                    "condition": target_model in socketed_gpu_models,
                },
                "Nvidia GOP Injection": {
                    "type": "checkbox",
                    "value": self.constants.nvidia_kepler_gop_injection,
                    "variable": "nvidia_kepler_gop_injection",
                    "description": ["Inject Nvidia Kepler GOP for boot screen support on PC GPUs."],
                    "condition": target_model in socketed_gpu_models,
                },
                "Graphics Override": {
                    "type": "choice",
                    "choices": ["None", "Nvidia Kepler", "AMD GCN", "AMD Polaris", "AMD Lexa", "AMD Navi"],
                    "value": f"{self.constants.imac_vendor} {self.constants.imac_model}".strip() if self.constants.imac_vendor != "None" else "None",
                    "variable": "",
                    "description": ["Override detected/assumed GPU on socketed MXM iMacs."],
                    "override_function": self.gpu_selection_click,
                    "condition": target_model in socketed_imac_models,
                },
            },
            "Developer": {
                "Validation": {"type": "title"},
                "Install latest nightly build": {
                    "type": "button",
                    "function": self.on_nightly,
                    "description": ["Download and install a branch build (check CHANGELOG first)."],
                },
                "Trigger Exception": {
                    "type": "button",
                    "function": self.on_test_exception,
                    "description": [],
                },
                "Export constants": {
                    "type": "button",
                    "function": self.on_export_constants,
                    "description": ["Export constants.py values to a text file."],
                },
                "Developer Root Volume Patching": {"type": "title"},
                "Mount Root Volume": {
                    "type": "button",
                    "function": self.on_mount_root_vol,
                    "description": ["Mount APFS root snapshot read/write for manual inspection."],
                },
                "Save Root Volume": {
                    "type": "button",
                    "function": self.on_bless_root_vol,
                    "description": ["Rebuild kernel cache and bless APFS root snapshot."],
                },
            },
        }

    def _build_sip_controls(self, page: wx.Window, col: wx.BoxSizer) -> None:
        link_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl = wx.StaticText(page, label="Flip individual bits matching")
        lbl.SetFont(gui_support.font_factory(12, wx.FONTWEIGHT_NORMAL))
        link_row.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)

        csr_link = wx.adv.HyperlinkCtrl(
            page,
            wx.ID_ANY,
            label="XNU's csr.h",
            url="https://github.com/apple-oss-distributions/xnu/blob/xnu-8020.101.4/bsd/sys/csr.h",
        )
        csr_link.SetFont(gui_support.font_factory(12, wx.FONTWEIGHT_NORMAL))
        csr_link.SetHoverColour(self.hyperlink_colour)
        csr_link.SetNormalColour(self.hyperlink_colour)
        csr_link.SetVisitedColour(self.hyperlink_colour)
        link_row.Add(csr_link, 0, wx.ALIGN_CENTER_VERTICAL)
        col.Add(link_row, 0, wx.BOTTOM, 6)

        if self.constants.custom_sip_value is not None:
            self.sip_value = int(self.constants.custom_sip_value, 16)
        elif self.constants.sip_status is True:
            self.sip_value = 0x00
        else:
            self.sip_value = 0x803

        self.sip_configured_label = wx.StaticText(page, label=f"Currently configured SIP: {hex(self.sip_value)}")
        self.sip_configured_label.SetFont(gui_support.font_factory(12, wx.FONTWEIGHT_BOLD))
        col.Add(self.sip_configured_label, 0, wx.BOTTOM, 2)

        booted_sip = wx.StaticText(page, label=f"Currently booted SIP: {hex(py_sip_xnu.SipXnu().get_sip_status().value)}")
        booted_sip.SetFont(gui_support.font_factory(12, wx.FONTWEIGHT_NORMAL))
        col.Add(booted_sip, 0, wx.BOTTOM, 8)

        grid = wx.GridSizer(cols=2, vgap=4, hgap=16)
        for sip_bit, meta in sip_data.system_integrity_protection.csr_values_extended.items():
            cb = wx.CheckBox(page, label=meta["name"].split("CSR_")[1])
            cb.SetFont(gui_support.font_factory(12, wx.FONTWEIGHT_NORMAL))
            cb.SetToolTip(f"Description: {meta['description']}\nValue: {hex(meta['value'])}\nIntroduced in: macOS {meta['introduced_friendly']}")
            cb.SetValue((self.sip_value & meta["value"]) == meta["value"])
            cb.Bind(wx.EVT_CHECKBOX, self.on_sip_value)
            grid.Add(cb, 0, wx.EXPAND)
        col.Add(grid, 0, wx.EXPAND | wx.BOTTOM, 6)

    def _build_serial_spoofing(self, page: wx.Window, col: wx.BoxSizer) -> None:
        row = wx.FlexGridSizer(cols=2, vgap=4, hgap=12)
        row.AddGrowableCol(0, 1)
        row.AddGrowableCol(1, 1)

        sn_lbl = wx.StaticText(page, label="Custom Serial Number")
        sn_lbl.SetFont(gui_support.font_factory(12, wx.FONTWEIGHT_BOLD))
        mlb_lbl = wx.StaticText(page, label="Custom Board Serial Number")
        mlb_lbl.SetFont(gui_support.font_factory(12, wx.FONTWEIGHT_BOLD))
        row.Add(sn_lbl)
        row.Add(mlb_lbl)

        self.custom_serial_number_textbox = wx.TextCtrl(page, value=self.constants.custom_serial_number, size=(195, -1))
        self.custom_serial_number_textbox.SetFont(gui_support.font_factory(12, wx.FONTWEIGHT_NORMAL))
        self.custom_serial_number_textbox.SetToolTip('Used when SMBIOS Spoof Level includes serial spoofing.')
        self.custom_serial_number_textbox.Bind(wx.EVT_TEXT, self.on_custom_serial_number_textbox)

        self.custom_board_serial_number_textbox = wx.TextCtrl(page, value=self.constants.custom_board_serial_number, size=(195, -1))
        self.custom_board_serial_number_textbox.SetFont(gui_support.font_factory(12, wx.FONTWEIGHT_NORMAL))
        self.custom_board_serial_number_textbox.SetToolTip('Used when SMBIOS Spoof Level includes board serial spoofing.')
        self.custom_board_serial_number_textbox.Bind(wx.EVT_TEXT, self.on_custom_board_serial_number_textbox)

        row.Add(self.custom_serial_number_textbox, 0, wx.EXPAND)
        row.Add(self.custom_board_serial_number_textbox, 0, wx.EXPAND)
        col.Add(row, 0, wx.EXPAND | wx.BOTTOM, 8)

        gen_btn = wx.Button(page, label=f"Generate S/N: {self.constants.custom_model or self.constants.computer.real_model}", size=(210, 28))
        gen_btn.SetFont(gui_support.font_factory(12, wx.FONTWEIGHT_NORMAL))
        gen_btn.Bind(wx.EVT_BUTTON, self.on_generate_serial_number)
        col.Add(gen_btn, 0, wx.BOTTOM, 6)

    def _build_app_stats(self, page: wx.Window, col: wx.BoxSizer) -> None:
        lines = (
            f"Application Information:\n"
            f"    Application Version: {self.constants.patcher_version}\n"
            f"    PatcherSupportPkg Version: {self.constants.patcher_support_pkg_version}\n"
            f"    Application Path: {self.constants.launcher_binary}\n"
            f"    Application Mount: {self.constants.payload_path}\n\n"
            f"Commit Information:\n"
            f"    Branch: {self.constants.commit_info[0]}\n"
            f"    Date: {self.constants.commit_info[1]}\n"
            f"    URL: {self.constants.commit_info[2] or 'N/A'}\n\n"
            f"Booted Information:\n"
            f"    Booted OS: XNU {self.constants.detected_os} ({self.constants.detected_os_version})\n"
            f"    Booted Patcher Version: {self.constants.computer.oclp_version}\n"
            f"    Booted OpenCore Version: {self.constants.computer.opencore_version}\n"
            f"    Booted OpenCore Disk: {self.constants.booted_oc_disk}\n\n"
            f"Hardware Information:\n    {pprint.pformat(self.constants.computer, indent=4)}\n"
        )
        self.app_stats = wx.TextCtrl(page, value=lines, size=(-1, 190), style=wx.TE_READONLY | wx.TE_MULTILINE | wx.TE_RICH2)
        self.app_stats.SetFont(gui_support.font_factory(12, wx.FONTWEIGHT_NORMAL))
        col.Add(self.app_stats, 0, wx.EXPAND | wx.BOTTOM, 8)

    def on_model_choice(self, event: wx.Event) -> None:
        selection = self.model_choice.GetStringSelection()
        if selection == "Host Model":
            selection = self.constants.computer.real_model
            self.constants.custom_model = None
            logging.info(f"Using Real Model: {self.constants.computer.real_model}")
            defaults.GenerateDefaults(self.constants.computer.real_model, True, self.constants)
        else:
            logging.info(f"Using Custom Model: {selection}")
            self.constants.custom_model = selection
            defaults.GenerateDefaults(self.constants.custom_model, False, self.constants)

        self.oc_settings_changed = True
        can_build = gui_support.CheckProperties(self.constants).host_can_build()
        self.rebuild_button.Enable(can_build)
        if hasattr(self.app, "refresh_menu"):
            self.app.refresh_menu()

        active_cat = self.categories[self.sidebar.GetSelection()] if self.sidebar.GetSelection() != wx.NOT_FOUND else None
        self._reload_categories(preserve_category=active_cat)

    def _on_checkbox(self, event: wx.Event, category: str, label: str) -> None:
        cb = event.GetEventObject()
        value = cb.GetValue()
        entry = self.settings[category][label]
        warning_pop = entry.get("warning", "")

        if warning_pop and value is True:
            warning = wx.MessageDialog(self.app, warning_pop, f"Warning: {label}", wx.YES_NO | wx.ICON_WARNING | wx.NO_DEFAULT)
            if warning.ShowModal() == wx.ID_NO:
                cb.SetValue(not value)
                return
            if label == "Allow native models" and self.constants.computer.real_model in smbios_data.smbios_dictionary:
                max_os = smbios_data.smbios_dictionary[self.constants.computer.real_model]["Max OS Supported"]
                if self.constants.detected_os > max_os:
                    chassis = "plastic" if self.constants.computer.real_model in ["MacBook4,1", "MacBook5,2", "MacBook6,1", "MacBook7,1"] else "aluminum"
                    dlg = wx.MessageDialog(
                        self.app,
                        f"This model ({self.constants.computer.real_model}) does not natively support {os_data.os_conversion.convert_kernel_to_marketing_name(self.constants.detected_os)}. "
                        f"Last native OS: {os_data.os_conversion.convert_kernel_to_marketing_name(max_os)}.\n\n"
                        f"Toggling this option will break booting. You may end up with a {chassis} brick.",
                        "Are you certain?",
                        wx.YES_NO | wx.ICON_WARNING | wx.NO_DEFAULT,
                    )
                    if dlg.ShowModal() == wx.ID_NO:
                        cb.SetValue(not value)
                        return

        if "override_function" in entry:
            if entry["variable"] not in self._APP_ONLY_SETTINGS:
                self.oc_settings_changed = True
            entry["override_function"](entry["variable"], value, entry.get("constants_variable"))
            return

        self._update_setting(entry["variable"], value)
        self.oc_settings_changed = True
        if label == "Allow native models":
            can_build = gui_support.CheckProperties(self.constants).host_can_build()
            self.rebuild_button.Enable(can_build)
            if hasattr(self.app, "refresh_menu"):
                self.app.refresh_menu()

    def _on_spinctrl(self, event: wx.Event, category: str, label: str) -> None:
        self._update_setting(self.settings[category][label]["variable"], event.GetEventObject().GetValue())
        self.oc_settings_changed = True

    def _on_choice(self, event: wx.Event, category: str, label: str) -> None:
        self._update_setting(self.settings[category][label]["variable"], event.GetString())
        self.oc_settings_changed = True

    def _update_setting(self, variable: str, value) -> None:
        logging.info(f"Updating Local Setting: {variable} = {value}")
        setattr(self.constants, variable, value)
        global_settings.GlobalEnviromentSettings().write_property(f"GUI:{variable}", "PYTHON_NONE_VALUE" if value is None else value)

    def _update_global_settings(self, variable: str, value, global_setting: str = None) -> None:
        logging.info(f"Updating Global Setting: {variable} = {value}")
        global_settings.GlobalEnviromentSettings().write_property(variable, "PYTHON_NONE_VALUE" if value is None else value)
        if global_setting is not None:
            self._update_setting(global_setting, value)

    def on_sip_value(self, event: wx.Event) -> None:
        meta = sip_data.system_integrity_protection.csr_values_extended[f"CSR_{event.GetEventObject().GetLabel()}"]
        self.sip_value = self.sip_value + meta["value"] if event.GetEventObject().GetValue() else self.sip_value - meta["value"]

        if hex(self.sip_value) == "0x0":
            self.constants.custom_sip_value = None
            self.constants.sip_status = True
            global_settings.GlobalEnviromentSettings().write_property("GUI:custom_sip_value", "PYTHON_NONE_VALUE")
            global_settings.GlobalEnviromentSettings().write_property("GUI:sip_status", True)
        elif hex(self.sip_value) == "0x803":
            self.constants.custom_sip_value = None
            self.constants.sip_status = False
            global_settings.GlobalEnviromentSettings().write_property("GUI:custom_sip_value", "PYTHON_NONE_VALUE")
            global_settings.GlobalEnviromentSettings().write_property("GUI:sip_status", False)
        else:
            self.constants.custom_sip_value = hex(self.sip_value)
            global_settings.GlobalEnviromentSettings().write_property("GUI:custom_sip_value", hex(self.sip_value))

        self.oc_settings_changed = True
        self.sip_configured_label.SetLabel(f"Currently configured SIP: {hex(self.sip_value)}")

    def on_generate_serial_number(self, event: wx.Event) -> None:
        dlg = wx.MessageDialog(
            self.app,
            "Take caution when using serial spoofing. Misuse can break power management.\n\nAre you certain you want to continue?",
            "Warning",
            wx.YES_NO | wx.ICON_WARNING | wx.NO_DEFAULT,
        )
        if dlg.ShowModal() != wx.ID_YES:
            return

        output = subprocess.run(
            [self.constants.macserial_path, "--generate", "--model", self.constants.custom_model or self.constants.computer.real_model, "--num", "1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        ).stdout.decode().strip().split(" | ")
        if len(output) == 2:
            self.custom_serial_number_textbox.SetValue(output[0])
            self.custom_board_serial_number_textbox.SetValue(output[1])
            self.oc_settings_changed = True
        else:
            wx.MessageBox(f"Failed to generate serial number:\n\n{output}", "Error", wx.OK | wx.ICON_ERROR)

    def on_custom_serial_number_textbox(self, event: wx.Event) -> None:
        self.constants.custom_serial_number = event.GetEventObject().GetValue()
        global_settings.GlobalEnviromentSettings().write_property("GUI:custom_serial_number", self.constants.custom_serial_number)
        self.oc_settings_changed = True

    def on_custom_board_serial_number_textbox(self, event: wx.Event) -> None:
        self.constants.custom_board_serial_number = event.GetEventObject().GetValue()
        global_settings.GlobalEnviromentSettings().write_property("GUI:custom_board_serial_number", self.constants.custom_board_serial_number)
        self.oc_settings_changed = True

    def fu_selection_click(self, event: wx.Event) -> None:
        self.oc_settings_changed = True
        value = event.GetEventObject().GetStringSelection()
        if value == "Enabled":
            self.constants.fu_status, self.constants.fu_arguments = True, None
        elif value == "Partial":
            self.constants.fu_status, self.constants.fu_arguments = True, " -disable_sidecar_mac"
        else:
            self.constants.fu_status, self.constants.fu_arguments = False, None

        global_settings.GlobalEnviromentSettings().write_property("GUI:fu_status", self.constants.fu_status)
        global_settings.GlobalEnviromentSettings().write_property(
            "GUI:fu_arguments", "PYTHON_NONE_VALUE" if self.constants.fu_arguments is None else self.constants.fu_arguments
        )

    def gpu_selection_click(self, event: wx.Event) -> None:
        self.oc_settings_changed = True
        gpu_choice = event.GetEventObject().GetStringSelection()
        logging.info(f"Updating GPU Selection: {gpu_choice}")
        if "AMD" in gpu_choice:
            self.constants.imac_vendor = "AMD"
            self.constants.metal_build = True
            self.constants.imac_model = gpu_choice.split("AMD ")[1]
            global_settings.GlobalEnviromentSettings().write_property("GUI:imac_model", self.constants.imac_model)
        elif "Nvidia" in gpu_choice:
            self.constants.imac_vendor = "Nvidia"
            self.constants.metal_build = True
            self.constants.imac_model = gpu_choice.split("Nvidia ")[1]
            global_settings.GlobalEnviromentSettings().write_property("GUI:imac_model", self.constants.imac_model)
        else:
            self.constants.imac_vendor = "None"
            self.constants.metal_build = False
        global_settings.GlobalEnviromentSettings().write_property("GUI:imac_vendor", self.constants.imac_vendor)
        global_settings.GlobalEnviromentSettings().write_property("GUI:metal_build", self.constants.metal_build)

    def on_reset_settings(self, event: wx.Event = None) -> None:
        dlg = wx.MessageDialog(
            self.app,
            gui_strings.SETTINGS["reset_confirm_msg"],
            gui_strings.SETTINGS["reset_confirm_title"],
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        )
        if dlg.ShowModal() != wx.ID_YES:
            return

        if not global_settings.GlobalEnviromentSettings().reset_settings(preserve_keys=["FirstLaunchWelcomeShown"]):
            wx.MessageDialog(self.app, gui_strings.SETTINGS["reset_error_msg"], "Error", wx.OK | wx.ICON_ERROR).ShowModal()
            return

        logging.info("Resetting settings to hardware defaults")
        fresh = constants.Constants()
        for attr in self._RESETTABLE_CONSTANTS:
            setattr(self.constants, attr, getattr(fresh, attr))

        defaults.GenerateDefaults(self.constants.computer.real_model, True, self.constants, ignore_settings_file=True)

        self.oc_settings_changed = True
        self.model_choice.SetSelection(self.model_choice.FindString("Host Model"))
        self.rebuild_button.Enable(gui_support.CheckProperties(self.constants).host_can_build())
        if hasattr(self.app, "refresh_menu"):
            self.app.refresh_menu()

        active_cat = self.categories[self.sidebar.GetSelection()] if self.sidebar.GetSelection() != wx.NOT_FOUND else None
        self._reload_categories(preserve_category=active_cat)

    def on_rebuild_opencore(self, event: wx.Event = None) -> None:
        if gui_support.CheckProperties(self.constants).host_can_build():
            self.app.navigate("build")

    def on_return(self, event: wx.Event = None) -> None:
        if self.oc_settings_changed and gui_support.CheckProperties(self.constants).host_can_build():
            dlg = wx.MessageDialog(
                self.app,
                gui_strings.SETTINGS["rebuild_prompt_msg"],
                gui_strings.SETTINGS["rebuild_prompt_title"],
                wx.YES_NO | wx.ICON_QUESTION,
            )
            if dlg.ShowModal() == wx.ID_YES:
                self.on_rebuild_opencore()
                return
        self.app.go_home()

    def on_nightly(self, event: wx.Event) -> None:
        branches = ["main"]
        if self.constants.commit_info[0] not in ["Running from source", "Built from source"]:
            branches = [self.constants.commit_info[0].split("/")[-1]]
        result = network_handler.NetworkUtilities().get("https://api.github.com/repos/dortania/OpenCore-Legacy-Patcher/branches")
        branch = branches[0]
        if result.status_code == 200:
            for item in result.json():
                if item["name"] != "gh-pages" and item["name"] not in branches:
                    branches.append(item["name"])
            with wx.SingleChoiceDialog(self.app, "Which branch would you like to download?", "Branch Selection", branches) as dialog:
                if dialog.ShowModal() == wx.ID_CANCEL:
                    return
                branch = dialog.GetStringSelection()

        self.app.navigate(
            "update",
            url=f"https://nightly.link/dortania/OpenCore-Legacy-Patcher/workflows/build-app-wxpython/{branch}/OpenCore-Patcher.pkg.zip",
            version_label="(Nightly)",
        )

    def on_export_constants(self, event: wx.Event) -> None:
        with wx.FileDialog(
            self.app,
            "Save Constants File",
            wildcard="Text files (*.txt)|*.txt",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            defaultFile=f"constants-{self.constants.patcher_version}.txt",
        ) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            pathname = fileDialog.GetPath()
            logging.info(f"Saving constants to {pathname}")
            with open(pathname, "w") as f:
                f.write(pprint.pformat(vars(self.constants), indent=4))

    def on_test_exception(self, event: wx.Event) -> None:
        raise Exception("Test Exception")

    def on_mount_root_vol(self, event: wx.Event) -> None:
        if sys_patch.PatchSysVolume("", self.constants)._mount_root_vol() is True:
            wx.MessageDialog(self.app, "Root Volume Mounted, remember to fix permissions before saving the Root Volume", "Success", wx.OK | wx.ICON_INFORMATION).ShowModal()
        else:
            wx.MessageDialog(self.app, "Root Volume Mount Failed, check terminal output", "Error", wx.OK | wx.ICON_ERROR).ShowModal()

    def on_bless_root_vol(self, event: wx.Event) -> None:
        if sys_patch.PatchSysVolume("", self.constants)._rebuild_root_volume() is True:
            wx.MessageDialog(self.app, "Root Volume saved, please reboot to apply changes", "Success", wx.OK | wx.ICON_INFORMATION).ShowModal()
        else:
            wx.MessageDialog(self.app, "Root Volume update Failed, check terminal output", "Error", wx.OK | wx.ICON_ERROR).ShowModal()