"""
gui_help.py: Help & Support Resources view
"""

import wx
import logging
import webbrowser

from .. import constants
from ..wx_gui import gui_support, gui_strings


class HelpPanel(wx.Panel):
    """
    In-window Help & Support resources view
    """

    def __init__(self, parent: wx.Window, app, global_constants: constants.Constants) -> None:
        super().__init__(parent)
        logging.info("Initializing Help Panel")
        self.constants = global_constants
        self.app = app

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(
            gui_support.PageHeader(
                self,
                gui_strings.HELP["title"],
                subtitle=gui_strings.HELP["subtitle"],
                back_label=gui_strings.NAV["return_main"],
                on_back=self.app.go_home,
            ),
            0,
            wx.EXPAND,
        )

        sizer.AddStretchSpacer(1)

        buttons = [
            (gui_strings.HELP["official_guide"], self.constants.guide_link),
            (gui_strings.HELP["discord"], self.constants.discord_link),
            (gui_strings.HELP["phone_support"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ]
        for label, url in buttons:
            btn = wx.Button(self, label=label, size=(240, 34))
            btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
            btn.Bind(wx.EVT_BUTTON, lambda event, target=url: webbrowser.open(target))
            sizer.Add(btn, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 12)

        sizer.AddStretchSpacer(2)
        self.SetSizer(sizer)
