# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["entrypoint.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=["cv2", "numpy"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="jingzhen-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
