from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort


if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")


def read_image(path: str, mode: int = cv2.IMREAD_COLOR) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), mode)
    if image is None:
        raise RuntimeError(f"无法读取图片：{path}")
    return image


def write_png(path: str, image: np.ndarray) -> None:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError(f"无法编码图片：{path}")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(target)


class LamaEngine:
    def __init__(self, model_path: Path, required_provider: str | None = None) -> None:
        options = ort.SessionOptions()
        options.log_severity_level = 3
        available = ort.get_available_providers()
        providers = [
            provider
            for provider in ("CUDAExecutionProvider", "CPUExecutionProvider")
            if provider in available
        ]
        if required_provider and required_provider not in providers:
            raise RuntimeError(f"所需推理设备不可用：{required_provider}")
        self.session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=providers
        )
        if required_provider:
            self.session.disable_fallback()
        self.provider = self.session.get_providers()[0]
        if required_provider and self.provider != required_provider:
            raise RuntimeError(
                f"模型未在所需设备运行：期望 {required_provider}，实际 {self.provider}"
            )

    def infer(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        resized_image = cv2.resize(image, (512, 512), interpolation=cv2.INTER_AREA)
        resized_mask = cv2.resize(mask, (512, 512), interpolation=cv2.INTER_NEAREST)
        image_blob = resized_image.transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        mask_blob = (resized_mask[None, None] > 0).astype(np.float32)
        output = self.session.run(
            ["output"], {"image": image_blob, "mask": mask_blob}
        )[0][0].transpose(1, 2, 0)
        return np.clip(output, 0, 255).astype(np.uint8)


def crop_bounds(mask: np.ndarray, margin: int = 160) -> tuple[int, int, int, int]:
    points = cv2.findNonZero(mask)
    if points is None:
        raise RuntimeError("选区为空，请先标记要移除的区域")
    x, y, width, height = cv2.boundingRect(points)
    image_height, image_width = mask.shape[:2]
    left = max(0, x - margin)
    top = max(0, y - margin)
    right = min(image_width, x + width + margin)
    bottom = min(image_height, y + height + margin)
    side = min(max(right - left, bottom - top, 512), image_width, image_height)
    center_x = x + width // 2
    center_y = y + height // 2
    left = min(max(0, center_x - side // 2), image_width - side)
    top = min(max(0, center_y - side // 2), image_height - side)
    return left, top, left + side, top + side


def _repair_component(
    engine: LamaEngine, image: np.ndarray, component_mask: np.ndarray
) -> np.ndarray:
    left, top, right, bottom = crop_bounds(component_mask)
    crop = image[top:bottom, left:right]
    crop_mask = component_mask[top:bottom, left:right]
    generated = engine.infer(crop, crop_mask)
    generated = cv2.resize(
        generated, (crop.shape[1], crop.shape[0]), interpolation=cv2.INTER_CUBIC
    )
    blend = cv2.GaussianBlur(crop_mask, (0, 0), 2.2).astype(np.float32) / 255.0
    blend[crop_mask == 0] = 0.0
    blend = blend[..., None]
    result = image.copy()
    result[top:bottom, left:right] = (
        generated * blend + crop * (1.0 - blend)
    ).astype(np.uint8)
    return result


def repair(engine: LamaEngine, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if mask.shape[:2] != image.shape[:2]:
        mask = cv2.resize(
            mask, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_NEAREST
        )
    mask = (mask > 0).astype(np.uint8) * 255
    if not mask.any():
        return image.copy()
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=1)
    component_count, labels = cv2.connectedComponents(mask)
    result = image.copy()
    for label in range(1, component_count):
        component_mask = np.where(labels == label, 255, 0).astype(np.uint8)
        result = _repair_component(engine, result, component_mask)
    return result


def process_job(engine: LamaEngine, job: dict[str, object]) -> dict[str, object]:
    started = time.perf_counter()
    source = str(job["source"])
    output = str(job["output"])
    image = read_image(source)
    mask = read_image(str(job["mask"]), cv2.IMREAD_GRAYSCALE)
    result = repair(engine, image, mask)
    write_png(output, result)
    return {
        "id": str(job.get("id", "")),
        "ok": True,
        "output": output,
        "width": int(result.shape[1]),
        "height": int(result.shape[0]),
        "elapsedMs": round((time.perf_counter() - started) * 1000),
    }


def serve(model_path: Path, required_provider: str | None = None) -> None:
    load_started = time.perf_counter()
    engine = LamaEngine(model_path, required_provider)
    print(
        json.dumps(
            {
                "ready": True,
                "loadMs": round((time.perf_counter() - load_started) * 1000),
                "provider": engine.provider,
            }
        ),
        flush=True,
    )
    for line in sys.stdin:
        request: dict[str, object] = {}
        try:
            request = json.loads(line)
            if request.get("command") == "stop":
                break
            response = process_job(engine, request)
        except Exception as error:
            response = {
                "id": str(request.get("id", "")),
                "ok": False,
                "error": str(error),
            }
        print(json.dumps(response, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(prog="lama-frame-engine")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--require-provider")
    args = parser.parse_args()
    if not args.model.is_file():
        raise FileNotFoundError(f"LaMa 模型不存在：{args.model}")
    if args.check:
        load_started = time.perf_counter()
        engine = LamaEngine(args.model, args.require_provider)
        image = np.zeros((512, 512, 3), dtype=np.uint8)
        mask = np.zeros((512, 512), dtype=np.uint8)
        mask[224:288, 224:288] = 255
        infer_started = time.perf_counter()
        engine.infer(image, mask)
        print(
            json.dumps(
                {
                    "ready": True,
                    "provider": engine.provider,
                    "loadMs": round((infer_started - load_started) * 1000),
                    "inferenceMs": round(
                        (time.perf_counter() - infer_started) * 1000
                    ),
                }
            ),
            flush=True,
        )
        return
    serve(args.model, args.require_provider)


if __name__ == "__main__":
    main()
