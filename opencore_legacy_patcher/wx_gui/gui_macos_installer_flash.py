"""
gui_macos_installer_flash.py: In-window macOS Installer Flash Panel
"""

import wx
import logging
import plistlib
import tempfile
import threading
import subprocess

from pathlib import Path

from .. import constants
from ..datasets import os_data
from ..volume import generate_copy_arguments
from ..wx_gui import gui_support, gui_strings
from ..support import (
    macos_installer_handler,
    utilities,
    network_handler,
    kdk_handler,
    metallib_handler,
    subprocess_wrapper,
)


class macOSInstallerFlashPanel(wx.Panel):
    """
    In-window multi-step installer selector, USB disk picker, and sequential flash/asset pipeline
    """

    def __init__(self, parent: wx.Window, app, global_constants: constants.Constants) -> None:
        super().__init__(parent)
        logging.info("Initializing macOS Installer Flash Panel")
        self.app = app
        self.constants = global_constants

        self.available_installers_local: dict = {}
        self.available_disks: dict = {}
        self.prepare_result: bool = False
        self.result: bool = False
        self.flash_error = None
        self.active_step: wx.Panel = None

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.sizer)

    def _set_step(self, panel: wx.Panel) -> None:
        if self.active_step is not None:
            self.sizer.Detach(self.active_step)
            self.active_step.Destroy()
        self.active_step = panel
        self.sizer.Add(panel, 1, wx.EXPAND)
        self.Layout()

    def start(self) -> None:
        self._scan_installers()

    def _scan_installers(self) -> None:
        self._set_step(
            gui_support.IndeterminateProgressPanel(
                self,
                self.constants,
                gui_strings.INSTALLER["fetching_local"],
                message=gui_strings.INSTALLER["fetching_local"],
                back_label=gui_strings.NAV["back"],
                on_back=lambda: self.app.navigate("installer_choice"),
            )
        )

        def _fetch():
            self.available_installers_local = macos_installer_handler.LocalInstallerCatalog().available_apps or {}

        thread = threading.Thread(target=_fetch)
        thread.start()
        gui_support.wait_for_thread(thread)
        self._show_installer_list()

    def _show_installer_list(self) -> None:
        step = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(
            gui_support.PageHeader(
                step,
                gui_strings.INSTALLER["select_local"],
                back_label=gui_strings.NAV["back"],
                on_back=lambda: self.app.navigate("installer_choice"),
            ),
            0,
            wx.EXPAND,
        )

        scroll = wx.ScrolledWindow(step, style=wx.VSCROLL)
        scroll.SetScrollRate(0, 16)
        list_sizer = wx.BoxSizer(wx.VERTICAL)

        if self.available_installers_local:
            logging.info("Installer(s) found:")
            entries = len(self.available_installers_local)
            for app_key, info in self.available_installers_local.items():
                logging.info(f"- {info['Short Name']}: {info['Version']} ({info['Build']})")
                unsupported = info["Minimum Host OS"] > self.constants.detected_os
                if unsupported:
                    min_str = os_data.os_conversion.convert_kernel_to_marketing_name(info["Minimum Host OS"])
                    app_str = f"{info['Short Name']} (Requires {min_str})"
                else:
                    app_str = f"{info['Short Name']}: {info['Version']} ({info['Build']})"

                btn = wx.Button(scroll, label=app_str, size=(420, 32))
                btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
                btn.Bind(wx.EVT_BUTTON, lambda event, inst=info: self.on_select(inst))
                if unsupported:
                    btn.Disable()
                elif entries == 1:
                    btn.SetDefault()
                list_sizer.Add(btn, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 8)
        else:
            empty = wx.StaticText(scroll, label=gui_strings.INSTALLER["no_local"])
            empty.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
            list_sizer.Add(empty, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.TOP, 20)

        scroll.SetSizer(list_sizer)
        scroll.FitInside()
        outer.Add(scroll, 1, wx.EXPAND | wx.ALL, 16)

        ret_btn = wx.Button(step, label=gui_strings.NAV["return_main"], size=(170, 30))
        ret_btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        ret_btn.Bind(wx.EVT_BUTTON, lambda event: self.app.go_home())
        outer.Add(ret_btn, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 16)

        step.SetSizer(outer)
        self._set_step(step)

    def on_select(self, installer: dict) -> None:
        logging.info(f"Selected installer: {installer['Short Name']} ({installer['Version']} ({installer['Build']}))")
        self._set_step(
            gui_support.IndeterminateProgressPanel(
                self,
                self.constants,
                gui_strings.INSTALLER["fetching_usb"],
                message=gui_strings.INSTALLER["fetching_usb"],
                back_label=gui_strings.NAV["back"],
                on_back=self._show_installer_list,
            )
        )

        def _fetch_disks():
            self.available_disks = macos_installer_handler.InstallerCreation().list_disk_to_format() or {}
            ignore = ("disk image", "read-only", "virtual")
            for disk in list(self.available_disks.keys()):
                if any(token in self.available_disks[disk]["name"].lower() for token in ignore):
                    del self.available_disks[disk]

        thread = threading.Thread(target=_fetch_disks)
        thread.start()
        gui_support.wait_for_thread(thread)
        self._show_disk_list(installer)

    def _show_disk_list(self, installer: dict) -> None:
        step = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(
            gui_support.PageHeader(
                step,
                gui_strings.INSTALLER["select_usb"],
                subtitle=f"Installer: {installer['Short Name']} ({installer['Version']})",
                back_label=gui_strings.NAV["back"],
                on_back=self._show_installer_list,
            ),
            0,
            wx.EXPAND,
        )

        scroll = wx.ScrolledWindow(step, style=wx.VSCROLL)
        scroll.SetScrollRate(0, 16)
        list_sizer = wx.BoxSizer(wx.VERTICAL)

        if self.available_disks:
            logging.info("Available disks:")
            entries = len(self.available_disks)
            for disk_key, dinfo in self.available_disks.items():
                logging.info(f" - {disk_key}: {dinfo['name']} - {utilities.human_fmt(dinfo['size'])}")
                btn = wx.Button(scroll, label=f"{disk_key}: {dinfo['name']} - {utilities.human_fmt(dinfo['size'])}", size=(460, 32))
                btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
                btn.Bind(wx.EVT_BUTTON, lambda event, d=dinfo: self.on_select_disk(d, installer))
                if entries == 1:
                    btn.SetDefault()
                list_sizer.Add(btn, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 8)
        else:
            empty = wx.StaticText(scroll, label=gui_strings.INSTALLER["no_usb"])
            empty.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_BOLD))
            list_sizer.Add(empty, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.TOP, 20)

        scroll.SetSizer(list_sizer)
        scroll.FitInside()
        outer.Add(scroll, 1, wx.EXPAND | wx.ALL, 16)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        rescan_btn = wx.Button(step, label=gui_strings.INSTALLER["rescan_usb"], size=(150, 30))
        rescan_btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        rescan_btn.Bind(wx.EVT_BUTTON, lambda event: self.on_select(installer))
        btn_row.Add(rescan_btn, 0, wx.RIGHT, 10)

        ret_btn = wx.Button(step, label=gui_strings.NAV["return_main"], size=(170, 30))
        ret_btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        ret_btn.Bind(wx.EVT_BUTTON, lambda event: self.app.go_home())
        btn_row.Add(ret_btn, 0)

        outer.Add(btn_row, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 16)
        step.SetSizer(outer)
        self._set_step(step)

    @staticmethod
    def _read_disk_mb(root_disk: str, fallback: float = 0.0) -> float:
        try:
            return float(utilities.monitor_disk_output(root_disk))
        except Exception:
            return fallback

    def on_select_disk(self, disk: dict, installer: dict) -> None:
        answer = wx.MessageBox(
            f"Are you sure you want to erase '{disk['name']}'?\nAll data will be lost, this cannot be undone.",
            "Confirmation",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        if answer != wx.YES:
            return

        logging.info(f"Selected disk: {disk['name']}")

        step = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)
        header = gui_support.PageHeader(step, f"Creating Installer: {installer['Short Name']}")
        outer.Add(header, 0, wx.EXPAND)
        outer.AddStretchSpacer(1)

        note1 = wx.StaticText(step, label="Creating macOS installers can take 30min+ on slower USB drives.", style=wx.ALIGN_CENTER_HORIZONTAL)
        note1.SetFont(gui_support.font_factory(12, wx.FONTWEIGHT_NORMAL))
        note1.SetForegroundColour(wx.Colour(128, 128, 128))
        outer.Add(note1, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 18)

        stage_label = wx.StaticText(step, label="Step 1 of 3: Flashing macOS Installer...", size=(540, -1), style=wx.ALIGN_CENTER_HORIZONTAL | wx.ST_NO_AUTORESIZE)
        stage_label.SetFont(gui_support.font_factory(14, wx.FONTWEIGHT_BOLD))
        outer.Add(stage_label, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 8)

        counter_label = wx.StaticText(step, label="Installer Written: 0.00 MB", size=(540, -1), style=wx.ALIGN_CENTER_HORIZONTAL | wx.ST_NO_AUTORESIZE)
        counter_label.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        outer.Add(counter_label, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 12)

        progress_bar = wx.Gauge(step, range=100, size=(380, 24))
        outer.Add(progress_bar, 0, wx.ALIGN_CENTER_HORIZONTAL)
        outer.AddStretchSpacer(2)

        step.SetSizer(outer)
        self._set_step(step)

        self.app.set_busy(True, "creating macOS installer")
        utilities.disable_sleep_while_running()
        try:
            if self._prepare_resources(installer["Path"], disk["identifier"]) is False:
                logging.error("Failed to prepare resources, cannot continue.")
                wx.MessageBox("Failed to prepare resources, cannot continue.", "Error", wx.OK | wx.ICON_ERROR)
                self.app.go_home()
                return

            progress_bar_animation = None

            # Step 1: Flash macOS installer only (separate from AutoPkg/KDK/Metallib bytes)
            estimated_installer_size = 16000
            progress_bar.SetRange(estimated_installer_size)

            root_disk = disk["identifier"][5:]
            initial_bytes_written = self._read_disk_mb(root_disk)
            self.result = False
            self.flash_error = None

            def _flash():
                logging.info(f"Flashing {installer['Path']} to {root_disk}")
                self.result = self._flash_installer()

            thread = threading.Thread(target=_flash)
            thread.start()

            while thread.is_alive():
                bytes_written = max(0.0, self._read_disk_mb(root_disk, initial_bytes_written) - initial_bytes_written)
                counter_label.SetLabel(f"Installer Written: {bytes_written:.2f} MB")
                progress_bar.SetValue(min(int(bytes_written), estimated_installer_size))

                wx.Yield()
                thread.join(timeout=self.constants.thread_sleep_interval)

            if self.result is False:
                logging.error("Failed to flash installer, cannot continue.")
                if self.flash_error:
                    output, error = self.flash_error
                    wx.MessageDialog(self.app, f"Failed to create macOS installer\n\nOutput: {output}\n\nError: {error}", "Error", wx.OK | wx.ICON_ERROR).ShowModal()
                self.app.go_home()
                return

            # Step 2: Download and copy AutoPkg-Assets / Metallib / KDK with separate progress & counters
            asset_state = {
                "stage": "Preparing Autopatching Assets...",
                "detail": "",
                "download": None,
                "copy_label": None,
                "copy_base_mb": 0.0,
                "failed": [],
            }

            asset_thread = threading.Thread(target=self._install_installer_pkg, args=(disk["identifier"], root_disk, asset_state))
            asset_thread.start()

            pulsing = False
            last_stage = ""
            last_detail = ""

            def _set_pulse(enable: bool) -> None:
                nonlocal pulsing, progress_bar_animation
                if enable and not pulsing:
                    progress_bar.SetRange(100)
                    progress_bar_animation = gui_support.GaugePulseCallback(self.constants, progress_bar)
                    progress_bar_animation.start_pulse()
                    pulsing = True
                elif not enable and pulsing:
                    progress_bar_animation.stop_pulse()
                    progress_bar.SetRange(100)
                    pulsing = False

            while asset_thread.is_alive():
                if asset_state["stage"] != last_stage:
                    last_stage = asset_state["stage"]
                    stage_label.SetLabel(f"Step 2 of 3: {last_stage}")

                dl = asset_state["download"]
                if dl is not None and dl.total_file_size > 0:
                    _set_pulse(False)
                    pct = min(int(dl.downloaded_file_size / dl.total_file_size * 100), 100)
                    text = f"{asset_state['detail']}: {utilities.human_fmt(dl.downloaded_file_size)} / {utilities.human_fmt(dl.total_file_size)} ({pct}%)"
                    progress_bar.SetValue(pct)
                elif dl is not None:
                    _set_pulse(True)
                    text = f"{asset_state['detail']}: {utilities.human_fmt(dl.downloaded_file_size)}"
                elif asset_state["copy_label"]:
                    _set_pulse(True)
                    asset_mb = max(0.0, self._read_disk_mb(root_disk, asset_state["copy_base_mb"]) - asset_state["copy_base_mb"])
                    text = f"{asset_state['copy_label']}: {asset_mb:.2f} MB written"
                else:
                    _set_pulse(True)
                    text = asset_state["detail"] or "Preparing..."

                if text != last_detail:
                    last_detail = text
                    counter_label.SetLabel(text)

                wx.Yield()
                asset_thread.join(timeout=self.constants.thread_sleep_interval)

            _set_pulse(False)

            # Step 3: Validate the installer
            stage_label.SetLabel("Step 3 of 3: Validating Installer Integrity...")
            counter_label.SetLabel("Verifying SharedSupport.dmg...")
            progress_bar.SetRange(100)
            progress_bar_animation = gui_support.GaugePulseCallback(self.constants, progress_bar)
            progress_bar_animation.start_pulse()

            error_message = self._validate_installer_pkg(disk["identifier"])
            progress_bar_animation.stop_pulse()

            if error_message != "":
                progress_bar.SetValue(0)
                wx.MessageBox(
                    f"Failed to validate installer, cannot continue.\nThis can generally happen due to a faulty USB drive.\n\n{error_message}",
                    "Corrupted Installer!",
                    wx.OK | wx.ICON_ERROR,
                )
                self.app.go_home()
                return

            progress_bar.SetValue(100)

            if asset_state["failed"]:
                summary = "\n".join(f"- {name}: {reason}" for name, reason in asset_state["failed"])
                wx.MessageBox(
                    "The macOS installer was created, however the following autopatching / support asset(s) could not be installed onto the USB drive:\n\n"
                    f"{summary}\n\n"
                    "Autopatching after macOS installation may not work without an active internet connection or manual package installation.",
                    "Autopatching Assets Incomplete",
                    wx.OK | wx.ICON_WARNING,
                )
        finally:
            self.app.set_busy(False)
            utilities.enable_sleep_after_running()

        if gui_support.CheckProperties(self.constants).host_can_build() is False:
            wx.MessageBox(
                "Installer created successfully! To install OpenCore to this USB, change Target Model in Settings.",
                "Successfully created the macOS installer!",
                wx.OK | wx.ICON_INFORMATION,
            )
            self.app.go_home()
            return

        answer = wx.MessageBox(
            "Installer created successfully! Would you like to continue and build/install OpenCore to this disk?",
            "Successfully created the macOS installer!",
            wx.YES_NO | wx.ICON_QUESTION,
        )
        if answer == wx.YES:
            self.app.navigate("build")
        else:
            self.app.go_home()

    def _prepare_resources(self, installer_path: str, disk: str) -> bool:
        def _prep():
            self.prepare_result = macos_installer_handler.InstallerCreation().generate_installer_creation_script(
                self.constants.payload_path, installer_path, disk
            )

        thread = threading.Thread(target=_prep)
        thread.start()
        gui_support.wait_for_thread(thread)
        return self.prepare_result

    def _flash_installer(self) -> bool:
        logging.info("Creating macOS installer")
        with open(self.constants.installer_sh_path, "r") as f:
            logging.info(f"installer.sh contents:\n{f.read()}")

        result = subprocess_wrapper.run_as_root(["/bin/sh", self.constants.installer_sh_path], capture_output=True, text=True)
        output = result.stdout
        error = result.stderr if result.stderr else ""

        if "Install media now available at" not in output:
            logging.info("Failed to create macOS installer")
            self.flash_error = (output, error)
            return False

        logging.info("Successfully created macOS installer")
        return True

    def _auto_package_handler(self, download_dir: Path, root_disk: str, asset_state: dict) -> None:
        asset_state.update(stage="Installing AutoPkg-Assets.pkg...", detail="Checking download link", download=None, copy_label=None)

        link = self.constants.installer_pkg_url
        if network_handler.NetworkUtilities(link).validate_link() is False:
            logging.info("Stock Install.pkg is missing on Github, falling back to Nightly")
            link = self.constants.installer_pkg_url_nightly
            if network_handler.NetworkUtilities(link).validate_link() is False:
                reason = "Release and nightly asset URLs are unreachable"
                logging.warning(f"Failed to retrieve AutoPkg-Assets.pkg: {reason}")
                asset_state["failed"].append(("AutoPkg-Assets.pkg", reason))
                return

        path = self.constants.installer_pkg_zip_path if link.endswith(".zip") else self.constants.installer_pkg_path

        autopkg_download = network_handler.DownloadObject(link, path)
        asset_state["detail"] = "Downloading AutoPkg-Assets.pkg"
        asset_state["download"] = autopkg_download
        autopkg_download.download(spawn_thread=False)
        utilities.disable_sleep_while_running()
        asset_state["download"] = None

        if autopkg_download.download_complete is False:
            reason = autopkg_download.error_msg or "Download failed"
            logging.warning(f"Failed to download AutoPkg-Assets.pkg: {reason}")
            asset_state["failed"].append(("AutoPkg-Assets.pkg", reason))
            return

        if str(path).endswith(".zip"):
            asset_state["detail"] = "Extracting AutoPkg-Assets.pkg..."
            if Path(self.constants.installer_pkg_path).exists():
                subprocess.run(["/bin/rm", self.constants.installer_pkg_path])
            unzip = subprocess.run(["/usr/bin/ditto", "-V", "-x", "-k", "--sequesterRsrc", "--rsrc", self.constants.installer_pkg_zip_path, self.constants.payload_path])
            if unzip.returncode != 0 or not Path(self.constants.installer_pkg_path).exists():
                reason = "Failed to extract AutoPkg-Assets archive"
                logging.warning(reason)
                asset_state["failed"].append(("AutoPkg-Assets.pkg", reason))
                return

        if not Path(self.constants.installer_pkg_path).exists():
            asset_state["failed"].append(("AutoPkg-Assets.pkg", "Downloaded package missing"))
            return

        asset_state["detail"] = ""
        asset_state["copy_base_mb"] = self._read_disk_mb(root_disk)
        asset_state["copy_label"] = "Copying AutoPkg-Assets.pkg"
        copy_res = subprocess.run(generate_copy_arguments(self.constants.installer_pkg_path, f"{download_dir}/"))
        asset_state["copy_label"] = None
        if copy_res.returncode != 0:
            asset_state["failed"].append(("AutoPkg-Assets.pkg", "Failed to copy package onto USB installer"))

    def _install_installer_pkg(self, disk: str, root_disk: str, asset_state: dict) -> None:
        logging.info("Installing Root Patcher assets to drive")
        disk = disk + "s2"

        try:
            path = utilities.grab_mount_point_from_disk(disk)
            if not path or not Path(path + "/System/Library/CoreServices/SystemVersion.plist").exists():
                asset_state["failed"].append(("Autopatching Assets", "Could not locate mounted macOS installer volume"))
                return

            os_version = plistlib.load(Path(path + "/System/Library/CoreServices/SystemVersion.plist").open("rb"))
            kernel_version = os_data.os_conversion.os_to_kernel(os_version["ProductVersion"])
            if int(kernel_version) < os_data.os_data.big_sur:
                logging.info("Installer unsupported, requires Big Sur or newer")
                return

            packages_dir = Path(path) / "Library" / "Packages"
            subprocess.run(["/bin/mkdir", "-p", str(packages_dir)])

            self._auto_package_handler(packages_dir, root_disk, asset_state)
            if int(kernel_version) >= os_data.os_data.sequoia:
                self._chainload_metallib(os_version["ProductBuildVersion"], os_version["ProductVersion"], packages_dir, root_disk, asset_state)
            if int(kernel_version) >= os_data.os_data.ventura:
                self._kdk_chainload(os_version["ProductBuildVersion"], os_version["ProductVersion"], packages_dir, root_disk, asset_state)
        except Exception as e:
            logging.error(f"Unexpected error installing assets to drive: {e}")
            asset_state["download"] = None
            asset_state["copy_label"] = None
            asset_state["failed"].append(("Autopatching Assets", str(e)))

    def _kdk_chainload(self, build: str, version: str, download_dir: Path, root_disk: str, asset_state: dict) -> None:
        asset_state.update(stage="Installing Kernel Debug Kit...", detail="Checking KDK catalog", download=None, copy_label=None)

        kdk_dmg_path = Path(download_dir) / "KDK.dmg"
        kdk_pkg_path = Path(download_dir) / "KDK.pkg"
        kdk_dmg_path.unlink(missing_ok=True)
        kdk_pkg_path.unlink(missing_ok=True)

        logging.info(f"Initiating KDK download (Build: {build}, Version: {version})")
        kdk_obj = kdk_handler.KernelDebugKitObject(self.constants, build, version, ignore_installed=True)
        if kdk_obj.success is False:
            reason = kdk_obj.error_msg or "Unable to resolve matching KDK"
            logging.info(f"Failed to retrieve KDK: {reason}")
            asset_state["failed"].append(("Kernel Debug Kit (KDK)", reason))
            return

        space = utilities.get_free_space(download_dir)
        if space < (kdk_obj.kdk_url_expected_size * 2):
            if space < kdk_obj.kdk_url_expected_size:
                reason = "Not enough free disk space on USB installer for KDK"
                logging.info(reason)
                asset_state["failed"].append(("Kernel Debug Kit (KDK)", reason))
                return
            kdk_dmg_path = self.constants.kdk_download_path

        kdk_download_obj = kdk_obj.retrieve_download(override_path=kdk_dmg_path)
        if kdk_download_obj is None:
            reason = kdk_obj.error_msg or "Unable to create KDK download"
            logging.info(f"Failed to retrieve KDK: {reason}")
            asset_state["failed"].append(("Kernel Debug Kit (KDK)", reason))
            return

        asset_state["detail"] = "Downloading KDK.dmg"
        asset_state["download"] = kdk_download_obj
        kdk_download_obj.download(spawn_thread=False)
        utilities.disable_sleep_while_running()
        asset_state["download"] = None

        if kdk_download_obj.download_complete is False:
            reason = kdk_download_obj.error_msg or "Download failed"
            logging.info(f"Failed to download KDK: {reason}")
            asset_state["failed"].append(("Kernel Debug Kit (KDK)", reason))
            return

        if not kdk_dmg_path.exists():
            asset_state["failed"].append(("Kernel Debug Kit (KDK)", "Downloaded KDK image missing"))
            return

        with tempfile.TemporaryDirectory() as mount_point:
            asset_state["detail"] = "Mounting KDK.dmg..."
            result = subprocess.run(["/usr/bin/hdiutil", "attach", kdk_dmg_path, "-mountpoint", mount_point, "-nobrowse"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if result.returncode != 0:
                subprocess_wrapper.log(result)
                asset_state["failed"].append(("Kernel Debug Kit (KDK)", "Failed to mount KDK disk image"))
                return

            asset_state["detail"] = ""
            asset_state["copy_base_mb"] = self._read_disk_mb(root_disk)
            asset_state["copy_label"] = "Copying KernelDebugKit.pkg"
            copy_res = subprocess.run(generate_copy_arguments(f"{mount_point}/KernelDebugKit.pkg", kdk_pkg_path))
            asset_state["copy_label"] = None

            asset_state["detail"] = "Unmounting KDK.dmg..."
            result = subprocess.run(["/usr/bin/hdiutil", "detach", mount_point], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if result.returncode != 0:
                subprocess_wrapper.log(result)

            if copy_res.returncode != 0:
                asset_state["failed"].append(("Kernel Debug Kit (KDK)", "Failed to copy KernelDebugKit.pkg onto USB installer"))

        kdk_dmg_path.unlink(missing_ok=True)

    def _chainload_metallib(self, build: str, version: str, download_dir: Path, root_disk: str, asset_state: dict) -> None:
        asset_state.update(stage="Installing MetallibSupportPkg...", detail="Checking Metallib catalog", download=None, copy_label=None)

        metallib_pkg_path = Path(download_dir) / "MetallibSupportPkg.pkg"
        metallib_pkg_path.unlink(missing_ok=True)

        logging.info(f"Initiating Metallib download (Build: {build}, Version: {version})")
        metallib_obj = metallib_handler.MetalLibraryObject(self.constants, build, version, ignore_installed=True)
        if metallib_obj.success is False:
            reason = metallib_obj.error_msg or "Unable to resolve matching Metallib"
            logging.info(f"Failed to retrieve Metallib: {reason}")
            asset_state["failed"].append(("MetallibSupportPkg.pkg", reason))
            return

        metallib_download_obj = metallib_obj.retrieve_download(override_path=metallib_pkg_path)
        if metallib_download_obj is None:
            reason = metallib_obj.error_msg or "Unable to create Metallib download"
            logging.info(f"Failed to retrieve Metallib: {reason}")
            asset_state["failed"].append(("MetallibSupportPkg.pkg", reason))
            return

        if utilities.get_free_space(download_dir) < 100 * 1024 * 1024:
            reason = "Not enough disk space on USB installer to download MetallibSupportPkg"
            logging.info(reason)
            asset_state["failed"].append(("MetallibSupportPkg.pkg", reason))
            return

        asset_state["detail"] = "Downloading MetallibSupportPkg.pkg"
        asset_state["download"] = metallib_download_obj
        metallib_download_obj.download(spawn_thread=False)
        utilities.disable_sleep_while_running()
        asset_state["download"] = None

        if metallib_download_obj.download_complete is False:
            reason = metallib_download_obj.error_msg or "Download failed"
            logging.info(f"Failed to download Metallib: {reason}")
            asset_state["failed"].append(("MetallibSupportPkg.pkg", reason))
            return

        if not metallib_pkg_path.exists():
            asset_state["failed"].append(("MetallibSupportPkg.pkg", "Downloaded package missing"))

    def _validate_installer_pkg(self, disk: str) -> str:
        logging.info("Validating installer pkg")
        error_message = ""

        def _integrity_check():
            nonlocal error_message
            dmg_path = None
            for folder in Path(utilities.grab_mount_point_from_disk(disk + "s2")).glob("*.app"):
                if folder.is_dir():
                    dmg_path = folder / "Contents" / "SharedSupport" / "SharedSupport.dmg"
                    break

            if dmg_path is None or not Path(dmg_path).exists():
                logging.error(f"Failed to find {dmg_path}")
                error_message = f"Failed to find {dmg_path}"
                return
            result = subprocess.run(["/usr/bin/hdiutil", "verify", dmg_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode != 0:
                if result.stdout:
                    logging.error(result.stdout.decode("utf-8"))
                    error_message = "STDOUT: " + result.stdout.decode("utf-8")
                if result.stderr:
                    logging.error(result.stderr.decode("utf-8"))
                    error_message += "\n\nSTDERR: " + result.stderr.decode("utf-8")

        thread = threading.Thread(target=_integrity_check)
        thread.start()
        gui_support.wait_for_thread(thread)

        if error_message == "":
            logging.info("Installer pkg validated")
        return error_message