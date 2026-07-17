from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np


def _write_png(path: Path, image: np.ndarray) -> None:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError(f"无法编码 LaMa 临时帧：{path}")
    encoded.tofile(path)


def _read_png(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"无法读取 LaMa 修复结果：{path}")
    return image


class LamaFrameClient:
    def __init__(self, engine_path: Path, model_path: Path) -> None:
        if not engine_path.is_file():
            raise FileNotFoundError(f"缺少 LaMa 高清修复引擎：{engine_path}")
        if not model_path.is_file():
            raise FileNotFoundError(f"缺少 LaMa 高清修复模型：{model_path}")
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._process = subprocess.Popen(
            [os.fspath(engine_path), "--model", os.fspath(model_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=creationflags,
        )
        self._temp = tempfile.TemporaryDirectory(prefix="jingzhen-lama-")
        self._root = Path(self._temp.name)
        ready = self._read_response()
        if ready.get("ready") is not True:
            self.close()
            raise RuntimeError(str(ready.get("error") or "LaMa 引擎初始化失败"))
        self.provider = str(ready.get("provider", "unknown"))
        self.load_ms = int(ready.get("loadMs", 0))
        self._index = 0

    def _read_response(self) -> dict[str, object]:
        if self._process.stdout is None:
            raise RuntimeError("LaMa 引擎输出管道不可用")
        line = self._process.stdout.readline()
        if not line:
            stderr = ""
            if self._process.stderr is not None:
                stderr = self._process.stderr.read().strip()
            raise RuntimeError(stderr or "LaMa 引擎意外退出")
        return json.loads(line)

    def repair_frame(self, frame: np.ndarray, mask: np.ndarray) -> np.ndarray:
        if not np.any(mask):
            return frame.copy()
        self._index += 1
        source = self._root / "source.png"
        mask_path = self._root / "mask.png"
        output = self._root / "output.png"
        _write_png(source, frame)
        _write_png(mask_path, np.where(mask > 0, 255, 0).astype(np.uint8))
        request = {
            "id": str(self._index),
            "source": os.fspath(source),
            "mask": os.fspath(mask_path),
            "output": os.fspath(output),
        }
        if self._process.stdin is None:
            raise RuntimeError("LaMa 引擎输入管道不可用")
        self._process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        self._process.stdin.flush()
        response = self._read_response()
        if response.get("ok") is not True:
            raise RuntimeError(str(response.get("error") or "LaMa 单帧修复失败"))
        repaired = _read_png(output)
        source.unlink(missing_ok=True)
        mask_path.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        return repaired

    def repair_frames(self, frames: np.ndarray, masks: np.ndarray) -> np.ndarray:
        return np.stack(
            [
                self.repair_frame(frame, mask)
                for frame, mask in zip(frames, masks, strict=True)
            ]
        )

    def close(self) -> None:
        process = getattr(self, "_process", None)
        if process is not None and process.poll() is None:
            if process.stdin is not None:
                try:
                    process.stdin.write('{"command":"stop"}\n')
                    process.stdin.flush()
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        temp = getattr(self, "_temp", None)
        if temp is not None:
            temp.cleanup()

    def __enter__(self) -> "LamaFrameClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
