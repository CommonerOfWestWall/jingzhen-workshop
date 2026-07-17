from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

import cv2

from . import __version__
from .composite import composite_repaired_video
from .inpaint import chunk_windows
from .tracking import track_template_overlay, track_video_project
from .video import probe_media, repair_preview, repair_video


def _runtime() -> dict[str, Any]:
    cuda_devices = 0
    try:
        cuda_devices = int(cv2.cuda.getCudaEnabledDeviceCount())
    except (AttributeError, cv2.error):
        pass
    gpu: dict[str, Any] | None = None
    if shutil.which("nvidia-smi"):
        process = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if process.returncode == 0 and process.stdout.strip():
            name, memory, driver = [part.strip() for part in process.stdout.splitlines()[0].split(",")]
            gpu = {"name": name, "memory_mib": int(memory), "driver": driver}
    return {
        "engine": __version__,
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "opencv": cv2.__version__,
        "opencv_cuda_devices": cuda_devices,
        "gpu": gpu,
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "offline": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jingzhen-engine")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("probe-runtime")
    chunks = subparsers.add_parser("plan-chunks")
    chunks.add_argument("--frames", type=int, required=True)
    chunks.add_argument("--chunk-size", type=int, default=80)
    chunks.add_argument("--overlap", type=int, default=10)
    probe = subparsers.add_parser("probe-media")
    probe.add_argument("path", type=Path)
    probe.add_argument("--ffprobe", default="ffprobe")
    repair = subparsers.add_parser("repair-video")
    repair.add_argument("--input", type=Path, required=True)
    repair.add_argument("--project", type=Path, required=True)
    repair.add_argument("--output", type=Path, required=True)
    repair.add_argument("--ffmpeg", default="ffmpeg")
    repair.add_argument("--ffprobe", default="ffprobe")
    repair.add_argument("--chunk-size", type=int, default=80)
    repair.add_argument("--overlap", type=int, default=10)
    repair.add_argument("--temporal-radius", type=int, default=2)
    repair.add_argument("--codec", choices=("h264", "h265"), default="h264")
    repair.add_argument("--crf", type=int, default=18)
    repair.add_argument("--allow-unsafe", action="store_true")
    repair.add_argument("--target-fps", type=float)
    repair.add_argument("--interpolation", choices=("fast", "motion"), default="fast")
    repair.add_argument("--cancel-file", type=Path)
    repair.add_argument("--repair-mode", choices=("quality", "fast"), default="quality")
    repair.add_argument("--lama-engine", type=Path)
    repair.add_argument("--lama-model", type=Path)
    tracking = subparsers.add_parser("track-template-overlay")
    tracking.add_argument("--input", type=Path, required=True)
    tracking.add_argument("--output-project", type=Path, required=True)
    tracking.add_argument("--template-frame", type=int, default=0)
    tracking.add_argument("--template-box", type=int, nargs=4, required=True)
    tracking.add_argument("--template-mask", type=Path, required=True)
    tracking.add_argument("--search-box", type=int, nargs=4, required=True)
    tracking.add_argument("--threshold", type=float, default=0.98)
    tracking.add_argument("--max-extrapolation", type=int, default=30)
    tracking.add_argument("--dilation", type=int, default=2)
    video_tracking = subparsers.add_parser("track-video")
    video_tracking.add_argument("--input", type=Path, required=True)
    video_tracking.add_argument("--project", type=Path, required=True)
    video_tracking.add_argument("--output-project", type=Path, required=True)
    composite = subparsers.add_parser("composite-repair")
    composite.add_argument("--input", type=Path, required=True)
    composite.add_argument("--repaired", type=Path, required=True)
    composite.add_argument("--project", type=Path, required=True)
    composite.add_argument("--output", type=Path, required=True)
    composite.add_argument("--ffmpeg", default="ffmpeg")
    composite.add_argument("--ffprobe", default="ffprobe")
    composite.add_argument("--feather", type=int, default=3)
    composite.add_argument("--crf", type=int, default=18)
    preview = subparsers.add_parser("preview-video")
    preview.add_argument("--input", type=Path, required=True)
    preview.add_argument("--project", type=Path, required=True)
    preview.add_argument("--output", type=Path, required=True)
    preview.add_argument("--start-frame", type=int, required=True)
    preview.add_argument("--end-frame", type=int, required=True)
    preview.add_argument("--ffmpeg", default="ffmpeg")
    preview.add_argument("--ffprobe", default="ffprobe")
    preview.add_argument("--repair-mode", choices=("quality", "fast"), default="quality")
    preview.add_argument("--lama-engine", type=Path)
    preview.add_argument("--lama-model", type=Path)
    return parser


def run(argv: Sequence[str] | None = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    if args.command == "probe-runtime":
        return {"ok": True, "command": args.command, "runtime": _runtime()}
    if args.command == "plan-chunks":
        windows = chunk_windows(
            frame_count=args.frames,
            chunk_size=args.chunk_size,
            overlap=args.overlap,
        )
        return {"ok": True, "command": args.command, "windows": windows}
    if args.command == "probe-media":
        return {
            "ok": True,
            "command": args.command,
            "media": probe_media(args.path, ffprobe=args.ffprobe),
        }
    if args.command == "repair-video":
        result = repair_video(
            input_path=args.input,
            project_path=args.project,
            output_path=args.output,
            ffmpeg=args.ffmpeg,
            ffprobe=args.ffprobe,
            chunk_size=args.chunk_size,
            overlap=args.overlap,
            temporal_radius=args.temporal_radius,
            codec=args.codec,
            crf=args.crf,
            allow_unsafe=args.allow_unsafe,
            target_fps=args.target_fps,
            interpolation=args.interpolation,
            cancel_file=args.cancel_file,
            repair_mode=args.repair_mode,
            lama_engine=args.lama_engine,
            lama_model=args.lama_model,
        )
        return {"ok": True, "command": args.command, **result}
    if args.command == "track-template-overlay":
        result = track_template_overlay(
            input_path=args.input,
            output_project=args.output_project,
            template_frame=args.template_frame,
            template_box=tuple(args.template_box),
            template_mask_path=args.template_mask,
            search_box=tuple(args.search_box),
            threshold=args.threshold,
            max_extrapolation=args.max_extrapolation,
            dilation=args.dilation,
        )
        return {"ok": True, "command": args.command, **result}
    if args.command == "track-video":
        def tracking_progress(stage: str, frame: int, total: int) -> None:
            print(
                json.dumps(
                    {
                        "event": "tracking-progress",
                        "stage": stage,
                        "frame": frame,
                        "total": total,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

        result = track_video_project(
            input_path=args.input,
            project_path=args.project,
            output_project=args.output_project,
            progress=tracking_progress,
        )
        return {"ok": True, "command": args.command, **result}
    if args.command == "composite-repair":
        result = composite_repaired_video(
            input_path=args.input,
            repaired_path=args.repaired,
            project_path=args.project,
            output_path=args.output,
            ffmpeg=args.ffmpeg,
            ffprobe=args.ffprobe,
            feather=args.feather,
            crf=args.crf,
        )
        return {"ok": True, "command": args.command, **result}
    if args.command == "preview-video":
        result = repair_preview(
            input_path=args.input,
            project_path=args.project,
            output_path=args.output,
            start_frame=args.start_frame,
            end_frame=args.end_frame,
            ffmpeg=args.ffmpeg,
            ffprobe=args.ffprobe,
            repair_mode=args.repair_mode,
            lama_engine=args.lama_engine,
            lama_model=args.lama_model,
        )
        return {"ok": True, "command": args.command, **result}
    raise AssertionError(f"unhandled command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = run(argv)
    except Exception as error:  # CLI boundary converts failures to structured output.
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
