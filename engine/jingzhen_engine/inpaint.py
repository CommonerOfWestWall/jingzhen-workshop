from __future__ import annotations

import cv2
import numpy as np


def chunk_windows(
    *, frame_count: int, chunk_size: int, overlap: int
) -> list[tuple[int, int]]:
    if frame_count < 0:
        raise ValueError("frame_count cannot be negative")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")
    if frame_count == 0:
        return []
    windows: list[tuple[int, int]] = []
    start = 0
    while start < frame_count:
        end = min(frame_count, start + chunk_size)
        windows.append((start, end))
        if end == frame_count:
            break
        start = end - overlap
    return windows


def _spatial_seed(frame: np.ndarray, mask: np.ndarray) -> np.ndarray:
    binary = np.where(mask > 0, 255, 0).astype(np.uint8)
    if not binary.any():
        return frame.copy()
    return cv2.inpaint(frame, binary, 3.0, cv2.INPAINT_TELEA)


def temporal_inpaint(
    frames: np.ndarray, masks: np.ndarray, *, temporal_radius: int = 2
) -> np.ndarray:
    """Multi-frame baseline repair.

    Spatial inpainting only seeds missing pixels. The delivered masked pixels are the
    temporal median of neighboring repaired frames, which reduces independent-frame
    flicker while preserving every unmasked input pixel exactly.
    """
    if frames.ndim != 4 or frames.shape[-1] != 3:
        raise ValueError("frames must have shape [time, height, width, 3]")
    if masks.shape != frames.shape[:3]:
        raise ValueError("masks must match frame time/height/width")
    if temporal_radius < 0:
        raise ValueError("temporal_radius cannot be negative")

    seeds = np.stack(
        [_spatial_seed(frame, mask) for frame, mask in zip(frames, masks, strict=True)]
    )
    repaired = frames.copy()
    for index in range(len(frames)):
        selected = masks[index] > 0
        if not selected.any():
            continue
        start = max(0, index - temporal_radius)
        end = min(len(frames), index + temporal_radius + 1)
        temporal = np.median(seeds[start:end].astype(np.float32), axis=0).astype(np.uint8)
        repaired[index][selected] = temporal[selected]
    return repaired


def refine_light_overlay_masks(
    frames: np.ndarray,
    masks: np.ndarray,
    *,
    threshold: float = 8.0,
    kernel_size: int = 15,
) -> np.ndarray:
    """Limit a broad fixed selection to persistent light strokes inside it."""
    if frames.ndim != 4 or frames.shape[-1] != 3:
        raise ValueError("frames must have shape [time, height, width, 3]")
    if masks.shape != frames.shape[:3]:
        raise ValueError("masks must match frame time/height/width")
    if threshold <= 0:
        raise ValueError("threshold must be positive")
    if kernel_size < 3 or kernel_size % 2 == 0:
        raise ValueError("kernel_size must be an odd number of at least 3")

    broad = np.max(masks, axis=0) > 0
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)
    )
    responses = []
    for frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        opened = cv2.morphologyEx(gray, cv2.MORPH_OPEN, kernel)
        responses.append(cv2.subtract(gray, opened))
    persistent = np.median(np.stack(responses).astype(np.float32), axis=0)
    refined = np.where(broad & (persistent >= threshold), 255, 0).astype(np.uint8)
    refined = cv2.morphologyEx(refined, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    refined = cv2.dilate(refined, np.ones((3, 3), np.uint8), iterations=1)
    return np.stack(
        [np.where(mask > 0, refined, 0).astype(np.uint8) for mask in masks]
    )


def _anchor_transforms(
    frames: np.ndarray, masks: np.ndarray, *, max_dimension: int = 320
) -> list[np.ndarray | None]:
    """Estimate affine coordinates from a shared anchor into every frame."""
    height, width = frames.shape[1:3]
    scale = min(1.0, max_dimension / max(height, width))
    small_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    gray = [
        cv2.resize(
            cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
            small_size,
            interpolation=cv2.INTER_AREA,
        )
        for frame in frames
    ]
    invalid = np.max(masks, axis=0)
    valid = cv2.resize(
        np.where(invalid > 0, 0, 255).astype(np.uint8),
        small_size,
        interpolation=cv2.INTER_NEAREST,
    )
    anchor = len(frames) // 2
    transforms: list[np.ndarray | None] = []
    criteria = (
        cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
        60,
        1e-5,
    )
    for index, image in enumerate(gray):
        if index == anchor:
            transforms.append(np.eye(3, dtype=np.float32))
            continue
        shift, response = cv2.phaseCorrelate(
            gray[anchor].astype(np.float32), image.astype(np.float32)
        )
        if not np.isfinite(shift).all() or response < 0.05:
            transforms.append(None)
            continue
        warp = np.array(
            [[1.0, 0.0, shift[0]], [0.0, 1.0, shift[1]]], dtype=np.float32
        )
        try:
            correlation, refined = cv2.findTransformECC(
                gray[anchor],
                image,
                warp,
                cv2.MOTION_AFFINE,
                criteria,
                valid,
                5,
            )
        except cv2.error:
            correlation = 0.0
            refined = warp
        if correlation >= 0.3:
            warp = refined
        aligned = cv2.warpAffine(
            image,
            warp,
            small_size,
            flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
            borderMode=cv2.BORDER_CONSTANT,
        )
        aligned_valid = cv2.warpAffine(
            valid,
            warp,
            small_size,
            flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP,
            borderMode=cv2.BORDER_CONSTANT,
        )
        comparison = (valid > 0) & (aligned_valid > 0)
        if np.count_nonzero(comparison) < 64:
            transforms.append(None)
            continue
        template_values = gray[anchor][comparison].astype(np.float32)
        aligned_values = aligned[comparison].astype(np.float32)
        if np.std(template_values) < 1.0 or np.std(aligned_values) < 1.0:
            transforms.append(None)
            continue
        measured = float(np.corrcoef(template_values, aligned_values)[0, 1])
        if not np.isfinite(measured) or measured < 0.3:
            transforms.append(None)
            continue
        warp[:, 2] /= scale
        homogeneous = np.eye(3, dtype=np.float32)
        homogeneous[:2] = warp
        transforms.append(homogeneous)
    return transforms


def motion_compensated_inpaint(
    frames: np.ndarray,
    masks: np.ndarray,
    *,
    reference_count: int = 12,
) -> np.ndarray:
    """Recover a screen-fixed mask from motion-aligned clean pixels in other frames.

    The fixed overlay stays in screen coordinates while the scene moves. After global
    alignment, the overlay masks no longer fully overlap; only reference pixels whose
    transformed mask is clear are admitted as temporal donors.
    """
    if frames.ndim != 4 or frames.shape[-1] != 3:
        raise ValueError("frames must have shape [time, height, width, 3]")
    if masks.shape != frames.shape[:3]:
        raise ValueError("masks must match frame time/height/width")
    if reference_count < 2:
        raise ValueError("reference_count must be at least 2")

    transforms = _anchor_transforms(frames, masks)
    repaired = frames.copy()
    frame_count, height, width = masks.shape
    clearances = [
        cv2.distanceTransform(np.where(mask == 0, 1, 0).astype(np.uint8), cv2.DIST_L2, 3)
        for mask in masks
    ]
    reference_indices = np.unique(
        np.linspace(0, frame_count - 1, min(reference_count, frame_count), dtype=int)
    ).tolist()

    for target_index in range(frame_count):
        selected = masks[target_index] > 0
        if not selected.any():
            continue
        if transforms[target_index] is None:
            repaired[target_index] = _spatial_seed(
                frames[target_index], masks[target_index]
            )
            continue
        ys, xs = np.nonzero(selected)
        padding = 14
        x0, x1 = max(0, int(xs.min()) - padding), min(width, int(xs.max()) + padding + 1)
        y0, y1 = max(0, int(ys.min()) - padding), min(height, int(ys.max()) + padding + 1)
        grid_y, grid_x = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        target_patch = frames[target_index, y0:y1, x0:x1]
        selected_patch = selected[y0:y1, x0:x1]
        inverse_target = np.linalg.inv(transforms[target_index])
        candidates: list[tuple[np.ndarray, np.ndarray, float]] = []

        for reference_index in reference_indices:
            if reference_index == target_index or transforms[reference_index] is None:
                continue
            target_to_reference = transforms[reference_index] @ inverse_target
            map_x = (
                target_to_reference[0, 0] * grid_x
                + target_to_reference[0, 1] * grid_y
                + target_to_reference[0, 2]
            ).astype(np.float32)
            map_y = (
                target_to_reference[1, 0] * grid_x
                + target_to_reference[1, 1] * grid_y
                + target_to_reference[1, 2]
            ).astype(np.float32)
            inside = (
                (map_x >= 0)
                & (map_x <= width - 1)
                & (map_y >= 0)
                & (map_y <= height - 1)
            )
            aligned = cv2.remap(
                frames[reference_index],
                map_x,
                map_y,
                interpolation=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT,
            )
            aligned_mask = cv2.remap(
                masks[reference_index],
                map_x,
                map_y,
                interpolation=cv2.INTER_NEAREST,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=255,
            )
            valid = inside & (aligned_mask == 0)
            context = valid & ~selected_patch
            adjusted = aligned.astype(np.float32)
            alignment_error = 1000.0
            if np.count_nonzero(context) >= 24:
                difference = target_patch.astype(np.float32)[context] - adjusted[context]
                offset = np.clip(np.median(difference, axis=0), -35.0, 35.0)
                adjusted = np.clip(adjusted + offset, 0, 255)
                alignment_error = float(
                    np.median(
                        np.abs(target_patch.astype(np.float32)[context] - adjusted[context])
                    )
                )
            donor = valid & selected_patch
            clearance = cv2.remap(
                clearances[reference_index],
                map_x,
                map_y,
                interpolation=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT,
            )
            weight = np.clip(clearance / 10.0, 0.0, 1.0)
            weight[~donor] = 0.0
            candidates.append((adjusted, weight, alignment_error))

        if not candidates:
            repaired[target_index] = _spatial_seed(frames[target_index], masks[target_index])
            continue
        best_error = min(error for _, _, error in candidates)
        numerator = np.zeros((*target_patch.shape[:2], 3), dtype=np.float32)
        denominator = np.zeros(target_patch.shape[:2], dtype=np.float32)
        for candidate, weight, error in candidates:
            if error > min(45.0, best_error + 12.0):
                continue
            quality = 1.0 / (1.0 + error / 12.0) ** 2
            weighted = weight * quality
            numerator += candidate * weighted[..., None]
            denominator += weighted
        donor_available = (denominator > 1e-5) & selected_patch
        donors = np.zeros_like(numerator)
        donors[donor_available] = (
            numerator[donor_available] / denominator[donor_available, None]
        )
        recovered = frames[target_index].copy()
        recovered_patch = recovered[y0:y1, x0:x1]
        recovered_patch[donor_available] = donors[donor_available].astype(np.uint8)
        missing = selected.copy()
        missing[y0:y1, x0:x1][donor_available] = False
        if missing.any():
            recovered = cv2.inpaint(
                recovered,
                np.where(missing, 255, 0).astype(np.uint8),
                3.0,
                cv2.INPAINT_TELEA,
            )
        repaired[target_index][selected] = recovered[selected]
    return repaired


def blend_overlap(
    left: np.ndarray, right: np.ndarray, overlap: int
) -> np.ndarray:
    if overlap <= 0:
        return np.concatenate((left, right), axis=0)
    if overlap > len(left) or overlap > len(right):
        raise ValueError("overlap exceeds chunk length")
    weights = np.linspace(0.0, 1.0, overlap + 2, dtype=np.float32)[1:-1]
    shape = (overlap,) + (1,) * (left.ndim - 1)
    merged = (
        left[-overlap:].astype(np.float32) * (1.0 - weights.reshape(shape))
        + right[:overlap].astype(np.float32) * weights.reshape(shape)
    ).astype(left.dtype)
    return np.concatenate((left[:-overlap], merged, right[overlap:]), axis=0)
