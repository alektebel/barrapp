"""The measurement reaches the phone without waiting for the vision models.

A real job on 2026-10-11 took 375 s: 57 s locating the exercise with a vision
model, 128 s of pose, under 1 s of measuring, and ~145 s of vision note and
second opinion after it. The note is advisory and separately sourced, so:

  * `measure_job` returns the payload the phone renders - reps, score, report,
    Spanish, sentinel-checked - with `visionStatus: "pending"` (or "skipped"
    when no vision endpoint is configured);
  * `add_vision` adds the note and second opinion afterwards and sets
    `visionStatus: "done"` (or "skipped"/"failed", never left "pending");
  * the worker writes `done` with the measurement first, then the vision;
  * localization runs alongside pose: fusion asks for the vision vote only
    when it needs it, by which time the 57 s call has finished.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server"), str(ROOT / "server" / "api")]
for k, v in {"JOBS_TABLE": "t-jobs", "FEEDBACK_TABLE": "t-fb", "REFERRALS_TABLE": "t-ref",
             "UPLOADS_TABLE": "t-up", "VIDEO_BUCKET": "t-bucket", "AWS_DEFAULT_REGION": "eu-west-1"}.items():
    os.environ.setdefault(k, v)

import process  # noqa: E402


def measured():
    return {
        "exercise": "push_up", "detected": {"label": "Push-up", "reason": "x"},
        "n_reps": 3, "n_candidates": 3, "reps": [], "sessions": [], "fps": 30.0,
        "duration_s": 10.0, "trim": None, "session": "2026-10-11", "sessionScore": 60,
        "sessionBand": "solid", "measurementVersion": 2, "blockers": [],
    }


REPORT = {"headline": "3 flexiones", "narrative": "Bien.", "nextSession": "Otra.",
          "proseSource": "llm:deepseek-v4-flash", "sessions": [], "reps": [], "blockers": []}


class Split(unittest.TestCase):
    def patches(self, note=None, configured=True):
        art = mock.Mock(clip=None, stills=["s.jpg"])
        art.as_trace_data.return_value = {}
        return [
            mock.patch.object(process, "analyze_clip", return_value=measured()),
            mock.patch.object(process, "write_report", side_effect=lambda m: dict(REPORT)),
            mock.patch.object(process, "technique_artifacts", return_value=art),
            mock.patch.object(process, "technique_note", return_value=note),
            mock.patch.object(process, "technique_second_opinion", return_value="clean"),
            mock.patch.object(process, "_vision_configured", return_value=configured),
            mock.patch.object(process, "_write_trace"),
        ]

    def run_with(self, fn, **kw):
        ps = self.patches(**kw)
        for p in ps:
            p.start()
        try:
            return fn()
        finally:
            for p in ps:
                p.stop()

    def test_measure_returns_without_any_vision_call(self):
        def go():
            out = process.measure_job({"id": "j"}, Path("/tmp/x.mp4"))
            process.technique_note.assert_not_called()
            process.technique_second_opinion.assert_not_called()
            return out
        out = self.run_with(go)
        self.assertEqual(out["visionStatus"], "pending")
        self.assertEqual(out["n_reps"], 3)
        self.assertEqual(out["i18n"]["locale"], "es")
        self.assertIn("traceId", out)

    def test_without_a_vision_endpoint_it_is_skipped_not_pending(self):
        out = self.run_with(lambda: process.measure_job({"id": "j"}, Path("/tmp/x.mp4")),
                            configured=False)
        self.assertEqual(out["visionStatus"], "skipped")

    def test_add_vision_completes_the_payload(self):
        note = {"headline": "en inglés", "narrative": "x", "visionObservations": [{"rep": "r1"}]}

        def go():
            out = process.measure_job({"id": "j"}, Path("/tmp/x.mp4"))
            return process.add_vision({"id": "j"}, Path("/tmp/x.mp4"), out)
        out = self.run_with(go, note=note)
        self.assertEqual(out["visionStatus"], "done")
        self.assertEqual(out["visionObservations"], [{"rep": "r1"}])
        self.assertEqual(out["visionVerdict"], "clean")
        self.assertEqual(out["headline"], "3 flexiones")  # the report keeps the headline

    def test_a_vision_failure_never_leaves_it_pending(self):
        def go():
            out = process.measure_job({"id": "j"}, Path("/tmp/x.mp4"))
            with mock.patch.object(process, "technique_note", side_effect=RuntimeError("boom")):
                return process.add_vision({"id": "j"}, Path("/tmp/x.mp4"), out)
        out = self.run_with(go)
        self.assertEqual(out["visionStatus"], "failed")
        self.assertEqual(out["n_reps"], 3)

    def test_process_job_is_still_both(self):
        out = self.run_with(lambda: process.process_job({"id": "j"}, Path("/tmp/x.mp4")),
                            note={"visionObservations": []})
        self.assertEqual(out["visionStatus"], "done")


class VisionInParallel(Split):
    def test_note_and_second_opinion_overlap(self):
        """Independent calls (124 s + 21 s measured): neither waits for the other."""
        both = threading.Barrier(2, timeout=2)

        def note(*a, **k):
            both.wait()  # deadlocks (BrokenBarrierError) if run one after the other
            return {"visionObservations": []}

        def second(*a, **k):
            both.wait()
            return "clean"

        def go():
            out = process.measure_job({"id": "j"}, Path("/tmp/x.mp4"))
            with mock.patch.object(process, "technique_note", side_effect=note), \
                    mock.patch.object(process, "technique_second_opinion", side_effect=second):
                return process.add_vision({"id": "j"}, Path("/tmp/x.mp4"), out)
        out = self.run_with(go)
        self.assertEqual(out["visionStatus"], "done")
        self.assertEqual(out["visionVerdict"], "clean")

    def test_a_second_opinion_without_a_note_is_not_kept(self):
        def go():
            out = process.measure_job({"id": "j"}, Path("/tmp/x.mp4"))
            return process.add_vision({"id": "j"}, Path("/tmp/x.mp4"), out)
        out = self.run_with(go, note=None)
        self.assertNotIn("visionVerdict", out)
        self.assertEqual(out["visionStatus"], "skipped")


class LazyVisionVote(unittest.TestCase):
    def test_a_callable_vote_is_resolved_only_when_asked(self):
        calls = []
        vote = lambda: calls.append(1) or "push-up"  # noqa: E731
        self.assertEqual(calls, [])
        self.assertEqual(process._resolve_vote(vote), "push-up")
        self.assertEqual(process._resolve_vote("pull-up"), "pull-up")
        self.assertIsNone(process._resolve_vote(None))

    def test_a_vote_that_raises_is_no_vote(self):
        def broken():
            raise RuntimeError("locate died")
        self.assertIsNone(process._resolve_vote(broken))


class Worker(unittest.TestCase):
    def setUp(self):
        import handler
        self.h = handler
        self.table = mock.Mock()
        self.table.get_item.return_value = {"Item": {"id": "j1", "owner": "o", "exercise": "auto"}}
        patches = [
            mock.patch.object(handler, "table", self.table),
            mock.patch.object(handler, "s3"),
            mock.patch.object(handler.uploads, "record"),
            mock.patch.object(handler.uploads, "trim"),
            mock.patch.object(handler, "_store_trimmed_clip", return_value=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        Path("/tmp/j1.mp4").write_bytes(b"x" * 10)
        self.addCleanup(lambda: Path("/tmp/j1.mp4").unlink(missing_ok=True))

    def statuses(self):
        out = []
        for call in self.table.update_item.call_args_list:
            vals = call.kwargs.get("ExpressionAttributeValues", {})
            if ":s" in vals:
                r = vals.get(":r") or {}
                out.append((vals[":s"], r.get("visionStatus") if isinstance(r, dict) else None))
        return out

    def test_done_is_written_before_the_vision_pass(self):
        order = []
        payload = {**measured(), "visionStatus": "pending", "traceId": "t"}
        with mock.patch("vision.locate_exercise", return_value=None), \
                mock.patch("process.measure_job", side_effect=lambda *a, **k: order.append("measure") or dict(payload)), \
                mock.patch("process.add_vision", side_effect=lambda j, p, r, **k: order.append(
                    ("vision", self.statuses()[-1])) or {**r, "visionStatus": "done"}):
            self.h.worker({"job_id": "j1", "owner": "o"}, None)
        self.assertEqual(order[0], "measure")
        # When the vision pass started, the phone could already read "done".
        self.assertEqual(order[1], ("vision", ("done", "pending")))
        self.assertEqual(self.statuses()[-1], ("done", "done"))

    def test_the_result_is_written_before_the_clip_is_cut(self):
        """Cutting and re-uploading the stored clip took ~44 s on job
        31103ccedfc3, all of it before the phone could read the result."""
        order = []
        payload = {**measured(), "visionStatus": "skipped", "traceId": "t",
                   "trim": {"startS": 1.0, "endS": 8.0}}
        self.table.update_item.side_effect = lambda **kw: order.append(
            ("write", kw.get("ExpressionAttributeValues", {}).get(":s")))
        with mock.patch("vision.locate_exercise", return_value=None), \
                mock.patch("process.measure_job", return_value=dict(payload)), \
                mock.patch("process.add_vision", side_effect=lambda j, p, r, **k: r), \
                mock.patch.object(self.h, "_store_trimmed_clip",
                                  side_effect=lambda *a, **k: order.append(("cut",)) or True):
            self.h.worker({"job_id": "j1", "owner": "o"}, None)
        first_done = order.index(("write", "done"))
        self.assertLess(first_done, order.index(("cut",)))
        # ...and the localization it produced is written too.
        final = self.table.update_item.call_args.kwargs["ExpressionAttributeValues"][":r"]
        self.assertEqual(final["localization"]["source"], "geometry")

    def test_localization_runs_while_the_pose_runs(self):
        started = threading.Event()

        def slow_locate(*a, **k):
            started.set()
            time.sleep(0.3)
            return {"exercise": "push-up", "usable": False}

        seen = {}

        def measure(job, path, on_stage=None, pose=None, vision_label=None):
            # Locate is already running when measuring starts...
            seen["started_before_measure"] = started.wait(1.0)
            # ...and the vote is fetched only when fusion asks for it.
            seen["vote"] = process._resolve_vote(vision_label)
            return {**measured(), "visionStatus": "skipped", "traceId": "t"}

        with mock.patch("vision.locate_exercise", side_effect=slow_locate), \
                mock.patch("process.measure_job", side_effect=measure), \
                mock.patch("process.add_vision", side_effect=lambda j, p, r, **k: r):
            self.h.worker({"job_id": "j1", "owner": "o"}, None)
        self.assertTrue(seen["started_before_measure"])
        self.assertEqual(seen["vote"], "push-up")


if __name__ == "__main__":
    unittest.main()
