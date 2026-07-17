import hashlib
import json
from pathlib import Path

import pytest

from jingzhen_engine.models import download_model, model_status


def test_download_model_verifies_size_and_sha(tmp_path: Path) -> None:
    payload = b"licensed model fixture"
    source = tmp_path / "source.bin"
    source.write_bytes(payload)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "models": [
                    {
                        "id": "fixture",
                        "delivery": "first-download",
                        "redistributable": True,
                        "filename": "fixture.bin",
                        "url": source.as_uri(),
                        "size": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    target = download_model(manifest, tmp_path / "models", "fixture")

    assert target.read_bytes() == payload
    assert model_status(manifest, tmp_path / "models")[0]["valid"] is True


def test_external_model_cannot_be_auto_downloaded(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "models": [
                    {
                        "id": "restricted",
                        "delivery": "external-directory",
                        "redistributable": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PermissionError):
        download_model(manifest, tmp_path / "models", "restricted")
