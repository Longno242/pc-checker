# PC Checker

PC Checker is a Windows desktop application for collecting hardware inventory, checking update status, and summarizing system health. It reads local system data through WMI and PowerShell, optionally queries Windows Update, and compares installed driver and firmware versions against vendor sources where available.

## Requirements

- Windows 10 or Windows 11
- Python 3.11 or newer
- PowerShell 5.1 or newer
- Internet access for online version checks and Windows Update queries

Optional:

- NVIDIA driver tools (`nvidia-smi`) for extended GPU telemetry

## Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/Longno242/pc-checker.git
cd pc-checker
pip install -r requirements.txt
```

## Usage

Run the application:

```bash
python main.py
```

Or use the included launcher:

```bat
run.bat
```

Select **Scan System** to collect hardware data and update status. Results are cached locally and reload on the next launch.

### Scan options

- **Cancel** stops an in-progress scan.
- **Skip WU** skips the Windows Update query. Driver, BIOS, and online version checks still run.
- **Settings** controls auto-scan on startup and the default Windows Update behavior.

### Reports and history

- **Export** writes an HTML report of the current scan.
- **History** loads one of the five most recent saved scans.

Scan data is stored under:

```text
%LOCALAPPDATA%\PCChecker
```

## Building a standalone executable

Install PyInstaller and run the build script:

```bat
build.bat
```

The executable is written to `dist\PC Checker.exe`.

## Project layout

```text
main.py                 Entry point
src/
  gui/                  CustomTkinter UI
  scanner/              Hardware, update, health, and monitoring logic
  storage/              Settings and scan persistence
  export/               HTML report generation
  utils/                Shared helpers
requirements.txt        Python dependencies
build.bat               PyInstaller build script
run.bat                 Windows launcher
```

## What the scan covers

| Area | Source |
|------|--------|
| CPU, RAM, motherboard, BIOS | WMI |
| GPU | WMI, `nvidia-smi` when available |
| Storage | WMI, Storage reliability counters |
| Displays | WMI, Win32 display APIs |
| Network adapters | WMI |
| Windows Update | Windows Update Agent (COM) |
| NVIDIA driver version | GeForce driver service |
| BIOS version (ASUS) | ASUS support API |
| Live telemetry | psutil, `nvidia-smi` |

Virtual display adapters (for example Meta/Oculus virtual monitors) are excluded from the primary GPU list.

## Health score

The health score is a weighted summary of scan results. It considers pending Windows updates, disk free space, BIOS age, drive health status, GPU driver status, and GPU temperature. It is intended as a quick summary, not a substitute for manual review.

## Limitations

- Windows Update queries can be slow or time out depending on system state and network conditions.
- Online BIOS and driver version checks depend on vendor APIs and may not cover every manufacturer or product.
- BIOS flashing is not performed by this application. Firmware updates must be installed through the manufacturer tools.

## License

MIT. See [LICENSE](LICENSE).
