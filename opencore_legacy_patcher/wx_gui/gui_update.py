"""
gui_update.py: In-window UI for updating OpenCore Legacy Patcher
"""

import wx
import sys
import time
import logging
import threading
import subprocess

from pathlib import Path

from .. import constants
from ..wx_gui import gui_support
from ..support import network_handler, updates, subprocess_wrapper


class UpdatePanel(wx.Panel):
    """
    In-window updater panel using DownloadPanel + IndeterminateProgressPanel
    """

    def __init__(self, parent: wx.Window, app, global_constants: constants.Constants, url: str = "", version_label: str = "") -> None:
        super().__init__(parent)
        logging.info("Initializing Update Panel")
        self.app = app
        self.constants = global_constants
        self.pkg_download_path = self.constants.payload_path / "OpenCore-Patcher.pkg"
        self.url = url
        self.version_label = version_label
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
        if self.url == "" or self.version_label == "":
            info = updates.CheckBinaryUpdates(self.constants).check_binary_updates()
            if info:
                self.version_label = info["Version"]
                self.url = info["Link"]
            else:
                wx.MessageBox("Failed to retrieve update information.", "Critical Error", wx.OK | wx.ICON_ERROR)
                sys.exit(1)

        logging.info(f"Update URL: {self.url} ({self.version_label})")

        self.app.set_busy(True, "updating application")
        try:
            prog = gui_support.IndeterminateProgressPanel(
                self,
                self.constants,
                "Updating OpenCore Legacy Patcher",
                message="Preparing download...",
            )
            self._set_step(prog)

            file_name = "OpenCore-Patcher.pkg.zip" if self.url.endswith(".zip") else "OpenCore-Patcher.pkg"
            download_obj = network_handler.DownloadObject(self.url, self.constants.payload_path / file_name)

            if not self.app.show_download(
                download_obj,
                f"OpenCore Patcher {self.version_label}",
                download_icon=str(self.constants.app_icon_path),
            ):
                wx.MessageBox(
                    "Failed to download update. Please manually download OpenCore Legacy Patcher from GitHub.",
                    "Critical Error!",
                    wx.OK | wx.ICON_ERROR,
                )
                sys.exit(1)

            prog = gui_support.IndeterminateProgressPanel(
                self,
                self.constants,
                f"Updating to {self.version_label}",
                message="Extracting update...",
            )
            self._set_step(prog)
            wx.Yield()

            if not self._run_bg(self._extract_update):
                sys.exit(1)

            prog.set_message("Installing update...")
            if not self._run_bg(self._install_update):
                sys.exit(1)

            prog.stop()
            self._show_complete()
        finally:
            self.app.set_busy(False)

    def _run_bg(self, fn) -> bool:
        ok = True

        def _wrap():
            nonlocal ok
            ok = fn()

        thread = threading.Thread(target=_wrap)
        thread.start()
        gui_support.wait_for_thread(thread)
        return ok

    def _extract_update(self) -> bool:
        if not self.url.endswith(".zip"):
            return True

        logging.info("Extracting nightly update")
        if Path(self.pkg_download_path).exists():
            subprocess.run(["/bin/rm", "-rf", str(self.pkg_download_path)])

        result = subprocess.run(
            ["/usr/bin/ditto", "-xk", str(self.constants.payload_path / "OpenCore-Patcher.pkg.zip"), str(self.constants.payload_path)],
            capture_output=True,
        )
        if result.returncode != 0:
            logging.error("Failed to extract update.")
            subprocess_wrapper.log(result)
            wx.CallAfter(wx.MessageBox, f"Failed to extract update. Error: {result.stderr.decode('utf-8')}", "Critical Error!", wx.OK | wx.ICON_ERROR)
            return False
        return True

    def _install_update(self) -> bool:
        logging.info(f"Installing update: {self.pkg_download_path}")
        result = subprocess_wrapper.run_as_root(["/usr/sbin/installer", "-pkg", str(self.pkg_download_path), "-target", "/"], capture_output=True)
        if result.returncode != 0:
            if "User cancelled" in result.stderr.decode("utf-8"):
                logging.info("User cancelled update")
                wx.CallAfter(wx.MessageBox, "User cancelled update", "Update Cancelled", wx.OK | wx.ICON_INFORMATION)
            else:
                logging.critical("Failed to install update.")
                subprocess_wrapper.log(result)
                subprocess.run(["/usr/bin/open", str(self.pkg_download_path)])
                wx.CallAfter(wx.MessageBox, "Failed to install update. Please install OpenCore-Patcher.pkg manually or download from GitHub.", "Critical Error!", wx.OK | wx.ICON_ERROR)
            return False
        return True

    def _show_complete(self) -> None:
        done = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(gui_support.PageHeader(done, "Update Complete!"), 0, wx.EXPAND)
        outer.AddStretchSpacer(1)

        lbl = wx.StaticText(done, label=f"{self.version_label} installed to:\n/Library/Application Support/Dortania", style=wx.ALIGN_CENTER_HORIZONTAL)
        lbl.SetFont(gui_support.font_factory(14, wx.FONTWEIGHT_BOLD))
        outer.Add(lbl, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 14)

        launch_lbl = wx.StaticText(done, label="Launching update shortly...", style=wx.ALIGN_CENTER_HORIZONTAL)
        launch_lbl.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        outer.Add(launch_lbl, 0, wx.ALIGN_CENTER_HORIZONTAL)
        outer.AddStretchSpacer(2)

        done.SetSizer(outer)
        self._set_step(done)

        thread = threading.Thread(target=self._launch_update)
        thread.start()
        gui_support.wait_for_thread(thread)

        for timer in range(5, 0, -1):
            launch_lbl.SetLabel(f"Closing old process in {timer} seconds")
            done.Layout()
            wx.Yield()
            time.sleep(1)

        sys.exit(0)

    def _launch_update(self) -> None:
        logging.info("Launching update: '/Library/Application Support/Dortania/OpenCore-Patcher.app'")
        subprocess.Popen(["/Library/Application Support/Dortania/OpenCore-Patcher.app/Contents/MacOS/OpenCore-Patcher", "--update_installed"])
