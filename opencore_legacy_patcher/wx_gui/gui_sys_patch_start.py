"""
gui_sys_patch_start.py: In-window Root Patching execution view
"""

import wx
import sys
import time
import logging
import traceback
import threading
import subprocess

from .. import constants
from ..datasets import os_data
from ..support import kdk_handler, metallib_handler
from ..sys_patch import sys_patch
from ..sys_patch.patchsets import HardwarePatchsetDetection, HardwarePatchsetSettings
from ..wx_gui import gui_support, gui_strings


class SysPatchStartPanel(wx.Panel):
    """
    Downloads KDK/Metallib if needed and applies or reverts root patches in-window
    """

    def __init__(
        self,
        parent: wx.Window,
        app,
        global_constants: constants.Constants,
        patches: dict = None,
        action: str = "patch",
    ) -> None:
        super().__init__(parent)
        logging.info("Initializing Root Patching Panel")
        self.app = app
        self.constants = global_constants
        self.patches = patches or {}
        self.action = action
        self.active_step: wx.Panel = None

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.sizer)

        if not self.patches:
            self.patches = HardwarePatchsetDetection(constants=self.constants).device_properties

    def _set_step(self, panel: wx.Panel) -> None:
        if self.active_step is not None:
            self.sizer.Detach(self.active_step)
            self.active_step.Destroy()
        self.active_step = panel
        self.sizer.Add(panel, 1, wx.EXPAND)
        self.Layout()

    def start(self) -> None:
        if self.action == "revert":
            self.revert_root_patching()
        else:
            self.start_root_patching()

    def _kdk_download(self) -> bool:
        logging.info("KDK missing, preparing KDK download")
        prog = gui_support.IndeterminateProgressPanel(
            self,
            self.constants,
            "Downloading Kernel Debug Kit",
            message="Fetching KDK database...",
        )
        self._set_step(prog)

        self.kdk_obj: kdk_handler.KernelDebugKitObject = None

        def _fetch():
            self.kdk_obj = kdk_handler.KernelDebugKitObject(
                self.constants,
                self.constants.detected_os_build,
                self.constants.detected_os_version,
            )

        thread = threading.Thread(target=_fetch)
        thread.start()
        gui_support.wait_for_thread(thread)

        if self.kdk_obj.success is False:
            wx.MessageBox(f"KDK download failed: {self.kdk_obj.error_msg}", "Error", wx.OK | wx.ICON_ERROR)
            return False

        kdk_download_obj = self.kdk_obj.retrieve_download()
        if not kdk_download_obj:
            return True

        if not self.app.show_download(kdk_download_obj, f"KDK Build {self.kdk_obj.kdk_url_build}"):
            return False

        val_panel = gui_support.IndeterminateProgressPanel(
            self,
            self.constants,
            f"Validating KDK: {self.kdk_obj.kdk_url_build}",
            message="Checking KDK disk image integrity...",
        )
        self._set_step(val_panel)
        wx.Yield()

        if self.kdk_obj.validate_kdk_checksum() is False:
            logging.error(f"KDK checksum validation failed: {self.kdk_obj.error_msg}")
            wx.MessageDialog(self.app, f"KDK checksum validation failed: {self.kdk_obj.error_msg}", "Error", wx.OK | wx.ICON_ERROR).ShowModal()
            return False

        logging.info("KDK download complete")
        return True

    def _metallib_download(self) -> bool:
        logging.info("MetallibSupportPkg missing, preparing Metallib download")
        prog = gui_support.IndeterminateProgressPanel(
            self,
            self.constants,
            "Downloading Metal Libraries",
            message="Fetching MetallibSupportPkg database...",
        )
        self._set_step(prog)

        self.metallib_obj: metallib_handler.MetalLibraryObject = None

        def _fetch():
            self.metallib_obj = metallib_handler.MetalLibraryObject(
                self.constants,
                self.constants.detected_os_build,
                self.constants.detected_os_version,
            )

        thread = threading.Thread(target=_fetch)
        thread.start()
        gui_support.wait_for_thread(thread)

        if self.metallib_obj.success is False:
            wx.MessageBox(f"Metallib download failed: {self.metallib_obj.error_msg}", "Error", wx.OK | wx.ICON_ERROR)
            return False

        dl_obj = self.metallib_obj.retrieve_download()
        if not dl_obj:
            return True

        if not self.app.show_download(dl_obj, f"Metallib Build {self.metallib_obj.metallib_url_build}"):
            return False

        inst_panel = gui_support.IndeterminateProgressPanel(
            self,
            self.constants,
            f"Installing Metallib: {self.metallib_obj.metallib_url_build}",
            message="Installing MetallibSupportPkg PKG...",
        )
        self._set_step(inst_panel)

        self.metallib_result = False

        def _install():
            self.metallib_result = self.metallib_obj.install_metallib()

        thread = threading.Thread(target=_install)
        thread.start()
        gui_support.wait_for_thread(thread)

        if self.metallib_result is False:
            wx.MessageBox(f"Metallib installation failed: {self.metallib_obj.error_msg}", "Error", wx.OK | wx.ICON_ERROR)
            return False

        logging.info("Metallib installation complete")
        return True

    def start_root_patching(self) -> None:
        logging.info("Starting root patching")
        self.app.set_busy(True, "root patching")
        try:
            while gui_support.PayloadMount(self.constants, self.app).is_unpack_finished() is False:
                wx.Yield()
                time.sleep(self.constants.thread_sleep_interval)

            if self.patches.get(HardwarePatchsetSettings.KERNEL_DEBUG_KIT_REQUIRED) is True:
                if self._kdk_download() is False:
                    self.app.go_home()
                    return

            if self.patches.get(HardwarePatchsetSettings.METALLIB_SUPPORT_PKG_REQUIRED) is True:
                if self._metallib_download() is False:
                    self.app.go_home()
                    return

            summary = [
                f"• {p}" for p in self.patches
                if not p.startswith("Settings") and not p.startswith("Validation") and self.patches[p] is True
            ]
            if summary:
                summary.insert(0, gui_strings.SYS_PATCH["will_patch"])

            log_panel = gui_support.LogOutputPanel(
                self,
                title=gui_strings.SYS_PATCH["patching_title"],
                summary_lines=summary,
                on_back=self.app.go_home,
            )
            self._set_step(log_panel)

            def _worker():
                with gui_support.capture_logs(log_panel.text_box):
                    try:
                        sys_patch.PatchSysVolume(self.constants.computer.real_model, self.constants, self.patches).start_patch()
                    except Exception:
                        logging.error("An internal error occurred while running the Root Patcher:\n")
                        logging.error(traceback.format_exc())

            thread = threading.Thread(target=_worker)
            thread.start()
            gui_support.wait_for_thread(thread)
        finally:
            self.app.set_busy(False)

        log_panel.finish()
        self._post_patch()

    def revert_root_patching(self) -> None:
        logging.info("Reverting root patches")
        log_panel = gui_support.LogOutputPanel(
            self,
            title=gui_strings.SYS_PATCH["reverting_title"],
            summary_lines=[gui_strings.SYS_PATCH["reverting_desc"]],
            on_back=self.app.go_home,
        )
        self._set_step(log_panel)

        self.app.set_busy(True, "reverting root patches")
        try:
            def _worker():
                with gui_support.capture_logs(log_panel.text_box):
                    try:
                        sys_patch.PatchSysVolume(self.constants.computer.real_model, self.constants, self.patches).start_unpatch()
                    except Exception:
                        logging.error("An internal error occurred while running the Root Patcher:\n")
                        logging.error(traceback.format_exc())

            thread = threading.Thread(target=_worker)
            thread.start()
            gui_support.wait_for_thread(thread)
        finally:
            self.app.set_busy(False)

        log_panel.finish()
        self._post_patch()

    def _post_patch(self) -> None:
        if self.constants.root_patcher_succeeded is False:
            return

        if self.constants.needs_to_open_preferences is False:
            gui_support.RestartHost(self.app).restart(message="Root Patcher finished successfully!\n\nWould you like to reboot now?")
            return

        if self.constants.detected_os >= os_data.os_data.ventura:
            gui_support.RestartHost(self.app).restart(
                message="Root Patcher finished successfully!\nIf prompted to open System Settings to authorize new kexts, that can be ignored. Your system is ready once restarted.\n\nWould you like to reboot now?"
            )
            return

        dlg = wx.MessageDialog(
            self.app,
            "Root volume patches were installed.\n\nmacOS requires approving the new kernel extensions in System Preferences before rebooting.\n\nOpen System Preferences now?",
            "Open System Preferences?",
            wx.YES_NO | wx.ICON_INFORMATION,
        )
        dlg.SetYesNoLabels("Open System Preferences", "Ignore")
        if dlg.ShowModal() == wx.ID_YES:
            output = subprocess.run(
                [
                    "/usr/bin/osascript", "-e",
                    'tell app "System Preferences" to activate',
                    "-e", 'tell app "System Preferences" to reveal anchor "General" of pane id "com.apple.preference.security"',
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if output.returncode != 0:
                subprocess.run(["/usr/bin/open", "-a", "System Preferences"])
            time.sleep(5)
            sys.exit(0)