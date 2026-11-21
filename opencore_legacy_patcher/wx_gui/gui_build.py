"""
gui_build.py: In-window UI for Building OpenCore
"""

import wx
import time
import logging
import threading
import traceback

from .. import constants
from ..efi_builder import build
from ..wx_gui import gui_support, gui_strings


class BuildPanel(wx.Panel):
    """
    Renders OpenCore build logs and post-build actions inside the main window
    """

    def __init__(self, parent: wx.Window, app, global_constants: constants.Constants) -> None:
        super().__init__(parent)
        logging.info("Initializing Build Panel")
        self.app = app
        self.constants = global_constants
        self.build_successful = False

        model = self.constants.custom_model or self.constants.computer.real_model
        self.log_panel = gui_support.LogOutputPanel(
            self,
            title=gui_strings.BUILD["title"],
            subtitle=f"Model: {model}",
            primary_label=gui_strings.BUILD["install_button"],
            on_primary=lambda: self.app.navigate("install_oc"),
            on_back=self.app.go_home,
        )

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.log_panel, 1, wx.EXPAND)
        self.SetSizer(sizer)

        if self.constants.update_stage != gui_support.AutoUpdateStages.INACTIVE:
            self.constants.update_stage = gui_support.AutoUpdateStages.BUILDING

    def start(self) -> None:
        self.app.set_busy(True, "building OpenCore")
        try:
            while gui_support.PayloadMount(self.constants, self.app).is_unpack_finished() is False:
                wx.Yield()
                time.sleep(self.constants.thread_sleep_interval)

            thread = threading.Thread(target=self._build)
            thread.start()
            gui_support.wait_for_thread(thread)
        finally:
            self.app.set_busy(False)

        self.log_panel.finish(enable_primary=self.build_successful)

        if self.build_successful is False:
            wx.MessageDialog(
                self.app,
                gui_strings.BUILD["error_msg"],
                gui_strings.BUILD["error_title"],
                wx.OK | wx.ICON_ERROR,
            ).ShowModal()
            return

        dlg = wx.MessageDialog(
            self.app,
            gui_strings.BUILD["done_msg"],
            gui_strings.BUILD["done_title"],
            wx.YES_NO | wx.ICON_QUESTION,
        )
        dlg.SetYesNoLabels(gui_strings.BUILD["install_now"], gui_strings.BUILD["view_log"])
        if dlg.ShowModal() == wx.ID_YES:
            self.app.navigate("install_oc")

    def _build(self) -> None:
        with gui_support.capture_logs(self.log_panel.text_box):
            try:
                build.BuildOpenCore(self.constants.custom_model or self.constants.computer.real_model, self.constants)
                self.build_successful = True
            except Exception:
                logging.error("An internal error occurred while building:\n")
                logging.error(traceback.format_exc())
                if "TypeError: unsupported type: <class 'NoneType'>" in traceback.format_exc():
                    logging.error("If you continue to see this error, reset settings or delete:")
                    logging.error("Path: /Users/Shared/.com.dortania.opencore-legacy-patcher.plist")
