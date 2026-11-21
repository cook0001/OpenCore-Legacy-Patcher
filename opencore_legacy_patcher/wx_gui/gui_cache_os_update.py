"""
gui_cache_os_update.py: UI for caching KDK/Metallib resources prior to macOS Software Update
"""

import wx
import sys
import time
import logging
import threading

from pathlib import Path

from .. import constants
from ..support import kdk_handler, utilities, metallib_handler
from ..wx_gui import gui_support
from ..sys_patch.patchsets import HardwarePatchsetDetection, HardwarePatchsetSettings


class OSCachePanel(wx.Panel):
    """
    In-window panel for caching KDK and Metallib packages when a staged OS update needs them
    """

    def __init__(self, parent: wx.Window, app, global_constants: constants.Constants) -> None:
        super().__init__(parent)
        logging.info("Initializing Prepare Update Panel")
        self.app = app
        self.constants = global_constants
        self.os_data = utilities.fetch_staged_update(variant="Preflight")
        self.did_cancel = -1
        self.download_obj = None

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(gui_support.PageHeader(self, "Preparing for macOS Software Update"), 0, wx.EXPAND)
        sizer.AddStretchSpacer(1)

        os_str = f"macOS {self.os_data[0]} ({self.os_data[1]})" if self.os_data[0] else ""
        self.info_label = wx.StaticText(self, label=f"{os_str}\nChecking required support packages...", style=wx.ALIGN_CENTER_HORIZONTAL)
        self.info_label.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        sizer.Add(self.info_label, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 14)

        self.progress_bar = wx.Gauge(self, range=100, size=(360, 22))
        self.progress_bar.Pulse()
        sizer.Add(self.progress_bar, 0, wx.ALIGN_CENTER_HORIZONTAL)
        sizer.AddStretchSpacer(2)
        self.SetSizer(sizer)

    @staticmethod
    def needs_caching(global_constants: constants.Constants) -> bool:
        staged = utilities.fetch_staged_update(variant="Preflight")
        if staged[0] is None:
            logging.info("No staged update found")
            return False
        results = HardwarePatchsetDetection(
            constants=global_constants,
            xnu_major=int(staged[1][:2]),
            xnu_minor=0,
            os_build=staged[1],
            os_version=staged[0],
        ).device_properties
        return any([
            results[HardwarePatchsetSettings.KERNEL_DEBUG_KIT_REQUIRED],
            results[HardwarePatchsetSettings.METALLIB_SUPPORT_PKG_REQUIRED],
        ])

    def start(self) -> None:
        if self.os_data[0] is None:
            sys.exit(0)

        results = HardwarePatchsetDetection(
            constants=self.constants,
            xnu_major=int(self.os_data[1][:2]),
            xnu_minor=0,
            os_build=self.os_data[1],
            os_version=self.os_data[0],
        ).device_properties

        if not any([results[HardwarePatchsetSettings.KERNEL_DEBUG_KIT_REQUIRED], results[HardwarePatchsetSettings.METALLIB_SUPPORT_PKG_REQUIRED]]):
            logging.info("No additional resources required")
            sys.exit(0)

        self.kdk_obj = None
        self.metallib_obj = None

        if results[HardwarePatchsetSettings.KERNEL_DEBUG_KIT_REQUIRED] is True:
            t = threading.Thread(target=lambda: setattr(self, "kdk_obj", kdk_handler.KernelDebugKitObject(self.constants, self.os_data[1], self.os_data[0], passive=True, check_backups_only=True)))
            t.start()
            gui_support.wait_for_thread(t)

        if results[HardwarePatchsetSettings.METALLIB_SUPPORT_PKG_REQUIRED] is True:
            t = threading.Thread(target=lambda: setattr(self, "metallib_obj", metallib_handler.MetalLibraryObject(self.constants, self.os_data[1], self.os_data[0])))
            t.start()
            gui_support.wait_for_thread(t)

        download_objects = {}
        if self.kdk_obj and self.kdk_obj.success is True:
            res = self.kdk_obj.retrieve_download()
            if res is not None:
                download_objects[f"KDK Build {self.kdk_obj.kdk_url_build}"] = res
        if self.metallib_obj and self.metallib_obj.success is True:
            res = self.metallib_obj.retrieve_download()
            if res is not None:
                download_objects[f"Metallib Build {self.metallib_obj.metallib_url_build}"] = res

        if not download_objects:
            sys.exit(0)

        self.did_cancel = -1
        threading.Thread(target=self._notify_user_thread, daemon=True).start()

        for _ in range(10):
            if self.did_cancel == 1:
                sys.exit(0)
            if self.did_cancel == -1:
                wx.Yield()
                time.sleep(1)

        for name, dl_obj in download_objects.items():
            self.download_obj = dl_obj
            if self.app.show_download(dl_obj, name):
                if name.startswith("KDK"):
                    self._handle_kdk(self.kdk_obj)
                elif name.startswith("Metallib"):
                    self._handle_metallib(self.metallib_obj)

        sys.exit(0)

    def _notify_user_thread(self) -> None:
        msg = (
            f"OpenCore Legacy Patcher detected a staged macOS update:\n{self.os_data[0]} ({self.os_data[1]})\n\n"
            "The patcher needs to download support resources required post-update.\n\n"
            "This may take a few minutes; the patcher will exit when done."
        )
        dlg = wx.MessageDialog(self.app, message=msg, caption="OpenCore Legacy Patcher", style=wx.YES_NO | wx.ICON_INFORMATION)
        dlg.SetYesNoLabels("&Ok", "&Cancel")
        if dlg.ShowModal() == wx.ID_NO:
            logging.info("User cancelled OS caching")
            if self.download_obj:
                self.download_obj.stop()
            self.did_cancel = 1
        else:
            self.did_cancel = 0

    def _handle_kdk(self, kdk_obj: kdk_handler.KernelDebugKitObject) -> None:
        self.kdk_checksum_result = False
        t = threading.Thread(target=lambda: setattr(self, "kdk_checksum_result", kdk_obj.validate_kdk_checksum()))
        t.start()
        gui_support.wait_for_thread(t)
        if not self.kdk_checksum_result or not Path(self.constants.kdk_download_path).exists():
            return

        t = threading.Thread(target=lambda: kdk_handler.KernelDebugKitUtilities().install_kdk_dmg(self.constants.kdk_download_path, only_install_backup=True))
        t.start()
        gui_support.wait_for_thread(t)

    def _handle_metallib(self, metallib_obj: metallib_handler.MetalLibraryObject) -> None:
        t = threading.Thread(target=metallib_obj.install_metallib)
        t.start()
        gui_support.wait_for_thread(t)
