from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from PIL import Image

from .video import _load_masks, probe_media


def _processing_size(width: int, height: int, processing_width: int) -> tuple[int, int]:
    if processing_width <= 0 or processing_width > width:
        raise ValueError("processing_width must be positive and no larger than input")
    processing_height = max(8, round((height * processing_width / width) / 8) * 8)
    return processing_width, processing_height


def _resolve_backend_paths(
    propainter_dir: Path, python_executable: Path
) -> tuple[Path, Path, Path]:
    root = propainter_dir.resolve()
    return root, root / "inference_propainter.py", python_executable.resolve()


def repair_video_propainter(
    *,
    input_path: Path,
    project_path: Path,
    output_path: Path,
    propainter_dir: Path,
    python_executable: Path,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    processing_width: int = 480,
    subvideo_length: int = 24,
    neighbor_length: int = 8,
    ref_stride: int = 12,
    crf: int = 18,
) -> dict[str, Any]:
    """Run an explicitly supplied, non-bundled ProPainter checkout."""
    propainter_dir, inference, python_executable = _resolve_backend_paths(
        propainter_dir, python_executable
    )
    if output_path.resolve() == input_path.resolve():
        raise ValueError("output must not overwrite input")
    if not inference.is_file():
        raise FileNotFoundError(f"ProPainter entry point not found: {inference}")
    if not python_executable.is_file():
        raise FileNotFoundError(f"Python executable not found: {python_executable}")
    for weight in (
        "ProPainter.pth",
        "raft-things.pth",
        "recurrent_flow_completion.pth",
    ):
        if not (propainter_dir / "weights" / weight).is_file():
            raise FileNotFoundError(f"ProPainter weight not found: {weight}")

    media = probe_media(input_path, ffprobe=ffprobe)
    if media["warnings"]:
        raise ValueError("; ".join(media["warnings"]))
    width, height = int(media["width"]), int(media["height"])
    process_width, process_height = _processing_size(width, height, processing_width)
    masks, confidence, project = _load_masks(
        project_path,
        width=width,
        height=height,
        frame_count=int(media["frame_count"]),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="jingzhen-propainter-") as temporary:
        work = Path(temporary)
        local_input = work / "input.mp4"
        shutil.copy2(input_path, local_input)
        if project["strategy"] == "fixed":
            mask_path = work / "mask.png"
            Image.fromarray(masks[0]).save(mask_path)
        else:
            mask_path = work / "masks"
            mask_path.mkdir()
            for index, mask in enumerate(masks):
                Image.fromarray(mask).save(mask_path / f"{index:05d}.png")

        results = work / "results"
        command = [
            os.fspath(python_executable),
            os.fspath(inference),
            "--video",
            os.fspath(local_input),
            "--mask",
            os.fspath(mask_path),
            "--output",
            os.fspath(results),
            "--width",
            str(process_width),
            "--height",
            str(process_height),
            "--mask_dilation",
            "2",
            "--ref_stride",
            str(ref_stride),
            "--neighbor_length",
            str(neighbor_length),
            "--subvideo_length",
            str(subvideo_length),
            "--save_fps",
            str(round(float(media["avg_fps"]))),
            "--fp16",
        ]
        process = subprocess.run(
            command,
            cwd=propainter_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if process.returncode != 0:
            raise RuntimeError(process.stderr.strip() or process.stdout.strip())
        repaired = results / "input" / "inpaint_out.mp4"
        if not repaired.is_file():
            raise RuntimeError("ProPainter completed without an output video")

        encoder = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            os.fspath(repaired),
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
            "-vf",
            f"scale={width}:{height}:flags=lanczos",
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
        mux = subprocess.run(encoder, capture_output=True, text=True, check=False)
        if mux.returncode != 0:
            output_path.unlink(missing_ok=True)
            raise RuntimeError(mux.stderr.strip() or "FFmpeg ProPainter mux failed")

    low_confidence = confidence < 0.5
    return {
        "output": os.fspath(output_path.resolve()),
        "frames": int(media["frame_count"]),
        "elapsedSeconds": round(time.perf_counter() - started, 3),
        "lowConfidenceFrames": low_confidence.nonzero()[0].tolist(),
        "backend": "propainter-external",
        "processingSize": [process_width, process_height],
        "media": probe_media(output_path, ffprobe=ffprobe),
    }
