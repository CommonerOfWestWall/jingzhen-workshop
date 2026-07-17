# -*- mode: python ; coding: utf-8 -*-

import os
import sys

a = Analysis(
    ["lama_gpu_launcher.py"],
    pathex=["."],
    binaries=[(os.path.join(sys.base_prefix, "python3.dll"), ".")],
    datas=[],
    hiddenimports=["lama_frame_engine", "platform", "ctypes"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "cv2",
        "numpy",
        "onnxruntime",
        "PIL",
        "torch",
        "scipy",
    ],
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
    name="lama-gpu-launcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
