from __future__ import annotations

import sys
from concurrent.futures import Future
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "server" / "api"))

import local_server  # noqa: E402


def test_local_server_publishes_measurement_before_advisory_enrichment(tmp_path,
                                                                       monkeypatch):
    job_id = "fast-result-test"
    video = tmp_path / f"{job_id}.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(local_server, "DATA", tmp_path)
    monkeypatch.setattr(local_server, "JOBS", {
        job_id: {"id": job_id, "owner": "device", "exercise": "auto",
                 "status": "processing", "createdAt": "test"}
    })
    events = []

    class ImmediatePool:
        def __init__(self, **_kwargs):
            pass

        def submit(self, fn):
            future = Future()
            # The test controls the result; no provider or network is used.
            future.set_result(None)
            return future

        def shutdown(self, **_kwargs):
            pass

    monkeypatch.setattr(local_server, "ThreadPoolExecutor", ImmediatePool)

    def measure(_job, _video, **kwargs):
        assert callable(kwargs["vision_label"])
        assert kwargs["vision_label"]() is None
        events.append("measured")
        return {"exercise": "pull_up", "n_reps": 10,
                "visionStatus": "pending", "proseStatus": "pending"}

    monkeypatch.setattr(local_server, "measure_job", measure)

    def add_vision(_job, _video, result):
        current = local_server.JOBS[job_id]
        assert current["status"] == "done"
        assert current["result"]["n_reps"] == 10
        assert current["resultReadyAtEpochMs"] > 0
        assert current["serverMeasurementMs"] >= 0
        events.append("vision")
        return {**result, "visionStatus": "skipped"}

    monkeypatch.setattr("process.add_vision", add_vision)
    monkeypatch.setattr("process.finish_prose",
                        lambda _job, result: {**result, "proseStatus": "fallback"})

    local_server._run(job_id)

    assert events == ["measured", "vision"]
    public = local_server._dump(local_server.JOBS[job_id])
    assert public["status"] == "done"
    assert public["result"]["n_reps"] == 10
    assert public["resultReadyAtEpochMs"] > 0
    assert public["serverMeasurementMs"] >= 0
