import pytest

from pathlib import Path

from jingzhen_engine.propainter import _processing_size, _resolve_backend_paths


def test_processing_size_preserves_portrait_ratio_on_eight_pixel_grid() -> None:
    assert _processing_size(720, 1280, 480) == (480, 856)


def test_processing_size_rejects_upscaling() -> None:
    with pytest.raises(ValueError):
        _processing_size(720, 1280, 960)


def test_backend_paths_are_absolute_before_subprocess_changes_directory(
    tmp_path: Path, monkeypatch
) -> None:
    backend = tmp_path / "backend"
    python = tmp_path / "runtime" / "python.exe"
    backend.mkdir()
    python.parent.mkdir()
    monkeypatch.chdir(tmp_path)

    root, inference, executable = _resolve_backend_paths(
        Path("backend"), Path("runtime/python.exe")
    )

    assert root == backend
    assert inference == backend / "inference_propainter.py"
    assert executable == python
    assert root.is_absolute()
    assert inference.is_absolute()
    assert executable.is_absolute()
