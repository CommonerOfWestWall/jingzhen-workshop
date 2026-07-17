import numpy as np

from jingzhen_engine.masks import (
    KeyframeMask,
    MaskShape,
    apply_morphology,
    build_mask_sequence,
    invalidated_range,
)


def test_fixed_mask_respects_time_range() -> None:
    shape = MaskShape(kind="rect", points=((0.25, 0.25), (0.5, 0.5)))
    masks, confidence = build_mask_sequence(
        width=100,
        height=80,
        frame_count=6,
        strategy="fixed",
        keyframes=(KeyframeMask(frame=2, shapes=(shape,)),),
        active_range=(1, 4),
    )

    assert masks.shape == (6, 80, 100)
    assert not masks[0].any()
    assert masks[1, 20:40, 25:50].all()
    assert not masks[5].any()
    assert np.all(confidence[1:5] == 1.0)


def test_moving_keyframes_interpolate_and_mark_long_gap_low_confidence() -> None:
    start = MaskShape(kind="rect", points=((0.1, 0.2), (0.2, 0.4)))
    end = MaskShape(kind="rect", points=((0.7, 0.2), (0.8, 0.4)))
    masks, confidence = build_mask_sequence(
        width=100,
        height=100,
        frame_count=11,
        strategy="moving",
        keyframes=(
            KeyframeMask(frame=0, shapes=(start,)),
            KeyframeMask(frame=10, shapes=(end,)),
        ),
        low_confidence_gap=4,
    )

    assert masks[5, 20:40, 40:60].any()
    assert confidence[0] == 1.0
    assert confidence[5] < 0.6
    assert confidence[10] == 1.0


def test_add_subtract_and_conservative_morphology() -> None:
    add = MaskShape(kind="rect", points=((0.1, 0.1), (0.5, 0.5)))
    subtract = MaskShape(
        kind="rect", points=((0.2, 0.2), (0.3, 0.3)), operation="subtract"
    )
    masks, _ = build_mask_sequence(
        width=100,
        height=100,
        frame_count=1,
        strategy="fixed",
        keyframes=(KeyframeMask(frame=0, shapes=(add, subtract)),),
    )
    alpha = apply_morphology(masks[0], dilation=2, feather=2)

    assert alpha[15, 15] > 0.9
    assert alpha[25, 25] < 0.1
    assert 0.0 < alpha[8, 20] < 1.0


def test_overlapping_add_shapes_form_one_union_mask() -> None:
    left = MaskShape(kind="rect", points=((0.1, 0.1), (0.5, 0.5)))
    right = MaskShape(kind="rect", points=((0.3, 0.3), (0.7, 0.7)))
    masks, _ = build_mask_sequence(
        width=100,
        height=100,
        frame_count=1,
        strategy="fixed",
        keyframes=(KeyframeMask(frame=0, shapes=(left, right)),),
    )

    assert masks[0, 20, 20] == 255
    assert masks[0, 40, 40] == 255
    assert masks[0, 60, 60] == 255
    assert set(np.unique(masks[0])) == {0, 255}


def test_keyframe_edit_only_invalidates_adjacent_interval() -> None:
    assert invalidated_range((0, 10, 20, 30), edited_frame=20) == (10, 30)
    assert invalidated_range((10,), edited_frame=10, frame_count=50) == (0, 49)
