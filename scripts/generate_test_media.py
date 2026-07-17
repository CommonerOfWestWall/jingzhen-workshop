from __future__ import annotations

import argparse
import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class Case:
    name: str
    width: int
    height: int
    fps: int
    frames: int
    mode: str
    audio_tracks: int = 0
    subtitle: bool = False


CASES = (
    Case("fixed_horizontal_24", 320, 180, 24, 48, "fixed", 1, True),
    Case("moving_horizontal_25", 320, 180, 25, 50, "moving"),
    Case("transform_horizontal_30", 320, 180, 30, 60, "transform", 1),
    Case("alpha_vertical_60", 180, 320, 60, 120, "alpha", 2),
)


def _base_frame(width: int, height: int, index: int, total: int) -> np.ndarray:
    x = np.arange(width, dtype=np.uint16)[None, :]
    y = np.arange(height, dtype=np.uint16)[:, None]
    frame = np.empty((height, width, 3), dtype=np.uint8)
    frame[:, :, 0] = ((x * 3 + index * 2) % 256).astype(np.uint8)
    frame[:, :, 1] = ((y * 4 + index * 3) % 256).astype(np.uint8)
    frame[:, :, 2] = (((x + y) * 2 + index * 5) % 256).astype(np.uint8)
    block = max(8, min(width, height) // 12)
    checker = (((x // block + y // block) % 2) * 35).astype(np.uint8)
    frame = cv2.add(frame, np.repeat(checker[:, :, None], 3, axis=2))
    phase = index / max(1, total - 1)
    person_x = int(width * (0.55 + 0.15 * math.sin(phase * math.tau)))
    cv2.circle(frame, (person_x, int(height * 0.45)), max(10, height // 12), (70, 150, 220), -1)
    cv2.rectangle(
        frame,
        (person_x - max(8, width // 30), int(height * 0.52)),
        (person_x + max(8, width // 30), int(height * 0.85)),
        (45, 95, 180),
        -1,
    )
    cv2.putText(
        frame,
        "AUTHORIZED TEST",
        (8, height - 12),
        cv2.FONT_HERSHEY_SIMPLEX,
        max(0.35, width / 800),
        (245, 245, 245),
        1,
        cv2.LINE_AA,
    )
    return frame


def _marker(size: tuple[int, int]) -> np.ndarray:
    width, height = size
    patch = np.zeros((height, width, 4), dtype=np.uint8)
    patch[:, :, :3] = (235, 235, 235)
    patch[:, :, 3] = 255
    cv2.rectangle(patch, (0, 0), (width - 1, height - 1), (25, 25, 25, 255), 2)
    cv2.line(patch, (5, 5), (width - 6, height - 6), (40, 40, 40, 255), 2)
    cv2.line(patch, (width - 6, 5), (5, height - 6), (40, 40, 40, 255), 2)
    return patch


def _composite(frame: np.ndarray, patch: np.ndarray, x: int, y: int, alpha: float) -> None:
    height, width = patch.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(frame.shape[1], x + width), min(frame.shape[0], y + height)
    if x1 >= x2 or y1 >= y2:
        return
    source = patch[y1 - y : y2 - y, x1 - x : x2 - x, :3].astype(np.float32)
    source_alpha = patch[y1 - y : y2 - y, x1 - x : x2 - x, 3].astype(np.float32) / 255
    source_alpha = (source_alpha * alpha)[:, :, None]
    target = frame[y1:y2, x1:x2].astype(np.float32)
    frame[y1:y2, x1:x2] = np.clip(
        source * source_alpha + target * (1 - source_alpha), 0, 255
    ).astype(np.uint8)


def _shape_rect(x: float, y: float, w: float, h: float, width: int, height: int) -> dict:
    margin = 3
    return {
        "kind": "rect",
        "points": [
            [(x - margin) / width, (y - margin) / height],
            [(x + w + margin) / width, (y + h + margin) / height],
        ],
    }


def _render_case(case: Case, root: Path, ffmpeg: str) -> dict:
    silent = root / f".{case.name}.silent.mp4"
    output = root / f"{case.name}.mp4"
    project_path = root / f"{case.name}.jzf.json"
    writer = cv2.VideoWriter(
        str(silent),
        cv2.VideoWriter_fourcc(*"mp4v"),
        case.fps,
        (case.width, case.height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"cannot create {silent}")
    marker = _marker((64, 28))
    keyframes: list[dict] = []
    for index in range(case.frames):
        progress = index / max(1, case.frames - 1)
        frame = _base_frame(case.width, case.height, index, case.frames)
        if case.mode == "fixed":
            x, y = 18, 18
            if index == 0:
                keyframes.append({"frame": 0, "shapes": [_shape_rect(x, y, 64, 28, case.width, case.height)]})
            _composite(frame, marker, x, y, 0.88)
        elif case.mode == "moving":
            x = int(12 + (case.width - 88) * progress)
            y = int(case.height * 0.3 + 18 * math.sin(progress * math.tau))
            if index % 6 == 0 or index == case.frames - 1:
                keyframes.append({"frame": index, "shapes": [_shape_rect(x, y, 64, 28, case.width, case.height)]})
            _composite(frame, marker, x, y, 0.92)
        elif case.mode == "transform":
            scale = 0.7 + 0.6 * progress
            angle = -25 + 65 * progress
            matrix = cv2.getRotationMatrix2D((32, 14), angle, scale)
            transformed = cv2.warpAffine(marker, matrix, (88, 64), borderValue=(0, 0, 0, 0))
            x = int(8 + (case.width - 105) * progress * progress)
            y = int(20 + (case.height - 100) * progress)
            if index % 15 == 0 or index == case.frames - 1:
                keyframes.append({"frame": index, "shapes": [_shape_rect(x, y, 88, 64, case.width, case.height)]})
            _composite(frame, transformed, x, y, 0.9)
        else:
            x = int(12 + (case.width - 88) * progress)
            y = int(case.height * 0.42 + 25 * math.sin(progress * math.tau * 2))
            opacity = 0.08 + 0.84 * (0.5 + 0.5 * math.sin(progress * math.tau * 4))
            if index % 10 == 0 or index == case.frames - 1:
                keyframes.append({"frame": index, "shapes": [_shape_rect(x, y, 64, 28, case.width, case.height)]})
            _composite(frame, marker, x, y, opacity)
            if 0.42 <= progress <= 0.58:
                cv2.rectangle(frame, (x + 12, y - 8), (x + 48, y + 42), (20, 190, 90), -1)
        writer.write(frame)
    writer.release()

    project = {
        "version": 1,
        "strategy": "alpha" if case.mode == "alpha" else ("fixed" if case.mode == "fixed" else "moving"),
        "activeRange": [0, case.frames - 1],
        "dilation": 2,
        "feather": 2,
        "lowConfidenceGap": max(8, case.fps // 2),
        "keyframes": keyframes,
    }
    project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")

    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(silent)]
    for track in range(case.audio_tracks):
        frequency = 440 + track * 220
        command += ["-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000:duration={case.frames / case.fps}"]
    subtitle_path = root / f".{case.name}.srt"
    if case.subtitle:
        subtitle_path.write_text(
            "1\n00:00:00,200 --> 00:00:01,500\nAuthorized regression sample\n",
            encoding="utf-8",
        )
        command += ["-i", str(subtitle_path)]
    command += ["-map", "0:v:0"]
    for track in range(case.audio_tracks):
        command += ["-map", f"{track + 1}:a:0"]
    if case.subtitle:
        command += ["-map", f"{case.audio_tracks + 1}:s:0"]
    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18"]
    if case.audio_tracks:
        command += ["-c:a", "aac", "-b:a", "128k"]
    if case.subtitle:
        command += ["-c:s", "mov_text"]
    command += ["-t", str(case.frames / case.fps), "-movflags", "+faststart", str(output)]
    subprocess.run(command, check=True)
    silent.unlink(missing_ok=True)
    subtitle_path.unlink(missing_ok=True)
    return {
        "name": case.name,
        "video": str(output),
        "project": str(project_path),
        "width": case.width,
        "height": case.height,
        "fps": case.fps,
        "frames": case.frames,
        "audioTracks": case.audio_tracks,
        "subtitleTracks": 1 if case.subtitle else 0,
        "mode": case.mode,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = [_render_case(case, args.output, args.ffmpeg) for case in CASES]
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"ok": True, "cases": len(manifest)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
