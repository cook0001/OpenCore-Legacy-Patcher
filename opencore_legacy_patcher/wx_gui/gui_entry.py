"""
gui_entry.py: Entry point for the wxPython GUI
"""

import wx
import sys
import atexit
import logging

from Cocoa import NSApp, NSApplication

from .. import constants
from ..support import global_settings
from ..sys_patch.patchsets import HardwarePatchsetDetection
from ..wx_gui import gui_main_menu, gui_cache_os_update


class SupportedEntryPoints:
    """
    Enum for supported entry points
    """
    MAIN_MENU  = "home"
    BUILD_OC   = "build"
    INSTALL_OC = "install_oc"
    SYS_PATCH  = "sys_patch_start"
    UPDATE_APP = "update"
    OS_CACHE   = "os_cache"


class EntryPoint:

    def __init__(self, global_constants: constants.Constants) -> None:
        self.app: wx.App = None
        self.frame: wx.Frame = None
        self.constants: constants.Constants = global_constants
        self.constants.gui_mode = True

    def _generate_base_data(self) -> None:
        self.app = wx.App()
        self.app.SetAppName(self.constants.patcher_name)

        # Reference:
        # - https://discuss.wxpython.org/t/macos-window-opens-in-the-background-and-does-not-receive-focus/36763/10
        NSApplication.sharedApplication()
        NSApp().activateIgnoringOtherApps_(True)

    def start(self, entry: str = SupportedEntryPoints.MAIN_MENU, start_patching: bool = False) -> None:
        """
        Launches entry point for the wxPython GUI
        """
        if "--reset_first_launch" in sys.argv:
            global_settings.GlobalEnviromentSettings().delete_property("FirstLaunchWelcomeShown")

        if entry == SupportedEntryPoints.OS_CACHE and not gui_cache_os_update.OSCachePanel.needs_caching(self.constants):
            return

        self._generate_base_data()

        initial_kwargs = {}
        if "--gui_patch" in sys.argv or "--gui_unpatch" in sys.argv or start_patching is True:
            entry = SupportedEntryPoints.SYS_PATCH
            initial_kwargs["patches"] = HardwarePatchsetDetection(constants=self.constants).device_properties
            initial_kwargs["action"] = "revert" if "--gui_unpatch" in sys.argv else "patch"

        logging.info(f"Entry point set: {entry}")

        # Normally set by main.py, but transitions from CLI mode may not have this set
        self.constants.gui_mode = True

        nightly = " (Nightly)" if not self.constants.commit_info[0].startswith("refs/tags") else ""
        self.frame = gui_main_menu.MainFrame(
            None,
            title=f"{self.constants.patcher_name} {self.constants.patcher_version}{nightly}",
            global_constants=self.constants,
            initial_view=entry,
            **initial_kwargs,
        )

        atexit.register(self.OnCloseFrame)
        self.app.MainLoop()

    def OnCloseFrame(self, event: wx.Event = None) -> None:
        """
        Closes the wxPython GUI
        """
        if not self.frame:
            return

        logging.info("Cleaning up wxPython GUI")
        try:
            self.frame.SetTransparent(0)
            wx.Yield()
            self.frame.DestroyChildren()
            self.frame.Destroy()
        except RuntimeError:
            pass
        if self.app:
            self.app.ExitMainLoop()
