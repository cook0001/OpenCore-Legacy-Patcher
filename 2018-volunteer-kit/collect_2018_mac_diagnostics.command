#!/bin/zsh
emulate -L zsh
setopt NULL_GLOB

SCRIPT_DIR="${0:A:h}"
EFI_PATH=""
OUT_DIR=""

usage() {
    cat <<'EOF'
Usage: collect_2018_mac_diagnostics.command [--efi PATH] [--out DIR]

Read-only diagnostic collector for 2018 T2 Macs (MacBookAir8,1, MacBookPro15,1,
MacBookPro15,2, Macmini8,1). Captures:
  - OpenCore logs (opencore-*.txt) and kernel/Bridge/SEP panic reports
  - Sanitized EFI/OC/config.plist, Kexts/ACPI inventory, OCLP/BridgePatcher logs
  - Raw IORegistry XML dumps for generating USBMaps/*.plist and hardware probes
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --efi)
            EFI_PATH="${2:-}"
            shift 2
            ;;
        --out)
            OUT_DIR="${2:-}"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

MODEL="$(/usr/sbin/sysctl -n hw.model 2>/dev/null || echo unknown-model)"
STAMP="$(/bin/date +%Y%m%d-%H%M%S)"

if [[ -z "$OUT_DIR" ]]; then
    if [[ -w "$SCRIPT_DIR" ]]; then
        OUT_DIR="$SCRIPT_DIR"
    else
        OUT_DIR="$HOME"
    fi
fi
/bin/mkdir -p "$OUT_DIR"

WORK_DIR="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/2018-mac-diag.XXXXXX")"
STAGE_DIR="$WORK_DIR/2018-mac-diag-${MODEL}-${STAMP}"
trap '/bin/rm -rf "$WORK_DIR"' EXIT

/bin/mkdir -p "$STAGE_DIR/ioreg" "$STAGE_DIR/efi_and_logs/panics" "$STAGE_DIR/efi_and_logs/efis"

sanitize_text() {
    LC_ALL=C /usr/bin/sed -E \
        -e "s/Serial Number \(system\):.*/Serial Number (system): [REDACTED]/g" \
        -e "s/Hardware UUID:.*/Hardware UUID: [REDACTED]/g" \
        -e "s/Provisioning UDID:.*/Provisioning UDID: [REDACTED]/g" \
        -e "s/MAC Address:.*/MAC Address: [REDACTED]/g" \
        -e "s/'uuid_sha1': '[^']*'/'uuid_sha1': '[REDACTED]'/g" \
        -e "s/(OCLP-Spoofed-SN|OCLP-Spoofed-MLB|fmm-mobileme-token-[^[:space:]]+|SystemSerialNumber[[:space:]:=]|MLB[[:space:]:=]).*/\1 [REDACTED]/g" \
        -e "s|/Users/[^/[:space:]'\"]+|/Users/[REDACTED]|g"
}

sanitize_config_plist() {
    local dst="$1"
    for key in SystemSerialNumber MLB SystemUUID ROM; do
        /usr/libexec/PlistBuddy -c "Delete :PlatformInfo:Generic:${key}" "$dst" 2>/dev/null || true
    done
}

echo "Collecting read-only diagnostics for $MODEL ..."

{
    echo "=== Timestamp ==="
    /bin/date -u
    echo
    echo "=== OS & Hardware ==="
    /usr/bin/sw_vers 2>&1
    /usr/bin/uname -a 2>&1
    /usr/sbin/sysctl hw.model machdep.cpu.brand_string kern.osversion kern.osrelease 2>&1
    echo
    echo "=== Board ID (IODeviceTree) ==="
    /usr/sbin/ioreg -l -p IODeviceTree -d 2 2>&1 | /usr/bin/grep -E '"(model|board-id|compatible)"' || true
    echo
    echo "=== SIP, Root Sealing & FileVault ==="
    /usr/bin/csrutil status 2>&1 || true
    /usr/bin/csrutil authenticated-root status 2>&1 || true
    /usr/bin/fdesetup status 2>&1 || true
    echo
    echo "=== NVRAM (Filtered) ==="
    /usr/sbin/nvram -p 2>&1 | sanitize_text || true
    echo
    echo "=== Disks, APFS Snapshots & Mounted Volumes ==="
    /usr/sbin/diskutil list 2>&1 || true
    /usr/sbin/diskutil apfs list 2>&1 || true
    echo
    echo "=== /Library/Extensions ==="
    /bin/ls -la /Library/Extensions 2>&1 || true
    echo
    echo "=== Loaded Non-Apple / Third-Party / USB / T2 Kexts ==="
    if /usr/bin/kmutil showloaded --no-kernel-components >/dev/null 2>&1; then
        /usr/bin/kmutil showloaded --no-kernel-components 2>&1
    else
        /usr/sbin/kextstat -l 2>&1
    fi
} > "$STAGE_DIR/summary.txt"

{
    /usr/sbin/system_profiler \
        SPHardwareDataType \
        SPiBridgeDataType \
        SPDisplaysDataType \
        SPAudioDataType \
        SPNVMeDataType \
        SPNetworkDataType \
        SPUSBHostDataType 2>&1
} | sanitize_text > "$STAGE_DIR/system_profiler.txt"

/usr/sbin/ioreg -a -l -c AppleUSBXHCIPCI -r > "$STAGE_DIR/ioreg/usb_xhci.plist" 2>/dev/null || true
/usr/sbin/ioreg -a -l -c AppleUSBXHCI -r > "$STAGE_DIR/ioreg/usb_xhci_all.plist" 2>/dev/null || true
/usr/sbin/ioreg -a -l -c AppleUSBHostController -r > "$STAGE_DIR/ioreg/usb_hosts.plist" 2>/dev/null || true
/usr/sbin/ioreg -a -l -c IOUSBHostDevice -r > "$STAGE_DIR/ioreg/usb_devices.plist" 2>/dev/null || true
/usr/sbin/ioreg -a -l -c IOPCIDevice -r > "$STAGE_DIR/ioreg/pci_devices.plist" 2>/dev/null || true
/usr/sbin/ioreg -a -l -p IODeviceTree > "$STAGE_DIR/ioreg/devicetree.plist" 2>/dev/null || true

{
    for cls in AppleSEPManager AppleUSBiBridge IOBufferCopyController AppleKeyStore BridgeAudioController BridgeAudioCommunication; do
        echo "=== ioreg class: $cls ==="
        /usr/sbin/ioreg -l -w0 -c "$cls" -r 2>&1 || true
        echo
    done
} | sanitize_text > "$STAGE_DIR/ioreg/t2_services.txt"

OC_LOG_COUNT=0
EFI_COUNT=0

copy_oc_logs_from() {
    local root_dir="$1"
    local f
    for f in \
        "$root_dir"/opencore-*.txt "$root_dir"/EFI/opencore-*.txt "$root_dir"/EFI/OC/opencore-*.txt \
        "$root_dir"/Lilu_*.txt "$root_dir"/EFI/Lilu_*.txt "$root_dir"/EFI/OC/Lilu_*.txt
    do
        if [[ -f "$f" ]]; then
            local base="${f:t}"
            sanitize_text < "$f" > "$STAGE_DIR/efi_and_logs/${OC_LOG_COUNT}_${base}"
            ((OC_LOG_COUNT++))
        fi
    done
}

copy_efi_tree_from() {
    local efi_root="$1"
    local tag="$2"
    if [[ -d "$efi_root/EFI/OC" ]]; then
        local dst="$STAGE_DIR/efi_and_logs/efis/$tag"
        /bin/mkdir -p "$dst"
        if [[ -f "$efi_root/EFI/OC/config.plist" ]]; then
            /bin/cp "$efi_root/EFI/OC/config.plist" "$dst/config.plist"
            sanitize_config_plist "$dst/config.plist"
        fi
        {
            echo "=== ACPI ==="
            /bin/ls -la "$efi_root/EFI/OC/ACPI" 2>&1 || true
            echo "=== Kexts ==="
            /bin/ls -la "$efi_root/EFI/OC/Kexts" 2>&1 || true
            echo "=== Drivers ==="
            /bin/ls -la "$efi_root/EFI/OC/Drivers" 2>&1 || true
            echo "=== EFI/OC Tree (depth 3) ==="
            /usr/bin/find "$efi_root/EFI/OC" -maxdepth 3 2>&1 | LC_ALL=C /usr/bin/sort || true
        } > "$dst/inventory.txt"
        ((EFI_COUNT++))
    fi
}

if [[ -n "$EFI_PATH" && -d "$EFI_PATH" ]]; then
    copy_oc_logs_from "$EFI_PATH"
    copy_efi_tree_from "$EFI_PATH" "specified_efi"
fi

local_idx=0
for vol in /Volumes/*; do
    [[ -d "$vol" ]] || continue
    copy_oc_logs_from "$vol"
    if [[ -d "$vol/EFI/OC" ]]; then
        copy_efi_tree_from "$vol" "vol_${local_idx}_${vol:t}"
        ((local_idx++))
    fi
done

if [[ -d "/EFI/OC" ]]; then
    copy_oc_logs_from "/"
    copy_efi_tree_from "/" "root_efi"
fi

PANIC_COUNT=0
typeset -U panic_files
panic_files=(
    /Library/Logs/DiagnosticReports/*.panic(N.om[1,10])
    /Library/Logs/DiagnosticReports/*Bridge*(N.om[1,10])
    /Library/Logs/DiagnosticReports/*SEP*(N.om[1,10])
    /Library/Logs/DiagnosticReports/*.ips(N.om[1,10])
)
for panic_file in "${panic_files[@]}"; do
    # Keep kernel/panic/SEP/Bridge reports, skip unrelated user/app .ips telemetry
    case "${panic_file:t}" in
        *.ips)
            case "${panic_file:t}" in
                *kernel*|*panic*|*Bridge*|*SEP*) ;;
                *) continue ;;
            esac
            ;;
    esac
    sanitize_text < "$panic_file" > "$STAGE_DIR/efi_and_logs/panics/${panic_file:t}"
    ((PANIC_COUNT++))
done

APP_LOG_COUNT=0
app_logs=( "$HOME/Library/Logs/Dortania"/OpenCore-Patcher_*.log(N.om[1,4]) "$HOME/Library/Logs"/*Bridge*/*.log(N.om[1,4]) )
for log_file in "${app_logs[@]}"; do
    sanitize_text < "$log_file" > "$STAGE_DIR/efi_and_logs/${log_file:t}"
    ((APP_LOG_COUNT++))
done

OUT_ZIP="$OUT_DIR/2018-mac-diag-${MODEL}-${STAMP}.zip"
(cd "$WORK_DIR" && /usr/bin/zip -rq "$OUT_ZIP" "2018-mac-diag-${MODEL}-${STAMP}")

echo
echo "Done! Bundle written to:"
echo "  $OUT_ZIP"
echo
echo "Captured:"
echo "  - Hardware / IOReg USB XML / T2 services / system_profiler"
echo "  - opencore-*.txt logs: $OC_LOG_COUNT"
echo "  - Sanitized EFI/OC trees: $EFI_COUNT"
echo "  - Panic/Bridge/SEP diagnostic reports: $PANIC_COUNT"
echo "  - Patcher app logs: $APP_LOG_COUNT"
if [[ $OC_LOG_COUNT -eq 0 ]]; then
    echo
    echo "Note: No opencore-*.txt found on currently mounted /Volumes/*."
    echo "If you booted from a test USB EFI partition, mount that EFI partition first and re-run with:"
    echo "  ./collect_2018_mac_diagnostics.command --efi /Volumes/EFI"
fi
