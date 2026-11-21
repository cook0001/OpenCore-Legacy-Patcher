"""
gui_install_oc.py: In-window UI for installing OpenCore to disk
"""

import wx
import logging
import threading
import traceback

from .. import constants
from ..datasets import os_data
from ..support import install
from ..wx_gui import gui_support, gui_strings


class InstallOCPanel(wx.Panel):
    """
    Multi-step disk/volume selection and OpenCore installation panel
    """

    def __init__(self, parent: wx.Window, app, global_constants: constants.Constants) -> None:
        super().__init__(parent)
        logging.info("Initializing Install OpenCore Panel")
        self.app = app
        self.constants = global_constants
        self.available_disks: dict = {}
        self.result: bool = False
        self.active_step: wx.Panel = None

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.sizer)

        if self.constants.update_stage != gui_support.AutoUpdateStages.INACTIVE:
            self.constants.update_stage = gui_support.AutoUpdateStages.INSTALLING

    def start(self) -> None:
        self._scan_disks()

    def _set_step(self, panel: wx.Panel) -> None:
        if self.active_step is not None:
            self.sizer.Detach(self.active_step)
            self.active_step.Destroy()
        self.active_step = panel
        self.sizer.Add(panel, 1, wx.EXPAND)
        self.Layout()

    def _scan_disks(self) -> None:
        self._set_step(
            gui_support.IndeterminateProgressPanel(
                self,
                self.constants,
                gui_strings.INSTALL_OC["title"],
                message=gui_strings.INSTALL_OC["fetching_disks"],
                on_back=self.app.go_home,
            )
        )

        thread = threading.Thread(target=self._fetch_disks)
        thread.start()
        gui_support.wait_for_thread(thread)
        self._show_disk_list()

    def _fetch_disks(self) -> None:
        self.available_disks = install.disk_installation(self.constants).list_disks() or {}
        ignore = ("disk image", "read-only", "virtual")
        for disk in list(self.available_disks.keys()):
            if any(token in self.available_disks[disk]["name"].lower() for token in ignore):
                del self.available_disks[disk]

    def _show_disk_list(self) -> None:
        step = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(
            gui_support.PageHeader(
                step,
                gui_strings.INSTALL_OC["title"],
                subtitle=gui_strings.INSTALL_OC["select_disk"],
                back_label=gui_strings.NAV["return_main"],
                on_back=self.app.go_home,
            ),
            0,
            wx.EXPAND,
        )

        note = wx.StaticText(step, label=gui_strings.INSTALL_OC["gpt_note"])
        note.SetFont(gui_support.font_factory(11, wx.FONTWEIGHT_NORMAL))
        note.SetForegroundColour(wx.Colour(128, 128, 128))
        outer.Add(note, 0, wx.LEFT | wx.RIGHT | wx.TOP, 16)

        scroll = wx.ScrolledWindow(step, style=wx.VSCROLL)
        scroll.SetScrollRate(0, 16)
        list_sizer = wx.BoxSizer(wx.VERTICAL)

        disk_root = None
        if self.constants.booted_oc_disk and self.constants.custom_model is None:
            stripped = self.constants.booted_oc_disk.replace("disk", "", 1)
            disk_root = "disk" + stripped.split("s")[0]
            logging.info(f"Checking if booted disk is present: {disk_root}")

        if self.available_disks:
            logging.info("Available disks:")
            single_item = len(self.available_disks) == 1
            for disk_key, info in self.available_disks.items():
                logging.info(f"- {info['disk']} - {info['name']} - {info['size']}")
                is_booted = disk_root == info["disk"]
                prefix = "* " if is_booted else ""
                btn = wx.Button(scroll, label=f"{prefix}{info['disk']} - {info['name']} - {info['size']}", size=(460, 32))
                btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
                btn.Bind(wx.EVT_BUTTON, lambda event, dk=disk_key: self._show_volumes(dk))
                if is_booted or single_item:
                    btn.SetDefault()
                list_sizer.Add(btn, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 8)
        else:
            empty = wx.StaticText(scroll, label=gui_strings.INSTALL_OC["no_disks"])
            empty.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_BOLD))
            list_sizer.Add(empty, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.TOP, 20)

        scroll.SetSizer(list_sizer)
        scroll.FitInside()
        outer.Add(scroll, 1, wx.EXPAND | wx.ALL, 16)

        if disk_root:
            booted_note = wx.StaticText(step, label=gui_strings.INSTALL_OC["booted_note"])
            booted_note.SetFont(gui_support.font_factory(11, wx.FONTWEIGHT_NORMAL))
            booted_note.SetForegroundColour(wx.Colour(128, 128, 128))
            outer.Add(booted_note, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 6)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        rescan_btn = wx.Button(step, label=gui_strings.INSTALL_OC["search_again"], size=(160, 30))
        rescan_btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        rescan_btn.Bind(wx.EVT_BUTTON, lambda event: self._scan_disks())
        btn_row.Add(rescan_btn, 0, wx.RIGHT, 10)

        back_btn = wx.Button(step, label=gui_strings.NAV["return_main"], size=(170, 30))
        back_btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        back_btn.Bind(wx.EVT_BUTTON, lambda event: self.app.go_home())
        btn_row.Add(back_btn, 0)

        outer.Add(btn_row, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 16)
        step.SetSizer(outer)
        self._set_step(step)

    def _show_volumes(self, disk_key: str) -> None:
        step = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(
            gui_support.PageHeader(
                step,
                gui_strings.INSTALL_OC["volumes_title"].format(disk=disk_key),
                back_label=gui_strings.NAV["back"],
                on_back=self._show_disk_list,
            ),
            0,
            wx.EXPAND,
        )

        scroll = wx.ScrolledWindow(step, style=wx.VSCROLL)
        scroll.SetScrollRate(0, 16)
        list_sizer = wx.BoxSizer(wx.VERTICAL)

        partitions = install.disk_installation(self.constants).list_partitions(disk_key, self.available_disks) or {}
        single_part = len(partitions) == 1
        logging.info(f"Available partitions for {disk_key}:")
        for part_key, pinfo in partitions.items():
            logging.info(f"- {pinfo['partition']} - {pinfo['name']} - {pinfo['size']}")
            btn = wx.Button(scroll, label=f"{pinfo['partition']} - {pinfo['name']} - {pinfo['size']}", size=(460, 32))
            btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
            btn.Bind(wx.EVT_BUTTON, lambda event, p=part_key: self._run_install(p))
            if single_part or self.constants.booted_oc_disk == pinfo["partition"]:
                btn.SetDefault()
            list_sizer.Add(btn, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 8)

        scroll.SetSizer(list_sizer)
        scroll.FitInside()
        outer.Add(scroll, 1, wx.EXPAND | wx.ALL, 16)

        back_btn = wx.Button(step, label=gui_strings.NAV["return_main"], size=(170, 30))
        back_btn.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        back_btn.Bind(wx.EVT_BUTTON, lambda event: self.app.go_home())
        outer.Add(back_btn, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 16)

        step.SetSizer(outer)
        self._set_step(step)

    def _run_install(self, partition: str) -> None:
        log_panel = gui_support.LogOutputPanel(
            self,
            title=gui_strings.INSTALL_OC["installing_title"].format(partition=partition),
            on_back=self.app.go_home,
        )
        self._set_step(log_panel)
        self.result = False

        self.app.set_busy(True, "installing OpenCore")
        try:
            def _worker():
                logging.info(f"Installing OpenCore to {partition}")
                with gui_support.capture_logs(log_panel.text_box):
                    try:
                        self.result = install.disk_installation(self.constants).install_opencore(partition)
                    except Exception:
                        logging.error("An internal error occurred while installing:\n")
                        logging.error(traceback.format_exc())

            thread = threading.Thread(target=_worker)
            thread.start()
            gui_support.wait_for_thread(thread)
        finally:
            self.app.set_busy(False)

        log_panel.finish()

        if self.result is True:
            if self.constants.update_stage != gui_support.AutoUpdateStages.INACTIVE and self.constants.detected_os >= os_data.os_data.big_sur:
                self.constants.update_stage = gui_support.AutoUpdateStages.UNPATCHING
                dlg = wx.MessageDialog(
                    self.app,
                    gui_strings.INSTALL_OC["update_patches_msg"],
                    "Success",
                    wx.YES_NO | wx.YES_DEFAULT,
                )
                if dlg.ShowModal() == wx.ID_YES:
                    self.app.navigate("sys_patch_display")
                return

            if not self.constants.custom_model:
                gui_support.RestartHost(self.app).restart(message=gui_strings.INSTALL_OC["reboot_msg"])
            else:
                wx.MessageDialog(
                    self.app,
                    gui_strings.INSTALL_OC["eject_msg"].format(model=self.constants.custom_model),
                    "Success",
                    wx.OK,
                ).ShowModal()
        elif self.constants.update_stage != gui_support.AutoUpdateStages.INACTIVE:
            self.constants.update_stage = gui_support.AutoUpdateStages.FINISHED
