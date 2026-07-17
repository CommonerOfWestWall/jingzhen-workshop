import numpy as np
from unittest.mock import patch

from jingzhen_engine.inpaint import (
    chunk_windows,
    motion_compensated_inpaint,
    refine_light_overlay_masks,
    temporal_inpaint,
)


def test_motion_compensated_inpaint_falls_back_when_alignment_fails() -> None:
    frames = np.full((3, 24, 32, 3), 30, dtype=np.uint8)
    frames[:, 8:16, 10:22] = 240
    masks = np.zeros((3, 24, 32), dtype=np.uint8)
    masks[:, 8:16, 10:22] = 255

    with patch("jingzhen_engine.inpaint._anchor_transforms", return_value=[None] * 3):
        repaired = motion_compensated_inpaint(frames, masks)

    assert np.array_equal(repaired[masks == 0], frames[masks == 0])
    assert not np.array_equal(repaired[masks > 0], frames[masks > 0])


def test_chunk_windows_overlap_without_losing_frames() -> None:
    windows = chunk_windows(frame_count=23, chunk_size=10, overlap=2)

    assert windows == [(0, 10), (8, 18), (16, 23)]
    covered = set()
    for start, end in windows:
        covered.update(range(start, end))
    assert covered == set(range(23))


def test_temporal_inpaint_preserves_unmasked_pixels_and_frame_count() -> None:
    frames = np.zeros((7, 32, 48, 3), dtype=np.uint8)
    for index in range(7):
        frames[index, :, :, 0] = np.arange(48, dtype=np.uint8)
        frames[index, :, :, 1] = index * 10
    masks = np.zeros((7, 32, 48), dtype=np.uint8)
    masks[:, 10:20, 15:25] = 255
    damaged = frames.copy()
    damaged[masks > 0] = 255

    repaired = temporal_inpaint(damaged, masks, temporal_radius=2)

    assert repaired.shape == frames.shape
    assert np.array_equal(repaired[masks == 0], damaged[masks == 0])
    assert repaired[:, 12:18, 17:23].mean() < 245


def test_motion_compensation_recovers_screen_fixed_occlusion() -> None:
    height, width = 96, 144
    rng = np.random.default_rng(7)
    texture = rng.integers(20, 235, (height, width + 36, 3), dtype=np.uint8)
    clean = np.stack([texture[:, offset : offset + width] for offset in range(0, 36, 4)])
    masks = np.zeros(clean.shape[:3], dtype=np.uint8)
    masks[:, 10:35, 12:55] = 255
    damaged = clean.copy()
    damaged[masks > 0] = (15, 15, 15)

    baseline = temporal_inpaint(damaged, masks, temporal_radius=2)
    result = motion_compensated_inpaint(damaged, masks)
    selected = masks > 0
    baseline_error = np.abs(baseline.astype(np.int16) - clean.astype(np.int16))[selected].mean()
    result_error = np.abs(result.astype(np.int16) - clean.astype(np.int16))[selected].mean()

    assert result_error < baseline_error * 0.55


def test_refine_light_overlay_preserves_unmarked_selection_interior() -> None:
    height, width = 72, 120
    gradient = np.linspace(35, 150, width + 16, dtype=np.uint8)
    clean = np.stack(
        [np.tile(gradient[offset : offset + width], (height, 1)) for offset in range(8)]
    )
    frames = np.repeat(clean[..., None], 3, axis=3)
    stroke = np.zeros((height, width), dtype=bool)
    stroke[10:13, 12:88] = True
    stroke[39:42, 12:88] = True
    stroke[10:42, 12:15] = True
    stroke[10:42, 85:88] = True
    frames[:, stroke] = (
        frames[:, stroke].astype(np.float32) * 0.45 + 255.0 * 0.55
    ).astype(np.uint8)
    broad = np.zeros(frames.shape[:3], dtype=np.uint8)
    broad[:, 7:45, 9:91] = 255

    refined = refine_light_overlay_masks(frames, broad)

    assert np.count_nonzero(refined[0][stroke]) / np.count_nonzero(stroke) > 0.9
    assert np.count_nonzero(refined[0]) < np.count_nonzero(broad[0]) * 0.5
    assert not refined[:, :5].any()
