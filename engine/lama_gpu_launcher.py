from __future__ import annotations

import os
import sys
from pathlib import Path

if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")


def runtime_root() -> Path:
    override = os.environ.get("JINGZHEN_GPU_RUNTIME")
    if override:
        return Path(override)
    executable = Path(sys.executable).resolve()
    return executable.parent / "gpu-runtime"


site_packages = runtime_root() / "site-packages"
if not site_packages.is_dir():
    raise RuntimeError("GPU 加速组件不完整，请在净帧工坊中重新安装")
sys.path.insert(0, os.fspath(site_packages))

_dll_handles = []
if os.name == "nt":
    nvidia_root = site_packages / "nvidia"
    dll_directories = sorted(nvidia_root.glob("*/bin"))
    for directory in dll_directories:
        if directory.is_dir():
            _dll_handles.append(os.add_dll_directory(directory))
    if dll_directories:
        os.environ["PATH"] = os.pathsep.join(
            [*(os.fspath(path) for path in dll_directories), os.environ.get("PATH", "")]
        )

import onnxruntime as ort  # noqa: E402

if hasattr(ort, "preload_dlls"):
    ort.preload_dlls(directory="")

from lama_frame_engine import main  # noqa: E402


if __name__ == "__main__":
    if "--require-provider" not in sys.argv:
        sys.argv.extend(["--require-provider", "CUDAExecutionProvider"])
    main()
