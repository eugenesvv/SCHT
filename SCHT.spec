# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

# SCHT is distributed as one self-contained Windows executable. Runtime assets
# and pywebview's native dependencies are embedded in the executable and are
# extracted by the PyInstaller bootloader while the app is running.
datas = [
    ('assets\\sc_hauling_logo.png', 'assets'),
    ('assets\\sc_hauling_logo_mark.png', 'assets'),
    ('assets\\help\\toolbar.jpg', 'assets\\help'),
    ('assets\\help\\dashboard.jpg', 'assets\\help'),
    ('assets\\help\\logistics_board.jpg', 'assets\\help'),
    ('assets\\help\\overlay.jpg', 'assets\\help'),
    ('assets\\help\\settings_menu.jpg', 'assets\\help'),
    ('assets\\help\\share_menu.jpg', 'assets\\help'),
    ('assets\\help\\contract_editor.jpg', 'assets\\help'),
]
binaries = []
hiddenimports = []
webview_bundle = collect_all('webview')
datas += webview_bundle[0]
binaries += webview_bundle[1]
hiddenimports += webview_bundle[2]


a = Analysis(
    ['sc_hauling_tracker.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SCHT',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
    icon=['assets\\sc_hauling_logo.ico'],
)
