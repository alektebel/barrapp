"""Stateless frame-chunk inference for the optional Ultralytics backend."""
from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np


def split_ranges(n_samples: int, n_workers: int) -> list[tuple[int, int]]:
    """Split sample indices into balanced, contiguous half-open ranges."""
    if n_samples <= 0:
        return []
    n_chunks = min(n_samples, max(1, n_workers))
    quotient, remainder = divmod(n_samples, n_chunks)
    chunks = []
    start = 0
    for i in range(n_chunks):
        end = start + quotient + (1 if i < remainder else 0)
        chunks.append((start, end))
        start = end
    return chunks


def dense_from_samples(samples: np.ndarray, sample_frames: list[int],
                       n_frames: int) -> np.ndarray:
    """Interpolate sampled COCO keypoints back onto original frame indices."""
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim != 3 or samples.shape[2] != 3:
        raise ValueError("samples must have shape (T, keypoints, 3)")
    if n_frames <= 0 or not sample_frames or len(sample_frames) != len(samples):
        raise ValueError("sample frame indices must match a nonempty sample array")
    x = np.asarray(sample_frames, dtype=np.int64)
    if x[0] < 0 or x[-1] >= n_frames or np.any(np.diff(x) <= 0):
        raise ValueError("sample frame indices must increase within the video")

    target = np.arange(n_frames, dtype=np.float64)
    dense = np.empty((n_frames, samples.shape[1], 3), dtype=np.float32)
    for joint in range(samples.shape[1]):
        for channel in range(3):
            dense[:, joint, channel] = np.interp(
                target, x, samples[:, joint, channel]
            )
    dense[:, :, 2] = np.clip(dense[:, :, 2], 0.0, 1.0)
    return dense


def _run_fork_workers(frames: list[np.ndarray], ranges: list[tuple[int, int]],
                     weights: str, imgsz: int, device: str, confidence: float,
                     root: Path) -> tuple[list[tuple[Path, Path]], float]:
    """Run Linux workers over inherited frames, avoiding Python/model re-imports."""
    from .ultralytics_chunk import _cpu_thread_limit, infer_frames
    import torch
    import ultralytics.utils as ultralytics_utils
    import ultralytics.utils.torch_utils as torch_utils

    output_reports = []
    children = []
    fork_failure: OSError | None = None
    started = time.perf_counter()
    for index, (start, end) in enumerate(ranges):
        output = root / f"pose-{index}.npy"
        report = root / f"timing-{index}.json"
        error = root / f"error-{index}.txt"
        try:
            pid = os.fork()
        except OSError as exc:
            fork_failure = exc
            break
        if pid == 0:
            try:
                if device.strip().lower() in {"cpu", ""}:
                    limit = _cpu_thread_limit()
                    torch.set_num_threads(limit)
                    ultralytics_utils.NUM_THREADS = limit
                    torch_utils.NUM_THREADS = limit
                chunk, timing = infer_frames(frames[start:end], weights, imgsz,
                                             device, confidence)
                np.save(output, chunk)
                report.write_text(json.dumps(timing, sort_keys=True))
                os._exit(0)
            except BaseException as exc:  # propagate child errors to the parent
                error.write_text(f"{type(exc).__name__}: {exc}")
                os._exit(1)
        children.append((pid, output, report, error))
        output_reports.append((output, report))

    failures = []
    for pid, _, _, error in children:
        _, status = os.waitpid(pid, 0)
        if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
            message = error.read_text() if error.exists() else f"worker exited with status {status}"
            failures.append(message)
    if failures:
        raise RuntimeError("forked pose worker failed: " + " | ".join(failures))
    if fork_failure is not None:
        raise OSError(f"could only launch {len(children)}/{len(ranges)} fork workers") from fork_failure
    return output_reports, time.perf_counter() - started


def infer_chunks(frames: list[np.ndarray], weights: str, imgsz: int,
                 device: str, n_workers: int, confidence: float = 0.25,
                 timing: dict[str, float] | None = None,
                 worker_timing: list[dict[str, float]] | None = None,
                 worker_mode: str = "subprocess") -> np.ndarray:
    """Infer decoded frames in isolated workers and return COCO-17 keypoints."""
    if worker_mode not in {"subprocess", "fork"}:
        raise ValueError(f"unknown pose worker mode: {worker_mode}")
    fork_unsupported = (not hasattr(os, "fork")
                       or device.strip().lower() not in {"", "cpu"})
    if worker_mode == "fork" and fork_unsupported:
        worker_mode = "subprocess"
        if timing is not None:
            timing["fork_fallback"] = 1.0
    ranges = split_ranges(len(frames), n_workers)
    if not ranges:
        raise RuntimeError("no video frames decoded")
    with tempfile.TemporaryDirectory(prefix="barra-yolo-") as temp:
        root = Path(temp)
        tasks = []
        stage_started = time.perf_counter()
        for index, (start, end) in enumerate(ranges):
            source = root / f"frames-{index}.npy"
            output = root / f"pose-{index}.npy"
            worker_report = root / f"timing-{index}.json"
            if worker_mode == "subprocess":
                np.save(source, np.stack(frames[start:end]))
                tasks.append((source, output, worker_report))
            else:
                tasks.append((start, end, output, worker_report))
        if timing is not None:
            timing["chunk_write_seconds"] = time.perf_counter() - stage_started

        if worker_mode == "fork":
            try:
                results, worker_wall = _run_fork_workers(
                    frames, ranges, weights, imgsz, device, confidence, root
                )
                if timing is not None:
                    timing["workers_wall_seconds"] = worker_wall
            except OSError:
                # A partial fork launch is reaped before this fallback. Rebuild
                # the serialized tasks only after it is safe to discard them.
                worker_mode = "subprocess"
                if timing is not None:
                    timing["fork_fallback"] = 1.0
                tasks = []
                stage_started = time.perf_counter()
                for index, (start, end) in enumerate(ranges):
                    source = root / f"frames-{index}.npy"
                    output = root / f"pose-{index}.npy"
                    worker_report = root / f"timing-{index}.json"
                    np.save(source, np.stack(frames[start:end]))
                    tasks.append((source, output, worker_report))
                if timing is not None:
                    timing["chunk_write_seconds"] = time.perf_counter() - stage_started

        if worker_mode == "subprocess":

            def infer(task: tuple[Path, Path, Path]) -> tuple[Path, Path]:
                source, output, worker_report = task
                subprocess.run(
                    [sys.executable, "-m", "barra.pose.ultralytics_chunk",
                     str(source), weights, str(imgsz), device, str(confidence),
                     str(output), str(worker_report)],
                    check=True, stdout=subprocess.DEVNULL,
                )
                if not output.exists():
                    raise RuntimeError("YOLO chunk worker returned no keypoints")
                return output, worker_report

            stage_started = time.perf_counter()
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(ranges)) as pool:
                results = list(pool.map(infer, tasks))
            if timing is not None:
                timing["workers_wall_seconds"] = time.perf_counter() - stage_started
        outputs = [result[0] for result in results]
        if worker_timing is not None:
            worker_timing.extend(json.loads(path.read_text()) for _, path in results)
        stage_started = time.perf_counter()
        parts = [np.load(path) for path in outputs]
        merged = np.concatenate(parts, axis=0)
        if timing is not None:
            timing["load_merge_seconds"] = time.perf_counter() - stage_started
    if any(len(part) != end - start
           for part, (start, end) in zip(parts, ranges)):
        raise RuntimeError("YOLO chunk returned an unexpected frame count")
    return merged
