"""A clip filmed upside down, in the dark, or with the athlete half out of frame.

Two real clips started this (production, 2026-10-28):
  * job f31bf9cfc335: dips, phone upside down. Geometry said muscle-up, the
    classifier back lever, vision hanging leg raise; six reps were scored for a
    movement nobody did.
  * job 0329d314fe5a: pull-ups at night, only the legs in frame. The message
    ("no stretch of this clip shows the athlete on the apparatus") told the
    athlete nothing about what to change.

The rules are pure, so they are tested on synthetic keypoints and labels; the
real clips were run through the whole pipeline separately (see the commit notes).
"""
from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

from barra import i18n  # noqa: E402
from barra import orientation as ori  # noqa: E402
from barra.fusion import fuse_detection  # noqa: E402


def person(nose_y, shoulder_y, hip_y, wrist_y=None, ankle_y=None, conf=0.9):
    """One frame of COCO-17 keypoints (x, y, conf); y grows downward."""
    kp = np.zeros((17, 3), dtype=np.float32)
    for i, y in ((ori.NOSE, nose_y), (ori.L_SHOULDER, shoulder_y), (ori.R_SHOULDER, shoulder_y),
                 (ori.L_HIP, hip_y), (ori.R_HIP, hip_y)):
        kp[i] = (100.0, y, conf)
    if wrist_y is not None:
        kp[ori.L_WRIST] = kp[ori.R_WRIST] = (100.0, wrist_y, conf)
    if ankle_y is not None:
        kp[ori.L_ANKLE] = kp[ori.R_ANKLE] = (100.0, ankle_y, conf)
    return kp


def clip(frame, n=30):
    return np.stack([frame] * n)


UPRIGHT = person(nose_y=100, shoulder_y=130, hip_y=230, wrist_y=60, ankle_y=400)
INVERTED = person(nose_y=330, shoulder_y=300, hip_y=200, wrist_y=250, ankle_y=40)
LEVER = person(nose_y=200, shoulder_y=205, hip_y=210, wrist_y=203, ankle_y=215)  # body horizontal


class TestSuspectInverted(unittest.TestCase):
    def test_an_upright_athlete_is_not_suspect(self):
        suspect, ev = ori.suspect_inverted(clip(UPRIGHT))
        self.assertFalse(suspect)
        self.assertEqual(ev["inverted_share"], 0.0)

    def test_a_head_below_the_hips_is_suspect(self):
        suspect, ev = ori.suspect_inverted(clip(INVERTED))
        self.assertTrue(suspect)
        self.assertGreater(ev["head_below_hips_median"], ori.BELOW_HIPS)

    def test_a_horizontal_body_is_never_suspect(self):
        """Front/back lever, planche and human flag are horizontal: the nose is
        level with the hips, not below them."""
        suspect, _ = ori.suspect_inverted(clip(LEVER))
        self.assertFalse(suspect)

    def test_too_few_readable_frames_says_nothing(self):
        blind = np.zeros((40, 17, 3), dtype=np.float32)
        suspect, ev = ori.suspect_inverted(blind)
        self.assertFalse(suspect)
        self.assertEqual(ev["frames"], 0)
        suspect, _ = ori.suspect_inverted(clip(INVERTED, n=ori.MIN_FRAMES - 1))
        self.assertFalse(suspect)

    def test_a_mostly_upright_clip_with_a_brief_inversion_is_not_suspect(self):
        """A skin-the-cat or a flip passes through head-below-hips for a
        moment; it must be most of the clip."""
        frames = np.concatenate([clip(UPRIGHT, 21), clip(INVERTED, 9)])
        suspect, ev = ori.suspect_inverted(frames)
        self.assertFalse(suspect, ev)

    def test_unreadable_frames_do_not_vote(self):
        blind = np.zeros((10, 17, 3), dtype=np.float32)
        frames = np.concatenate([clip(INVERTED, 8), blind])
        suspect, ev = ori.suspect_inverted(frames)
        self.assertTrue(suspect)
        self.assertEqual(ev["frames"], 8)


class TestDecide(unittest.TestCase):
    V = ori.Votes

    def test_it_turns_only_when_the_detectors_agree_once_turned(self):
        """The real dips clip: three different names as filmed, geometry and
        classifier both say dip once turned."""
        v = ori.decide(self.V("muscle_up", "back_lever"), self.V("dip", "dip"))
        self.assertTrue(v.rotate)
        self.assertEqual((v.status, v.rotated_by), ("rotated", 180))

    def test_a_clip_the_detectors_recognise_as_filmed_is_never_turned(self):
        """An upright back lever pulled from an inverted hang reads inverted on
        the pose; it is a back lever as filmed and stays one."""
        v = ori.decide(self.V("back_lever", "back_lever"), self.V("muscle_up", "squat"))
        self.assertFalse(v.rotate)
        self.assertEqual(v.status, "upright")

    def test_both_orientations_recognised_as_different_moves_stays_as_filmed(self):
        v = ori.decide(self.V("back_lever", "back_lever"), self.V("dip", "dip"))
        self.assertFalse(v.rotate)
        self.assertEqual(v.status, "ambiguous")

    def test_vision_can_break_that_tie_toward_the_turned_clip(self):
        v = ori.decide(self.V("back_lever", "back_lever"), self.V("dip", "dip"),
                       vision_label="Dips")
        self.assertTrue(v.rotate)

    def test_nothing_recognised_either_way_is_uncertain_not_turned(self):
        """A handstand (inverted on purpose) usually lands here: neither
        orientation gives two detectors the same name."""
        v = ori.decide(self.V("unknown", "handstand"), self.V("squat", "dip"))
        self.assertFalse(v.rotate)
        self.assertEqual(v.status, "uncertain")

    def test_an_unknown_name_is_not_an_agreement(self):
        self.assertIsNone(ori.agreement(self.V("unknown", "unknown")))
        self.assertIsNone(ori.agreement(self.V("", "")))
        self.assertEqual(ori.agreement(self.V("pull-up", "pull_up")), "pull_up")

    # The second path, measured on the corpus: a pull-up clip turned 180 degrees
    # read (push_up, handstand 0.45) as filmed and (unknown, pull_up 0.59) once
    # turned. Geometry never agrees there - it is the weakest detector - so it
    # needs the classifier's lift AND the vision model naming the same thing.
    FILMED = V("push_up", "handstand", 0.445)
    TURNED = V("unknown", "pull_up", 0.587)

    def test_the_classifiers_lift_turns_the_clip_when_vision_backs_it(self):
        v = ori.decide(self.FILMED, self.TURNED, vision_label="Pull-ups")
        self.assertTrue(v.rotate)
        self.assertEqual(v.status, "rotated")

    def test_without_vision_the_classifiers_lift_is_not_enough(self):
        v = ori.decide(self.FILMED, self.TURNED)
        self.assertFalse(v.rotate)
        self.assertEqual(v.status, "uncertain")

    def test_vision_naming_the_inverted_movement_keeps_the_clip_as_filmed(self):
        v = ori.decide(self.FILMED, self.TURNED, vision_label="Handstand")
        self.assertFalse(v.rotate)

    def test_a_confident_inverted_class_is_never_turned(self):
        """A real handstand: the classifier is sure as filmed."""
        v = ori.decide(self.V("handstand", "handstand", 0.93), self.TURNED, vision_label="pull-ups")
        self.assertFalse(v.rotate)
        self.assertFalse(ori.soft_candidate(self.V("", "handstand", 0.93), self.TURNED))

    def test_an_ordinary_movement_as_filmed_is_never_turned(self):
        """The turned muscle-up clip is still read as a muscle-up at 0.995:
        the detectors are partly flip-invariant, and what works stays."""
        self.assertFalse(ori.soft_candidate(self.V("unknown", "muscle_up", 0.995),
                                            self.V("muscle_up", "pull_up", 0.28)))

    def test_a_turned_reading_that_is_weak_or_contradicted_is_not_a_lift(self):
        self.assertFalse(ori.soft_candidate(self.FILMED, self.V("unknown", "pull_up", 0.45)))
        self.assertFalse(ori.soft_candidate(self.FILMED, self.V("unknown", "pull_up", 0.50)))  # gain < 0.1
        self.assertFalse(ori.soft_candidate(self.FILMED, self.V("dip", "pull_up", 0.9)))       # geometry disagrees
        self.assertFalse(ori.soft_candidate(self.FILMED, self.V("unknown", "handstand", 0.9)))
        self.assertFalse(ori.soft_candidate(self.FILMED, None))

    def test_a_clip_that_could_not_be_turned_is_uncertain(self):
        v = ori.decide(self.V("muscle_up", "back_lever"), None)
        self.assertFalse(v.rotate)
        self.assertEqual(v.status, "uncertain")


class TestFraming(unittest.TestCase):
    def test_a_dark_clip_says_so(self):
        self.assertIn("framing_dark", ori.framing_issues(clip(UPRIGHT), luma=18.0))
        self.assertEqual(ori.framing_issues(clip(UPRIGHT), luma=120.0), [])
        self.assertEqual(ori.framing_issues(clip(UPRIGHT), luma=None), [])

    def test_only_the_legs_in_frame(self):
        legs = person(0, 0, 0, ankle_y=400, conf=0.0)
        legs[ori.L_ANKLE] = legs[ori.R_ANKLE] = (100.0, 400.0, 0.9)
        self.assertEqual(ori.framing_issues(clip(legs), luma=120.0), ["framing_legs_only"])

    def test_nobody_in_frame(self):
        self.assertEqual(ori.framing_issues(np.zeros((30, 17, 3), np.float32), luma=120.0),
                         ["framing_no_athlete"])

    def test_in_the_dark_nobody_in_frame_is_the_lights_fault(self):
        """Night clips lose the legs too; saying "you are out of frame" would
        send the athlete to fix the wrong thing."""
        self.assertEqual(ori.framing_issues(np.zeros((30, 17, 3), np.float32), luma=15.0),
                         ["framing_dark"])

    def test_a_well_framed_clip_has_no_issues(self):
        full = person(100, 130, 230, wrist_y=60, ankle_y=400)
        full[ori.L_WRIST] = full[ori.R_WRIST] = (100.0, 60.0, 0.9)
        self.assertEqual(ori.framing_issues(clip(full), luma=110.0), [])


class TestBrightness(unittest.TestCase):
    def test_mean_luma_of_the_sampled_frames(self):
        dark = np.full((8, 8, 3), 20, np.uint8)
        light = np.full((8, 8, 3), 180, np.uint8)
        self.assertAlmostEqual(ori.brightness([dark, light]), 100.0)
        self.assertIsNone(ori.brightness([]))


class TestFusionOnAnUnreliablePose(unittest.TestCase):
    GEOM = {"exercise": "muscle_up", "confidence": 0.7}
    MODEL = {"exercise": "back_lever", "confidence": 0.95, "marginToRunnerUp": 0.9}
    VISION = {"exercise": "Hanging Leg Raise"}

    def test_three_different_names_on_a_clean_pose_still_let_vision_decide(self):
        """Measured: vision is right 21/25 when geometry and the classifier split."""
        fused = fuse_detection(self.GEOM, self.MODEL, self.VISION)
        self.assertEqual(fused["status"], "vision-decides")

    def test_three_different_names_on_an_unreliable_pose_abstain(self):
        fused = fuse_detection(self.GEOM, self.MODEL, self.VISION, pose_reliable=False)
        self.assertEqual(fused["exercise"], "unknown")
        self.assertEqual(fused["status"], "three-way-disagreement-abstain")
        self.assertEqual(fused["confidence"], 0.0)

    def test_two_of_three_agreeing_is_untouched_by_an_unreliable_pose(self):
        fused = fuse_detection({"exercise": "dip", "confidence": 0.5},
                               {"exercise": "dip", "confidence": 0.8, "marginToRunnerUp": 0.5},
                               self.VISION, pose_reliable=False)
        self.assertEqual(fused["exercise"], "dip")

    def test_a_coin_flip_classifier_is_not_a_third_voice(self):
        weak = {"exercise": "back_lever", "confidence": 0.1, "marginToRunnerUp": 0.0}
        fused = fuse_detection(self.GEOM, weak, self.VISION, pose_reliable=False)
        self.assertEqual(fused["status"], "vision-decides")


class TestSpanishMessages(unittest.TestCase):
    CODES = ("orientation_rotated", "orientation_suspect", "framing_dark",
             "framing_legs_only", "framing_no_athlete")

    def test_every_code_has_a_spanish_message_that_says_what_to_do(self):
        for code in self.CODES:
            missing: list[str] = []
            text = i18n.localize_text(code, missing)
            self.assertEqual(missing, [], code)
            self.assertNotEqual(text, code)
            self.assertTrue(i18n.looks_spanish(text), text)
            self.assertEqual(i18n.english_words(text), [], text)

    def test_the_advice_is_actionable(self):
        self.assertIn("luz", i18n.localize_text("framing_dark"))
        self.assertIn("2-3 metros", i18n.localize_text("framing_legs_only"))
        self.assertIn("del revés", i18n.localize_text("orientation_suspect"))
        self.assertIn("del revés", i18n.localize_text("orientation_rotated"))

    def test_the_payload_localizes_blockers_and_notes(self):
        p = i18n.localize_payload({"blockers": ["framing_dark"], "notes": ["orientation_rotated"]})
        self.assertTrue(p["blockers"][0].startswith("Hay muy poca luz"))
        self.assertTrue(p["notes"][0].startswith("El vídeo estaba del revés"))
        self.assertEqual(p["i18n"]["untranslated"], [])


class TestAnnotateCapture(unittest.TestCase):
    def setUp(self):
        from process import _annotate_capture
        self.annotate = _annotate_capture

    GENERIC = ("no stretch of this clip shows the athlete on the apparatus - "
               "the hands were never still on anything fixed")

    def test_unmeasured_dark_clip_gets_the_actionable_blocker_first(self):
        m = {"countStatus": "unmeasured", "n_reps": 0, "blockers": [self.GENERIC],
             "detected": {"framing": ["framing_dark"], "orientation": None}}
        self.annotate(m)
        self.assertEqual(m["blockers"], ["framing_dark"])
        self.assertEqual(m["notes"], [])

    def test_other_blockers_are_kept_after_the_actionable_ones(self):
        m = {"countStatus": "unmeasured", "n_reps": 0, "blockers": ["something else"],
             "detected": {"framing": ["framing_legs_only"], "orientation": None}}
        self.annotate(m)
        self.assertEqual(m["blockers"], ["framing_legs_only", "something else"])

    def test_a_rotated_clip_says_so_in_the_notes_and_the_payload(self):
        m = {"countStatus": "geometry", "n_reps": 6, "blockers": [],
             "detected": {"framing": [], "orientation": {
                 "status": "rotated", "rotatedBy": 180, "reason": "x", "evidence": {}}}}
        self.annotate(m)
        self.assertEqual(m["orientation"], {"rotatedBy": 180, "status": "rotated", "reason": "x"})
        self.assertEqual(m["notes"], ["orientation_rotated"])
        self.assertEqual(m["blockers"], [])

    def test_an_unresolved_inversion_on_an_unmeasured_clip_says_to_turn_the_phone(self):
        m = {"countStatus": "unmeasured", "n_reps": 0, "blockers": [],
             "detected": {"framing": [], "orientation": {
                 "status": "uncertain", "rotatedBy": 0, "reason": "x"}}}
        self.annotate(m)
        self.assertEqual(m["blockers"], ["orientation_suspect"])

    def test_a_measured_dark_clip_keeps_its_result_and_gets_a_note(self):
        m = {"countStatus": "geometry", "n_reps": 5, "blockers": [],
             "detected": {"framing": ["framing_dark"], "orientation": None}}
        self.annotate(m)
        self.assertEqual(m["blockers"], [])
        self.assertEqual(m["notes"], ["framing_dark"])

    def test_a_normal_clip_is_left_alone(self):
        m = {"countStatus": "geometry", "n_reps": 5, "blockers": ["x"],
             "detected": {"framing": [], "orientation": None}}
        self.annotate(m)
        self.assertEqual((m["blockers"], m["notes"], m["orientation"]), (["x"], [], None))

    def test_no_detected_dict_does_not_crash(self):
        m = {"countStatus": "unmeasured", "n_reps": 0, "blockers": ["Could not open"],
             "detected": None}
        self.annotate(m)
        self.assertEqual(m["blockers"], ["Could not open"])


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class TestRotateClip(unittest.TestCase):
    def test_the_turned_clip_is_the_picture_flipped_both_ways(self):
        import subprocess
        import tempfile

        import cv2

        from barra.frames import rotate_clip

        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "src.mp4"
            # Left half white, bottom half red: any flip is visible.
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                 "color=c=black:s=160x120:d=1,drawbox=x=0:y=0:w=80:h=120:color=white:t=fill,"
                 "drawbox=x=0:y=60:w=160:h=60:color=red:t=fill",
                 "-pix_fmt", "yuv420p", str(src)], check=True)
            out = rotate_clip(src, Path(d) / "turned.mp4")
            self.assertIsNotNone(out)

            def frame(p):
                cap = cv2.VideoCapture(str(p))
                ok, f = cap.read()
                cap.release()
                self.assertTrue(ok)
                return f

            a, b = frame(src), frame(out)
            self.assertEqual(a.shape[:2], b.shape[:2])
            # top-left of the source (white, above the red) is bottom-right now.
            self.assertGreater(float(a[10, 10].mean()), 200)
            self.assertGreater(float(b[-10, -10].mean()), 200)
            self.assertGreater(float(a[-10, -10][2]), 150)   # red at the bottom...
            self.assertGreater(float(b[10, 10][2]), 150)     # ...is at the top turned


if __name__ == "__main__":
    unittest.main()
