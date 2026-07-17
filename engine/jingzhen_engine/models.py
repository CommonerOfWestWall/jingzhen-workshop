from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Callable


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or not isinstance(manifest.get("models"), list):
        raise ValueError("unsupported model manifest")
    return manifest


def find_model(manifest: dict[str, Any], model_id: str) -> dict[str, Any]:
    for model in manifest["models"]:
        if model.get("id") == model_id:
            return model
    raise KeyError(f"unknown model: {model_id}")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def model_status(manifest_path: Path, models_dir: Path) -> list[dict[str, Any]]:
    manifest = load_manifest(manifest_path)
    result = []
    for model in manifest["models"]:
        filename = model.get("filename")
        target = models_dir / filename if filename else None
        present = bool(target and target.is_file())
        valid = bool(
            present
            and target
            and target.stat().st_size == model.get("size")
            and sha256_file(target) == model.get("sha256")
        )
        result.append({**model, "present": present, "valid": valid})
    return result


def download_model(
    manifest_path: Path,
    models_dir: Path,
    model_id: str,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    model = find_model(load_manifest(manifest_path), model_id)
    if model.get("delivery") != "first-download" or not model.get("redistributable"):
        raise PermissionError("this model must be installed from an external directory")
    models_dir.mkdir(parents=True, exist_ok=True)
    target = models_dir / model["filename"]
    part = target.with_suffix(target.suffix + ".part")
    expected_size = int(model["size"])
    if target.is_file() and target.stat().st_size == expected_size:
        if sha256_file(target) == model["sha256"]:
            return target
        target.unlink()

    offset = part.stat().st_size if part.exists() else 0
    request = urllib.request.Request(model["url"])
    if offset:
        request.add_header("Range", f"bytes={offset}-")
    with urllib.request.urlopen(request, timeout=60) as response:
        resumed = response.status == 206 and offset > 0
        if not resumed:
            offset = 0
        mode = "ab" if resumed else "wb"
        with part.open(mode) as stream:
            downloaded = offset
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(downloaded, expected_size)
            stream.flush()
            os.fsync(stream.fileno())
    if part.stat().st_size != expected_size:
        raise RuntimeError(
            f"model size mismatch: expected {expected_size}, got {part.stat().st_size}"
        )
    actual_sha = sha256_file(part)
    if actual_sha != model["sha256"]:
        raise RuntimeError(f"model checksum mismatch: {actual_sha}")
    part.replace(target)
    return target
