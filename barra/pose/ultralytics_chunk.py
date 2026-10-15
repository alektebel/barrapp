"""One isolated Ultralytics inference chunk, invoked by ultralytics_parallel."""
from __future__ import annotations

import os
import json
import sys
import time
from pathlib import Path

import numpy as np


def _cpu_thread_limit() -> int:
    raw = os.environ.get("BARRA_POSE_CPU_THREADS", "1").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def infer_frames(frames: np.ndarray, weights: str, imgsz: int, device: str,
                 confidence: float) -> tuple[np.ndarray, dict[str, float]]:
    """Run one chunk, usable by subprocess and inherited-fork workers."""
    total_started = time.perf_counter()
    stage = time.perf_counter()
    from ultralytics import YOLO
    import torch
    import ultralytics.utils as ultralytics_utils
    import ultralytics.utils.torch_utils as torch_utils
    imports = time.perf_counter() - stage

    # select_device("cpu") restores this version-sensitive Ultralytics
    # constant, so cap it as well as PyTorch's current intra-op setting.
    if device.strip().lower() in {"cpu", ""}:
        limit = _cpu_thread_limit()
        torch.set_num_threads(limit)
        ultralytics_utils.NUM_THREADS = limit
        torch_utils.NUM_THREADS = limit

    stage = time.perf_counter()
    model = YOLO(weights)
    model_load = time.perf_counter() - stage
    rows = []
    stage = time.perf_counter()
    for result in model.predict(source=list(frames), stream=True, verbose=False,
                                device=device, imgsz=imgsz, conf=confidence):
        row = np.zeros((17, 3), dtype=np.float32)
        keypoints = result.keypoints
        if keypoints is not None and keypoints.xy is not None and len(keypoints.xy):
            boxes = result.boxes
            person = 0
            if boxes is not None and len(boxes):
                areas = (boxes.xywh[:, 2] * boxes.xywh[:, 3]).cpu().numpy()
                person = int(np.argmax(areas))
            person = min(person, len(keypoints.xy) - 1)
            xy = keypoints.xy[person].cpu().numpy()
            conf = (keypoints.conf[person].cpu().numpy()
                    if keypoints.conf is not None else np.ones(len(xy)))
            count = min(17, len(xy), len(conf))
            row[:count, :2], row[:count, 2] = xy[:count], conf[:count]
        rows.append(row)
    if len(rows) != len(frames):
        raise RuntimeError(f"model returned {len(rows)} rows for {len(frames)} frames")
    inference = time.perf_counter() - stage
    return np.stack(rows), {
        "imports_seconds": imports,
        "model_load_seconds": model_load,
        "inference_seconds": inference,
        "worker_total_seconds": time.perf_counter() - total_started,
    }


def main(argv: list[str]) -> int:
    source, weights, imgsz_s, device, confidence_s, output, *timing_output = argv
    total_started = time.perf_counter()
    frames = np.load(source)
    input_load = time.perf_counter() - total_started
    rows, timing = infer_frames(frames, weights, int(imgsz_s), device,
                                float(confidence_s))
    stage = time.perf_counter()
    np.save(Path(output), rows)
    timing["input_load_seconds"] = input_load
    timing["output_save_seconds"] = time.perf_counter() - stage
    if timing_output:
        timing["worker_total_seconds"] = time.perf_counter() - total_started
        Path(timing_output[0]).write_text(json.dumps(timing, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
