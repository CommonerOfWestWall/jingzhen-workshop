from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from jingzhen_engine.lama import LamaFrameClient


def test_lama_client_rejects_missing_resources(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="LaMa 高清修复引擎"):
        LamaFrameClient(tmp_path / "missing.exe", tmp_path / "missing.onnx")


def test_lama_client_skips_empty_mask_without_process() -> None:
    client = object.__new__(LamaFrameClient)
    frame = np.full((12, 16, 3), 80, dtype=np.uint8)
    mask = np.zeros((12, 16), dtype=np.uint8)

    repaired = client.repair_frame(frame, mask)

    assert np.array_equal(repaired, frame)
    assert repaired is not frame
