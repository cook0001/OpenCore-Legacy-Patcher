# Privacy Policy

**Repository:** [https://github.com/cook0001/OpenCore-Legacy-Patcher](https://github.com/cook0001/OpenCore-Legacy-Patcher)  
**Project Site:** [https://oclp.patchcraft.dev/](https://oclp.patchcraft.dev/)  
**Legal & Attributions:** [https://patchcraft.dev/legal.html](https://patchcraft.dev/legal.html)

## Telemetry & Crash Reporting

Builds produced from this independent fork (`cook0001/OpenCore-Legacy-Patcher`) compile with empty `ANALYTICS_SERVER` and `SITE_KEY` values in `opencore_legacy_patcher/support/analytics_handler.py`. As a result, **no background telemetry, hardware UUIDs, or crash logs are transmitted** to PatchCraft or to Dortania.

## User-Initiated Network Requests

Network connections occur only when you run actions that fetch external assets or metadata, such as:

- Downloading macOS installers or catalog metadata from Apple Software Update servers
- Fetching KDK / `MetallibSupportPkg` manifests or release assets from GitHub / upstream Dortania endpoints
- Checking for repository releases on GitHub

Read-only volunteer diagnostic capture scripts save archives locally on your Mac; nothing is uploaded automatically unless you choose to attach a bundle to a GitHub issue.

## Upstream Attribution & Non-Affiliation

> This product includes software developed by Dortania and OpenCore Legacy Patcher contributors.

This repository is an independent fork of [dortania/OpenCore-Legacy-Patcher](https://github.com/dortania/OpenCore-Legacy-Patcher) governed by the 4-clause BSD license in [LICENSE.txt](LICENSE.txt). It is not affiliated with or endorsed by Dortania or Apple Inc.

## Contact

For privacy or security questions regarding this fork, email [support@patchcraft.dev](mailto:support@patchcraft.dev) or open an issue / security advisory at [https://github.com/cook0001/OpenCore-Legacy-Patcher/issues](https://github.com/cook0001/OpenCore-Legacy-Patcher/issues).
