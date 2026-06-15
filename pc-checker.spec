# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

block_cipher = None

hiddenimports = [
    "src.gui.app",
    "src.gui.theme",
    "src.gui.widgets",
    "src.gui.serialization",
    "src.scanner.hardware",
    "src.scanner.updates",
    "src.scanner.health",
    "src.scanner.monitoring",
    "src.scanner.version_check",
    "src.storage.persistence",
    "src.export.report",
    "src.utils.formatters",
    "src.utils.powershell",
    "src.utils.version",
]

datas = []
binaries = []
_ctk = collect_all("customtkinter")
datas += _ctk[0]
binaries += _ctk[1]
hiddenimports += _ctk[2]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="PC-Checker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
