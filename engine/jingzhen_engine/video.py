from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .inpaint import (
    motion_compensated_inpaint,
    refine_light_overlay_masks,
    temporal_inpaint,
)
from .lama import LamaFrameClient
from .masks import (
    KeyframeMask,
    MaskShape,
    apply_morphology,
    build_mask_sequence,
    rasterize_shapes,
)


def _fraction(value: str | None) -> float:
    if not value or value == "0/0":
        return 0.0
    numerator, denominator = value.split("/", 1)
    return float(numerator) / float(denominator)


def probe_media(path: Path, *, ffprobe: str = "ffprobe") -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    process = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            os.fspath(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or "ffprobe failed")
    raw = json.loads(process.stdout)
    streams = raw.get("streams", [])
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    if not videos:
        raise ValueError("input has no video stream")
    video = videos[0]
    avg_fps = _fraction(video.get("avg_frame_rate"))
    nominal_fps = _fraction(video.get("r_frame_rate"))
    pix_fmt = str(video.get("pix_fmt", ""))
    transfer = str(video.get("color_transfer", ""))
    rotation = int(video.get("tags", {}).get("rotate", 0) or 0)
    for side_data in video.get("side_data_list", []):
        if "rotation" in side_data:
            rotation = int(side_data["rotation"])
    warnings: list[str] = []
    if transfer in {"smpte2084", "arib-std-b67"}:
        warnings.append("HDR 输入首版不保证色彩正确，默认阻止处理")
    if any(token in pix_fmt for token in ("10", "12", "p010")):
        warnings.append("10/12-bit 输入首版不保证位深，默认阻止处理")
    if avg_fps and nominal_fps and abs(avg_fps - nominal_fps) > 0.01:
        warnings.append("检测到可能的可变帧率，默认阻止处理以避免音画不同步")
    if rotation % 360:
        warnings.append("检测到旋转元数据，首版需先烘焙方向后处理")
    duration = float(raw.get("format", {}).get("duration") or video.get("duration") or 0)
    frame_count = int(video.get("nb_frames") or round(duration * avg_fps))
    return {
        "path": os.fspath(path.resolve()),
        "width": int(video["width"]),
        "height": int(video["height"]),
        "duration": duration,
        "frame_count": frame_count,
        "avg_fps": avg_fps,
        "nominal_fps": nominal_fps,
        "pixel_format": pix_fmt,
        "color_transfer": transfer,
        "rotation": rotation,
        "audio_streams": [
            {
                "index": stream.get("index"),
                "codec": stream.get("codec_name"),
                "channels": stream.get("channels"),
                "language": stream.get("tags", {}).get("language"),
            }
            for stream in streams
            if stream.get("codec_type") == "audio"
        ],
        "subtitle_streams": [
            {
                "index": stream.get("index"),
                "codec": stream.get("codec_name"),
                "language": stream.get("tags", {}).get("language"),
            }
            for stream in streams
            if stream.get("codec_type") == "subtitle"
        ],
        "warnings": warnings,
    }


def _shape(raw: dict[str, Any]) -> MaskShape:
    return MaskShape(
        kind=raw["kind"],
        points=tuple((float(point[0]), float(point[1])) for point in raw["points"]),
        operation=raw.get("operation", "add"),
        brush_size=float(raw.get("brushSize", 0.02)),
    )


def _load_masks(
    project_path: Path, *, width: int, height: int, frame_count: int
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    project = json.loads(project_path.read_text(encoding="utf-8"))
    keyframes = tuple(
        KeyframeMask(
            frame=int(item["frame"]),
            shapes=tuple(_shape(shape) for shape in item["shapes"]),
        )
        for item in project["keyframes"]
    )
    active_range = project.get("activeRange")
    masks, confidence = build_mask_sequence(
        width=width,
        height=height,
        frame_count=frame_count,
        strategy=project["strategy"],
        keyframes=keyframes,
        active_range=tuple(active_range) if active_range else None,
        low_confidence_gap=int(project.get("lowConfidenceGap", 12)),
    )
    tracked_confidence = project.get("trackingConfidence")
    if isinstance(tracked_confidence, list) and len(tracked_confidence) == frame_count:
        confidence = np.clip(
            np.asarray(tracked_confidence, dtype=np.float32), 0.0, 1.0
        )
    fixed_shapes = tuple(
        _shape(shape) for shape in project.get("fixedShapes", [])
    )
    if fixed_shapes:
        fixed_mask = rasterize_shapes(fixed_shapes, width, height)
        masks = np.maximum(masks, fixed_mask[None, :, :])
    dilation = int(project.get("dilation", 2))
    feather = int(project.get("feather", 2))
    if dilation or feather:
        masks = np.stack(
            [
                np.where(
                    apply_morphology(mask, dilation=dilation, feather=feather) >= 0.15,
                    255,
                    0,
                ).astype(np.uint8)
                for mask in masks
            ]
        )
    return masks, confidence, project


def _repair_frames(
    frames: np.ndarray,
    masks: np.ndarray,
    *,
    strategy: str,
    temporal_radius: int,
    refine_light_overlay: bool = False,
    repair_mode: str = "fast",
    lama_client: LamaFrameClient | None = None,
) -> np.ndarray:
    if repair_mode not in {"fast", "quality"}:
        raise ValueError(f"unsupported repair mode: {repair_mode}")
    if repair_mode == "quality":
        if lama_client is None:
            raise RuntimeError("高质量修复需要 LaMa 引擎和模型")
        return lama_client.repair_frames(frames, masks)
    if strategy in {"fixed", "alpha"} and len(frames) >= 2:
        if strategy == "alpha" or refine_light_overlay:
            masks = refine_light_overlay_masks(frames, masks)
        return motion_compensated_inpaint(frames, masks)
    return temporal_inpaint(frames, masks, temporal_radius=temporal_radius)


def _frame_rate_filter(target_fps: float | None, interpolation: str) -> str | None:
    if target_fps is None:
        return None
    if not 1.0 <= target_fps <= 120.0:
        raise ValueError("target fps must be between 1 and 120")
    fps = f"{target_fps:.6f}".rstrip("0").rstrip(".")
    if interpolation == "fast":
        return f"fps=fps={fps}"
    if interpolation == "motion":
        return f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
    raise ValueError(f"unsupported interpolation mode: {interpolation}")


def _emit_progress(frame: int, total: int, started: float, stage: str) -> None:
    elapsed = max(time.perf_counter() - started, 0.001)
    speed = frame / elapsed
    remaining = (total - frame) / speed if speed > 0 else None
    print(
        json.dumps(
            {
                "event": "progress",
                "stage": stage,
                "frame": frame,
                "total": total,
                "fps": round(speed, 3),
                "remainingSeconds": round(remaining, 1) if remaining is not None else None,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def _emit_stage(stage: str, frame: int, total: int) -> None:
    print(
        json.dumps(
            {
                "event": "progress",
                "stage": stage,
                "frame": frame,
                "total": total,
                "fps": 0.0,
                "remainingSeconds": None,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def repair_video(
    *,
    input_path: Path,
    project_path: Path,
    output_path: Path,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    chunk_size: int = 80,
    overlap: int = 10,
    temporal_radius: int = 2,
    codec: str = "h264",
    crf: int = 18,
    allow_unsafe: bool = False,
    target_fps: float | None = None,
    interpolation: str = "fast",
    cancel_file: Path | None = None,
    repair_mode: str = "quality",
    lama_engine: Path | None = None,
    lama_model: Path | None = None,
) -> dict[str, Any]:
    if output_path.resolve() == input_path.resolve():
        raise ValueError("output must not overwrite input")
    if overlap < temporal_radius:
        raise ValueError("overlap must be at least temporal_radius")
    media = probe_media(input_path, ffprobe=ffprobe)
    if media["warnings"] and not allow_unsafe:
        raise ValueError("; ".join(media["warnings"]))
    capture = cv2.VideoCapture(os.fspath(input_path))
    if not capture.isOpened():
        raise RuntimeError("OpenCV could not open input")
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    masks, confidence, project = _load_masks(
        project_path, width=width, height=height, frame_count=total
    )
    use_lama = repair_mode == "quality"
    lama_client: LamaFrameClient | None = None
    if use_lama:
        if lama_engine is None or lama_model is None:
            capture.release()
            raise RuntimeError("高质量修复资源不完整，请重新解压免安装版")
        _emit_stage("model", 0, total)
        try:
            lama_client = LamaFrameClient(lama_engine, lama_model)
        except Exception:
            capture.release()
            raise
    output_path.parent.mkdir(parents=True, exist_ok=True)
    silent = output_path.with_name(f".{output_path.stem}.silent.mp4")
    writer = cv2.VideoWriter(
        os.fspath(silent), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError("OpenCV could not create intermediate video")

    started = time.perf_counter()
    frame_index = 0
    buffer_frames: list[np.ndarray] = []
    buffer_masks: list[np.ndarray] = []
    processing_error: Exception | None = None
    processing_chunk_size = 4 if use_lama else chunk_size
    processing_overlap = 0 if use_lama else overlap
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            buffer_frames.append(frame)
            buffer_masks.append(masks[frame_index])
            frame_index += 1
            if len(buffer_frames) < processing_chunk_size:
                continue
            repaired = _repair_frames(
                np.stack(buffer_frames),
                np.stack(buffer_masks),
                strategy=project["strategy"],
                temporal_radius=temporal_radius,
                refine_light_overlay=bool(project.get("refineLightOverlay", False)),
                repair_mode=repair_mode,
                lama_client=lama_client,
            )
            emit_count = len(buffer_frames) - processing_overlap
            for output_frame in repaired[:emit_count]:
                writer.write(output_frame)
            buffer_frames = buffer_frames[emit_count:]
            buffer_masks = buffer_masks[emit_count:]
            _emit_progress(frame_index - len(buffer_frames), total, started, "repair")
            if cancel_file is not None and cancel_file.exists():
                raise RuntimeError("任务已在安全分段边界取消")
        if buffer_frames:
            repaired = _repair_frames(
                np.stack(buffer_frames),
                np.stack(buffer_masks),
                strategy=project["strategy"],
                temporal_radius=temporal_radius,
                refine_light_overlay=bool(project.get("refineLightOverlay", False)),
                repair_mode=repair_mode,
                lama_client=lama_client,
            )
            for output_frame in repaired:
                writer.write(output_frame)
        _emit_progress(frame_index, total, started, "repair")
    except Exception as error:
        processing_error = error
    finally:
        capture.release()
        writer.release()
        if lama_client is not None:
            lama_client.close()
    if processing_error is not None:
        silent.unlink(missing_ok=True)
        raise processing_error

    video_encoder = "libx264" if codec == "h264" else "libx265"
    frame_filter = _frame_rate_filter(target_fps, interpolation)
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
    ]
    if frame_filter:
        command.extend(["-vf", frame_filter, "-fps_mode", "cfr"])
    command.extend(
        [
            "-c:v",
            video_encoder,
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
    )
    _emit_stage("encode", frame_index, total)
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or "FFmpeg mux failed")
    _emit_stage("finalize", frame_index, total)
    silent.unlink(missing_ok=True)
    low_confidence = np.flatnonzero(confidence < 0.5).tolist()
    return {
        "output": os.fspath(output_path.resolve()),
        "frames": frame_index,
        "elapsedSeconds": round(time.perf_counter() - started, 3),
        "lowConfidenceFrames": low_confidence,
        "targetFps": target_fps,
        "interpolation": interpolation,
        "repairMode": repair_mode,
        "media": probe_media(output_path, ffprobe=ffprobe),
    }


def repair_preview(
    *,
    input_path: Path,
    project_path: Path,
    output_path: Path,
    start_frame: int,
    end_frame: int,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    temporal_radius: int = 2,
    repair_mode: str = "quality",
    lama_engine: Path | None = None,
    lama_model: Path | None = None,
) -> dict[str, Any]:
    """Render a short, silent visual preview without touching the source file."""
    media = probe_media(input_path, ffprobe=ffprobe)
    unsafe_preview_warnings = [
        warning
        for warning in media["warnings"]
        if "可变帧率" not in warning
    ]
    if unsafe_preview_warnings:
        raise ValueError("; ".join(unsafe_preview_warnings))
    total = int(media["frame_count"])
    start = max(0, min(start_frame, total - 1))
    end = max(start, min(end_frame, total - 1))
    capture = cv2.VideoCapture(os.fspath(input_path))
    if not capture.isOpened():
        raise RuntimeError("OpenCV could not open input")
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    masks, _, project = _load_masks(
        project_path, width=width, height=height, frame_count=total
    )
    capture.set(cv2.CAP_PROP_POS_FRAMES, start)
    frames: list[np.ndarray] = []
    for _ in range(start, end + 1):
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    if not frames:
        raise RuntimeError("无法读取预览区间")

    use_lama = repair_mode == "quality"
    if use_lama and (lama_engine is None or lama_model is None):
        raise RuntimeError("高质量修复资源不完整，请重新解压免安装版")
    lama_client = (
        LamaFrameClient(lama_engine, lama_model)
        if use_lama and lama_engine is not None and lama_model is not None
        else None
    )
    try:
        repaired = _repair_frames(
            np.stack(frames),
            masks[start : start + len(frames)],
            strategy=project["strategy"],
            temporal_radius=temporal_radius,
            refine_light_overlay=bool(project.get("refineLightOverlay", False)),
            repair_mode=repair_mode,
            lama_client=lama_client,
        )
    finally:
        if lama_client is not None:
            lama_client.close()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    silent = output_path.with_name(f".{output_path.stem}.silent.mp4")
    writer = cv2.VideoWriter(
        os.fspath(silent), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not create preview")
    try:
        for frame in repaired:
            writer.write(frame)
    finally:
        writer.release()
    process = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            os.fspath(silent),
            "-map",
            "0:v:0",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "veryfast",
            "-movflags",
            "+faststart",
            os.fspath(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    silent.unlink(missing_ok=True)
    if process.returncode != 0:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(process.stderr.strip() or "FFmpeg preview encode failed")
    return {
        "output": os.fspath(output_path.resolve()),
        "startFrame": start,
        "endFrame": start + len(frames) - 1,
        "frames": len(frames),
    }
