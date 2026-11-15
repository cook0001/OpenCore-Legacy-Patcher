# 2018 Mac Volunteer Capture Kit

These read-only tools collect hardware dumps, USB port maps, OpenCore debug logs (`opencore-*.txt`), and `BridgePatcher`/T2 diagnostics from **2018 T2 Macs** (`MacBookAir8,1`, `MacBookPro15,1`, `MacBookPro15,2`, `Macmini8,1`) without modifying your internal macOS drive.

Sibling models (`MacBookAir8,2`, `MacBookPro15,3`, `MacBookPro15,4`) are also welcome as reference captures.

To check your exact identifier in Terminal:
```sh
sysctl -n hw.model
```

---

## Where to Get the Files

- **Mode 1 only (script runs directly on your current macOS)**:
  Download [collect_2018_mac_diagnostics.command](https://raw.githubusercontent.com/cook0001/OpenCore-Legacy-Patcher/rd/2018-mac-support/2018-volunteer-kit/collect_2018_mac_diagnostics.command) (or `2018-Native-Capture-Kit.zip` from [Releases](https://github.com/cook0001/OpenCore-Legacy-Patcher/releases)).
- **Mode 2 (external USB debug OpenCore EFIs)**:
  Download `<Model>-Diag-EFI.zip` for your Mac model from [Releases](https://github.com/cook0001/OpenCore-Legacy-Patcher/releases).

Note on macOS Gatekeeper: Running via `zsh ./collect_2018_mac_diagnostics.command` in Terminal works directly without needing Xcode Command Line Tools, Homebrew, or `chmod +x`, and avoids Finder's unsigned `.command` double-click block.

---

## Mode 1: Zero-Risk Native Hardware & USB Map Capture (Start Here)

Run this on your normal **Sonoma or Sequoia** install. No reboot, no SIP changes, and no USB installer required (~5 seconds):

1. **Before running the script**, briefly plug a USB drive, mouse, or USB-C adapter into **every physical USB-A, USB-C, and Thunderbolt port** on your Mac (test both a USB 2.0 device and a USB 3.0 device if you have both). On 2018 Macs, unused Thunderbolt USB controllers power down and will not appear in IORegistry until awakened.
2. Open **Terminal** in the folder containing the script and run:
   ```sh
   zsh ./collect_2018_mac_diagnostics.command
   ```
   (Or run `curl -fsSLO https://raw.githubusercontent.com/cook0001/OpenCore-Legacy-Patcher/rd/2018-mac-support/2018-volunteer-kit/collect_2018_mac_diagnostics.command && zsh ./collect_2018_mac_diagnostics.command` after inspecting the script.)
3. Upload the generated `2018-mac-diag-*.zip` (written next to the script or in your `$HOME` folder).

What Mode 1 gives us:
- Exact board IDs (`IODeviceTree`, e.g. checking `MacBookAir8,1` variants), Intel/AMD GPU PCI IDs, Broadcom Wi-Fi/BT, Ethernet, and NVMe controller info.
- Full `AppleUSBXHCIPCI` / `AppleUSBXHCI` / `IOUSBHostDevice` IORegistry XML dumps needed to build OCLP `USBMaps/<Model>.plist` for macOS Tahoe.
- Native T2/SEP service trees (`AppleSEPManager`, `AppleUSBiBridge`, `IOBufferCopyController`, `AppleKeyStore`, `BridgeAudio*`).

---

## Mode 2: Capture `opencore-*.txt` on a Spare External USB Drive

This captures where unmodified DEBUG OpenCore + verbose macOS Tahoe stops on a 2018 T2 Mac without touching your internal drive or NVRAM.

### One-Time T2 Security Preparation (Required for External USB EFI Boot)

By default, 2018 T2 Macs block booting `EFI Boot` from external USB drives:
1. Shut down, power on, and hold **`Command + R`** to enter **macOS Recovery**.
2. Choose **Utilities -> Startup Security Utility** (unlock with your admin password).
3. Temporarily select **No Security** and **Allow booting from external or removable media**.
4. You can restore **Full Security** / **Disallow booting from external media** at any time after testing.

### Boot & Capture Steps

1. Prepare a **spare USB flash drive or external USB SSD** formatted as **GPT / FAT32** (or use an external macOS Tahoe installer USB whose EFI partition you want to test with).
2. Extract `<Model>-Diag-EFI.zip` for your Mac (`MacBookAir8,1`, `MacBookPro15,1`, `MacBookPro15,2`, or `Macmini8,1`) and copy the `EFI` folder onto the **USB drive's `EFI` partition** (never onto your internal disk).
   - This config uses OpenCore DEBUG (`Target=0x43`, `DisplayLevel=0x80000042`), verbose `-v`, `-liludbgall liludump=90`, `DebugEnhancer.kext`, `SecureBootModel=Disabled`, and neutral serial settings.
3. Reboot holding **`Option` (`Alt`)**, select **`EFI Boot`**, and attempt booting your **external Tahoe installer or external test volume**.
4. If macOS kernel panics or hangs after OpenCore hands off to the kernel, **take a clear photo of the screen** showing the panic backtrace (`AppleSEPManager`, `AppleKeyStore`, `IOBufferCopyController`, `AppleCredentialManager`, etc.).
5. Reboot back into your normal internal macOS install with the test USB still plugged in, then mount the USB drive's `EFI` partition in Terminal:
   ```sh
   diskutil list external
   sudo diskutil mount diskXs1    # replace diskXs1 with the EFI partition ID shown above
   ```
6. Run the collector pointing at the mounted EFI volume (replace `/Volumes/EFI` if mounted at `/Volumes/EFI 1`):
   ```sh
   zsh ./collect_2018_mac_diagnostics.command --efi /Volumes/EFI
   ```
7. Upload the new `2018-mac-diag-*.zip` together with your screen photo.

---

## Mode 3: Working or Test `BridgePatcher` Reference Capture

If you have already booted or tested **BridgePatcher** on an external test volume:

1. Mount your test EFI partition if it is not already mounted (`diskutil list` + `sudo diskutil mount diskXs1`).
2. Run:
   ```sh
   zsh ./collect_2018_mac_diagnostics.command --efi /Volumes/EFI
   ```
3. Upload the generated `.zip`. It captures:
   - Sanitized `EFI/OC/config.plist` (`ACPI->Add`, `Kernel->Block/Patch/Add`, `NVRAM boot-args`, `SecureBootModel`) and recursive `EFI/OC` file inventory
   - `opencore-*.txt` and `Lilu_*.txt` logs if present
   - Loaded third-party/T2/USB kexts (`kmutil showloaded` / `kextstat`), `/Library/Extensions` listing, `csrutil status` / `authenticated-root status`, APFS snapshot layout
   - T2 SEP / `AppleUSBiBridge` / `IOBufferCopyController` / `BridgeAudio*` IORegistry dumps and `/Library/Logs/DiagnosticReports` kernel/Bridge/SEP reports

---

## Privacy & Redaction

Before zipping, the collector automatically strips or replaces:
- `SystemSerialNumber`, `MLB`, `SystemUUID`, and `ROM` from any copied `config.plist` (`PlistBuddy Delete`)
- Hardware serial numbers, Hardware UUIDs, Provisioning UDIDs, MAC addresses, `uuid_sha1`, `OCLP-Spoofed-*`, and `fmm-mobileme-token-*` values in text outputs
- Local macOS usernames in `/Users/<name>` paths

You are always welcome to unzip and inspect `2018-mac-diag-*.zip` before posting it.

---

## Where to Post Your `.zip` Bundle

Post your `2018-mac-diag-*.zip` (and optional Mode 2 screen photo) on the repository's **Issues** tab:
- **Repository Issues**: https://github.com/cook0001/OpenCore-Legacy-Patcher/issues
  - Use either the pinned **`[2018 T2 R&D] Post Your 2018 Mac Diagnostic Bundles Here`** thread (just reply and drag-and-drop your `.zip`) or click **New Issue -> 2018 T2 Mac Volunteer Data**.
  - Include your `hw.model`, capture mode (`Mode 1` / `Mode 2` / `Mode 3`), and macOS version tested.
  - GitHub supports `.zip` attachments up to 25 MB in comments; typical diagnostic bundles are well under 1 MB. If a bundle is larger, attach a file-sharing link instead.

---

## Maintainer Quick Reference

Extract draft `USBMaps/<Model>.plist`, PCI IDs, panic summaries, `opencore-*.txt` highlights, and sanitized `config.plist` diffs from any volunteer bundle:

```sh
python3 2018-volunteer-kit/parse_volunteer_bundle.py path/to/2018-mac-diag-*.zip --usb-out draft_usb.plist
```
