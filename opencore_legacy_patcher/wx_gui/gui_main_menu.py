"""
gui_main_menu.py: Single persistent window shell, Home view, and view router
"""

import wx
import wx.html2
import sys
import logging
import requests
import markdown2
import threading
import webbrowser

from pathlib import Path
from base64 import b64encode
from html import escape
from io import BytesIO

from .. import constants
from ..support import global_settings, updates
from ..datasets import os_data, css_data
from ..wx_gui import gui_support, gui_strings, gui_download


class HomePanel(wx.Panel):
    """
    Main menu panel hosted inside the single persistent MainFrame
    """

    def __init__(self, parent: wx.Window, app, global_constants: constants.Constants) -> None:
        super().__init__(parent)
        self.app = app
        self.constants = global_constants
        self.build_button: wx.Button = None
        self.patch_button: wx.Button = None
        self.model_label: wx.StaticText = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.AddSpacer(14)

        bmp = wx.Bitmap(str(self.constants.icns_resource_path / "OC-Patcher.icns"), wx.BITMAP_TYPE_ICON).ConvertToImage().Rescale(88, 88, wx.IMAGE_QUALITY_HIGH)
        outer.Add(wx.StaticBitmap(self, bitmap=wx.Bitmap(bmp)), 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 6)

        title = wx.StaticText(self, label=gui_strings.APP_NAME)
        title.SetFont(gui_support.font_factory(22, wx.FONTWEIGHT_BOLD))
        outer.Add(title, 0, wx.ALIGN_CENTER_HORIZONTAL)

        nightly = " (Nightly)" if not self.constants.commit_info[0].startswith("refs/tags") else ""
        ver = wx.StaticText(self, label=f"Version {self.constants.patcher_version}{nightly}")
        ver.SetFont(gui_support.font_factory(12, wx.FONTWEIGHT_NORMAL))
        ver.SetForegroundColour(wx.Colour(128, 128, 128))
        outer.Add(ver, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.TOP, 2)

        model = self.constants.custom_model or self.constants.computer.real_model
        self.model_label = wx.StaticText(self, label=f"Model: {model}", size=(480, -1), style=wx.ALIGN_CENTER_HORIZONTAL | wx.ST_NO_AUTORESIZE)
        self.model_label.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        outer.Add(self.model_label, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.TOP | wx.BOTTOM, 8)

        # 2x2 Main action grid preserving original workflow familiarity
        grid = wx.GridSizer(rows=2, cols=2, vgap=14, hgap=18)
        cards = [
            (
                "build",
                gui_strings.MAIN_MENU["build_title"],
                gui_strings.MAIN_MENU["build_desc"],
                str(self.constants.icns_resource_path / "OC-Build.icns"),
                lambda: self.app.navigate("build"),
            ),
            (
                "installer",
                gui_strings.MAIN_MENU["installer_title"],
                gui_strings.MAIN_MENU["installer_desc"],
                str(self.constants.icns_resource_path / "OC-Installer.icns"),
                lambda: self.app.navigate("installer_choice"),
            ),
            (
                "patch",
                gui_strings.MAIN_MENU["patch_title"],
                gui_strings.MAIN_MENU["patch_desc"],
                str(self.constants.icns_resource_path / "OC-Patch.icns"),
                lambda: self.app.navigate("sys_patch_display"),
            ),
            (
                "help",
                gui_strings.MAIN_MENU["help_title"],
                gui_strings.MAIN_MENU["help_desc"],
                str(self.constants.icns_resource_path / "OC-Support.icns"),
                lambda: self.app.navigate("help"),
            ),
        ]

        for key, btn_label, desc_text, icon_path, handler in cards:
            card = wx.Panel(self)
            row = wx.BoxSizer(wx.HORIZONTAL)
            ibmp = wx.Bitmap(icon_path, wx.BITMAP_TYPE_ICON).ConvertToImage().Rescale(52, 52, wx.IMAGE_QUALITY_HIGH)
            row.Add(wx.StaticBitmap(card, bitmap=wx.Bitmap(ibmp)), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)

            col = wx.BoxSizer(wx.VERTICAL)
            btn = wx.Button(card, label=btn_label, size=(195, 30))
            btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
            btn.Bind(wx.EVT_BUTTON, lambda evt, fn=handler: fn())
            col.Add(btn, 0, wx.BOTTOM, 4)

            desc = wx.StaticText(card, label=desc_text)
            desc.SetFont(gui_support.font_factory(10, wx.FONTWEIGHT_NORMAL))
            desc.SetForegroundColour(wx.Colour(128, 128, 128))
            col.Add(desc, 0)

            row.Add(col, 1, wx.ALIGN_CENTER_VERTICAL)
            card.SetSizer(row)
            grid.Add(card, 0, wx.EXPAND)

            if key == "build":
                self.build_button = btn
            elif key == "patch":
                self.patch_button = btn

        outer.Add(grid, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.ALL, 12)
        outer.AddStretchSpacer(1)

        footer_btns = wx.BoxSizer(wx.HORIZONTAL)
        settings_btn = wx.Button(self, label=gui_strings.MAIN_MENU["settings"], size=(120, 30))
        settings_btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        settings_btn.Bind(wx.EVT_BUTTON, lambda evt: self.app.navigate("settings"))
        footer_btns.Add(settings_btn, 0, wx.RIGHT, 12)

        credits_btn = wx.Button(self, label=gui_strings.MAIN_MENU["credits"], size=(120, 30))
        credits_btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        credits_btn.Bind(wx.EVT_BUTTON, lambda evt: self.app.navigate("credits"))
        footer_btns.Add(credits_btn, 0)

        outer.Add(footer_btns, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 8)

        copy_label = wx.StaticText(self, label=self.constants.copyright_date)
        copy_label.SetFont(gui_support.font_factory(10, wx.FONTWEIGHT_NORMAL))
        copy_label.SetForegroundColour(wx.Colour(128, 128, 128))
        outer.Add(copy_label, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 12)

        self.SetSizer(outer)
        self.refresh()

    def refresh(self) -> None:
        model = self.constants.custom_model or self.constants.computer.real_model
        self.model_label.SetLabel(f"Model: {model}")
        if self.build_button is not None:
            self.build_button.Enable(gui_support.CheckProperties(self.constants).host_can_build())
        if self.patch_button is not None:
            self.patch_button.Enable(self.constants.detected_os >= os_data.os_data.big_sur)
        self.Layout()


class WebContentPanel(wx.Panel):
    """
    In-window HTML/WebView host for First-Launch Welcome, Credits, and Update Changelog
    """

    def __init__(
        self,
        parent: wx.Window,
        app,
        title: str,
        html_content: str,
        base_uri: str = "",
        subtitle: str = "",
        buttons: list = None,
        on_nav=None,
        on_back=None,
    ) -> None:
        super().__init__(parent)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(gui_support.PageHeader(self, title, subtitle=subtitle, back_label=gui_strings.NAV["return_main"], on_back=on_back), 0, wx.EXPAND)

        web_view = wx.html2.WebView.New(self, style=wx.BORDER_SUNKEN)
        web_view.EnableContextMenu(False)
        web_view.SetPage(html_content, base_uri)
        if on_nav is not None:
            web_view.Bind(wx.html2.EVT_WEBVIEW_NAVIGATING, on_nav)
            web_view.Bind(wx.html2.EVT_WEBVIEW_NEWWINDOW, on_nav)
        outer.Add(web_view, 1, wx.EXPAND | wx.ALL, 12)

        if buttons:
            btn_row = wx.BoxSizer(wx.HORIZONTAL)
            for idx, (label, callback, is_default) in enumerate(buttons):
                btn = wx.Button(self, label=label)
                btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
                btn.Bind(wx.EVT_BUTTON, lambda evt, cb=callback: cb())
                if is_default:
                    btn.SetDefault()
                btn_row.Add(btn, 0, wx.RIGHT if idx < len(buttons) - 1 else 0, 10)
            outer.Add(btn_row, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 14)

        self.SetSizer(outer)


class MainFrame(wx.Frame):
    """
    Single persistent 640x520 application window hosting swappable workflow panels
    """

    WINDOW_SIZE = (640, 520)

    def __init__(
        self,
        parent: wx.Frame,
        title: str,
        global_constants: constants.Constants,
        screen_location: tuple = None,
        initial_view: str = "home",
        **initial_kwargs,
    ) -> None:
        logging.info("Initializing Main Window Shell")
        super().__init__(
            parent,
            title=title,
            size=self.WINDOW_SIZE,
            style=wx.DEFAULT_FRAME_STYLE & ~(wx.RESIZE_BORDER | wx.MAXIMIZE_BOX),
        )
        gui_support.GenerateMenubar(self, global_constants).generate()

        self.constants = global_constants
        self.title = title
        self._busy_reason = ""
        self.constants.update_stage = gui_support.AutoUpdateStages.INACTIVE

        self.book = wx.Simplebook(self)
        self.home_panel = HomePanel(self.book, app=self, global_constants=self.constants)
        self.book.AddPage(self.home_panel, "home")

        root_sizer = wx.BoxSizer(wx.VERTICAL)
        root_sizer.Add(self.book, 1, wx.EXPAND)
        self.SetSizer(root_sizer)

        self.Bind(wx.EVT_CLOSE, self._on_close)
        if screen_location:
            self.SetPosition(screen_location)
        else:
            self.Centre()
        self.Show()

        if initial_view != "home":
            self.navigate(initial_view, **initial_kwargs)
        elif global_settings.GlobalEnviromentSettings().read_property("FirstLaunchWelcomeShown") is not True:
            wx.CallAfter(self.navigate, "welcome")
        else:
            wx.CallAfter(self._preflight_checks)

    def set_busy(self, busy: bool, reason: str = "") -> None:
        self._busy_reason = reason if busy else ""

    def _on_close(self, event: wx.CloseEvent) -> None:
        if self._busy_reason:
            wx.MessageBox(
                f"Cannot close OpenCore Legacy Patcher while {self._busy_reason} is in progress.",
                "Operation in Progress",
                wx.OK | wx.ICON_WARNING,
            )
            event.Veto()
            return
        self.Destroy()

    def _clear_transient_pages(self) -> None:
        while self.book.GetPageCount() > 1:
            page = self.book.GetPage(1)
            self.book.RemovePage(1)
            page.Destroy()

    def go_home(self) -> None:
        self.book.SetSelection(0)
        self._clear_transient_pages()
        self.home_panel.refresh()

    def refresh_menu(self) -> None:
        self.home_panel.refresh()

    def show_download(self, download_obj, item_name: str, download_icon: str = None, title: str = None) -> bool:
        panel = gui_download.DownloadPanel(
            self.book,
            app=self,
            global_constants=self.constants,
            download_obj=download_obj,
            item_name=item_name,
            download_icon=download_icon,
            title=title,
        )
        self._swap_page(panel, "download")
        return panel.run()

    def _swap_page(self, panel: wx.Panel, name: str) -> None:
        # Insert new page before deleting old transient page to avoid flashing home_panel
        self.book.AddPage(panel, name)
        new_idx = self.book.GetPageCount() - 1
        self.book.SetSelection(new_idx)
        while self.book.GetPageCount() > 2:
            old = self.book.GetPage(1)
            self.book.RemovePage(1)
            old.Destroy()
        self.Layout()

    def navigate(self, route: str, **kwargs) -> None:
        if route == "home":
            self.go_home()
            return

        if route == "build":
            from ..wx_gui import gui_build
            panel = gui_build.BuildPanel(self.book, app=self, global_constants=self.constants)
        elif route == "install_oc":
            from ..wx_gui import gui_install_oc
            panel = gui_install_oc.InstallOCPanel(self.book, app=self, global_constants=self.constants)
        elif route == "sys_patch_display":
            from ..wx_gui import gui_sys_patch_display
            panel = gui_sys_patch_display.SysPatchDisplayPanel(self.book, app=self, global_constants=self.constants)
        elif route == "sys_patch_start":
            from ..wx_gui import gui_sys_patch_start
            panel = gui_sys_patch_start.SysPatchStartPanel(self.book, app=self, global_constants=self.constants, **kwargs)
        elif route == "installer_choice":
            from ..wx_gui import gui_macos_installer_download
            panel = gui_macos_installer_download.macOSInstallerChoicePanel(self.book, app=self, global_constants=self.constants)
        elif route == "installer_catalog":
            from ..wx_gui import gui_macos_installer_download
            panel = gui_macos_installer_download.macOSInstallerCatalogPanel(self.book, app=self, global_constants=self.constants)
        elif route == "installer_flash":
            from ..wx_gui import gui_macos_installer_flash
            panel = gui_macos_installer_flash.macOSInstallerFlashPanel(self.book, app=self, global_constants=self.constants)
        elif route == "settings":
            from ..wx_gui import gui_settings
            panel = gui_settings.SettingsPanel(self.book, app=self, global_constants=self.constants)
        elif route == "help":
            from ..wx_gui import gui_help
            panel = gui_help.HelpPanel(self.book, app=self, global_constants=self.constants)
        elif route == "update":
            from ..wx_gui import gui_update
            panel = gui_update.UpdatePanel(self.book, app=self, global_constants=self.constants, **kwargs)
        elif route == "os_cache":
            from ..wx_gui import gui_cache_os_update
            panel = gui_cache_os_update.OSCachePanel(self.book, app=self, global_constants=self.constants)
        elif route in ("welcome", "credits"):
            panel = self._build_credits_panel(first_launch=(route == "welcome"))
        elif route == "changelog":
            panel = self._build_changelog_panel(**kwargs)
        else:
            raise ValueError(f"Unknown route: {route}")

        self._swap_page(panel, route)
        if hasattr(panel, "start"):
            wx.CallAfter(panel.start)

    def _build_credits_panel(self, first_launch: bool = False) -> WebContentPanel:
        html_path = Path(__file__).with_name("credits.html")
        logo = wx.Bitmap(str(self.constants.icns_resource_path / "OC-Patcher.icns"), wx.BITMAP_TYPE_ICON).ConvertToImage()
        logo_stream = BytesIO()
        logo.SaveFile(logo_stream, wx.BITMAP_TYPE_PNG)
        page = html_path.read_text(encoding="utf-8")
        page = page.replace("{{LOGO}}", b64encode(logo_stream.getvalue()).decode("ascii"))
        page = page.replace("{{VERSION}}", escape(self.constants.patcher_version))
        page = page.replace("{{MODE}}", "welcome" if first_launch else "credits")

        def _dismiss_welcome():
            global_settings.GlobalEnviromentSettings().write_property("FirstLaunchWelcomeShown", True)
            self.go_home()
            wx.CallAfter(self._preflight_checks)

        def _on_nav(event):
            url = event.GetURL()
            if first_launch and url == "oclp://welcome/close":
                event.Veto()
                wx.CallAfter(_dismiss_welcome)
            elif url.startswith(("https://", "http://")):
                event.Veto()
                webbrowser.open(url)

        title = gui_strings.MAIN_MENU["welcome_title"] if first_launch else gui_strings.MAIN_MENU["credits_title"]
        buttons = [] if first_launch else [(gui_strings.NAV["close"], self.go_home, True)]
        return WebContentPanel(
            self.book,
            app=self,
            title=title,
            html_content=page,
            base_uri=html_path.as_uri(),
            buttons=buttons,
            on_nav=_on_nav,
            on_back=None if first_launch else self.go_home,
        )

    def _build_changelog_panel(self, oclp_url: str, oclp_version: str, oclp_github_url: str) -> WebContentPanel:
        url = "https://api.github.com/repos/dortania/OpenCore-Legacy-Patcher/releases/latest"
        try:
            response = requests.get(url, timeout=10).json()
            changelog = response["body"].split("## Asset Information")[0]
        except Exception:
            changelog = gui_strings.MAIN_MENU["changelog_unavailable"]

        html_markdown = markdown2.markdown(changelog, extras=["tables"]).replace("<a href=", "<a target='_blank' href=")
        nightly = " (Nightly)" if not self.constants.commit_info[0].startswith("refs/tags") else ""
        html_code = (
            f"<html><head><style>{css_data.updater_css}</style></head>"
            f"<body class='markdown-body'>{html_markdown}</body></html>"
        )
        subtitle = gui_strings.MAIN_MENU["update_available_desc"].format(
            new_version=oclp_version,
            current_version=f"{self.constants.patcher_version}{nightly}",
        )

        def _on_nav(event):
            target = event.GetURL()
            if target.startswith(("https://", "http://")):
                event.Veto()
                webbrowser.open(target)

        return WebContentPanel(
            self.book,
            app=self,
            title=gui_strings.MAIN_MENU["update_available_title"],
            subtitle=subtitle,
            html_content=html_code,
            buttons=[
                (gui_strings.MAIN_MENU["dismiss"], self.go_home, False),
                (gui_strings.MAIN_MENU["view_github"], lambda: webbrowser.open(oclp_github_url), False),
                (gui_strings.MAIN_MENU["download_install"], lambda: self.navigate("update", url=oclp_url, version_label=oclp_version), True),
            ],
            on_nav=_on_nav,
            on_back=self.go_home,
        )

    def _preflight_checks(self) -> None:
        if (
            self.constants.computer.build_model is not None
            and self.constants.computer.build_model != self.constants.computer.real_model
            and self.constants.host_is_hackintosh is False
        ):
            wx.MessageDialog(
                self,
                gui_strings.MAIN_MENU["unsupported_config_msg"].format(build_model=self.constants.computer.build_model),
                gui_strings.MAIN_MENU["unsupported_config_title"],
                style=wx.OK | wx.ICON_EXCLAMATION,
            ).ShowModal()
            self.navigate("build")
            return

        if "--update_installed" in sys.argv and self.constants.has_checked_updates is False and gui_support.CheckProperties(self.constants).host_can_build():
            self.constants.has_checked_updates = True
            pop = wx.MessageDialog(
                self,
                gui_strings.MAIN_MENU["post_update_msg"].format(version=self.constants.patcher_version),
                gui_strings.MAIN_MENU["post_update_title"],
                style=wx.YES_NO | wx.YES_DEFAULT | wx.ICON_INFORMATION,
            )
            if pop.ShowModal() != wx.ID_YES:
                logging.info("Skipping OpenCore and root volume patch update...")
                return
            logging.info("Updating OpenCore and root volume patches...")
            self.constants.update_stage = gui_support.AutoUpdateStages.CHECKING
            self.navigate("build")
            return

        threading.Thread(target=self._check_for_updates, daemon=True).start()

    def _check_for_updates(self) -> None:
        if self.constants.has_checked_updates is True:
            return
        if global_settings.GlobalEnviromentSettings().read_property("IgnoreAppUpdates") is True:
            self.constants.ignore_updates = True
            return

        self.constants.ignore_updates = False
        self.constants.has_checked_updates = True
        info = updates.CheckBinaryUpdates(self.constants).check_binary_updates()
        if not info:
            return

        logging.info(f"New version: {info['Version']}")
        wx.CallAfter(self.navigate, "changelog", oclp_url=info["Link"], oclp_version=info["Version"], oclp_github_url=info["Github Link"])
