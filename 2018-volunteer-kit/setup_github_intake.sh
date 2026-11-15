#!/bin/zsh
emulate -L zsh
set -euo pipefail

REPO="cook0001/OpenCore-Legacy-Patcher"
SCRIPT_DIR="${0:A:h}"
DIST_DIR="$SCRIPT_DIR/dist"
RELEASE_TAG="2018-volunteer-kit-v1"
ISSUE_TITLE="[2018 T2 R&D] Post Your 2018 Mac Diagnostic Bundles Here"
LABEL_NAME="2018-volunteer-data"

if ! command -v gh >/dev/null 2>&1; then
    echo "gh CLI not found. Install GitHub CLI first." >&2
    exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
    echo "gh is not logged in. Run: gh auth login" >&2
    exit 1
fi

echo "Enabling GitHub Issues on $REPO ..."
gh repo edit "$REPO" --enable-issues

echo "Ensuring label $LABEL_NAME exists ..."
gh label create "$LABEL_NAME" \
    --repo "$REPO" \
    --color "1d76db" \
    --description "2018 T2 Mac hardware dumps, opencore logs, and USB maps" \
    --force

EXISTING_ISSUE="$(gh issue list --repo "$REPO" --search "$ISSUE_TITLE in:title" --state open --json number,title --jq '.[0].number // ""')"
if [[ -z "$EXISTING_ISSUE" ]]; then
    echo "Creating pinned volunteer data collection issue ..."
    ISSUE_URL="$(gh issue create \
        --repo "$REPO" \
        --title "$ISSUE_TITLE" \
        --label "$LABEL_NAME" \
        --body-file - <<'EOF'
Reply below and drag-and-drop your sanitized `2018-mac-diag-*.zip` bundle (plus an optional verbose panic screen photo for Mode 2).

Full instructions and safety notes are in `2018-volunteer-kit/README.md` on the `rd/2018-mac-support` branch:
https://github.com/cook0001/OpenCore-Legacy-Patcher/blob/rd/2018-mac-support/2018-volunteer-kit/README.md

### Copy-Paste Comment Template

- **Model (`sysctl -n hw.model`)**:
- **Mode (`Mode 1` / `Mode 2` / `Mode 3`)**:
- **macOS Version(s)**:
- **USB-A/USB-C ports populated before Mode 1?** (`Yes` / `No`):
- **Notes / Panic stage**:
- **Attachment**: *(drag and drop `2018-mac-diag-*.zip` here)*
EOF
)"
    ISSUE_NUM="${ISSUE_URL##*/}"
    gh issue pin "$ISSUE_NUM" --repo "$REPO"
    echo "Created and pinned: $ISSUE_URL"
else
    echo "Collection issue already open: https://github.com/$REPO/issues/$EXISTING_ISSUE"
fi

ASSETS=("$DIST_DIR"/*.zip(N))
if (( ${#ASSETS} == 0 )); then
    echo "No ZIP archives found in $DIST_DIR; run build_volunteer_kit.py first." >&2
    exit 1
fi
if gh release view "$RELEASE_TAG" --repo "$REPO" >/dev/null 2>&1; then
    echo "Updating release $RELEASE_TAG assets ..."
    gh release upload "$RELEASE_TAG" "${ASSETS[@]}" --repo "$REPO" --clobber
else
    echo "Creating prerelease $RELEASE_TAG with volunteer diagnostic EFIs ..."
    gh release create "$RELEASE_TAG" "${ASSETS[@]}" \
        --repo "$REPO" \
        --target "rd/2018-mac-support" \
        --prerelease \
        --title "2018 T2 Mac Volunteer Capture Kit" \
        --notes-file "$SCRIPT_DIR/README.md"
fi

echo "Done! Release and Issue intake configured for $REPO."
