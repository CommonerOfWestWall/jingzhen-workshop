from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .video import _load_masks, probe_media


def blend_repaired_frames(
    original: np.ndarray,
    repaired: np.ndarray,
    masks: np.ndarray,
    *,
    feather: int = 3,
) -> np.ndarray:
    if original.shape != repaired.shape or original.ndim != 4:
        raise ValueError("original and repaired frames must have the same 4D shape")
    if masks.shape != original.shape[:3]:
        raise ValueError("masks must match frame time/height/width")
    if feather < 0:
        raise ValueError("feather cannot be negative")
    output = original.copy()
    for index, mask in enumerate(masks):
        alpha = (mask > 0).astype(np.float32)
        if feather:
            size = feather * 2 + 1
            alpha = cv2.GaussianBlur(alpha, (size, size), feather / 2)
        alpha = alpha[..., None]
        output[index] = np.clip(
            original[index].astype(np.float32) * (1.0 - alpha)
            + repaired[index].astype(np.float32) * alpha,
            0,
            255,
        ).astype(np.uint8)
    return output


def composite_repaired_video(
    *,
    input_path: Path,
    repaired_path: Path,
    project_path: Path,
    output_path: Path,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    feather: int = 3,
    crf: int = 18,
) -> dict[str, Any]:
    if output_path.resolve() in {input_path.resolve(), repaired_path.resolve()}:
        raise ValueError("output must not overwrite either input")
    media = probe_media(input_path, ffprobe=ffprobe)
    repaired_media = probe_media(repaired_path, ffprobe=ffprobe)
    keys = ("width", "height", "frame_count", "avg_fps")
    if any(media[key] != repaired_media[key] for key in keys):
        raise ValueError("original and repaired media structure must match")

    original_capture = cv2.VideoCapture(os.fspath(input_path))
    repaired_capture = cv2.VideoCapture(os.fspath(repaired_path))
    originals: list[np.ndarray] = []
    repairs: list[np.ndarray] = []
    while True:
        original_ok, original = original_capture.read()
        repaired_ok, repair = repaired_capture.read()
        if not original_ok or not repaired_ok:
            if original_ok != repaired_ok:
                raise RuntimeError("original and repaired frame counts differ")
            break
        originals.append(original)
        repairs.append(repair)
    original_capture.release()
    repaired_capture.release()
    if not originals:
        raise RuntimeError("composite inputs have no frames")

    width, height = int(media["width"]), int(media["height"])
    masks, _, _ = _load_masks(
        project_path, width=width, height=height, frame_count=len(originals)
    )
    started = time.perf_counter()
    blended = blend_repaired_frames(
        np.stack(originals), np.stack(repairs), masks, feather=feather
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    silent = output_path.with_name(f".{output_path.stem}.silent.mp4")
    writer = cv2.VideoWriter(
        os.fspath(silent),
        cv2.VideoWriter_fourcc(*"mp4v"),
        float(media["avg_fps"]),
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not create composite intermediate")
    try:
        for frame in blended:
            writer.write(frame)
    finally:
        writer.release()

    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        os.fspath(silent),
        "-i",
        os.fspath(input_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a?",
        "-map",
        "1:s?",
        "-map_metadata",
        "1",
        "-map_chapters",
        "1",
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-preset",
        "medium",
        "-c:a",
        "copy",
        "-c:s",
        "mov_text",
        "-movflags",
        "+faststart",
        os.fspath(output_path),
    ]
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    silent.unlink(missing_ok=True)
    if process.returncode != 0:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(process.stderr.strip() or "FFmpeg composite mux failed")
    return {
        "output": os.fspath(output_path.resolve()),
        "frames": len(blended),
        "elapsedSeconds": round(time.perf_counter() - started, 3),
        "media": probe_media(output_path, ffprobe=ffprobe),
    }
