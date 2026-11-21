"""
gui_about.py: About frame
"""

import wx
import logging

from .. import constants

from ..wx_gui import gui_support, gui_strings


class AboutFrame(wx.Frame):

    def __init__(self, global_constants: constants.Constants) -> None:
        if wx.FindWindowByName(gui_strings.ABOUT["title"]):
            return

        logging.info("Generating About frame")
        super(AboutFrame, self).__init__(
            None,
            title=gui_strings.ABOUT["title"],
            name=gui_strings.ABOUT["title"],
            size=(360, 340),
            style=wx.DEFAULT_FRAME_STYLE & ~(wx.RESIZE_BORDER | wx.MAXIMIZE_BOX),
        )
        self.constants: constants.Constants = global_constants
        self._generate_elements()
        self.Centre()
        self.Show()

    def _generate_elements(self) -> None:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.AddSpacer(16)

        icon_bmp = wx.Bitmap(str(self.constants.app_icon_path), wx.BITMAP_TYPE_ICON)
        icon_img = icon_bmp.ConvertToImage().Rescale(72, 72, wx.IMAGE_QUALITY_HIGH)
        icon = wx.StaticBitmap(panel, bitmap=wx.Bitmap(icon_img))
        sizer.Add(icon, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 10)

        title = wx.StaticText(panel, label=gui_strings.APP_NAME)
        title.SetFont(gui_support.font_factory(18, wx.FONTWEIGHT_BOLD))
        sizer.Add(title, 0, wx.ALIGN_CENTER_HORIZONTAL)

        version = wx.StaticText(panel, label=f"Version {self.constants.patcher_version}")
        version.SetFont(gui_support.font_factory(12, wx.FONTWEIGHT_NORMAL))
        version.SetForegroundColour(wx.Colour(128, 128, 128))
        sizer.Add(version, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.TOP | wx.BOTTOM, 6)

        desc = wx.StaticText(panel, label=gui_strings.ABOUT["tagline"], style=wx.ALIGN_CENTER_HORIZONTAL)
        desc.SetFont(gui_support.font_factory(12, wx.FONTWEIGHT_NORMAL))
        sizer.Add(desc, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.ALL, 12)

        copy_label = wx.StaticText(panel, label=self.constants.copyright_date)
        copy_label.SetFont(gui_support.font_factory(10, wx.FONTWEIGHT_NORMAL))
        copy_label.SetForegroundColour(wx.Colour(128, 128, 128))
        sizer.Add(copy_label, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 16)

        panel.SetSizerAndFit(sizer)
        self.Fit()
