import json

import cv2
import numpy as np

from jingzhen_engine.tracking import (
    extrapolate_offscreen_tracks,
    track_masks_bidirectional,
    track_template_overlay,
    track_video_project,
)


def _iou(left: np.ndarray, right: np.ndarray) -> float:
    intersection = np.count_nonzero((left > 0) & (right > 0))
    union = np.count_nonzero((left > 0) | (right > 0))
    return intersection / max(1, union)


def test_bidirectional_tracking_handles_motion_scale_rotation_and_relock() -> None:
    height, width = 120, 160
    frames: list[np.ndarray] = []
    expected_masks: list[np.ndarray] = []
    base = np.zeros((height, width), dtype=np.uint8)
    cv2.rectangle(base, (58, 45), (88, 67), 255, -1)
    cv2.line(base, (61, 48), (85, 64), 0, 2)
    cv2.circle(base, (66, 54), 3, 0, -1)
    center = (73.0, 56.0)

    for index in range(28):
        x = index * 1.7 + index * index * 0.025
        y = 5.0 * np.sin(index / 5.0)
        scale = 1.0 + index * 0.006
        angle = index * 0.8
        transform = cv2.getRotationMatrix2D(center, angle, scale)
        transform[:, 2] += (x, y)
        mask = cv2.warpAffine(base, transform, (width, height), flags=cv2.INTER_NEAREST)
        frame = np.full((height, width, 3), 45, dtype=np.uint8)
        frame[mask > 0] = (210, 180, 90)
        frame = cv2.GaussianBlur(frame, (3, 3), 0)
        if 12 <= index <= 14:
            frame[35:85, 65:125] = 45
        frames.append(frame)
        expected_masks.append(mask)

    anchors = {
        0: expected_masks[0],
        16: expected_masks[16],
        27: expected_masks[27],
    }
    masks, confidence = track_masks_bidirectional(frames, anchors)

    assert np.array_equal(masks[0], expected_masks[0])
    assert np.array_equal(masks[16], expected_masks[16])
    assert np.array_equal(masks[27], expected_masks[27])
    visible_ious = [
        _iou(masks[index], expected_masks[index])
        for index in range(len(frames))
        if not 12 <= index <= 14
    ]
    assert float(np.median(visible_ious)) > 0.72
    assert min(confidence[12:15]) < 0.5


def test_offscreen_extrapolation_keeps_long_hidden_interval_empty() -> None:
    detections = [
        *[(frame, 60 + frame * 8, 20) for frame in range(5)],
        *[(frame, 92 - (frame - 15) * 8, 20) for frame in range(15, 20)],
    ]

    positions = extrapolate_offscreen_tracks(
        detections,
        frame_count=20,
        frame_width=100,
        frame_height=80,
        box_width=8,
        box_height=8,
    )

    assert set(positions) == {*range(5), *range(15, 20)}


def test_template_tracking_rejects_proportional_brightness_false_matches(
    tmp_path,
) -> None:
    video_path = tmp_path / "overlay.avi"
    mask_path = tmp_path / "mask.png"
    project_path = tmp_path / "project.json"
    writer = cv2.VideoWriter(
        str(video_path), cv2.VideoWriter_fourcc(*"FFV1"), 24, (96, 72)
    )
    assert writer.isOpened()

    mask = np.zeros((20, 20), dtype=np.uint8)
    diamond = np.array([[10, 2], [18, 10], [10, 18], [2, 10]], dtype=np.int32)
    cv2.fillConvexPoly(mask, diamond, 255)
    encoded, contents = cv2.imencode(".png", mask)
    assert encoded
    contents.tofile(mask_path)

    for frame_index in range(12):
        frame = np.full((72, 96, 3), 60, dtype=np.uint8)
        if frame_index < 5:
            x = 10 + frame_index * 2
            roi = frame[20:40, x : x + 20]
            roi[mask > 0] = 160
        writer.write(frame)
    writer.release()

    result = track_template_overlay(
        input_path=video_path,
        output_project=project_path,
        template_frame=0,
        template_box=(10, 20, 20, 20),
        template_mask_path=mask_path,
        search_box=(0, 0, 96, 72),
        threshold=0.98,
        max_extrapolation=0,
        dilation=2,
    )

    project = json.loads(project_path.read_text(encoding="utf-8"))
    assert result["matchedFrames"] == 5
    assert project["templateTracking"]["matchedFrames"] == [0, 1, 2, 3, 4]


def test_track_video_project_writes_per_frame_masks_and_confidence(tmp_path) -> None:
    video_path = tmp_path / "moving.avi"
    input_project = tmp_path / "input.json"
    output_project = tmp_path / "tracked.json"
    writer = cv2.VideoWriter(
        str(video_path), cv2.VideoWriter_fourcc(*"FFV1"), 24, (80, 60)
    )
    assert writer.isOpened()
    for frame_index in range(8):
        frame = np.full((60, 80, 3), 30, dtype=np.uint8)
        cv2.rectangle(frame, (10 + frame_index * 2, 20), (23 + frame_index * 2, 31), (220, 180, 90), -1)
        cv2.line(frame, (11 + frame_index * 2, 21), (22 + frame_index * 2, 30), (20, 20, 20), 2)
        writer.write(frame)
    writer.release()
    input_project.write_text(
        json.dumps(
            {
                "version": 1,
                "strategy": "moving",
                "activeRange": [0, 7],
                "keyframes": [
                    {
                        "frame": 0,
                        "shapes": [
                            {
                                "kind": "rect",
                                "operation": "add",
                                "points": [[10 / 79, 20 / 59], [23 / 79, 31 / 59]],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = track_video_project(
        input_path=video_path,
        project_path=input_project,
        output_project=output_project,
    )

    tracked = json.loads(output_project.read_text(encoding="utf-8"))
    assert result["trackedFrames"] == 8
    assert len(tracked["keyframes"]) == 8
    assert len(tracked["trackingConfidence"]) == 8
    assert all(keyframe["shapes"] for keyframe in tracked["keyframes"])
