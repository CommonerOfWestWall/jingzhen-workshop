import numpy as np

from jingzhen_engine.composite import blend_repaired_frames


def test_blend_repaired_frames_preserves_pixels_outside_mask() -> None:
    original = np.full((2, 24, 32, 3), 30, dtype=np.uint8)
    repaired = np.full_like(original, 210)
    masks = np.zeros((2, 24, 32), dtype=np.uint8)
    masks[:, 8:16, 10:22] = 255

    result = blend_repaired_frames(original, repaired, masks, feather=2)

    assert np.array_equal(result[:, :4], original[:, :4])
    assert np.all(result[:, 10:14, 13:19] == 210)
    assert np.any((result > 30) & (result < 210))
