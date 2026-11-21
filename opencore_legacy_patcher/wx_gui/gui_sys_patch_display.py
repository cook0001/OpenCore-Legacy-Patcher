"""
gui_sys_patch_display.py: In-window UI for displaying applicable root patches
"""

import wx
import logging
import plistlib
import threading

from pathlib import Path

from .. import constants
from ..sys_patch.patchsets import HardwarePatchsetDetection, HardwarePatchsetValidation
from ..wx_gui import gui_support, gui_strings


class SysPatchDisplayPanel(wx.Panel):
    """
    Detects and presents applicable root volume patches inside the main window
    """

    def __init__(self, parent: wx.Window, app, global_constants: constants.Constants) -> None:
        super().__init__(parent)
        logging.info("Initializing Root Patch Display Panel")
        self.app = app
        self.constants = global_constants
        self.available_patches = False
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
        self._set_step(
            gui_support.IndeterminateProgressPanel(
                self,
                self.constants,
                gui_strings.SYS_PATCH["display_title"],
                message=gui_strings.SYS_PATCH["fetching"],
                on_back=self.app.go_home,
            )
        )

        patches: dict = {}

        def _fetch():
            nonlocal patches
            patches = HardwarePatchsetDetection(constants=self.constants).device_properties

        thread = threading.Thread(target=_fetch)
        thread.start()
        gui_support.wait_for_thread(thread)

        self._render_summary(patches)

        if self.constants.update_stage != gui_support.AutoUpdateStages.INACTIVE and self.available_patches is False:
            gui_support.RestartHost(self.app).restart(message=gui_strings.SYS_PATCH["no_new_reboot"])

    def _render_summary(self, patches: dict) -> None:
        can_unpatch = not patches[HardwarePatchsetValidation.UNPATCHING_NOT_POSSIBLE]
        applicable = [
            patch for patch in patches
            if not patch.startswith("Settings") and not patch.startswith("Validation") and patches[patch] is True
        ]
        if not applicable:
            logging.info("No applicable patches available")
            patches = {}

        no_new_patches = not self._check_if_new_patches_needed(patches) if patches else False

        step = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(
            gui_support.PageHeader(
                step,
                gui_strings.SYS_PATCH["display_title"],
                subtitle=gui_strings.SYS_PATCH["available"],
                back_label=gui_strings.NAV["return_main"],
                on_back=self.app.go_home,
            ),
            0,
            wx.EXPAND,
        )

        scroll = wx.ScrolledWindow(step, style=wx.VSCROLL)
        scroll.SetScrollRate(0, 16)
        body = wx.BoxSizer(wx.VERTICAL)

        if not patches:
            lbl = wx.StaticText(scroll, label=gui_strings.SYS_PATCH["none_required"])
            lbl.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
            body.Add(lbl, 0, wx.ALL, 8)
        else:
            if no_new_patches:
                lbl = wx.StaticText(scroll, label=gui_strings.SYS_PATCH["already_installed"])
                lbl.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
                body.Add(lbl, 0, wx.ALL, 8)
            else:
                logging.info("Available patches:")
                for patch in applicable:
                    logging.info(f"- {patch}")
                    lbl = wx.StaticText(scroll, label=f"• {patch}")
                    lbl.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
                    body.Add(lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

            if patches[HardwarePatchsetValidation.PATCHING_NOT_POSSIBLE] is True:
                blk_hdr = wx.StaticText(scroll, label=gui_strings.SYS_PATCH["cannot_patch"])
                blk_hdr.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_BOLD))
                body.Add(blk_hdr, 0, wx.TOP | wx.BOTTOM, 8)

                for patch in patches:
                    if not patch.startswith("Validation") or patches[patch] is False:
                        continue
                    if patch in (HardwarePatchsetValidation.PATCHING_NOT_POSSIBLE, HardwarePatchsetValidation.UNPATCHING_NOT_POSSIBLE):
                        continue
                    reason = wx.StaticText(scroll, label=f"• {patch.split('Validation: ')[1]}")
                    reason.SetFont(gui_support.font_factory(12, wx.FONTWEIGHT_NORMAL))
                    reason.Wrap(540)
                    body.Add(reason, 0, wx.LEFT | wx.BOTTOM, 6)
            elif self.constants.computer.oclp_sys_version and self.constants.computer.oclp_sys_date:
                date_parts = self.constants.computer.oclp_sys_date.split(" @")
                date_str = date_parts[0] if len(date_parts) == 2 else ""
                hist_hdr = wx.StaticText(scroll, label=gui_strings.SYS_PATCH["last_patched"])
                hist_hdr.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_BOLD))
                body.Add(hist_hdr, 0, wx.TOP, 10)
                hist_val = wx.StaticText(scroll, label=f"{self.constants.computer.oclp_sys_version}, {date_str}")
                hist_val.SetFont(gui_support.font_factory(12, wx.FONTWEIGHT_NORMAL))
                hist_val.SetForegroundColour(wx.Colour(128, 128, 128))
                body.Add(hist_val, 0, wx.TOP, 4)

        scroll.SetSizer(body)
        scroll.FitInside()
        outer.Add(scroll, 1, wx.EXPAND | wx.ALL, 16)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        start_btn = wx.Button(step, label=gui_strings.SYS_PATCH["start_button"], size=(175, 32))
        start_btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        start_btn.Bind(wx.EVT_BUTTON, lambda event: self.app.navigate("sys_patch_start", patches=patches, action="patch"))
        btn_row.Add(start_btn, 0, wx.RIGHT, 10)

        revert_btn = wx.Button(step, label=gui_strings.SYS_PATCH["revert_button"], size=(175, 32))
        revert_btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        revert_btn.Bind(wx.EVT_BUTTON, lambda event: self.app.navigate("sys_patch_start", patches=patches, action="revert"))
        btn_row.Add(revert_btn, 0, wx.RIGHT, 10)

        ret_btn = wx.Button(step, label=gui_strings.NAV["return_main"], size=(165, 32))
        ret_btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        ret_btn.Bind(wx.EVT_BUTTON, lambda event: self.app.go_home())
        btn_row.Add(ret_btn, 0)

        if not patches:
            start_btn.Disable()
        else:
            self.available_patches = True
            if patches[HardwarePatchsetValidation.PATCHING_NOT_POSSIBLE] is True or no_new_patches:
                start_btn.Disable()
            else:
                start_btn.SetDefault()
        if not can_unpatch:
            revert_btn.Disable()

        outer.Add(btn_row, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 16)
        step.SetSizer(outer)
        self._set_step(step)

    def _check_if_new_patches_needed(self, patches: dict) -> bool:
        logging.info("Checking if new patches are needed")
        if self.constants.commit_info[0] in ["Running from source", "Built from source"]:
            return True
        if self.constants.computer.oclp_sys_url != self.constants.commit_info[2]:
            return True

        oclp_plist = "/System/Library/CoreServices/OpenCore-Legacy-Patcher.plist"
        if not Path(oclp_plist).exists():
            return True

        oclp_plist_data = plistlib.load(open(oclp_plist, "rb"))
        for patch in patches:
            if not patch.startswith("Settings") and not patch.startswith("Validation") and patches[patch] is True:
                if patch.split(": ")[1] not in oclp_plist_data:
                    logging.info(f"- Patch {patch} not installed")
                    return True

        logging.info("No new patches detected for system")
        return False