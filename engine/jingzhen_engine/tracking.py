from __future__ import annotations

import json
import os
from pathlib import Path
from collections.abc import Callable, Sequence
from typing import Any

import cv2
import numpy as np

from .masks import MaskShape, rasterize_shapes


TrackingProgress = Callable[[str, int, int], None]


def _gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return frame
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def _feature_points(gray: np.ndarray, mask: np.ndarray) -> np.ndarray | None:
    search = cv2.dilate(
        np.where(mask > 0, 255, 0).astype(np.uint8),
        np.ones((11, 11), np.uint8),
    )
    points = cv2.goodFeaturesToTrack(
        gray,
        maxCorners=160,
        qualityLevel=0.006,
        minDistance=3,
        mask=search,
        blockSize=5,
    )
    if points is None or len(points) < 4:
        ys, xs = np.nonzero(search)
        if not len(xs):
            return None
        stride = max(1, len(xs) // 80)
        points = np.column_stack((xs[::stride], ys[::stride])).astype(np.float32)
        points = points.reshape(-1, 1, 2)
    return points.astype(np.float32)


def _template_translation(
    previous_gray: np.ndarray, next_gray: np.ndarray, mask: np.ndarray
) -> tuple[np.ndarray, float] | None:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    height, width = previous_gray.shape
    x1, x2 = int(xs.min()), int(xs.max()) + 1
    y1, y2 = int(ys.min()), int(ys.max()) + 1
    margin = max(12, round(max(x2 - x1, y2 - y1) * 0.7))
    tx1, tx2 = max(0, x1 - 3), min(width, x2 + 3)
    ty1, ty2 = max(0, y1 - 3), min(height, y2 + 3)
    template = previous_gray[ty1:ty2, tx1:tx2]
    sx1, sx2 = max(0, tx1 - margin), min(width, tx2 + margin)
    sy1, sy2 = max(0, ty1 - margin), min(height, ty2 + margin)
    search = next_gray[sy1:sy2, sx1:sx2]
    if (
        template.size == 0
        or search.shape[0] < template.shape[0]
        or search.shape[1] < template.shape[1]
    ):
        return None
    response = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, location = cv2.minMaxLoc(response)
    if not np.isfinite(score):
        return None
    transform = np.array(
        [[1.0, 0.0, location[0] + sx1 - tx1], [0.0, 1.0, location[1] + sy1 - ty1]],
        dtype=np.float32,
    )
    return transform, max(0.0, min(1.0, float(score)))


def _track_step(
    previous_frame: np.ndarray, next_frame: np.ndarray, mask: np.ndarray
) -> tuple[np.ndarray, float]:
    previous_gray, next_gray = _gray(previous_frame), _gray(next_frame)
    points = _feature_points(previous_gray, mask)
    transform: np.ndarray | None = None
    confidence = 0.0
    if points is not None and len(points) >= 4:
        tracked, status, _ = cv2.calcOpticalFlowPyrLK(
            previous_gray,
            next_gray,
            points,
            None,
            winSize=(31, 31),
            maxLevel=3,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        if tracked is not None and status is not None:
            returned, back_status, _ = cv2.calcOpticalFlowPyrLK(
                next_gray,
                previous_gray,
                tracked,
                None,
                winSize=(31, 31),
                maxLevel=3,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
            )
            if returned is not None and back_status is not None:
                forward = tracked.reshape(-1, 2)
                backward = returned.reshape(-1, 2)
                original = points.reshape(-1, 2)
                error = np.linalg.norm(original - backward, axis=1)
                valid = (
                    (status.reshape(-1) > 0)
                    & (back_status.reshape(-1) > 0)
                    & np.isfinite(error)
                    & (error <= 3.0)
                )
                if np.count_nonzero(valid) >= 4:
                    transform, inliers = cv2.estimateAffinePartial2D(
                        original[valid],
                        forward[valid],
                        method=cv2.RANSAC,
                        ransacReprojThreshold=3.0,
                        maxIters=1000,
                        confidence=0.99,
                        refineIters=10,
                    )
                    if transform is not None:
                        scale = float(np.hypot(transform[0, 0], transform[0, 1]))
                        valid_ratio = np.count_nonzero(valid) / len(points)
                        inlier_ratio = (
                            float(np.mean(inliers)) if inliers is not None else 0.0
                        )
                        fb_score = float(np.exp(-np.median(error[valid]) / 2.0))
                        scale_score = float(np.exp(-abs(np.log(max(scale, 1e-6))) * 5.0))
                        confidence = valid_ratio * inlier_ratio * fb_score * scale_score
                        if not 0.75 <= scale <= 1.33:
                            transform = None
                            confidence = 0.0
    if transform is None or confidence < 0.18:
        fallback = _template_translation(previous_gray, next_gray, mask)
        if fallback is not None and fallback[1] > confidence:
            transform, confidence = fallback
    if transform is None:
        return mask.copy(), 0.0
    height, width = mask.shape
    warped = cv2.warpAffine(
        mask,
        transform,
        (width, height),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
    )
    previous_area = max(1, int(np.count_nonzero(mask)))
    warped_area = int(np.count_nonzero(warped))
    if not 0.65 <= warped_area / previous_area <= 1.5:
        return mask.copy(), 0.0
    return np.where(warped > 0, 255, 0).astype(np.uint8), float(confidence)


def _propagate(
    frames: Sequence[np.ndarray],
    start: int,
    end: int,
    start_mask: np.ndarray,
    *,
    stage: str,
    on_step: Callable[[str], None] | None = None,
) -> tuple[dict[int, np.ndarray], dict[int, float]]:
    step = 1 if end >= start else -1
    masks = {start: start_mask.copy()}
    confidence = {start: 1.0}
    current_mask = start_mask.copy()
    current_confidence = 1.0
    for frame in range(start + step, end + step, step):
        current_mask, step_confidence = _track_step(
            frames[frame - step], frames[frame], current_mask
        )
        current_confidence = current_confidence * 0.55 + step_confidence * 0.45
        masks[frame] = current_mask.copy()
        confidence[frame] = current_confidence
        if on_step is not None:
            on_step(stage)
    return masks, confidence


def _centroid_and_area(mask: np.ndarray) -> tuple[float, float, float] | None:
    moments = cv2.moments(np.where(mask > 0, 1, 0).astype(np.uint8))
    if moments["m00"] <= 0:
        return None
    return (
        moments["m10"] / moments["m00"],
        moments["m01"] / moments["m00"],
        moments["m00"],
    )


def _blend_propagations(left: np.ndarray, right: np.ndarray, amount: float) -> np.ndarray:
    left_pose, right_pose = _centroid_and_area(left), _centroid_and_area(right)
    if left_pose is None:
        return right.copy()
    if right_pose is None:
        return left.copy()
    scale = np.sqrt(max(1.0, right_pose[2]) / max(1.0, left_pose[2]))
    blended_scale = float(np.exp(np.log(max(scale, 1e-6)) * amount))
    target_x = left_pose[0] + (right_pose[0] - left_pose[0]) * amount
    target_y = left_pose[1] + (right_pose[1] - left_pose[1]) * amount
    transform = np.array(
        [
            [blended_scale, 0.0, target_x - left_pose[0] * blended_scale],
            [0.0, blended_scale, target_y - left_pose[1] * blended_scale],
        ],
        dtype=np.float32,
    )
    height, width = left.shape
    return cv2.warpAffine(
        left,
        transform,
        (width, height),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
    )


def track_masks_bidirectional(
    frames: Sequence[np.ndarray],
    anchors: dict[int, np.ndarray],
    *,
    active_range: tuple[int, int] | None = None,
    progress: TrackingProgress | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    if not frames:
        raise ValueError("tracking input has no frames")
    if not anchors:
        raise ValueError("moving tracking requires at least one keyframe mask")
    frame_count = len(frames)
    height, width = frames[0].shape[:2]
    ordered = sorted(anchors)
    if ordered[0] < 0 or ordered[-1] >= frame_count:
        raise ValueError("tracking keyframe is outside the video")
    if any(mask.shape != (height, width) for mask in anchors.values()):
        raise ValueError("tracking mask dimensions do not match the video")
    range_start, range_end = active_range or (0, frame_count - 1)
    range_start = max(0, range_start)
    range_end = min(frame_count - 1, range_end)
    output = np.zeros((frame_count, height, width), dtype=np.uint8)
    confidence = np.zeros(frame_count, dtype=np.float32)
    total_steps = (
        ordered[0] - range_start
        + range_end
        - ordered[-1]
        + sum((right - left) * 2 for left, right in zip(ordered, ordered[1:], strict=False))
    )
    processed_steps = 0

    def on_step(stage: str) -> None:
        nonlocal processed_steps
        processed_steps += 1
        if progress is not None and (
            processed_steps % 4 == 0 or processed_steps == total_steps
        ):
            progress(stage, processed_steps, max(1, total_steps))

    first = ordered[0]
    backward_masks, backward_conf = _propagate(
        frames,
        first,
        range_start,
        anchors[first],
        stage="backward",
        on_step=on_step,
    )
    for frame, mask in backward_masks.items():
        output[frame] = mask
        confidence[frame] = backward_conf[frame]

    for left_frame, right_frame in zip(ordered, ordered[1:], strict=False):
        forward_masks, forward_conf = _propagate(
            frames,
            left_frame,
            right_frame,
            anchors[left_frame],
            stage="forward",
            on_step=on_step,
        )
        reverse_masks, reverse_conf = _propagate(
            frames,
            right_frame,
            left_frame,
            anchors[right_frame],
            stage="backward",
            on_step=on_step,
        )
        span = max(1, right_frame - left_frame)
        for frame in range(left_frame, right_frame + 1):
            amount = (frame - left_frame) / span
            output[frame] = _blend_propagations(
                forward_masks[frame], reverse_masks[frame], amount
            )
            confidence[frame] = min(
                forward_conf[frame], reverse_conf[frame]
            )

    last = ordered[-1]
    forward_masks, forward_conf = _propagate(
        frames,
        last,
        range_end,
        anchors[last],
        stage="forward",
        on_step=on_step,
    )
    for frame, mask in forward_masks.items():
        output[frame] = mask
        confidence[frame] = forward_conf[frame]

    for frame, mask in anchors.items():
        output[frame] = mask
        confidence[frame] = 1.0
    if progress is not None and total_steps == 0:
        progress("forward", 1, 1)
    return output, confidence


def _project_shape(raw: dict[str, Any]) -> MaskShape:
    return MaskShape(
        kind=raw["kind"],
        points=tuple((float(point[0]), float(point[1])) for point in raw["points"]),
        operation=raw.get("operation", "add"),
        brush_size=float(raw.get("brushSize", 0.02)),
    )


def _mask_shapes(mask: np.ndarray) -> list[dict[str, Any]]:
    height, width = mask.shape
    contours, _ = cv2.findContours(
        np.where(mask > 0, 255, 0).astype(np.uint8),
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    shapes: list[dict[str, Any]] = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(contour) < 2:
            continue
        perimeter = cv2.arcLength(contour, closed=True)
        points = cv2.approxPolyDP(
            contour, epsilon=max(0.75, perimeter * 0.003), closed=True
        ).reshape(-1, 2)
        if len(points) < 3:
            x, y, box_width, box_height = cv2.boundingRect(contour)
            points = np.asarray(
                [
                    [x, y],
                    [x + box_width - 1, y],
                    [x + box_width - 1, y + box_height - 1],
                    [x, y + box_height - 1],
                ],
                dtype=np.int32,
            )
        shapes.append(
            {
                "kind": "lasso",
                "operation": "add",
                "points": [
                    [
                        float(point[0]) / max(1, width - 1),
                        float(point[1]) / max(1, height - 1),
                    ]
                    for point in points
                ],
            }
        )
    return shapes


def _low_confidence_ranges(
    confidence: np.ndarray, *, start: int, end: int, threshold: float = 0.5
) -> list[list[int]]:
    frames = [frame for frame in range(start, end + 1) if confidence[frame] < threshold]
    ranges: list[list[int]] = []
    for frame in frames:
        if not ranges or frame > ranges[-1][1] + 1:
            ranges.append([frame, frame])
        else:
            ranges[-1][1] = frame
    return ranges


def track_video_project(
    *,
    input_path: Path,
    project_path: Path,
    output_project: Path,
    progress: TrackingProgress | None = None,
) -> dict[str, Any]:
    project = json.loads(project_path.read_text(encoding="utf-8"))
    capture = cv2.VideoCapture(os.fspath(input_path))
    if not capture.isOpened():
        raise RuntimeError("OpenCV could not open tracking input")
    frames: list[np.ndarray] = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    if not frames:
        raise RuntimeError("tracking input has no frames")
    height, width = frames[0].shape[:2]
    raw_range = project.get("activeRange") or [0, len(frames) - 1]
    active_range = (
        max(0, int(raw_range[0])),
        min(len(frames) - 1, int(raw_range[1])),
    )
    anchors: dict[int, np.ndarray] = {}
    for item in project.get("keyframes", []):
        frame = int(item["frame"])
        if frame < active_range[0] or frame > active_range[1]:
            continue
        shapes = tuple(_project_shape(shape) for shape in item.get("shapes", []))
        if shapes:
            anchors[frame] = rasterize_shapes(shapes, width, height)
    masks, confidence = track_masks_bidirectional(
        frames,
        anchors,
        active_range=active_range,
        progress=progress,
    )
    tracked_keyframes = [
        {"frame": frame, "shapes": _mask_shapes(masks[frame])}
        for frame in range(active_range[0], active_range[1] + 1)
    ]
    ranges = _low_confidence_ranges(
        confidence, start=active_range[0], end=active_range[1]
    )
    tracked = {
        **project,
        "keyframes": tracked_keyframes,
        "trackingEngine": "opencv-bidirectional-affine-v1",
        "trackingConfidence": [round(float(value), 4) for value in confidence],
        "lowConfidenceRanges": ranges,
    }
    output_project.parent.mkdir(parents=True, exist_ok=True)
    output_project.write_text(
        json.dumps(tracked, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return {
        "project": os.fspath(output_project.resolve()),
        "frameCount": len(frames),
        "trackedFrames": len(tracked_keyframes),
        "lowConfidenceRanges": ranges,
        "minimumConfidence": round(
            float(np.min(confidence[active_range[0] : active_range[1] + 1])), 4
        ),
    }


def _intersects_frame(
    x: float,
    y: float,
    box_width: int,
    box_height: int,
    frame_width: int,
    frame_height: int,
) -> bool:
    return x < frame_width and y < frame_height and x + box_width > 0 and y + box_height > 0


def _predict(
    samples: list[tuple[int, int, int]], frame: int, *, from_end: bool
) -> tuple[int, int]:
    selected = samples[-16:] if from_end else samples[:16]
    times = np.asarray([item[0] for item in selected], dtype=np.float64)
    degree = min(2, len(selected) - 1)
    x_curve = np.polyfit(times, [item[1] for item in selected], degree)
    y_curve = np.polyfit(times, [item[2] for item in selected], degree)
    return round(float(np.polyval(x_curve, frame))), round(float(np.polyval(y_curve, frame)))


def _runs(detections: list[tuple[int, int, int]]) -> list[list[tuple[int, int, int]]]:
    groups: list[list[tuple[int, int, int]]] = []
    for detection in detections:
        if not groups or detection[0] > groups[-1][-1][0] + 1:
            groups.append([detection])
        else:
            groups[-1].append(detection)
    return groups


def extrapolate_offscreen_tracks(
    detections: list[tuple[int, int, int]],
    *,
    frame_count: int,
    frame_width: int,
    frame_height: int,
    box_width: int,
    box_height: int,
    max_extrapolation: int = 30,
) -> dict[int, tuple[int, int]]:
    positions = {frame: (x, y) for frame, x, y in detections}
    for run in _runs(detections):
        if len(run) < 3:
            continue
        start, end = run[0][0], run[-1][0]
        for frame in range(start - 1, max(-1, start - max_extrapolation - 1), -1):
            if frame < 0 or frame in positions:
                continue
            x, y = _predict(run, frame, from_end=False)
            if not _intersects_frame(
                x, y, box_width, box_height, frame_width, frame_height
            ):
                break
            positions[frame] = (x, y)
        for frame in range(end + 1, min(frame_count, end + max_extrapolation + 1)):
            if frame in positions:
                continue
            x, y = _predict(run, frame, from_end=True)
            if not _intersects_frame(
                x, y, box_width, box_height, frame_width, frame_height
            ):
                break
            positions[frame] = (x, y)
    return positions


def track_template_overlay(
    *,
    input_path: Path,
    output_project: Path,
    template_frame: int,
    template_box: tuple[int, int, int, int],
    template_mask_path: Path,
    search_box: tuple[int, int, int, int],
    threshold: float = 0.98,
    max_extrapolation: int = 30,
    dilation: int = 2,
) -> dict[str, Any]:
    capture = cv2.VideoCapture(os.fspath(input_path))
    if not capture.isOpened():
        raise RuntimeError("OpenCV could not open tracking input")
    frames: list[np.ndarray] = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    if not frames:
        raise RuntimeError("tracking input has no frames")
    if not 0 <= template_frame < len(frames):
        raise ValueError("template_frame is outside the video")
    if dilation < 0:
        raise ValueError("dilation cannot be negative")

    frame_height, frame_width = frames[0].shape[:2]
    x, y, box_width, box_height = template_box
    if box_width <= 0 or box_height <= 0:
        raise ValueError("template box must be positive")
    if x < 0 or y < 0 or x + box_width > frame_width or y + box_height > frame_height:
        raise ValueError("template box must be fully inside the template frame")
    template = frames[template_frame][y : y + box_height, x : x + box_width]
    try:
        encoded_mask = np.fromfile(template_mask_path, dtype=np.uint8)
    except OSError as error:
        raise FileNotFoundError(template_mask_path) from error
    template_mask = cv2.imdecode(encoded_mask, cv2.IMREAD_GRAYSCALE)
    if template_mask is None:
        raise FileNotFoundError(template_mask_path)
    if template_mask.shape != (box_height, box_width):
        raise ValueError("template mask dimensions must match template box")
    contours, _ = cv2.findContours(
        np.where(template_mask > 0, 255, 0).astype(np.uint8),
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    if not contours:
        raise ValueError("template mask has no foreground")
    contour = max(contours, key=cv2.contourArea)
    contour = cv2.approxPolyDP(contour, epsilon=1.0, closed=True).reshape(-1, 2)

    search_x, search_y, search_width, search_height = search_box
    detections: list[tuple[int, int, int]] = []
    scores: list[float] = []
    for index, frame in enumerate(frames):
        padded = cv2.copyMakeBorder(
            frame,
            0,
            box_height,
            0,
            box_width,
            cv2.BORDER_CONSTANT,
            value=0,
        )
        x1 = min(padded.shape[1], search_x + search_width)
        y1 = min(padded.shape[0], search_y + search_height)
        search = padded[search_y:y1, search_x:x1]
        if search.shape[1] < box_width or search.shape[0] < box_height:
            raise ValueError("search box is smaller than template")
        response = cv2.matchTemplate(
            search, template, cv2.TM_SQDIFF_NORMED, mask=template_mask
        )
        response = np.nan_to_num(
            response, nan=np.inf, posinf=np.inf, neginf=np.inf
        )
        distance, _, location, _ = cv2.minMaxLoc(response)
        score = max(0.0, min(1.0, 1.0 - float(distance)))
        scores.append(float(score))
        if score >= threshold:
            detections.append(
                (index, location[0] + search_x, location[1] + search_y)
            )

    positions = extrapolate_offscreen_tracks(
        detections,
        frame_count=len(frames),
        frame_width=frame_width,
        frame_height=frame_height,
        box_width=box_width,
        box_height=box_height,
        max_extrapolation=max_extrapolation,
    )
    keyframes = []
    for frame in range(len(frames)):
        shapes = []
        if frame in positions:
            px, py = positions[frame]
            translated = [
                (
                    min(frame_width - 1, max(0, px + int(point[0]))),
                    min(frame_height - 1, max(0, py + int(point[1]))),
                )
                for point in contour
            ]
            if len(set(translated)) >= 3:
                shapes.append(
                    {
                        "kind": "lasso",
                        "operation": "add",
                        "points": [
                            [point_x / (frame_width - 1), point_y / (frame_height - 1)]
                            for point_x, point_y in translated
                        ],
                    }
                )
        keyframes.append({"frame": frame, "shapes": shapes})

    project = {
        "version": 1,
        "strategy": "moving",
        "activeRange": [0, len(frames) - 1],
        "dilation": dilation,
        "feather": 0,
        "lowConfidenceGap": 12,
        "templateTracking": {
            "threshold": threshold,
            "matchedFrames": [item[0] for item in detections],
            "extrapolatedFrames": sorted(set(positions) - {item[0] for item in detections}),
        },
        "keyframes": keyframes,
    }
    output_project.parent.mkdir(parents=True, exist_ok=True)
    output_project.write_text(
        json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "project": os.fspath(output_project.resolve()),
        "frameCount": len(frames),
        "matchedFrames": len(detections),
        "maskedFrames": len(positions),
        "minimumAcceptedScore": min((scores[item[0]] for item in detections), default=0.0),
        "maximumRejectedScore": max(
            (score for index, score in enumerate(scores) if index not in positions),
            default=0.0,
        ),
    }
