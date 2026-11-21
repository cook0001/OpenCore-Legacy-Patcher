"""
gui_support.py: Utilities for interacting with wxPython GUI
"""

import wx
import sys
import time
import logging
import plistlib
import threading
import subprocess
import applescript
import contextlib
import packaging.version

from pathlib import Path

from . import gui_about, gui_strings

from .. import constants

from ..detections import device_probe

from ..datasets import (
    model_array,
    os_data,
    smbios_data
)


def get_font_face():
    if not get_font_face.font_face:
        get_font_face.font_face = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT).GetFaceName() or "Lucida Grande"

    return get_font_face.font_face


get_font_face.font_face = None


# Centralize the common options for font creation
def font_factory(size: int, weight):
    return wx.Font(size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, weight, False, get_font_face())


class AutoUpdateStages:
    INACTIVE = 0
    CHECKING = 1
    BUILDING = 2
    INSTALLING = 3
    UNPATCHING = 4
    FINISHED = 5


class GenerateMenubar:

    def __init__(self, frame: wx.Frame, global_constants: constants.Constants) -> None:
        self.frame: wx.Frame = frame
        self.constants: constants.Constants = global_constants


    def generate(self) -> wx.MenuBar:
        menubar = wx.MenuBar()
        fileMenu = wx.Menu()

        aboutItem = fileMenu.Append(wx.ID_ABOUT, "&About OpenCore Legacy Patcher")
        fileMenu.AppendSeparator()
        revealLogItem = fileMenu.Append(wx.ID_ANY, "&Reveal Log File")

        menubar.Append(fileMenu, "&File")
        self.frame.SetMenuBar(menubar)

        self.frame.Bind(wx.EVT_MENU, lambda event: gui_about.AboutFrame(self.constants), aboutItem)
        self.frame.Bind(wx.EVT_MENU, lambda event: subprocess.run(["/usr/bin/open", "--reveal", self.constants.log_filepath]), revealLogItem)


class GaugePulseCallback:
    """
    Uses an alternative Pulse() method for wx.Gauge() on macOS Monterey+ with non-Metal GPUs
    Dirty hack, however better to display some form of animation than none at all

    Note: This work-around is no longer needed on hosts using PatcherSupportPkg 1.1.2 or newer
    """

    def __init__(self, global_constants: constants.Constants, gauge: wx.Gauge) -> None:
        self.gauge: wx.Gauge = gauge

        self.pulse_thread: threading.Thread = None
        self.pulse_thread_active: bool = False

        self.gauge_value: int = 0
        self.pulse_forward: bool = True

        self.max_value: int = gauge.GetRange()

        self.non_metal_alternative: bool = CheckProperties(global_constants).host_is_non_metal()
        if self.non_metal_alternative is True:
            if CheckProperties(global_constants).host_psp_version() >= packaging.version.Version("1.1.2"):
                self.non_metal_alternative = False


    def start_pulse(self) -> None:
        if self.non_metal_alternative is False:
            self.gauge.Pulse()
            return
        if self.pulse_thread_active:
            return
        self.pulse_thread_active = True
        self.pulse_thread = threading.Thread(target=self._pulse, daemon=True)
        self.pulse_thread.start()


    def stop_pulse(self) -> None:
        if self.non_metal_alternative is False:
            return
        self.pulse_thread_active = False
        if self.pulse_thread and self.pulse_thread.is_alive():
            self.pulse_thread.join(timeout=1.0)


    def _pulse(self) -> None:
        while self.pulse_thread_active:
            if self.gauge_value == 0:
                self.pulse_forward = True

            elif self.gauge_value == self.max_value:
                self.pulse_forward = False

            if self.pulse_forward:
                self.gauge_value += 1
            else:
                self.gauge_value -= 1

            wx.CallAfter(self.gauge.SetValue, self.gauge_value)
            time.sleep(0.005)


class CheckProperties:

    def __init__(self, global_constants: constants.Constants) -> None:
        self.constants: constants.Constants = global_constants


    def host_can_build(self):
        """
        Check if host supports building OpenCore configs
        """
        if self.constants.custom_model:
            return True
        if self.constants.host_is_hackintosh is True:
            return False
        if self.constants.allow_oc_everywhere is True:
            return True
        if self.constants.computer.real_model in model_array.SupportedSMBIOS:
            return True

        return False


    def host_is_non_metal(self, general_check: bool = False):
        """
        Check if host is non-metal
        Primarily for wx.Gauge().Pulse() workaround (where animation doesn't work on Monterey+)
        """

        if self.constants.detected_os < os_data.os_data.monterey and general_check is False:
            return False
        if self.constants.detected_os < os_data.os_data.big_sur and general_check is True:
            return False
        if not Path("/System/Library/PrivateFrameworks/SkyLight.framework/Versions/A/SkyLightOld.dylib").exists():
            # SkyLight stubs are only used on non-Metal
            return False

        return True

    def host_is_solarium(self) -> bool:
        """
        Check if running on macOS 26, and if Solarium refresh is enabled
        """

        if self.constants.detected_os < os_data.os_data.tahoe:
            return False

        # If we are a release build, we are not Solarium for now
        if self.constants.commit_info[0].startswith('refs/tags'):
            return False

        return True


    def host_has_cpu_gen(self, gen: int) -> bool:
        """
        Check if host has a CPU generation equal to or greater than the specified generation
        """
        model = self.constants.custom_model if self.constants.custom_model else self.constants.computer.real_model
        if model in smbios_data.smbios_dictionary:
            if smbios_data.smbios_dictionary[model]["CPU Generation"] >= gen:
                return True
        return False


    def host_psp_version(self) -> packaging.version.Version:
        """
        Grab PatcherSupportPkg version from OpenCore-Legacy-Patcher.plist
        """
        oclp_plist_path = "/System/Library/CoreServices/OpenCore-Legacy-Patcher.plist"
        if not Path(oclp_plist_path).exists():
            return packaging.version.Version("0.0.0")

        oclp_plist = plistlib.load(open(oclp_plist_path, "rb"))
        if "PatcherSupportPkg" not in oclp_plist:
            return packaging.version.Version("0.0.0")

        if oclp_plist["PatcherSupportPkg"].startswith("v"):
            oclp_plist["PatcherSupportPkg"] = oclp_plist["PatcherSupportPkg"][1:]

        return packaging.version.parse(oclp_plist["PatcherSupportPkg"])

    def host_has_3802_gpu(self) -> bool:
        """
        Check if either host, or override model, has a 3802 GPU
        """

        gpu_archs = []
        if self.constants.custom_model:
            model = self.constants.custom_model
        else:
            model = self.constants.computer.real_model
            gpu_archs = [gpu.arch for gpu in self.constants.computer.gpus]

        if not gpu_archs:
            gpu_archs = smbios_data.smbios_dictionary.get(model, {}).get("Stock GPUs", [])

        for arch in gpu_archs:
            if arch in [
                device_probe.Intel.Archs.Ivy_Bridge,
                device_probe.Intel.Archs.Haswell,
                device_probe.NVIDIA.Archs.Kepler,
            ]:
                return True

        return False

class PayloadMount:

    def __init__(self, global_constants: constants.Constants, frame: wx.Frame) -> None:
        self.constants: constants.Constants = global_constants
        self.frame: wx.Frame = frame


    def is_unpack_finished(self):
        if self.constants.unpack_thread.is_alive():
            return False

        if Path(self.constants.payload_kexts_path).exists():
            return True

        # Raise error to end program
        popup = wx.MessageDialog(
            self.frame,
            f"During unpacking of our internal files, we seemed to have encountered an error.\n\nIf you keep seeing this error, please try rebooting and redownloading the application.",
            "Internal Error occurred!",
            style=wx.OK | wx.ICON_EXCLAMATION
        )
        popup.ShowModal()
        self.frame.Freeze()
        sys.exit(1)


class ThreadHandler(logging.Handler):
    """
    Reroutes logging output to a wx.TextCtrl using UI callbacks
    """

    def __init__(self, text_box: wx.TextCtrl):
        logging.Handler.__init__(self)
        self.text_box = text_box


    def emit(self, record: logging.LogRecord):
        wx.CallAfter(self.text_box.AppendText, self.format(record) + '\n')


def wait_for_thread(thread: threading.Thread, sleep_interval=None):
    """
    Waits for a thread to finish while processing UI events at regular intervals
    to prevent UI freezing and excessive CPU usage.
    """
    # Use the passed sleep_interval, or get from global_constants
    interval = sleep_interval if sleep_interval is not None else constants.Constants().thread_sleep_interval

    while thread.is_alive():
        wx.Yield()
        thread.join(timeout=interval)


class RestartHost:
    """
    Restarts the host machine
    """

    def __init__(self, frame: wx.Frame) -> None:
        self.frame: wx.Frame = frame


    def restart(self, event: wx.Event = None, message: str = ""):
        self.popup = wx.MessageDialog(
            self.frame,
            message,
            "Reboot to apply?",
            wx.YES_NO | wx.YES_DEFAULT | wx.ICON_INFORMATION
        )
        self.popup.SetYesNoLabels("Reboot", "Ignore")
        answer = self.popup.ShowModal()
        if answer == wx.ID_YES:
            # Reboots with Count Down prompt (user can still dismiss if needed)
            self.frame.Hide()
            wx.Yield()
            try:
                applescript.AppleScript('tell app "loginwindow" to «event aevtrrst»').run()
            except applescript.ScriptError as e:
                logging.error(f"Error while trying to reboot: {e}")
            sys.exit(0)


@contextlib.contextmanager
def capture_logs(text_box: wx.TextCtrl):
    """
    Safely attach ThreadHandler to root logger and always detach that exact handler
    """
    logger = logging.getLogger()
    handler = ThreadHandler(text_box)
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


class PageHeader(wx.Panel):
    """
    Standard top header bar for views inside the single-window shell
    """

    def __init__(self, parent: wx.Window, title: str, subtitle: str = "", back_label: str = gui_strings.NAV["back"], on_back=None) -> None:
        super().__init__(parent)
        outer = wx.BoxSizer(wx.VERTICAL)
        row = wx.BoxSizer(wx.HORIZONTAL)

        self.back_button = None
        if on_back is not None:
            self.back_button = wx.Button(self, label=f"← {back_label}")
            self.back_button.SetFont(font_factory(12, wx.FONTWEIGHT_NORMAL))
            self.back_button.Bind(wx.EVT_BUTTON, lambda event: on_back())
            row.Add(self.back_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)

        text_col = wx.BoxSizer(wx.VERTICAL)
        self.title_label = wx.StaticText(self, label=title)
        self.title_label.SetFont(font_factory(18, wx.FONTWEIGHT_BOLD))
        text_col.Add(self.title_label, 0)

        self.subtitle_label = None
        if subtitle:
            self.subtitle_label = wx.StaticText(self, label=subtitle)
            self.subtitle_label.SetFont(font_factory(12, wx.FONTWEIGHT_NORMAL))
            self.subtitle_label.SetForegroundColour(wx.Colour(128, 128, 128))
            text_col.Add(self.subtitle_label, 0, wx.TOP, 2)

        row.Add(text_col, 1, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 16)
        outer.AddSpacer(10)
        outer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 16)
        self.SetSizer(outer)

    def set_subtitle(self, subtitle: str) -> None:
        if self.subtitle_label is not None:
            self.subtitle_label.SetLabel(subtitle)

    def set_back_enabled(self, enabled: bool) -> None:
        if self.back_button is not None:
            self.back_button.Enable(enabled)


class IndeterminateProgressPanel(wx.Panel):
    """
    Reusable indeterminate loading/progress panel
    """

    def __init__(self, parent: wx.Window, global_constants: constants.Constants, title: str, message: str = "", back_label: str = None, on_back=None) -> None:
        super().__init__(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.header = PageHeader(self, title, back_label=back_label or gui_strings.NAV["return_main"], on_back=on_back)
        sizer.Add(self.header, 0, wx.EXPAND)

        sizer.AddStretchSpacer(1)

        self.status_label = wx.StaticText(self, label=message, style=wx.ALIGN_CENTER_HORIZONTAL)
        self.status_label.SetFont(font_factory(14, wx.FONTWEIGHT_NORMAL))
        sizer.Add(self.status_label, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.LEFT | wx.RIGHT, 30)
        sizer.AddSpacer(14)

        self.progress_bar = wx.Gauge(self, range=100, size=(340, 24), style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)
        sizer.Add(self.progress_bar, 0, wx.ALIGN_CENTER_HORIZONTAL)

        sizer.AddStretchSpacer(2)
        self.SetSizer(sizer)

        self._pulse = GaugePulseCallback(global_constants, self.progress_bar)
        self._pulse.start_pulse()

    def set_message(self, message: str) -> None:
        self.status_label.SetLabel(message)
        self.Layout()

    def stop(self) -> None:
        if self._pulse:
            self._pulse.stop_pulse()

    def Destroy(self) -> bool:
        self.stop()
        return super().Destroy()


class LogOutputPanel(wx.Panel):
    """
    Reusable log-streaming task view (used for Build, Install OpenCore, Root Patching)
    """

    def __init__(self, parent: wx.Window, title: str, subtitle: str = "", summary_lines: list = None, primary_label: str = None, on_primary=None, on_back=None) -> None:
        super().__init__(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.header = PageHeader(self, title, subtitle=subtitle, back_label=gui_strings.NAV["return_main"], on_back=on_back)
        self.header.set_back_enabled(False)
        sizer.Add(self.header, 0, wx.EXPAND)

        if summary_lines:
            summary = wx.StaticText(self, label="\n".join(summary_lines))
            summary.SetFont(font_factory(12, wx.FONTWEIGHT_NORMAL))
            sizer.Add(summary, 0, wx.LEFT | wx.RIGHT | wx.TOP, 16)

        self.text_box = wx.TextCtrl(self, value="", style=wx.TE_READONLY | wx.TE_MULTILINE | wx.TE_RICH2)
        self.text_box.SetFont(font_factory(12, wx.FONTWEIGHT_NORMAL))
        sizer.Add(self.text_box, 1, wx.EXPAND | wx.ALL, 16)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.primary_button = None
        if primary_label and on_primary is not None:
            self.primary_button = wx.Button(self, label=primary_label, size=(190, 30))
            self.primary_button.SetFont(font_factory(13, wx.FONTWEIGHT_NORMAL))
            self.primary_button.Bind(wx.EVT_BUTTON, lambda event: on_primary())
            self.primary_button.Disable()
            btn_row.Add(self.primary_button, 0, wx.RIGHT, 10)

        self.return_button = wx.Button(self, label=gui_strings.NAV["return_main"], size=(180, 30))
        self.return_button.SetFont(font_factory(13, wx.FONTWEIGHT_NORMAL))
        if on_back is not None:
            self.return_button.Bind(wx.EVT_BUTTON, lambda event: on_back())
        self.return_button.Disable()
        btn_row.Add(self.return_button, 0)

        sizer.Add(btn_row, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 16)
        self.SetSizer(sizer)

    def finish(self, enable_primary: bool = False) -> None:
        self.header.set_back_enabled(True)
        self.return_button.Enable(True)
        if self.primary_button is not None:
            self.primary_button.Enable(enable_primary)