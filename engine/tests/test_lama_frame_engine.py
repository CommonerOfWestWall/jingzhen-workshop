import numpy as np

from lama_frame_engine import repair


def test_disconnected_masks_are_repaired_as_separate_regions() -> None:
    image = np.full((1280, 720, 3), 20, dtype=np.uint8)
    mask = np.zeros((1280, 720), dtype=np.uint8)
    mask[10:60, 10:120] = 255
    mask[1160:1240, 620:710] = 255

    class FakeEngine:
        calls = 0

        def infer(self, crop: np.ndarray, crop_mask: np.ndarray) -> np.ndarray:
            self.calls += 1
            return np.full_like(crop, 180)

    engine = FakeEngine()
    result = repair(engine, image, mask)  # type: ignore[arg-type]

    assert engine.calls == 2
    assert result[30, 40].mean() == 180
    assert result[1200, 680].mean() == 180
    assert result[640, 360].mean() == 20
