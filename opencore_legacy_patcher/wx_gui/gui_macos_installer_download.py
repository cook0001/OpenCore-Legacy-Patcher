"""
gui_macos_installer_download.py: In-window UI for choosing or downloading a macOS installer
"""

import wx
import locale
import logging
import threading
import webbrowser

from .. import constants, sucatalog
from ..datasets import os_data, smbios_data, cpu_data
from ..support import macos_installer_handler, utilities, network_handler
from ..wx_gui import gui_support, gui_strings


class macOSInstallerChoicePanel(wx.Panel):
    """
    Entry step for creating a macOS installer (download vs local .app)
    """

    def __init__(self, parent: wx.Window, app, global_constants: constants.Constants) -> None:
        super().__init__(parent)
        logging.info("Initializing macOS Installer Choice Panel")
        self.app = app
        self.constants = global_constants

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(
            gui_support.PageHeader(
                self,
                gui_strings.INSTALLER["choice_title"],
                back_label=gui_strings.NAV["return_main"],
                on_back=self.app.go_home,
            ),
            0,
            wx.EXPAND,
        )
        sizer.AddStretchSpacer(1)

        dl_btn = wx.Button(self, label=gui_strings.INSTALLER["download_btn"], size=(240, 34))
        dl_btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        dl_btn.Bind(wx.EVT_BUTTON, lambda event: self.app.navigate("installer_catalog"))
        dl_btn.SetDefault()
        sizer.Add(dl_btn, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 12)

        ex_btn = wx.Button(self, label=gui_strings.INSTALLER["existing_btn"], size=(240, 34))
        ex_btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        ex_btn.Bind(wx.EVT_BUTTON, lambda event: self.app.navigate("installer_flash"))
        sizer.Add(ex_btn, 0, wx.ALIGN_CENTER_HORIZONTAL)

        sizer.AddStretchSpacer(2)
        self.SetSizer(sizer)


class macOSInstallerCatalogPanel(wx.Panel):
    """
    Fetches AppleDB installers, handles download, SHA validation, and PKG extraction in-window
    """

    def __init__(self, parent: wx.Window, app, global_constants: constants.Constants) -> None:
        super().__init__(parent)
        logging.info("Initializing macOS Installer Catalog Panel")
        self.app = app
        self.constants = global_constants

        self.catalog_products = None
        self.available_installers = None
        self.available_installers_latest = None
        self.active_step: wx.Panel = None
        self.extract_result: bool = False

        self.icons = [[self._icon_to_bitmap(i), self._icon_to_bitmap(i, (64, 64))] for i in self.constants.icons_path]

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.sizer)

    def _icon_to_bitmap(self, icon: str, size: tuple = (32, 32)) -> wx.Bitmap:
        return wx.Bitmap(wx.Bitmap(icon, wx.BITMAP_TYPE_ICON).ConvertToImage().Rescale(size[0], size[1], wx.IMAGE_QUALITY_HIGH))

    def _macos_version_to_icon(self, version: int) -> int:
        try:
            self.constants.icons_path[version - 19]
            return version - 19
        except IndexError:
            return 0

    def _set_step(self, panel: wx.Panel) -> None:
        if self.active_step is not None:
            self.sizer.Detach(self.active_step)
            self.active_step.Destroy()
        self.active_step = panel
        self.sizer.Add(panel, 1, wx.EXPAND)
        self.Layout()

    def start(self) -> None:
        self._set_step(
            gui_support.IndeterminateProgressPanel(
                self,
                self.constants,
                gui_strings.INSTALLER["catalog_title"],
                message=gui_strings.INSTALLER["fetching_catalog"],
                back_label=gui_strings.NAV["back"],
                on_back=lambda: self.app.navigate("installer_choice"),
            )
        )

        def _fetch():
            logging.info("Fetching AppleDB products")
            self.catalog_products = sucatalog.AppleDBProducts(self.constants)
            if self.catalog_products.data is None:
                logging.error("Failed to fetch installers from AppleDB")
                return
            self.available_installers = self.catalog_products.products
            self.available_installers_latest = self.catalog_products.latest_products

        thread = threading.Thread(target=_fetch)
        thread.start()
        gui_support.wait_for_thread(thread)
        self._display_available_installers()

    def _display_available_installers(self, show_full: bool = False) -> None:
        bundles = [wx.BitmapBundle.FromBitmaps(icon) for icon in self.icons]

        step = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(
            gui_support.PageHeader(
                step,
                gui_strings.INSTALLER["catalog_title"],
                back_label=gui_strings.NAV["back"],
                on_back=lambda: self.app.navigate("installer_choice"),
            ),
            0,
            wx.EXPAND,
        )

        self.list = wx.ListCtrl(step, wx.NewIdRef(), style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_NO_HEADER | wx.BORDER_SUNKEN)
        self.list.SetSmallImages(bundles)
        self.list.InsertColumn(0, "Title", width=220)
        self.list.InsertColumn(1, "Version", width=85)
        self.list.InsertColumn(2, "Build", width=85)
        self.list.InsertColumn(3, "Size", width=85)
        self.list.InsertColumn(4, "Release Date", width=110)

        installers = self.available_installers_latest if not show_full else self.available_installers
        if installers:
            locale.setlocale(locale.LC_TIME, "")
            logging.info(f"Available installers from AppleDB ({'All entries' if show_full else 'Latest only'}):")
            for item in installers:
                logging.info(f"- {item['Title']} ({item['Version']} - {item['Build']})")
                index = self.list.InsertItem(self.list.GetItemCount(), f"{item['Title']}")
                self.list.SetItemImage(index, self._macos_version_to_icon(int(item["Build"][:2])))
                self.list.SetItem(index, 1, item["Version"])
                self.list.SetItem(index, 2, item["Build"])
                self.list.SetItem(index, 3, utilities.human_fmt(item["InstallAssistant"]["Size"]))
                self.list.SetItem(index, 4, item["PostDate"].strftime("%x"))
        else:
            logging.error("No installers found from AppleDB")
            wx.MessageDialog(self.app, "Failed to fetch installers from AppleDB", "Error", wx.OK | wx.ICON_ERROR).ShowModal()

        if not show_full:
            self.list.Select(-1)

        self.list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._on_select_list)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_select_list)
        outer.Add(self.list, 1, wx.EXPAND | wx.ALL, 16)

        self.showolder_cb = wx.CheckBox(step, label=gui_strings.INSTALLER["show_older"])
        self.showolder_cb.SetValue(show_full)
        self.showolder_cb.Bind(wx.EVT_CHECKBOX, lambda event: self._display_available_installers(self.showolder_cb.GetValue()))
        outer.Add(self.showolder_cb, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 10)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.copy_button = wx.Button(step, label=gui_strings.INSTALLER["copy_link"], size=(110, 30))
        self.copy_button.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        self.copy_button.Bind(wx.EVT_BUTTON, lambda event, data=installers: self._on_copy_link(data))
        self.copy_button.Disable()
        btn_row.Add(self.copy_button, 0, wx.RIGHT, 10)

        self.select_button = wx.Button(step, label="Download", size=(150, 30))
        self.select_button.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        self.select_button.Bind(wx.EVT_BUTTON, lambda event, data=installers: self._on_download_installer(data))
        self.select_button.SetDefault()
        self.select_button.Disable()
        btn_row.Add(self.select_button, 0, wx.RIGHT, 10)

        ret_btn = wx.Button(step, label=gui_strings.NAV["return_main"], size=(170, 30))
        ret_btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        ret_btn.Bind(wx.EVT_BUTTON, lambda event: self.app.go_home())
        btn_row.Add(ret_btn, 0)

        outer.Add(btn_row, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 16)
        step.SetSizer(outer)
        self._set_step(step)

    def _on_select_list(self, event) -> None:
        has_sel = self.list.GetSelectedItemCount() > 0
        self.select_button.Enable(has_sel)
        self.copy_button.Enable(has_sel)

    def _on_copy_link(self, installers: list) -> None:
        selected_item = self.list.GetFirstSelected()
        if selected_item == -1:
            return
        clipboard = wx.Clipboard.Get()
        if not clipboard.IsOpened():
            clipboard.Open()
        clipboard.SetData(wx.TextDataObject(installers[selected_item]["InstallAssistant"]["URL"]))
        clipboard.Close()
        wx.MessageDialog(self.app, gui_strings.INSTALLER["copied_msg"], "", wx.OK | wx.ICON_INFORMATION).ShowModal()

    def _on_download_installer(self, installers: list) -> None:
        selected_item = self.list.GetFirstSelected()
        if selected_item == -1:
            return
        selected = installers[selected_item]
        logging.info(f"Selected macOS {selected['Version']} ({selected['Build']})")

        problems = []
        model = self.constants.custom_model or self.constants.computer.real_model
        if model in smbios_data.smbios_dictionary and selected["InstallAssistant"]["XNUMajor"] >= os_data.os_data.ventura:
            if smbios_data.smbios_dictionary[model]["CPU Generation"] <= cpu_data.CPUGen.penryn or model in ["MacPro4,1", "MacPro5,1", "Xserve3,1"]:
                problems.append("Lack of internal Keyboard/Trackpad in macOS installer." if model.startswith("MacBook") else "Lack of internal Keyboard/Mouse in macOS installer.")

        if problems:
            logging.warning(f"Potential issues with {model} and {selected['Version']} ({selected['Build']}): {problems}")
            dlg = wx.MessageDialog(
                self.app,
                f"Your model ({model}) may not be fully supported by this installer. You may encounter the following issues:\n\n"
                + "\n".join(problems)
                + "\n\nFor more information, see associated page. Otherwise, we recommend using macOS Monterey.",
                "Potential Issues",
                wx.YES_NO | wx.CANCEL | wx.ICON_WARNING,
            )
            dlg.SetYesNoCancelLabels("View GitHub Issue", "Download Anyways", "Cancel")
            res = dlg.ShowModal()
            if res == wx.ID_CANCEL:
                return
            if res == wx.ID_YES:
                webbrowser.open("https://github.com/dortania/OpenCore-Legacy-Patcher/issues/1021")
                return

        host_space = utilities.get_free_space()
        needed_space = selected["InstallAssistant"]["Size"] * 2
        if host_space < needed_space:
            logging.error(f"Insufficient space: {utilities.human_fmt(host_space)} available vs {utilities.human_fmt(needed_space)} required")
            wx.MessageDialog(
                self.app,
                f"Not enough free space to download and extract this installer.\n\n{utilities.human_fmt(host_space)} available vs {utilities.human_fmt(needed_space)} required.",
                "Insufficient Space",
                wx.OK | wx.ICON_WARNING,
            ).ShowModal()
            return

        expected_checksum, checksum_algo = self.catalog_products.checksum_for_product(selected)
        download_obj = network_handler.DownloadObject(
            selected["InstallAssistant"]["URL"],
            self.constants.payload_path / "InstallAssistant.pkg",
            checksum_algo=checksum_algo,
        )
        icon = self.constants.icons_path[self._macos_version_to_icon(selected["InstallAssistant"]["XNUMajor"])]

        if not self.app.show_download(
            download_obj,
            f"macOS {selected['Version']} ({selected['Build']})",
            download_icon=icon,
        ):
            self.app.go_home()
            return

        self._validate_and_extract(expected_checksum, download_obj.checksum)

    def _validate_and_extract(self, expected_checksum: str, calculated_checksum: str) -> None:
        if expected_checksum != calculated_checksum:
            logging.error(f"Checksum validation failed: Expected {expected_checksum}, got {calculated_checksum}")
            wx.MessageBox(
                "Checksum validation failed!\n\nThis generally happens when downloading on unstable connections.\n\nPlease try downloading again on a stable connection.",
                "Corrupted Installer!",
                wx.OK | wx.ICON_ERROR,
            )
            self.app.go_home()
            return

        logging.info("macOS installer validated")
        self.app.set_busy(True, "extracting macOS installer")
        try:
            self._set_step(
                gui_support.IndeterminateProgressPanel(
                    self,
                    self.constants,
                    gui_strings.INSTALLER["extracting_title"],
                    message=gui_strings.INSTALLER["extracting_desc"],
                )
            )
            self.extract_result = False

            def _extract():
                self.extract_result = macos_installer_handler.InstallerCreation().install_macOS_installer(self.constants.payload_path)

            thread = threading.Thread(target=_extract)
            thread.start()
            gui_support.wait_for_thread(thread)
        finally:
            self.app.set_busy(False)

        if self.extract_result is False:
            wx.MessageBox(gui_strings.INSTALLER["extract_fail"], "Error", wx.OK | wx.ICON_ERROR)
            self.app.go_home()
            return

        answer = wx.MessageBox(
            gui_strings.INSTALLER["flash_prompt_msg"],
            gui_strings.INSTALLER["flash_prompt_title"],
            wx.YES_NO | wx.ICON_QUESTION,
        )
        if answer == wx.YES:
            self.app.navigate("installer_flash")
        else:
            self.app.go_home()