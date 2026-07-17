from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

import cv2
import numpy as np

ShapeKind = Literal["rect", "lasso", "brush"]
Operation = Literal["add", "subtract"]
Strategy = Literal["fixed", "moving", "alpha"]


@dataclass(frozen=True)
class MaskShape:
    kind: ShapeKind
    points: tuple[tuple[float, float], ...]
    operation: Operation = "add"
    brush_size: float = 0.02


@dataclass(frozen=True)
class KeyframeMask:
    frame: int
    shapes: tuple[MaskShape, ...]


def _pixel_points(
    points: Sequence[tuple[float, float]], width: int, height: int
) -> np.ndarray:
    converted = [
        (
            int(round(np.clip(x, 0.0, 1.0) * (width - 1))),
            int(round(np.clip(y, 0.0, 1.0) * (height - 1))),
        )
        for x, y in points
    ]
    return np.asarray(converted, dtype=np.int32)


def rasterize_shapes(
    shapes: Sequence[MaskShape], width: int, height: int
) -> np.ndarray:
    mask = np.zeros((height, width), dtype=np.uint8)
    for shape in shapes:
        if not shape.points:
            continue
        value = 255 if shape.operation == "add" else 0
        points = _pixel_points(shape.points, width, height)
        if shape.kind == "rect" and len(points) >= 2:
            x1, y1 = points[0]
            x2, y2 = points[-1]
            cv2.rectangle(
                mask,
                (min(x1, x2), min(y1, y2)),
                (max(x1, x2), max(y1, y2)),
                value,
                thickness=-1,
            )
        elif shape.kind == "lasso" and len(points) >= 3:
            cv2.fillPoly(mask, [points], value)
        elif shape.kind == "brush":
            thickness = max(1, int(round(shape.brush_size * min(width, height))))
            if len(points) == 1:
                cv2.circle(mask, tuple(points[0]), thickness // 2, value, -1)
            else:
                cv2.polylines(
                    mask,
                    [points],
                    isClosed=False,
                    color=value,
                    thickness=thickness,
                    lineType=cv2.LINE_AA,
                )
    return mask


def _interpolate_shape(left: MaskShape, right: MaskShape, amount: float) -> MaskShape:
    if left.kind != right.kind or len(left.points) != len(right.points):
        return left if amount < 0.5 else right
    points = tuple(
        (
            x1 + (x2 - x1) * amount,
            y1 + (y2 - y1) * amount,
        )
        for (x1, y1), (x2, y2) in zip(left.points, right.points, strict=True)
    )
    return MaskShape(
        kind=left.kind,
        points=points,
        operation=left.operation,
        brush_size=left.brush_size + (right.brush_size - left.brush_size) * amount,
    )


def _interpolate_shapes(
    left: Sequence[MaskShape], right: Sequence[MaskShape], amount: float
) -> tuple[MaskShape, ...]:
    if len(left) != len(right):
        return tuple(left if amount < 0.5 else right)
    return tuple(
        _interpolate_shape(a, b, amount) for a, b in zip(left, right, strict=True)
    )


def build_mask_sequence(
    *,
    width: int,
    height: int,
    frame_count: int,
    strategy: Strategy,
    keyframes: Sequence[KeyframeMask],
    active_range: tuple[int, int] | None = None,
    low_confidence_gap: int = 12,
) -> tuple[np.ndarray, np.ndarray]:
    if width <= 0 or height <= 0 or frame_count <= 0:
        raise ValueError("width, height and frame_count must be positive")
    if not keyframes:
        raise ValueError("at least one keyframe is required")
    ordered = tuple(sorted(keyframes, key=lambda item: item.frame))
    if ordered[0].frame < 0 or ordered[-1].frame >= frame_count:
        raise ValueError("keyframe is outside the video")

    masks = np.zeros((frame_count, height, width), dtype=np.uint8)
    confidence = np.zeros(frame_count, dtype=np.float32)
    range_start, range_end = active_range or (0, frame_count - 1)
    range_start = max(0, range_start)
    range_end = min(frame_count - 1, range_end)

    if strategy == "fixed":
        fixed = rasterize_shapes(ordered[0].shapes, width, height)
        masks[range_start : range_end + 1] = fixed
        confidence[range_start : range_end + 1] = 1.0
        return masks, confidence

    for frame in range(range_start, range_end + 1):
        exact = next((item for item in ordered if item.frame == frame), None)
        if exact is not None:
            shapes = exact.shapes
            confidence[frame] = 1.0
        else:
            left = next((item for item in reversed(ordered) if item.frame < frame), None)
            right = next((item for item in ordered if item.frame > frame), None)
            if left is None:
                shapes = right.shapes  # type: ignore[union-attr]
                distance = right.frame - frame  # type: ignore[union-attr]
            elif right is None:
                shapes = left.shapes
                distance = frame - left.frame
            else:
                amount = (frame - left.frame) / (right.frame - left.frame)
                shapes = _interpolate_shapes(left.shapes, right.shapes, amount)
                distance = min(frame - left.frame, right.frame - frame)
            confidence[frame] = max(0.2, 1.0 - distance / max(1, low_confidence_gap))
        masks[frame] = rasterize_shapes(shapes, width, height)
    return masks, confidence


def apply_morphology(
    mask: np.ndarray, *, dilation: int = 2, feather: int = 2
) -> np.ndarray:
    if mask.ndim != 2:
        raise ValueError("mask must be a 2D array")
    binary = np.where(mask > 0, 255, 0).astype(np.uint8)
    if dilation > 0:
        size = dilation * 2 + 1
        binary = cv2.dilate(binary, np.ones((size, size), np.uint8))
    alpha = binary.astype(np.float32) / 255.0
    if feather > 0:
        size = feather * 2 + 1
        alpha = cv2.GaussianBlur(alpha, (size, size), sigmaX=max(0.5, feather / 2))
    return np.clip(alpha, 0.0, 1.0)


def invalidated_range(
    keyframe_frames: Sequence[int], *, edited_frame: int, frame_count: int | None = None
) -> tuple[int, int]:
    ordered = sorted(set(keyframe_frames))
    if len(ordered) <= 1:
        return (0, max(0, (frame_count or 1) - 1))
    before = [frame for frame in ordered if frame < edited_frame]
    after = [frame for frame in ordered if frame > edited_frame]
    start = before[-1] if before else 0
    end = after[0] if after else max(ordered[-1], (frame_count or 1) - 1)
    return start, end
