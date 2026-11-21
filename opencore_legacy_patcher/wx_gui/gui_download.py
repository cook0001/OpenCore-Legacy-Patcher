"""
gui_download.py: Reusable in-window Download Progress view
"""

import wx
import logging
import time

from .. import constants
from ..wx_gui import gui_support, gui_strings
from ..support import network_handler, utilities


class DownloadPanel(wx.Panel):
    """
    Renders file download progress inside the main window without spawning modals
    """

    def __init__(
        self,
        parent: wx.Window,
        app,
        global_constants: constants.Constants,
        download_obj: network_handler.DownloadObject,
        item_name: str,
        download_icon: str = None,
        title: str = None,
    ) -> None:
        super().__init__(parent)
        logging.info("Initializing Download Panel")
        self.constants = global_constants
        self.app = app
        self.download_obj = download_obj
        self.item_name = item_name
        self.user_cancelled = False

        icon_path = download_icon or "/System/Library/CoreServices/Installer.app/Contents/Resources/package.icns"

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.header = gui_support.PageHeader(
            self,
            title or gui_strings.DOWNLOAD["title"].format(item=item_name),
        )
        sizer.Add(self.header, 0, wx.EXPAND)
        sizer.AddStretchSpacer(1)

        bmp = wx.Bitmap(icon_path, wx.BITMAP_TYPE_ICON).ConvertToImage().Rescale(84, 84, wx.IMAGE_QUALITY_HIGH)
        sizer.Add(wx.StaticBitmap(self, bitmap=wx.Bitmap(bmp)), 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 14)

        self.progress_bar = wx.Gauge(self, range=100, size=(380, 22), style=wx.GA_SMOOTH | wx.GA_PROGRESS)
        sizer.Add(self.progress_bar, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 10)

        self.amount_label = wx.StaticText(
            self,
            label=gui_strings.DOWNLOAD["preparing"],
            size=(480, -1),
            style=wx.ALIGN_CENTER_HORIZONTAL | wx.ST_NO_AUTORESIZE,
        )
        self.amount_label.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        sizer.Add(self.amount_label, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 18)

        self.cancel_button = wx.Button(self, label=gui_strings.NAV["cancel"], size=(120, 30))
        self.cancel_button.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        self.cancel_button.Bind(wx.EVT_BUTTON, lambda event: self.terminate_download())
        sizer.Add(self.cancel_button, 0, wx.ALIGN_CENTER_HORIZONTAL)

        sizer.AddStretchSpacer(2)
        self.SetSizer(sizer)

    def run(self) -> bool:
        """
        Execute download while keeping UI responsive; returns True on completion
        """
        if self.app:
            self.app.set_busy(True, f"Downloading {self.item_name}")
        try:
            self.download_obj.download()
            last_label = ""
            while self.download_obj.is_active():
                pct = round(self.download_obj.get_percent())
                if pct == -1:
                    amount_str = (
                        f"{utilities.human_fmt(self.download_obj.downloaded_file_size)} downloaded "
                        f"({utilities.human_fmt(self.download_obj.get_speed())}/s)"
                    )
                    self.progress_bar.Pulse()
                else:
                    amount_str = (
                        f"{utilities.seconds_to_readable_time(self.download_obj.get_time_remaining())} left - "
                        f"{utilities.human_fmt(self.download_obj.downloaded_file_size)} of "
                        f"{utilities.human_fmt(self.download_obj.total_file_size)} "
                        f"({utilities.human_fmt(self.download_obj.get_speed())}/s)"
                    )
                    self.progress_bar.SetValue(max(1, min(int(pct), 100)))

                if amount_str != last_label:
                    last_label = amount_str
                    self.amount_label.SetLabel(amount_str)

                wx.Yield()
                time.sleep(self.constants.thread_sleep_interval)

            if self.download_obj.download_complete is False and self.user_cancelled is False:
                wx.MessageBox(
                    gui_strings.DOWNLOAD["failed_msg"].format(error=self.download_obj.error_msg),
                    "Error",
                    wx.OK | wx.ICON_ERROR,
                )
            return self.download_obj.download_complete is True
        finally:
            if self.app:
                self.app.set_busy(False)

    def terminate_download(self) -> None:
        if wx.MessageBox(
            gui_strings.DOWNLOAD["cancel_msg"],
            gui_strings.DOWNLOAD["cancel_title"],
            wx.YES_NO | wx.ICON_QUESTION | wx.NO_DEFAULT,
        ) == wx.YES:
            logging.info("User cancelled download")
            self.user_cancelled = True
            self.download_obj.stop()
