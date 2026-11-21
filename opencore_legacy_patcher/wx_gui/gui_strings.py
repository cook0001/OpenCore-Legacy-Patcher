"""
gui_strings.py: Centralized user-facing UI strings for localization readiness
"""


APP_NAME = "OpenCore Legacy Patcher"

NAV = {
    "return_main": "Return to Main Menu",
    "back": "Back",
    "close": "Close",
    "cancel": "Cancel",
    "refresh": "Refresh",
}

MAIN_MENU = {
    "build_title": "Build and Install OpenCore",
    "build_desc": "Build an OpenCore configuration and\ninstall it to an internal or USB drive.",
    "installer_title": "Create macOS Installer",
    "installer_desc": "Download macOS or flash an existing\ninstaller onto a USB drive.",
    "patch_title": "Post-Install Root Patch",
    "patch_desc": "Install hardware drivers and root\npatches after macOS installation.",
    "help_title": "Help & Resources",
    "help_desc": "Guides, troubleshooting docs, and\ncommunity support links.",
    "settings": "Settings",
    "credits": "Credits",
    "unsupported_config_title": "Unsupported Configuration Detected!",
    "unsupported_config_msg": (
        "This Mac is booting OpenCore built for a different model ({build_model}).\n\n"
        "Configs are tailored per model and should not be reused across different Macs.\n\n"
        "Please build and install a new OpenCore config, then reboot."
    ),
    "post_update_title": "Update Successful!",
    "post_update_msg": (
        "OpenCore Legacy Patcher has been updated to {version}.\n\n"
        "Would you like to update OpenCore and your root volume patches?"
    ),
    "update_available_title": "A new version of OpenCore Legacy Patcher is available!",
    "update_available_desc": "Version {new_version} is available (currently running {current_version}). Would you like to update?",
    "changelog_unavailable": "## Unable to fetch changelog\n\nPlease check the GitHub release page for details.",
    "dismiss": "Dismiss",
    "view_github": "View on GitHub",
    "download_install": "Download and Install",
    "welcome_title": "Welcome",
    "credits_title": "Credits",
}

ABOUT = {
    "title": "About",
    "tagline": "Written by Mac hobbyists dedicated to keeping\nolder Macs out of landfills.",
}

HELP = {
    "title": "Help & Support Resources",
    "subtitle": "Guides and community resources for OpenCore Legacy Patcher:",
    "official_guide": "Official Guide",
    "phone_support": "Official Phone Support",
    "discord": "Community Discord Server",
}

DOWNLOAD = {
    "title": "Downloading: {item}",
    "preparing": "Preparing download...",
    "cancel_title": "Cancel Download",
    "cancel_msg": "Are you sure you want to cancel this download?",
    "failed_msg": "Download failed:\n{error}",
}

BUILD = {
    "title": "Build and Install OpenCore",
    "install_button": "Install OpenCore to Disk",
    "error_title": "Error Building OpenCore",
    "error_msg": "An error occurred while building OpenCore.",
    "done_title": "OpenCore Build Complete",
    "done_msg": "Would you like to install the built OpenCore configuration to a disk now?",
    "install_now": "Install to Disk",
    "view_log": "View Build Log",
}

INSTALL_OC = {
    "title": "Install OpenCore",
    "fetching_disks": "Scanning local disks...",
    "select_disk": "Select a target disk to install OpenCore onto:",
    "gpt_note": "Missing a disk? Ensure it is GUID/GPT partitioned with a FAT32 EFI partition.",
    "booted_note": "Marked disk (*): Currently booted OpenCore drive.",
    "no_disks": "No eligible GPT/FAT32 disks found.",
    "search_again": "Scan Disks Again",
    "volumes_title": "Select EFI Partition on {disk}",
    "installing_title": "Installing OpenCore to {partition}",
    "update_patches_msg": "OpenCore has finished installing to disk.\n\nWould you like to update your root patches next? This will require a reboot.",
    "reboot_msg": "OpenCore has finished installing to disk.\n\nReboot, hold the Option key, and choose EFI Boot / OpenCore.\n\nWould you like to reboot now?",
    "eject_msg": "OpenCore has finished installing to disk.\n\nYou can eject the drive, insert it into the {model}, reboot holding Option, and select EFI Boot.",
}

SYS_PATCH = {
    "display_title": "Post-Install Root Patch",
    "fetching": "Detecting applicable patches for this Mac...",
    "available": "Applicable root patches for your system:",
    "none_required": "No root patches are required for this system.",
    "already_installed": "All applicable root patches are already installed.",
    "cannot_patch": "Root patching is currently blocked:",
    "last_patched": "Root volume last patched:",
    "start_button": "Start Root Patching",
    "revert_button": "Revert Root Patches",
    "patching_title": "Installing Root Patches",
    "reverting_title": "Reverting Root Patches",
    "will_patch": "Applying the following patches:",
    "reverting_desc": "Reverting root volume to the last sealed APFS snapshot...",
    "no_new_reboot": "No new root patch updates are required.\n\nWould you like to reboot to apply your updated OpenCore build?",
}

INSTALLER = {
    "choice_title": "Create macOS Installer",
    "download_btn": "Download macOS Installer",
    "existing_btn": "Use Existing macOS Installer",
    "fetching_catalog": "Fetching available macOS installers...",
    "catalog_title": "Select macOS Installer to Download",
    "copy_link": "Copy Link",
    "copied_msg": "Download link copied to clipboard.",
    "show_older": "Show Older / Beta Versions",
    "extracting_title": "Extracting macOS Installer",
    "extracting_desc": "Extracting InstallAssistant.pkg... This may take a few minutes.",
    "extract_ok": "Successfully extracted macOS installer.",
    "extract_fail": "Failed to extract macOS installer.",
    "flash_prompt_title": "Create macOS Installer?",
    "flash_prompt_msg": "Finished extracting the installer. Would you like to flash it to a USB drive now?",
    "fetching_local": "Scanning /Applications for macOS installers...",
    "select_local": "Select a local macOS Installer:",
    "no_local": "No macOS installers found in /Applications.",
    "fetching_usb": "Scanning local disks...",
    "select_usb": "Select target USB drive (ALL DATA WILL BE ERASED):",
    "no_usb": "No eligible USB or external disks found.",
    "rescan_usb": "Rescan Disks",
}

SETTINGS = {
    "title": "Settings",
    "target_model": "Target Model",
    "target_model_desc": "Overrides the Mac model used for builds.",
    "reset_btn": "Reset Settings",
    "rebuild_btn": "Rebuild OpenCore",
    "reset_confirm_title": "Reset Settings?",
    "reset_confirm_msg": "Reset all OpenCore Legacy Patcher settings back to defaults?\n\nThis removes saved overrides in /Users/Shared/.com.dortania.opencore-legacy-patcher.plist.",
    "reset_error_msg": "Failed to reset settings file. Check permissions on /Users/Shared/.com.dortania.opencore-legacy-patcher.plist.",
    "rebuild_prompt_title": "Rebuild OpenCore?",
    "rebuild_prompt_msg": "OpenCore build settings were modified.\n\nWould you like to apply these settings and rebuild OpenCore now?",
}
