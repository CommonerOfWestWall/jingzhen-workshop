from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from jingzhen_engine.video import probe_media  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--outputs", type=Path)
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()
    cases = json.loads(args.manifest.read_text(encoding="utf-8"))
    results = []
    failed = False
    for case in cases:
        source = Path(case["video"])
        target = args.outputs / f"{case['name']}_clean.mp4" if args.outputs else source
        media = probe_media(target, ffprobe=args.ffprobe)
        checks = {
            "frameCount": media["frame_count"] == case["frames"],
            "resolution": (media["width"], media["height"]) == (case["width"], case["height"]),
            "fps": abs(media["avg_fps"] - case["fps"]) < 0.02,
            "audioTracks": len(media["audio_streams"]) == case["audioTracks"],
            "subtitleTracks": len(media["subtitle_streams"]) == case["subtitleTracks"],
            "noWarnings": not media["warnings"],
        }
        passed = all(checks.values())
        failed = failed or not passed
        results.append({"name": case["name"], "passed": passed, "checks": checks, "media": media})
    print(json.dumps({"ok": not failed, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
