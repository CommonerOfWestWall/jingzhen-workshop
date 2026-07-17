from pathlib import Path

import pytest

import json

import numpy as np

from jingzhen_engine.video import (
    _emit_stage,
    _fraction,
    _frame_rate_filter,
    _load_masks,
    _repair_frames,
    probe_media,
)


def test_fixed_layer_is_combined_with_moving_masks(tmp_path: Path) -> None:
    project = {
        "strategy": "moving",
        "activeRange": [0, 1],
        "dilation": 0,
        "feather": 0,
        "fixedShapes": [
            {
                "kind": "rect",
                "operation": "add",
                "points": [[0.0, 0.0], [0.2, 0.2]],
            }
        ],
        "keyframes": [
            {
                "frame": 0,
                "shapes": [
                    {
                        "kind": "rect",
                        "operation": "add",
                        "points": [[0.7, 0.7], [0.9, 0.9]],
                    }
                ],
            },
            {
                "frame": 1,
                "shapes": [
                    {
                        "kind": "rect",
                        "operation": "add",
                        "points": [[0.75, 0.7], [0.95, 0.9]],
                    }
                ],
            },
        ],
    }
    path = tmp_path / "project.json"
    path.write_text(json.dumps(project), encoding="utf-8")

    masks, _, _ = _load_masks(path, width=100, height=100, frame_count=2)

    assert np.all(masks[:, 5:15, 5:15] == 255)
    assert np.all(masks[0, 75:85, 75:85] == 255)


def test_fraction_handles_valid_and_missing_rates() -> None:
    assert _fraction("30000/1001") == pytest.approx(29.97003, rel=1e-5)
    assert _fraction("0/0") == 0.0


def test_probe_media_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        probe_media(tmp_path / "missing.mp4")


def test_frame_rate_filters_support_fast_and_motion_modes() -> None:
    assert _frame_rate_filter(None, "fast") is None
    assert _frame_rate_filter(30, "fast") == "fps=fps=30"
    assert _frame_rate_filter(60, "motion").startswith("minterpolate=fps=60:")
    with pytest.raises(ValueError):
        _frame_rate_filter(121, "fast")


def test_post_repair_stages_are_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    _emit_stage("encode", 193, 193)
    _emit_stage("finalize", 193, 193)

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [event["stage"] for event in events] == ["encode", "finalize"]
    assert all(event["frame"] == event["total"] == 193 for event in events)


def test_quality_fixed_mode_uses_lama_without_refining_full_mask() -> None:
    frames = np.full((2, 24, 32, 3), 40, dtype=np.uint8)
    masks = np.zeros((2, 24, 32), dtype=np.uint8)
    masks[:, 4:12, 5:20] = 255

    class FakeLama:
        received: np.ndarray | None = None

        def repair_frames(self, input_frames: np.ndarray, input_masks: np.ndarray) -> np.ndarray:
            self.received = input_masks.copy()
            return np.full_like(input_frames, 90)

    lama = FakeLama()
    repaired = _repair_frames(
        frames,
        masks,
        strategy="alpha",
        temporal_radius=2,
        refine_light_overlay=True,
        repair_mode="quality",
        lama_client=lama,  # type: ignore[arg-type]
    )

    assert np.array_equal(lama.received, masks)
    assert repaired.mean() == 90


def test_quality_fixed_mode_never_silently_falls_back() -> None:
    frames = np.zeros((2, 12, 16, 3), dtype=np.uint8)
    masks = np.zeros((2, 12, 16), dtype=np.uint8)
    masks[:, 2:6, 3:8] = 255

    with pytest.raises(RuntimeError, match="LaMa"):
        _repair_frames(
            frames,
            masks,
            strategy="fixed",
            temporal_radius=2,
            repair_mode="quality",
        )


def test_quality_moving_mode_uses_lama_instead_of_blur_baseline() -> None:
    frames = np.full((3, 20, 30, 3), 35, dtype=np.uint8)
    masks = np.zeros((3, 20, 30), dtype=np.uint8)
    masks[0, 5:10, 4:9] = 255
    masks[1, 6:11, 7:12] = 255
    masks[2, 7:12, 11:16] = 255

    class FakeLama:
        called = False

        def repair_frames(self, input_frames: np.ndarray, input_masks: np.ndarray) -> np.ndarray:
            self.called = True
            assert np.array_equal(input_masks, masks)
            return np.full_like(input_frames, 120)

    lama = FakeLama()
    repaired = _repair_frames(
        frames,
        masks,
        strategy="moving",
        temporal_radius=2,
        repair_mode="quality",
        lama_client=lama,  # type: ignore[arg-type]
    )

    assert lama.called
    assert repaired.mean() == 120
