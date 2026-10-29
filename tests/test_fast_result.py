"""The measurement reaches the phone without waiting for the vision models.

A real job on 2026-10-11 took 375 s: 57 s locating the exercise with a vision
model, 128 s of pose, under 1 s of measuring, and ~145 s of vision note and
second opinion after it. The note is advisory and separately sourced, so:

    Spanish, sentinel-checked - with `visionStatus: "pending"` (or "skipped"
    when no vision endpoint is configured) and `proseStatus` tracking the
    model prose the same way;
  * `add_vision` adds the note and second opinion afterwards and sets
    `visionStatus: "done"` (or "skipped"/"failed", never left "pending");
  * the result carries the deterministic Spanish prose at once
    (`proseStatus: "pending"`, `proseSource: "fallback"`); `finish_prose`
    upgrades it afterwards with the model's prose, judged, or leaves the
    fallback standing with the reason;
  * the worker writes `done` with the measurement first, then the vision;
  * localization runs alongside pose: fusion uses the vision vote only if it
    finished during pose; a late vote never delays the first result.
"""
from __future__ import annotations

import json
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

import llm  # noqa: E402
import process  # noqa: E402


def measured():
    return {
        "exercise": "push_up", "detected": {"label": "Push-up", "reason": "x"},
        "n_reps": 3, "n_candidates": 3, "reps": [], "sessions": [], "fps": 30.0,
        "duration_s": 10.0, "trim": None, "session": "2026-10-11", "sessionScore": 60,
        "sessionBand": "solid", "measurementVersion": 2, "blockers": [],
    }


class Split(unittest.TestCase):
    def patches(self, note=None, configured=True):
        art = mock.Mock(clip=None, stills=["s.jpg"])
        art.as_trace_data.return_value = {}
        return [
            mock.patch.object(process, "analyze_clip", return_value=measured()),
            mock.patch.object(process.llm, "config", return_value=None),
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
        self.assertEqual(out["headline"], "3 flexiones verificadas, sólida")  # the report keeps the headline

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
        self.assertEqual(out["proseStatus"], "done")


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


class FastProse(unittest.TestCase):
    """The model prose follows the result, like the vision note.

    A measured number must never wait for a sentence: the report model cost
    ~10-15 s of the critical path (docs/SPEED-PLAN.md B). The deterministic
    Spanish text goes out first and the model's prose replaces it only when
    it lands and passes the same judgement `report.write_report` applies.
    """

    def patches(self, configured=True, llm_configured=None):
        art = mock.Mock(clip=None, stills=[])
        art.as_trace_data.return_value = {}
        ps = [
            mock.patch.object(process, "analyze_clip", return_value=measured()),
            mock.patch.object(process, "technique_artifacts", return_value=art),
            mock.patch.object(process, "technique_note", return_value=None),
            mock.patch.object(process, "technique_second_opinion", return_value=None),
            mock.patch.object(process, "_vision_configured", return_value=configured),
            mock.patch.object(process, "_write_trace"),
        ]
        if llm_configured is not None:
            ps.insert(1, mock.patch.object(process.llm, "config",
                                           return_value=("u", "k") if llm_configured else None))
        return ps

    def run_with(self, fn, ps=None):
        for p in ps or self.patches():
            p.start()
        try:
            return fn()
        finally:
            for p in ps or []:
                p.stop()

    def test_first_write_has_fallback_prose_and_no_model_call(self):
        """The payload written for the phone carries usable Spanish prose
        immediately, and no model was asked before it was written."""
        with mock.patch.object(llm, "complete") as complete:
            out = self.run_with(lambda: process.measure_job({"id": "j"}, Path("/tmp/x.mp4")),
                                ps=self.patches(llm_configured=True))
        complete.assert_not_called()
        self.assertEqual(out["proseStatus"], "pending")
        self.assertEqual(out["proseSource"], "fallback")
        self.assertTrue(out["headline"])
        self.assertTrue(out["narrative"])
        self.assertTrue(out["nextSession"])
        from barra.i18n import english_words
        for k in ("headline", "narrative", "nextSession"):
            self.assertEqual(english_words(out[k]), [], out[k])

    def test_finish_prose_upgrades_with_judged_model_prose(self):
        good = json.dumps({"headline": "3 dominadas verificadas, sólidas",
                           "narrative": "Hiciste 3 repeticiones bien verificadas.",
                           "nextSession": "Graba cinco o seis repeticiones."}, ensure_ascii=False)

        def go():
            out = process.measure_job({"id": "j"}, Path("/tmp/x.mp4"))
            self.assertEqual(out["proseStatus"], "pending")
            return process.finish_prose({"id": "j"}, out)
        with mock.patch.object(llm, "complete",
                               return_value=llm.ChatResult(model="deepseek-v4-flash", text=good)):
            out = self.run_with(go, ps=self.patches(llm_configured=True))
        self.assertEqual(out["proseStatus"], "done")
        self.assertEqual(out["proseSource"], "llm:deepseek-v4-flash")
        self.assertEqual(out["headline"], "3 dominadas verificadas, sólidas")

    def test_finish_prose_rejects_an_invented_number(self):
        bad = json.dumps({"headline": "3 dominadas",
                          "narrative": "Hiciste 12 repeticiones perfectas.",
                          "nextSession": "Graba cinco o seis repeticiones."}, ensure_ascii=False)

        def go():
            out = process.measure_job({"id": "j"}, Path("/tmp/x.mp4"))
            return process.finish_prose({"id": "j"}, out)
        with mock.patch.object(llm, "complete",
                               return_value=llm.ChatResult(model="m", text=bad)):
            out = self.run_with(go, ps=self.patches(llm_configured=True))
        self.assertEqual(out["proseStatus"], "fallback")
        self.assertEqual(out["proseSource"], "fallback")
        self.assertIn("invented_number", out["proseRejected"])
        # The fallback stands; never an empty headline.
        self.assertTrue(out["headline"])
        self.assertEqual(out["n_reps"], 3)

    def test_finish_prose_on_a_failure_leaves_the_fallback(self):
        def go():
            out = process.measure_job({"id": "j"}, Path("/tmp/x.mp4"))
            return process.finish_prose({"id": "j"}, out)
        with mock.patch.object(llm, "complete",
                               return_value=llm.ChatResult(model="m", error="401 no access", status=401)):
            out = self.run_with(go, ps=self.patches(llm_configured=True))
        self.assertEqual(out["proseStatus"], "failed")
        self.assertEqual(out["proseSource"], "fallback")
        self.assertTrue(out["headline"])

    def test_record_trace_false_leaves_the_trace_to_the_caller(self):
        """The worker runs the prose beside the vision pass; two threads on one
        trace would scramble its current stage, so it records the step itself."""
        good = json.dumps({"headline": "3 dominadas verificadas, sólidas",
                           "narrative": "Hiciste 3 repeticiones bien verificadas.",
                           "nextSession": "Graba cinco o seis repeticiones."}, ensure_ascii=False)

        def go():
            out = process.measure_job({"id": "j"}, Path("/tmp/x.mp4"))
            ref = process.trace_ref(out)
            self.assertIsNotNone(ref)
            before = len(ref[0].entries)
            done = process.finish_prose({"id": "j"}, out, record_trace=False)
            self.assertEqual(len(ref[0].entries), before)   # untouched
            self.assertEqual(done["proseStatus"], "done")
            process.record_prose_trace({"id": "j"}, done, ref)
            self.assertGreater(len(ref[0].entries), before)
            self.assertIn("model prose", [e.message for e in ref[0].of_stage("prose")])
        with mock.patch.object(llm, "complete",
                               return_value=llm.ChatResult(model="m", text=good)):
            self.run_with(go, ps=self.patches(llm_configured=True))

    def test_without_an_llm_there_is_no_pending_state(self):
        def go():
            out = process.measure_job({"id": "j"}, Path("/tmp/x.mp4"))
            self.assertEqual(out["proseStatus"], "done")
            self.assertEqual(out["proseSource"], "fallback")
            out2 = process.finish_prose({"id": "j"}, out)
            self.assertEqual(out2["proseStatus"], "done")
            return out2
        out = self.run_with(go, ps=self.patches(llm_configured=False))
        self.assertEqual(out["proseSource"], "fallback")
        self.assertEqual(out["proseRejected"], "not_configured")

    def test_finish_prose_keeps_the_trace_keys(self):
        """The deferred pass must not rebuild the payload's provenance from
        nothing: the `_finish` keys the phone already read stay."""
        def go():
            out = process.measure_job({"id": "j"}, Path("/tmp/x.mp4"))
            return process.finish_prose({"id": "j"}, out)
        out = self.run_with(go)
        self.assertIn("traceId", out)
        self.assertIn("provenance", out)
        self.assertIn("i18n", out)

    def test_process_job_is_still_both(self):
        # No note configured: the vision pass is skipped, the prose is done.
        out = self.run_with(lambda: process.process_job({"id": "j"}, Path("/tmp/x.mp4")),
                            ps=self.patches(llm_configured=False))
        self.assertEqual(out["visionStatus"], "skipped")
        self.assertEqual(out["proseStatus"], "done")


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

    def test_worker_marks_handler_entry_before_import_ready_and_download(self):
        with mock.patch("vision.locate_exercise", return_value=None), \
                mock.patch("process.measure_job", return_value={**measured(),
                    "visionStatus": "skipped", "traceId": "t"}), \
                mock.patch("process.add_vision", side_effect=lambda j, p, r, **k: r):
            self.h.worker({"job_id": "j1", "owner": "o"}, None)
        names = [call.args[2] for call in self.h.uploads.record.call_args_list]
        self.assertLess(names.index("worker-entry"), names.index("worker-ready"))
        self.assertLess(names.index("worker-ready"), names.index("stage"))
        ready = next(call for call in self.h.uploads.record.call_args_list
                     if call.args[2] == "worker-ready")
        self.assertIn("importMs", ready.kwargs)

    def test_pose_import_warmup_overlaps_s3_download_before_measurement(self):
        order = []
        warmup = object()
        payload = {**measured(), "visionStatus": "skipped", "traceId": "t"}
        self.h.s3.download_file.side_effect = lambda *a: order.append("download")

        def start_warmup():
            order.append("warmup-start")
            return warmup

        def finish_warmup(value):
            self.assertIs(value, warmup)
            order.append("warmup-finish")
            return {"ready": True, "outcome": "ready", "elapsedMs": 120,
                    "waitMs": 5}

        def measure(*args, **kwargs):
            order.append("measure")
            return dict(payload)

        with mock.patch.object(self.h, "start_pose_runtime_warmup",
                               side_effect=start_warmup), \
                mock.patch.object(self.h, "finish_pose_runtime_warmup",
                                   side_effect=finish_warmup), \
                mock.patch("vision.locate_exercise", return_value=None), \
                mock.patch("process.measure_job", side_effect=measure), \
                mock.patch("process.add_vision", side_effect=lambda j, p, r, **k: r):
            self.h.worker({"job_id": "j1", "owner": "o"}, None)

        self.assertLess(order.index("warmup-start"), order.index("download"))
        self.assertLess(order.index("download"), order.index("warmup-finish"))
        self.assertLess(order.index("warmup-finish"), order.index("measure"))
        timing = next(call for call in self.h.uploads.record.call_args_list
                      if call.args[2] == "worker-timing").kwargs
        self.assertEqual(timing["poseWarmupOutcome"], "ready")
        self.assertEqual(timing["poseWarmupElapsedMs"], 120)
        self.assertEqual(timing["poseWarmupWaitMs"], 5)

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

        def measure(job, path, on_stage=None, pose=None, vision_label=None, vision_window=None):
            # Locate is already running when measuring starts...
            seen["started_before_measure"] = started.wait(1.0)
            # ...and finishes while the measured pose is in flight.
            time.sleep(0.35)
            # ...and the vote is fetched only when fusion asks for it.
            seen["vote"] = process._resolve_vote(vision_label)
            return {**measured(), "visionStatus": "skipped", "traceId": "t"}

        with mock.patch("vision.locate_exercise", side_effect=slow_locate), \
                mock.patch("process.measure_job", side_effect=measure), \
                mock.patch("process.add_vision", side_effect=lambda j, p, r, **k: r):
            self.h.worker({"job_id": "j1", "owner": "o"}, None)
        self.assertTrue(seen["started_before_measure"])
        self.assertEqual(seen["vote"], "push-up")

    def test_a_late_vote_is_waited_for_only_when_asked(self):
        # Fusion asks with a wait only when geometry and the model disagree
        # (process.VISION_VOTE_WAIT_S); WA0020 on 2026-10-16 came back as
        # "muscle-up, 0 reps" because the push-up vote was a few seconds late.
        def slow_locate(*a, **k):
            time.sleep(0.3)
            return {"exercise": "push-up", "usable": True}

        seen = {}

        def measure(job, path, on_stage=None, pose=None, vision_label=None, vision_window=None):
            seen["no_wait"] = process._resolve_vote(vision_label, 0.0)
            seen["waited"] = process._resolve_vote(vision_label, 2.0)
            return {**measured(), "visionStatus": "skipped", "traceId": "t"}

        with mock.patch("vision.locate_exercise", side_effect=slow_locate), \
                mock.patch("process.measure_job", side_effect=measure), \
                mock.patch("process.add_vision", side_effect=lambda j, p, r, **k: r):
            self.h.worker({"job_id": "j1", "owner": "o"}, None)
        self.assertIsNone(seen["no_wait"])
        self.assertEqual(seen["waited"], "push-up")

    def test_locator_and_fusion_wait_durations_are_saved_after_first_result(self):
        def slow_locate(*a, **k):
            time.sleep(0.05)
            return {"exercise": "push_up", "usable": True,
                    "startS": 1.0, "endS": 8.0}

        def measure(_job, _path, on_stage=None, pose=None, vision_label=None, vision_window=None):
            # Model the pose stage taking longer than localization. The vote
            # is ready by fusion, so the result path must not wait here.
            time.sleep(0.08)
            self.assertEqual(process._resolve_vote(vision_label), "push_up")
            return {**measured(), "visionStatus": "skipped", "traceId": "t"}

        with mock.patch("vision.locate_exercise", side_effect=slow_locate), \
                mock.patch("process.measure_job", side_effect=measure), \
                mock.patch("process.add_vision", side_effect=lambda j, p, r, **k: r):
            self.h.worker({"job_id": "j1", "owner": "o"}, None)

        events = {call.args[2]: call for call in self.h.uploads.record.call_args_list}
        timing = events["worker-timing"].kwargs
        locator = events["locator-finished"].kwargs
        self.assertLess(timing["fusionWaitMs"], 10)
        self.assertEqual(timing["fusionOutcome"], "ready")
        self.assertTrue(timing["locatorCompleteAtResult"])
        self.assertGreaterEqual(timing["locatorMsAtResult"], 40)
        self.assertGreaterEqual(locator["durationMs"], 40)
        self.assertTrue(locator["resultPersisted"])
        self.assertEqual(locator["postResultWaitMs"], 0)
        self.assertGreaterEqual(timing["clipDownloadUs"], 0)
        self.assertGreaterEqual(timing["processingStateWriteUs"], 0)
        self.assertGreaterEqual(timing["resultWriteUs"], 0)
        self.assertGreater(timing["stageWriteCount"], 0)
        self.assertGreaterEqual(timing["stageTableUs"], 0)
        self.assertGreaterEqual(timing["stageUploadLogUs"], 0)
        self.assertGreaterEqual(timing["stageTotalUs"], 0)
        self.assertGreaterEqual(timing["stageSlowestUs"], 0)
        self.assertIsInstance(timing["stageSlowestName"], str)

    def test_late_locator_time_is_recorded_after_result_without_moving_done(self):
        started = threading.Event()
        order = []

        def slow_locate(*a, **k):
            started.set()
            time.sleep(0.12)
            order.append("locator-finished")
            return None

        seen = {}

        def measure(*a, vision_label=None, **k):
            self.assertTrue(started.wait(1))
            seen["vote"] = process._resolve_vote(vision_label)
            return {**measured(), "visionStatus": "skipped", "traceId": "t"}

        self.table.update_item.side_effect = lambda **kw: order.append(
            "done" if kw.get("ExpressionAttributeValues", {}).get(":s") == "done"
            else "other-write")
        with mock.patch("vision.locate_exercise", side_effect=slow_locate), \
                mock.patch("process.measure_job", side_effect=measure), \
                mock.patch("process.add_vision", side_effect=lambda j, p, r, **k: r):
            self.h.worker({"job_id": "j1", "owner": "o"}, None)

        self.assertLess(order.index("done"), order.index("locator-finished"))
        self.assertIsNone(seen["vote"])
        events = {call.args[2]: call for call in self.h.uploads.record.call_args_list}
        timing = events["worker-timing"].kwargs
        locator = events["locator-finished"].kwargs
        self.assertEqual(timing["fusionOutcome"], "timeout")
        self.assertLess(timing["fusionWaitMs"], 10)
        self.assertFalse(timing["locatorCompleteAtResult"])
        self.assertGreaterEqual(locator["durationMs"], 100)
        self.assertTrue(locator["resultPersisted"])
        self.assertGreaterEqual(locator["postResultWaitMs"], 50)

    def test_prose_pass_runs_after_the_first_result_write(self):
        order = []
        payload = {**measured(), "visionStatus": "skipped", "proseStatus": "pending",
                   "proseSource": "fallback", "traceId": "t"}
        self.table.update_item.side_effect = lambda **kw: order.append(
            ("write", kw.get("ExpressionAttributeValues", {}).get(":s")))

        def finish_prose(job, result, **k):
            order.append(("prose", self.statuses()[-1]))
            return {**result, "proseStatus": "done", "proseSource": "llm:deepseek-v4-flash",
                    "headline": "3 flexiones del modelo"}

        with mock.patch("vision.locate_exercise", return_value=None), \
                mock.patch("process.measure_job", return_value=dict(payload)), \
                mock.patch("process.add_vision", side_effect=lambda j, p, r, **k: r), \
                mock.patch("process.finish_prose", side_effect=finish_prose):
            self.h.worker({"job_id": "j1", "owner": "o"}, None)
        first_done = order.index(("write", "done"))
        # When the prose pass ran, the phone could already read a done result.
        self.assertEqual(order[first_done + 1][0], "prose")
        self.assertEqual(order[first_done + 1][1][0], "done")
        final = self.table.update_item.call_args.kwargs["ExpressionAttributeValues"][":r"]
        self.assertEqual(final["proseStatus"], "done")
        self.assertEqual(final["headline"], "3 flexiones del modelo")

    # -- the three post-result branches run at once (docs/SPEED-ROUND3.md) ---
    def _all_pending(self):
        return {**measured(), "visionStatus": "pending", "proseStatus": "pending",
                "proseSource": "fallback", "traceId": "t", "headline": "fallback",
                "trim": {"startS": 1.0, "endS": 8.0}}

    def _written(self):
        return [c.kwargs["ExpressionAttributeValues"][":r"]
                for c in self.table.update_item.call_args_list
                if ":r" in c.kwargs.get("ExpressionAttributeValues", {})]

    def test_store_vision_and_prose_overlap(self):
        """Serial, they cost cut+upload (15-45 s) + vision (14-180 s) + prose
        (20-40 s) after the result; the prose depends on neither."""
        all_three = threading.Barrier(3, timeout=3)

        def vision(j, p, r, **k):
            all_three.wait()  # BrokenBarrierError if any branch waits for another
            return {**r, "visionStatus": "done", "visionObservations": [{"rep": "r1"}]}

        def prose(j, r, **k):
            all_three.wait()
            return {**r, "proseStatus": "done", "proseSource": "llm:m", "headline": "del modelo"}

        def store(*a, **k):
            all_three.wait()
            return True

        with mock.patch("vision.locate_exercise", return_value=None), \
                mock.patch("process.measure_job", return_value=self._all_pending()), \
                mock.patch("process.add_vision", side_effect=vision), \
                mock.patch("process.finish_prose", side_effect=prose), \
                mock.patch.object(self.h, "_store_trimmed_clip", side_effect=store):
            self.h.worker({"job_id": "j1", "owner": "o"}, None)
        final = self._written()[-1]
        # Every branch's keys survive the merge.
        self.assertEqual(final["visionStatus"], "done")
        self.assertEqual(final["visionObservations"], [{"rep": "r1"}])
        self.assertEqual(final["proseStatus"], "done")
        self.assertEqual(final["headline"], "del modelo")
        self.assertEqual(final["localization"]["source"], "geometry")
        self.assertEqual(final["n_reps"], 3)

    def test_the_prose_reaches_the_phone_while_the_vision_is_still_running(self):
        """The prose used to wait for the slowest vision call (up to ~180 s)."""
        prose_seen = threading.Event()
        seen = {}

        def vision(j, p, r, **k):
            seen["prose_landed_first"] = prose_seen.wait(3)
            seen["on_phone"] = [w.get("proseStatus") for w in self._written()]
            return {**r, "visionStatus": "done"}

        def prose(j, r, **k):
            return {**r, "proseStatus": "done", "proseSource": "llm:m", "headline": "del modelo"}

        real_write = self.h._write_result

        def write(job_id, result):
            real_write(job_id, result)
            if result.get("proseStatus") == "done":
                prose_seen.set()

        with mock.patch("vision.locate_exercise", return_value=None), \
                mock.patch("process.measure_job", return_value=self._all_pending()), \
                mock.patch("process.add_vision", side_effect=vision), \
                mock.patch("process.finish_prose", side_effect=prose), \
                mock.patch.object(self.h, "_write_result", side_effect=write):
            self.h.worker({"job_id": "j1", "owner": "o"}, None)
        self.assertTrue(seen["prose_landed_first"])
        self.assertIn("done", seen["on_phone"])
        # ...and the prose written first was not lost when the vision landed.
        self.assertEqual(self._written()[-1]["headline"], "del modelo")
        self.assertEqual(self._written()[-1]["visionStatus"], "done")

    def test_a_vision_crash_keeps_the_prose_and_the_job(self):
        with mock.patch("vision.locate_exercise", return_value=None), \
                mock.patch("process.measure_job", return_value=self._all_pending()), \
                mock.patch("process.add_vision", side_effect=RuntimeError("boom")), \
                mock.patch("process.finish_prose", side_effect=lambda j, r, **k: {
                    **r, "proseStatus": "done", "headline": "del modelo"}):
            self.h.worker({"job_id": "j1", "owner": "o"}, None)
        final = self._written()[-1]
        self.assertEqual(final["visionStatus"], "failed")
        self.assertEqual(final["proseStatus"], "done")
        self.assertEqual(self.statuses()[-1][0], "done")

    def test_the_prose_step_is_recorded_in_the_trace_once_at_the_end(self):
        trace = mock.Mock()
        with mock.patch("vision.locate_exercise", return_value=None), \
                mock.patch("process.measure_job", return_value=self._all_pending()), \
                mock.patch("process.trace_ref", return_value=(trace, "auto")), \
                mock.patch("process.record_prose_trace") as record, \
                mock.patch("process.add_vision", side_effect=lambda j, p, r, **k: r), \
                mock.patch("process.finish_prose", side_effect=lambda j, r, **k: {
                    **r, "proseStatus": "done"}):
            self.h.worker({"job_id": "j1", "owner": "o"}, None)
        record.assert_called_once()
        self.assertEqual(record.call_args.args[1]["proseStatus"], "done")

    def test_a_prose_failure_does_not_fail_the_job(self):
        payload = {**measured(), "visionStatus": "skipped", "proseStatus": "pending",
                   "proseSource": "fallback", "traceId": "t"}
        with mock.patch("vision.locate_exercise", return_value=None), \
                mock.patch("process.measure_job", return_value=dict(payload)), \
                mock.patch("process.add_vision", side_effect=lambda j, p, r, **k: r), \
                mock.patch("process.finish_prose", side_effect=RuntimeError("boom")):
            self.h.worker({"job_id": "j1", "owner": "o"}, None)
        final = self.table.update_item.call_args.kwargs["ExpressionAttributeValues"][":r"]
        # The pass failed, not the job: the fallback text stands.
        self.assertEqual(final["proseStatus"], "failed")
        self.assertEqual(final["n_reps"], 3)
        self.assertEqual(self.statuses()[-1][0], "done")



if __name__ == "__main__":
    unittest.main()
